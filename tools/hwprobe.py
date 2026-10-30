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


def gpu_working_set_gb() -> float:
    """How much memory Metal recommends the GPU use, across every process together (D36)."""
    try:
        import mlx.core as mx

        return round(mx.metal.device_info()["max_recommended_working_set_size"] / 2**30, 1)
    except Exception:
        return 0.0


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
        "gpu_working_set_gb": gpu_working_set_gb(),
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
    tuning["lab"] = lab_tuning(hw, (previous or {}).get("lab", {}))
    # Measured by tools/tag_bench.py, so a re-probe has nothing to derive it from.
    if previous and "tag" in previous:
        tuning["tag"] = previous["tag"]
    return tuning


def lab_tuning(hw: dict, previous: dict) -> dict:
    """How many lab jobs share the GPU, and each one's memory cap (D36).

    The number of jobs is measured by tools/lab_bench.py, not derived, so it is kept across
    re-probes; until the benchmark has run it is one. Each job gets an equal share of 90 % of
    the GPU working set, and at most a quarter of its share as cache, so the jobs' caches
    cannot together grow past what the GPU can hold."""
    jobs = int(previous.get("parallel_jobs", 1))
    share = round(hw.get("gpu_working_set_gb", 0) * 0.9 / jobs, 1)
    lab = {"parallel_jobs": jobs, "job_memory_gb": share, "job_cache_gb": round(share / 4, 1)}
    for key in ("parallel_jobs_status", "bench"):
        if key in previous:
            lab[key] = previous[key]
    return lab


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
