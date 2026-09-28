"""Read-only local resource snapshots; no credentials or conversation content."""

import argparse
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def memory_snapshot():
    if os.name != "nt":
        return {"available": False, "reason": "windows_probe_only"}

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong)
            for name in (
                "total",
                "free",
                "page_total",
                "page_free",
                "virtual_total",
                "virtual_free",
                "extended_free",
            )
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return {"available": False, "reason": "probe_failed"}
    return {
        "available": True,
        "total_bytes": status.total,
        "available_bytes": status.free,
        "used_bytes": status.total - status.free,
    }


def gpu_snapshot():
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        rows = []
        for line in result.stdout.strip().splitlines():
            index, name, total, used, free = [part.strip() for part in line.split(",")]
            rows.append(
                {
                    "index": int(index),
                    "name": name,
                    "total_mib": int(total),
                    "used_mib": int(used),
                    "free_mib": int(free),
                }
            )
        return {"available": True, "devices": rows}
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        return {"available": False, "reason": type(error).__name__}


def snapshot():
    return {
        "at": datetime.now(timezone.utc).isoformat(),
        "memory": memory_snapshot(),
        "gpu": gpu_snapshot(),
    }


def listening(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def inventory(model_roots):
    result = snapshot()
    result.update(
        cpu={"logical_threads": os.cpu_count(), "processor": platform.processor()},
        disk_free_bytes=shutil.disk_usage(ROOT).free,
        ports={str(p): listening(p) for p in (8000, 8001, 8080, 11434, 12393)},
    )
    result["models"] = []
    for directory in model_roots:
        if directory.is_dir():
            for file in sorted(directory.rglob("*")):
                if file.is_file() and file.suffix in {".gguf", ".safetensors"}:
                    result["models"].append(
                        {"path": str(file.resolve()), "bytes": file.stat().st_size}
                    )
    return result


def summarize(samples):
    """Observed whole-machine peaks, not per-process allocation or exact maxima."""
    ram = [s["memory"]["used_bytes"] for s in samples if s["memory"]["available"]]
    gpu = {}
    for sample in samples:
        for device in sample["gpu"].get("devices", []):
            key = str(device["index"])
            gpu[key] = max(gpu.get(key, 0), device["used_mib"])
    return {
        "sample_count": len(samples),
        "system_ram_used_peak_bytes": max(ram) if ram else None,
        "gpu_used_peak_mib": gpu,
        "scope": "whole_machine_sampled",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", type=Path, action="append")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = inventory(args.model_root or [Path("D:/models"), ROOT / "models/decision"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(f"Resource report: {args.output.resolve()}")


if __name__ == "__main__":
    main()
