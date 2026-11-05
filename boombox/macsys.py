"""macOS helpers: system volume, keeping the laptop awake, disk space."""

import os
import shutil
import subprocess


def output_volume():
    """(volume 0-100, muted) or (None, None) if unavailable."""
    try:
        out = subprocess.run(["osascript", "-e", "get volume settings"],
                             capture_output=True, text=True, timeout=5).stdout
        parts = dict(p.strip().split(":", 1) for p in out.strip().split(","))
        vol = parts.get("output volume", "missing value")
        return (None if vol == "missing value" else int(vol)), parts.get("output muted") == "true"
    except Exception:
        return None, None


def keep_awake():
    """Prevent display/system sleep while this process runs."""
    try:
        return subprocess.Popen(["caffeinate", "-dims", "-w", str(os.getpid())])
    except Exception:
        return None


def free_gb(path):
    try:
        return shutil.disk_usage(path).free / 1e9
    except Exception:
        return None
