"""Read-only host resource snapshot with a one-second CPU sample."""
import ctypes
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time


def snapshot():
    value = {"machine": platform.node(), "platform": platform.platform(), "logical_cpus": os.cpu_count(),
        "python": sys.executable, "working_directory": str(Path.cwd()), "disk_free_bytes": shutil.disk_usage(Path.cwd()).free}
    if os.name == "nt":
        from ctypes import wintypes
        class Memory(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [(key, ctypes.c_ulonglong) for key in
                ("total_physical", "available_physical", "total_page", "available_page", "total_virtual", "available_virtual", "extended_virtual")]
        memory = Memory(); memory.length = ctypes.sizeof(memory)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            raise ctypes.WinError()
        value.update(memory_load_percent=memory.load, memory_available_bytes=memory.available_physical, memory_total_bytes=memory.total_physical)
        def cpu_times():
            fields = [wintypes.FILETIME() for _ in range(3)]
            if not ctypes.windll.kernel32.GetSystemTimes(*(ctypes.byref(field) for field in fields)):
                raise ctypes.WinError()
            return [field.dwLowDateTime + (field.dwHighDateTime << 32) for field in fields]
        before = cpu_times(); time.sleep(1); after = cpu_times()
        idle, kernel, user = [right-left for left, right in zip(before, after)]
        value["cpu_busy_percent_1s"] = 100.*(1-idle/(kernel+user)) if kernel+user else None
    else:
        value["load_average"] = os.getloadavg()
        value["memory_info"] = Path("/proc/meminfo").read_text()
    return value


if __name__ == "__main__":
    destination = Path(sys.argv[1])
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(snapshot(), stream, indent=2)
    print(destination.read_text())
