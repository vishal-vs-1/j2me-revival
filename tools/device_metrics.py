"""Read-only Windows process/GPU measurements for isolated enhancement benchmarks."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os
import re
import time

MIB=1024*1024


class MemoryStatus(C.Structure):
    _fields_=[('length',W.DWORD),('load',W.DWORD),*[(name,C.c_ulonglong) for name in
        ('total','available','total_page','available_page','total_virtual','available_virtual','extended')]]


def host_memory():
    value=MemoryStatus();value.length=C.sizeof(value)
    if not C.windll.kernel32.GlobalMemoryStatusEx(C.byref(value)):raise C.WinError()
    return {'total_bytes':value.total,'available_bytes':value.available,'logical_cpus':os.cpu_count() or 1}


class ProcessMemory(C.Structure):
    _fields_=[('cb',W.DWORD),('faults',W.DWORD),*[(name,C.c_size_t) for name in
        ('peak_working','working','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile','private')]]


def process_sample(handle):
    memory=ProcessMemory();memory.cb=C.sizeof(memory)
    psapi=C.WinDLL('psapi.dll');psapi.GetProcessMemoryInfo.argtypes=[W.HANDLE,C.c_void_p,W.DWORD]
    ok=psapi.GetProcessMemoryInfo(W.HANDLE(int(handle)),C.byref(memory),memory.cb)
    times=(C.c_ulonglong*4)()
    kernel=C.WinDLL('kernel32.dll')
    kernel.GetProcessTimes.argtypes=[W.HANDLE,C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p]
    got=kernel.GetProcessTimes(W.HANDLE(int(handle)),*[C.byref(times,i*8) for i in range(4)])
    return {'host_private_mb':memory.private/MIB if ok else None,
            'host_peak_working_mb':memory.peak_working/MIB if ok else None,
            'cpu_seconds':(times[2]+times[3])/1e7 if got else None}


class _CounterUnion(C.Union):
    _fields_=[('number',C.c_double),('integer',C.c_longlong),('pointer',C.c_void_p)]


class _CounterValue(C.Structure):
    _fields_=[('status',W.DWORD),('value',_CounterUnion)]


class _CounterItem(C.Structure):
    _fields_=[('name',W.LPWSTR),('data',_CounterValue)]


class WindowsGpuCounters:
    """GPU memory is per process. Shared and dedicated bytes are kept separate."""
    def __init__(self):
        self.api=C.WinDLL('pdh.dll');self.query=W.HANDLE();self.counters={}
        self.engine_query=W.HANDLE();self.engine_counter=W.HANDLE();self.last_engine=0.;self.engine_values={}
        self.api.PdhOpenQueryW.argtypes=[W.LPCWSTR,C.c_size_t,C.POINTER(W.HANDLE)]
        self.api.PdhAddEnglishCounterW.argtypes=[W.HANDLE,W.LPCWSTR,C.c_size_t,C.POINTER(W.HANDLE)]
        self.api.PdhCollectQueryData.argtypes=[W.HANDLE]
        self.api.PdhCloseQuery.argtypes=[W.HANDLE]
        self.api.PdhGetFormattedCounterArrayW.argtypes=[W.HANDLE,W.DWORD,C.POINTER(W.DWORD),C.POINTER(W.DWORD),C.c_void_p]
        code=self.api.PdhOpenQueryW(None,0,C.byref(self.query))
        if code:raise OSError(f'Windows performance query unavailable: {code & 0xffffffff:x}')
        for name,path in [('dedicated',r'\GPU Process Memory(*)\Dedicated Usage'),
                          ('shared',r'\GPU Process Memory(*)\Shared Usage')]:
            handle=W.HANDLE()
            if self.api.PdhAddEnglishCounterW(self.query,path,0,C.byref(handle))==0:self.counters[name]=handle
        self.api.PdhCollectQueryData(self.query)
        if self.api.PdhOpenQueryW(None,0,C.byref(self.engine_query))==0:
            self.api.PdhAddEnglishCounterW(self.engine_query,r'\GPU Engine(*)\Utilization Percentage',0,C.byref(self.engine_counter))
            self.api.PdhCollectQueryData(self.engine_query)

    def _values(self,counter,pid):
        size=W.DWORD();count=W.DWORD();flags=0x200|0x8000
        self.api.PdhGetFormattedCounterArrayW(counter,flags,C.byref(size),C.byref(count),None)
        if not size.value:return []
        buffer=C.create_string_buffer(size.value)
        if self.api.PdhGetFormattedCounterArrayW(counter,flags,C.byref(size),C.byref(count),buffer)!=0:return []
        rows=C.cast(buffer,C.POINTER(_CounterItem))
        return [rows[i].data.value.number for i in range(count.value)
                if rows[i].data.status in (0,1) and re.match(r'pid_'+str(pid)+r'_',rows[i].name or '')]

    def sample(self,pid):
        if self.api.PdhCollectQueryData(self.query)!=0:return {}
        result={}
        for name,counter in self.counters.items():
            values=self._values(counter,pid)
            if values:result[name]=sum(values)/MIB
        # Rate counters need a longer interval than instantaneous memory gauges.
        if self.engine_query and time.monotonic()-self.last_engine>=1.0:
            self.last_engine=time.monotonic()
            if self.api.PdhCollectQueryData(self.engine_query)==0:
                values=self._values(self.engine_counter,pid)
                if values:self.engine_values[pid]=min(100.,max(0.,max(values)))
        if pid in self.engine_values:result['engine']=self.engine_values[pid]
        return result

    def close(self):
        if self.query:self.api.PdhCloseQuery(self.query);self.query=W.HANDLE()
        if self.engine_query:self.api.PdhCloseQuery(self.engine_query);self.engine_query=W.HANDLE()


class NvidiaMetrics:
    def __init__(self):
        self.api=C.WinDLL('nvml.dll')
        if self.api.nvmlInit_v2()!=0:raise OSError('NVML is unavailable')
        self.handle=C.c_void_p()
        self.api.nvmlDeviceGetHandleByIndex_v2.argtypes=[C.c_uint,C.POINTER(C.c_void_p)]
        self.api.nvmlDeviceGetMemoryInfo.argtypes=[C.c_void_p,C.c_void_p]
        self.api.nvmlDeviceGetUtilizationRates.argtypes=[C.c_void_p,C.c_void_p]
        if self.api.nvmlDeviceGetHandleByIndex_v2(0,C.byref(self.handle))!=0:raise OSError('NVIDIA GPU unavailable')

    def sample(self):
        memory=(C.c_ulonglong*3)();util=(C.c_uint*2)();result={}
        if self.api.nvmlDeviceGetMemoryInfo(self.handle,C.byref(memory))==0:
            result.update(total_mb=memory[0]/MIB,free_mb=memory[1]/MIB,used_mb=memory[2]/MIB)
        if self.api.nvmlDeviceGetUtilizationRates(self.handle,C.byref(util))==0:
            result.update(gpu_pct=util[0],memory_controller_pct=util[1])
        return result

    def close(self):self.api.nvmlShutdown()
