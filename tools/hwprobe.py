"""Hardware probe (spec section 2).

Writes config/hardware.toml and derives config/tuning.toml. Every parallelism and
model setting downstream is read from tuning.toml; nothing is hard-coded.
Lifted from KINFOLK/tools/hwprobe.py and adapted for the mlx tagger (see REUSE.md).
"""
from __future__ import annotations

import datetime as dt
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import tomli_w

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


def sh(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def gpu_cores() -> int:
    m = re.search(r"Total Number of Cores:\s*(\d+)", sh(["system_profiler", "SPDisplaysDataType"]))
    return int(m.group(1)) if m else 0


def metal_available() -> bool:
    try:
        import mlx.core as mx

        return bool(mx.metal.is_available())
    except Exception:
        return False


def probe() -> dict:
    usage = shutil.disk_usage(ROOT)
    return {
        "probed_at": dt.datetime.now().isoformat(timespec="seconds"),
        "chip": sh(["sysctl", "-n", "machdep.cpu.brand_string"]),
        "performance_cores": int(sh(["sysctl", "-n", "hw.perflevel0.physicalcpu"]) or 0),
        "efficiency_cores": int(sh(["sysctl", "-n", "hw.perflevel1.physicalcpu"]) or 0),
        "unified_memory_gb": round(int(sh(["sysctl", "-n", "hw.memsize"]) or 0) / 2**30, 1),
        "gpu_cores": gpu_cores(),
        "free_disk_gb": round(usage.free / 2**30, 1),
        "metal_available": metal_available(),
    }


def derive(hw: dict, previous: dict | None) -> dict:
    cpu_workers = max(2, hw["performance_cores"] - 2)
    tuning = {
        "cpu_workers": cpu_workers,
        "io_workers": 8,
        "model_backend": "mlx" if hw["metal_available"] else "cpu",
        "model_id": "Qwen/Qwen2.5-3B-Instruct",
        "model_instances": 1,
        "tag_batch_size": 8,
        "memory_headroom_gb": 24,
        "max_compute_hours": 24,
        "ncbi_rate_per_second": 3,
        "env": {
            "TOKENIZERS_PARALLELISM": "false",
            "OMP_NUM_THREADS": str(cpu_workers),
        },
    }
    # Keep decisions the smoke test or a fallback made across re-probes.
    if previous:
        for key in ("model_id", "tag_batch_size", "model_backend", "max_compute_hours",
                    "ncbi_rate_per_second", "tag_batch_size_status"):
            if key in previous:
                tuning[key] = previous[key]
    return tuning


def main() -> None:
    CONFIG.mkdir(exist_ok=True)
    hw = probe()
    tuning_path = CONFIG / "tuning.toml"
    previous = tomllib.loads(tuning_path.read_text()) if tuning_path.exists() else None
    (CONFIG / "hardware.toml").write_text(tomli_w.dumps(hw))
    tuning_path.write_text(tomli_w.dumps(derive(hw, previous)))
    print(tomli_w.dumps(hw))
    print(tomli_w.dumps(derive(hw, previous)))


if __name__ == "__main__":
    main()
