"""Hardware reads, pure preparation budgets, and bounded model-process supervision."""
from __future__ import annotations

import atexit
import ctypes as C
from dataclasses import dataclass
import os
import threading

MIB=1024**2
GIB=1024**3


class ResourcePressure(RuntimeError):
    """Work can be retried when memory becomes available; source pixels are valid."""


def host_memory():
    if os.name=='nt':
        class Status(C.Structure):
            _fields_=[('length',C.c_uint32),('load',C.c_uint32),*[(name,C.c_uint64) for name in
                ('total','available','total_page','available_page','total_virtual','available_virtual','extended')]]
        value=Status();value.length=C.sizeof(value)
        if C.windll.kernel32.GlobalMemoryStatusEx(C.byref(value)):
            return {'total_bytes':int(value.total),'available_bytes':int(value.available),
                    'logical_cpus':os.cpu_count() or 1}
    else:
        try:
            size=os.sysconf('SC_PAGE_SIZE')
            return {'total_bytes':os.sysconf('SC_PHYS_PAGES')*size,
                    'available_bytes':os.sysconf('SC_AVPHYS_PAGES')*size,'logical_cpus':os.cpu_count() or 1}
        except (OSError,ValueError,AttributeError):pass
    return {'total_bytes':0,'available_bytes':0,'logical_cpus':os.cpu_count() or 1}


_nvml=None
_nvml_lock=threading.Lock()


def gpu_memory(device):
    """Optional NVIDIA global memory sample; ambiguous identical GPUs use conservative budgets."""
    global _nvml
    if os.name!='nt' or not device or device.get('vendor')!=0x10de:return None
    try:
        with _nvml_lock:
            if _nvml is False:return None
            if _nvml is None:
                api=C.WinDLL('nvml.dll')
                if api.nvmlInit_v2()!=0:_nvml=False;return None
                api.nvmlDeviceGetHandleByIndex_v2.argtypes=[C.c_uint,C.POINTER(C.c_void_p)]
                api.nvmlDeviceGetName.argtypes=[C.c_void_p,C.c_void_p,C.c_uint]
                api.nvmlDeviceGetMemoryInfo.argtypes=[C.c_void_p,C.c_void_p]
                _nvml=api;atexit.register(api.nvmlShutdown)
            count=C.c_uint()
            if _nvml.nvmlDeviceGetCount_v2(C.byref(count))!=0:return None
            matches=[]
            for index in range(count.value):
                handle=C.c_void_p();name=C.create_string_buffer(128)
                if _nvml.nvmlDeviceGetHandleByIndex_v2(index,C.byref(handle))!=0:continue
                if _nvml.nvmlDeviceGetName(handle,name,len(name))!=0:continue
                if name.value.decode(errors='replace').casefold()==device['name'].casefold():matches.append(handle)
            if len(matches)!=1:return None
            value=(C.c_ulonglong*3)()
            if _nvml.nvmlDeviceGetMemoryInfo(matches[0],C.byref(value))!=0:return None
            return {'total_bytes':int(value[0]),'free_bytes':int(value[1]),'used_bytes':int(value[2])}
    except (OSError,AttributeError,KeyError):return None


@dataclass(frozen=True)
class PreparationBudget:
    max_images: int
    max_pixels: int
    processing_threads: int=1
    gpu_budget_bytes: int=0
    gpu_reserve_bytes: int=0
    reason: str=''


def plan_budget(device,available_ram,logical_cpus,*,gpu_free=None):
    """Memory ceilings are headroom targets, never allocations made to fill unused RAM."""
    if available_ram and available_ram<768*MIB:
        return PreparationBudget(1,65_536,reason='Waiting for free system memory before preparing AI artwork.')
    kind=(device or {}).get('kind','unknown')
    if kind=='integrated':
        if available_ram and available_ram<2*GIB:
            return PreparationBudget(1,65_536,reason='Waiting for free system memory before using shared graphics memory.')
        count=256 if available_ram>=5*GIB//2 else 64
        shared=min(768*MIB,available_ram//4) if available_ram else 256*MIB
        return PreparationBudget(count,262_144,gpu_budget_bytes=shared)
    if kind=='dedicated':
        total=int(device.get('device_local_bytes',0))
        budget=min(2*GIB,total//2) if total else 512*MIB
        reserve=max(256*MIB,total//8) if total else 256*MIB
        if gpu_free is not None:budget=min(budget,max(0,gpu_free-reserve))
        if available_ram and available_ram<3*GIB//2:
            return PreparationBudget(1,65_536,reason='Waiting for free system memory before preparing AI artwork.')
        if budget<384*MIB:
            return PreparationBudget(1,65_536,reason='Waiting for graphics memory; Fast pixel can prepare artwork on CPU.')
        if budget>=1792*MIB and available_ram>=2*GIB:
            threads=2 if logical_cpus>=4 else 1
            return PreparationBudget(512,1_048_576,threads,budget,reserve)
        if budget>=GIB:return PreparationBudget(128,524_288,1,budget,reserve)
        return PreparationBudget(32,131_072,1,budget,reserve)
    return PreparationBudget(16,65_536)


def current_budget():
    from gpu_policy import devices,settings,choose_device
    available=devices()
    if not available:
        return PreparationBudget(1,65_536,reason='AI artwork needs a compatible graphics device. Choose Fast pixel for CPU preparation.')
    device=choose_device(settings()['enhance_gpu'],available)
    memory=host_memory();graphics=gpu_memory(device)
    return plan_budget(device,memory['available_bytes'],memory['logical_cpus'],
                       gpu_free=graphics['free_bytes'] if graphics else None)


def budget_violation(budget,host_available,graphics,baseline_used):
    if host_available and host_available<768*MIB:return 'System memory is low; artwork preparation will retry later.'
    if graphics:
        if budget.gpu_budget_bytes and graphics['used_bytes']-baseline_used>budget.gpu_budget_bytes:
            return 'Artwork reached the graphics-memory budget; retrying with smaller work.'
        if budget.gpu_reserve_bytes and graphics['free_bytes']<budget.gpu_reserve_bytes:
            return 'Graphics memory is needed by other applications; artwork will retry later.'
    return ''


class ModelMemoryGuard:
    """Samples memory while our own child runs; native allocations can briefly overshoot between samples."""
    def __init__(self,process,device,budget,*,baseline_used=None):
        self.process,self.device,self.budget=process,device,budget
        initial=gpu_memory(device) if baseline_used is None else None
        self.baseline=baseline_used if baseline_used is not None else initial['used_bytes'] if initial else 0
        self.reason='';self.stop=threading.Event();self.peak_extra_bytes=0
        self.thread=threading.Thread(target=self._watch,name='model-memory-budget',daemon=True)

    def start(self):self.thread.start()

    def _watch(self):
        while not self.stop.wait(0.1):
            if self.process.poll() is not None:return
            graphics=gpu_memory(self.device)
            if graphics:self.peak_extra_bytes=max(self.peak_extra_bytes,graphics['used_bytes']-self.baseline)
            reason=budget_violation(self.budget,host_memory()['available_bytes'],graphics,self.baseline)
            if reason:
                self.reason=reason
                try:self.process.terminate()
                except OSError:pass
                return

    def close(self):self.stop.set();self.thread.join(timeout=1)
