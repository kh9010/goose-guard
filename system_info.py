"""
System information helpers for the Goose Guard status page.
All checks are best-effort and degrade gracefully on non-Pi hosts.
"""

import os
import shutil
import socket
import subprocess
import time


_START_TIME = time.time()


def get_uptime_seconds():
    """Return system uptime in seconds, falling back to process uptime."""
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except (FileNotFoundError, ValueError, OSError):
        return time.time() - _START_TIME


def format_uptime(seconds):
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"


def get_cpu_temp_c():
    """Read CPU temperature in °C from the Pi thermal zone."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return round(int(f.read().strip()) / 1000, 1)
    except (FileNotFoundError, ValueError, OSError):
        return None


def get_disk_usage(path="/"):
    try:
        total, used, free = shutil.disk_usage(path)
        return {
            "total_gb": round(total / (1024 ** 3), 1),
            "used_gb": round(used / (1024 ** 3), 1),
            "free_gb": round(free / (1024 ** 3), 1),
            "percent_used": round(used / total * 100, 1),
        }
    except OSError:
        return None


def get_load_average():
    try:
        return list(os.getloadavg())
    except (OSError, AttributeError):
        return None


def get_memory_info():
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, rest = line.partition(":")
                parts = rest.strip().split()
                if parts:
                    info[key] = int(parts[0])
        total_kb = info.get("MemTotal", 0)
        available_kb = info.get("MemAvailable", info.get("MemFree", 0))
        if not total_kb:
            return None
        used_kb = total_kb - available_kb
        return {
            "total_mb": round(total_kb / 1024),
            "used_mb": round(used_kb / 1024),
            "available_mb": round(available_kb / 1024),
            "percent_used": round(used_kb / total_kb * 100, 1),
        }
    except (FileNotFoundError, ValueError, OSError):
        return None


def get_hostname():
    try:
        return os.uname().nodename
    except AttributeError:
        return socket.gethostname()


def get_ip_address():
    """Best-effort discovery of the primary outbound IP."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return None


def get_service_status(service_name="goose-guard"):
    """Check systemd service state. Returns 'active', 'inactive', or 'unknown'."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service_name],
            capture_output=True, text=True, timeout=2,
        )
        status = result.stdout.strip()
        return status if status else "unknown"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return "unknown"


def collect():
    """Snapshot of all system vitals for the status page."""
    return {
        "hostname": get_hostname(),
        "ip": get_ip_address(),
        "uptime": format_uptime(get_uptime_seconds()),
        "cpu_temp_c": get_cpu_temp_c(),
        "load_average": get_load_average(),
        "memory": get_memory_info(),
        "disk": get_disk_usage(),
        "service": get_service_status(),
    }
