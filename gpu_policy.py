"""App-scoped GPU preference, Vulkan inventory and explicit inference device selection."""
from __future__ import annotations
import ctypes as C
import json,os,sys,threading,time,uuid
from pathlib import Path
from app_paths import RESOURCE_ROOT, DATA_ROOT
from platform_support import IS_WINDOWS, IS_LINUX

ROOT=RESOURCE_ROOT
SETTINGS=DATA_ROOT/'library/settings.json'
MODES=('auto','dedicated','integrated','system')
DEFAULTS={'render_gpu':'auto','enhance_gpu':'auto'}
_lock=threading.RLock()
_inventory=None

def settings():
    try:
        value=json.loads(SETTINGS.read_text(encoding='utf-8'))
        return {key:value.get(key) if value.get(key) in MODES else default for key,default in DEFAULTS.items()}
    except (OSError,ValueError):return DEFAULTS.copy()

def save_settings(**changes):
    with _lock:
        value=settings()
        for key,mode in changes.items():
            if key not in DEFAULTS or mode not in MODES:raise ValueError('Unknown GPU preference')
            value[key]=mode
        SETTINGS.parent.mkdir(parents=True,exist_ok=True)
        temp=SETTINGS.with_name('settings.'+uuid.uuid4().hex+'.tmp')
        temp.write_text(json.dumps(value,indent=2),encoding='utf-8');os.replace(temp,SETTINGS)
        return value

def _load_vulkan():
    """Load the Vulkan shared library for the current platform.

    Raises OSError if the driver is not installed; callers must treat this as
    'no GPU available' rather than a fatal error.
    """
    if IS_WINDOWS:
        return C.WinDLL('vulkan-1.dll')
    if IS_LINUX:
        return C.CDLL('libvulkan.so.1')
    raise OSError(f'Vulkan enumeration is not supported on {sys.platform}')


def devices(refresh=False):
    """Enumerate Vulkan physical devices.

    Returns [] if Vulkan is unavailable (driver not installed, unsupported OS).
    The returned device indices are what the NCNN runtime sees when it loads the
    same Vulkan library in-process; cross-process index stability is not
    guaranteed by the Vulkan spec and must be verified separately.
    """
    global _inventory
    with _lock:
        if _inventory is not None and not refresh:return list(_inventory)
        try:
            vk=_load_vulkan()
        except OSError:
            # Vulkan driver absent or unsupported platform — non-fatal.
            _inventory=[];return []
        instance=C.c_void_p()
        class App(C.Structure):
            _fields_=[('sType',C.c_uint32),('pNext',C.c_void_p),('name',C.c_char_p),('version',C.c_uint32),('engine',C.c_char_p),('engineVersion',C.c_uint32),('api',C.c_uint32)]
        class Info(C.Structure):
            _fields_=[('sType',C.c_uint32),('pNext',C.c_void_p),('flags',C.c_uint32),('application',C.POINTER(App)),('layerCount',C.c_uint32),('layers',C.c_void_p),('extensionCount',C.c_uint32),('extensions',C.c_void_p)]
        class MemoryType(C.Structure):
            _fields_=[('flags',C.c_uint32),('heap',C.c_uint32)]
        class MemoryHeap(C.Structure):
            _fields_=[('size',C.c_uint64),('flags',C.c_uint32)]
        class MemoryProperties(C.Structure):
            _fields_=[('type_count',C.c_uint32),('types',MemoryType*32),
                      ('heap_count',C.c_uint32),('heaps',MemoryHeap*16)]
        try:
            vk.vkCreateInstance.argtypes=[C.POINTER(Info),C.c_void_p,C.POINTER(C.c_void_p)];vk.vkCreateInstance.restype=C.c_int
            vk.vkEnumeratePhysicalDevices.argtypes=[C.c_void_p,C.POINTER(C.c_uint32),C.POINTER(C.c_void_p)];vk.vkEnumeratePhysicalDevices.restype=C.c_int
            vk.vkGetPhysicalDeviceProperties.argtypes=[C.c_void_p,C.c_void_p]
            vk.vkGetPhysicalDeviceMemoryProperties.argtypes=[C.c_void_p,C.POINTER(MemoryProperties)]
            vk.vkDestroyInstance.argtypes=[C.c_void_p,C.c_void_p]
            app=App(0,None,b'JAR Revival',1,b'JAR Revival',1,1<<22)
            info=Info(1,None,0,C.pointer(app),0,None,0,None)
            code=vk.vkCreateInstance(C.byref(info),None,C.byref(instance))
            if code!=0 or not instance.value:
                _inventory=[];return []
        except Exception:
            _inventory=[];return []

        try:
            count=C.c_uint32(0)
            code=vk.vkEnumeratePhysicalDevices(instance,C.byref(count),None)
            if code!=0 or count.value==0:
                _inventory=[];return []
            handles=(C.c_void_p*count.value)()
            code=vk.vkEnumeratePhysicalDevices(instance,C.byref(count),handles)
            if code not in (0,5):
                _inventory=[];return []
            result=[]
            for index,handle in enumerate(handles[:count.value]):
                if not handle:continue
                try:
                    raw=C.create_string_buffer(4096);vk.vkGetPhysicalDeviceProperties(handle,raw)
                    fields=(C.c_uint32*5).from_buffer(raw);kind=fields[4]
                    if kind not in (1,2,3):continue
                    memory=MemoryProperties();vk.vkGetPhysicalDeviceMemoryProperties(handle,C.byref(memory))
                    local=sum(memory.heaps[i].size for i in range(min(memory.heap_count,16)) if memory.heaps[i].flags&1)
                    name=raw.raw[20:276].split(b'\0',1)[0].decode('utf-8',errors='replace')
                    result.append({'index':index,'name':name,
                                   'kind':{1:'integrated',2:'dedicated',3:'virtual'}[kind],'vendor':int(fields[2]),
                                   'device_local_bytes':int(local),'driver_version':int(fields[1])})
                except Exception:
                    continue
            _inventory=result;return list(result)
        except Exception:
            _inventory=[];return []
        finally:
            if instance and instance.value:
                try:vk.vkDestroyInstance(instance,None)
                except Exception:pass

def choose_device(mode,available=None):
    available=devices() if available is None else available
    if mode not in MODES:raise ValueError('Unknown GPU preference')
    if mode=='system':return None
    if mode in ('dedicated','integrated'):
        choices=[device for device in available if device['kind']==mode]
        if not choices:raise RuntimeError(f'No {mode} Vulkan GPU is available. Choose Auto or another GPU.')
        return choices[0]
    ranked=sorted(available,key=lambda device:({'dedicated':0,'integrated':1,'virtual':2}.get(device['kind'],3),device['index']))
    return ranked[0] if ranked else None

def inference_arguments():
    available=devices()
    if not available:raise RuntimeError('AI artwork needs a compatible graphics device. Choose Fast pixel for CPU preparation.')
    device=choose_device(settings()['enhance_gpu'],available)
    return (['-g',str(device['index'])] if device else []),device

def player_java(mode):
    """Return the path to the private runtime java binary and, on Windows, set
    the per-app GPU preference in the registry for this executable only.
    """
    from platform_support import java_binary_name
    if mode not in MODES:raise ValueError('Unknown GPU preference')
    executable=ROOT/'tools/runtime/bin'/java_binary_name()
    if not executable.exists():raise RuntimeError('The private player runtime is missing. Run python tools/setup_runtime.py.')
    if os.name=='nt':
        import winreg
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\DirectX\UserGpuPreferences',0,winreg.KEY_SET_VALUE) as key:
                if mode=='system':
                    try:winreg.DeleteValue(key,str(executable))
                    except FileNotFoundError:pass
                else:
                    preference=1 if mode=='integrated' else 2
                    winreg.SetValueEx(key,str(executable),0,winreg.REG_SZ,f'GpuPreference={preference};')
        except OSError:
            # A locked-down Windows account may reject the per-app GPU preference.
            # Keep playback usable with Windows' existing default GPU selection.
            pass
    return str(executable)

def expected_device(mode):
    try:return choose_device(mode)
    except (OSError,RuntimeError):return None
