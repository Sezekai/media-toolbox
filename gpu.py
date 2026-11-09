"""The NVIDIA GPU, for decoding videos while the duplicate engine fingerprints them (STANDARDS.md, "GPU").

Settings has Use: Auto / GPU / CPU. Auto uses the GPU when nvidia-smi finds one. If GPU decoding fails, the
scan runs again on the CPU instead of failing. The AMD integrated GPU can't do CUDA, so it's never offered."""
import os
import shutil
import subprocess
import sys

import settings

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
SAFE_MODE = False  # set by the window when it starts in safe mode: the GPU stays off


def _smi():
    found = shutil.which("nvidia-smi")
    if found:
        return found
    candidate = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
    return candidate if os.path.exists(candidate) else None


def _query(fields):
    exe = _smi()
    if not exe:
        return None
    try:
        out = subprocess.run([exe, f"--query-gpu={fields}", "--format=csv,noheader,nounits"], capture_output=True,
                             text=True, timeout=4, creationflags=_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    return [part.strip() for part in out.stdout.strip().splitlines()[0].split(",")]


def detect():
    """{"name", "driver", "memory_mb"} for the first NVIDIA GPU, or None."""
    row = _query("name,driver_version,memory.total")
    if not row or len(row) < 3:
        return None
    try:
        return {"name": row[0], "driver": row[1], "memory_mb": float(row[2])}
    except ValueError:
        return {"name": row[0], "driver": row[1], "memory_mb": 0.0}


def stats():
    """{"name", "load", "used_mb", "total_mb"} right now, or None."""
    row = _query("name,utilization.gpu,memory.used,memory.total")
    if not row or len(row) < 4:
        return None
    try:
        return {"name": row[0], "load": float(row[1]), "used_mb": float(row[2]), "total_mb": float(row[3])}
    except ValueError:
        return None


def mode():
    return settings.load().get("gpu_use", "auto")


def use_gpu():
    """(True/False, reason) for the next scan."""
    if SAFE_MODE:
        return False, "Safe mode is on, so the GPU stays off."
    choice = mode()
    if choice == "cpu":
        return False, "Settings say to use the CPU."
    found = detect()
    if not found:
        reason = "No NVIDIA GPU was found." if choice == "gpu" else "No NVIDIA GPU, so the CPU is used."
        return False, reason
    return True, f"Using the {found['name']}."


def chip_text(s):
    return f"{s['name']} \u00b7 {s['load']:.0f}% \u00b7 {s['used_mb'] / 1024:.1f} / {s['total_mb'] / 1024:.1f} GB"
