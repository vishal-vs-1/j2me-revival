"""Platform identification, binary naming conventions, and cross-platform locking.

Note: Windows and Linux (x86_64) are currently supported. macOS is not
advertised as supported because the private OpenJDK runtime, Vulkan/MoltenVK,
and Real-ESRGAN AI paths have not been built or validated for macOS.
"""
import os
import sys

IS_WINDOWS = sys.platform == 'win32'
IS_LINUX = sys.platform.startswith('linux')
IS_MACOS = sys.platform == 'darwin'


def java_binary_name(tool='java') -> str:
    """Return platform executable name for Java tools (e.g., 'java.exe' on Windows, 'java' on Linux)."""
    return f"{tool}.exe" if IS_WINDOWS else tool


def ncnn_binary_name() -> str:
    """Return platform executable name for Real-ESRGAN NCNN binary."""
    return 'realesrgan-ncnn-vulkan.exe' if IS_WINDOWS else 'realesrgan-ncnn-vulkan'


def lwjgl_classifier() -> str:
    """Return Maven classifier suffix for LWJGL 3 native jars on supported platforms."""
    if IS_WINDOWS:
        return '-natives-windows'
    if IS_LINUX:
        return '-natives-linux'
    if IS_MACOS:
        raise NotImplementedError(
            "macOS is not currently supported: requires verified runtime, MoltenVK, and AI paths."
        )
    raise NotImplementedError(f"Unsupported operating system for LWJGL natives: {sys.platform}")


def file_lock(file_obj):
    """Acquire a non-blocking single-instance lock across platforms.

    Raises OSError if the file is already locked by another process.
    """
    if IS_WINDOWS:
        import msvcrt
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def open_in_file_manager(path):
    """Open a folder path in the platform's default file manager."""
    import shutil
    import subprocess
    if IS_WINDOWS:
        os.startfile(path)
    elif IS_LINUX:
        tool = shutil.which('xdg-open')
        if not tool:
            raise FileNotFoundError(
                f"Cannot open '{path}': 'xdg-open' command was not found on PATH. "
                "Install 'xdg-utils' on your Linux distribution or open the directory manually."
            )
        try:
            subprocess.Popen([tool, str(path)])
        except OSError as error:
            raise OSError(f"Failed to launch file manager with xdg-open: {error}") from error
    elif IS_MACOS:
        raise NotImplementedError("macOS is not currently supported.")
    else:
        raise NotImplementedError(f"Opening file manager is not supported on {sys.platform}")

