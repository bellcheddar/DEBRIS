"""Run an MLX entry point with this process's share of GPU memory capped (D36).

The GPU can address about 115 GB, but every MLX process grows its own buffer cache as if it
had all of it, and nothing coordinates two of them: a training run beside a scoring run
exhausted the GPU and killed the scoring. Two processes can share the GPU safely only when
each is told its share. The caps come from config/tuning.toml through the environment, so
the same command runs uncapped when nothing sets them.

  python pipeline/mlx_capped.py mlx_lm.lora --model ... --train ...
"""
from __future__ import annotations

import os
import runpy
import sys

GIB = 2 ** 30


def apply_caps() -> dict:
    """Read the caps from the environment and give them to MLX before anything is allocated."""
    import mlx.core as mx

    applied = {}
    memory = float(os.environ.get("DEBRIS_MLX_MEMORY_GB") or 0)
    cache = float(os.environ.get("DEBRIS_MLX_CACHE_GB") or 0)
    if memory:
        mx.set_memory_limit(int(memory * GIB))
        applied["memory_gb"] = memory
    if cache:
        mx.set_cache_limit(int(cache * GIB))
        applied["cache_gb"] = cache
    return applied


def caps_env(memory_gb: float | None, cache_gb: float | None) -> dict:
    """The environment a child process needs to run under these caps."""
    env = {}
    if memory_gb:
        env["DEBRIS_MLX_MEMORY_GB"] = str(memory_gb)
    if cache_gb:
        env["DEBRIS_MLX_CACHE_GB"] = str(cache_gb)
    return env


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: mlx_capped.py <module> [args...]")
    apply_caps()
    module = sys.argv[1]
    sys.argv = [module] + sys.argv[2:]
    runpy.run_module(module, run_name="__main__", alter_sys=True)
