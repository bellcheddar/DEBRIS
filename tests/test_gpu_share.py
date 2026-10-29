"""Sharing the GPU between lab jobs safely (D36).

Two MLX processes each grew a cache as if they had the whole GPU, and one of them died for
it. These tests hold the pieces that stop that: the caps reach the child process, the shares
never add up to more than the GPU holds, and a measured job count survives a re-probe.
"""
from __future__ import annotations

import subprocess
import sys

from pipeline import common as c
from pipeline import mlx_capped


def test_no_caps_means_no_environment():
    assert mlx_capped.caps_env(None, None) == {}
    assert mlx_capped.caps_env(48.4, 12.1) == {"DEBRIS_MLX_MEMORY_GB": "48.4",
                                               "DEBRIS_MLX_CACHE_GB": "12.1"}


def test_the_caps_reach_a_child_process(tmp_path):
    """The launcher sets the limit before the module it runs allocates anything."""
    # set_memory_limit returns the limit it replaces, which is the one the launcher set.
    (tmp_path / "_capped_probe.py").write_text(
        "import mlx.core as mx\nprint(mx.set_memory_limit(1 << 30))\n")
    env = {"DEBRIS_MLX_MEMORY_GB": "3", "DEBRIS_MLX_CACHE_GB": "1",
           "PATH": "/usr/bin:/bin", "PYTHONPATH": str(tmp_path)}
    out = subprocess.run([sys.executable, str(c.ROOT / "pipeline" / "mlx_capped.py"),
                          "_capped_probe"], env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert int(out.stdout.strip().splitlines()[-1]) == 3 * 2**30


def test_job_shares_never_exceed_the_gpu():
    sys.path.insert(0, str(c.ROOT / "tools"))
    import hwprobe
    hw = {"gpu_working_set_gb": 107.5}
    for jobs in (1, 2, 3):
        lab = hwprobe.lab_tuning(hw, {"parallel_jobs": jobs})
        assert lab["job_memory_gb"] * jobs <= 107.5
        assert lab["job_cache_gb"] <= lab["job_memory_gb"] / 4 + 0.05


def test_a_measured_job_count_survives_a_reprobe():
    sys.path.insert(0, str(c.ROOT / "tools"))
    import hwprobe
    previous = {"parallel_jobs": 2, "parallel_jobs_status": "measured 2026-10-29", "bench": "{}"}
    lab = hwprobe.lab_tuning({"gpu_working_set_gb": 107.5}, previous)
    assert lab["parallel_jobs"] == 2 and lab["parallel_jobs_status"] == "measured 2026-10-29"
    assert hwprobe.lab_tuning({"gpu_working_set_gb": 107.5}, {})["parallel_jobs"] == 1, \
        "one job until the benchmark says otherwise"
