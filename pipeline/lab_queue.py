"""Run lab experiments side by side, each under its share of the GPU (LAB_PLAN.md, D36).

How many run at once is not decided here: tools/lab_bench.py measures it with the GPU idle
and writes `parallel_jobs` and the per-job caps into the [lab] table of config/tuning.toml.
Each experiment is its own `lab.py run` process, given its caps through the environment, so
its scoring (in process) and its trainings (through pipeline/mlx_capped.py) both stay inside
its share. Rounds are fixed here, in the parent, before anything starts, so two experiments
starting together can never claim the same wandb round.

A failed experiment is logged and the queue carries on; rerunning the same command resumes
it, because every unit inside `lab.py run` skips work already on disk.

  pixi run lab-queue phase1                 # configurations 2 to 8; 1 reuses the baseline
  pixi run lab-queue phase0-seeds phase1-c2
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import tomllib
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import common as c
from pipeline import lab
from pipeline.mlx_capped import caps_env

TUNING = c.ROOT / "config" / "tuning.toml"
POLL = 30


def settings() -> dict:
    """The measured sharing settings, or one job under the default cap until measured."""
    table = tomllib.loads(TUNING.read_text()).get("lab", {}) if TUNING.exists() else {}
    return {"jobs": max(1, int(table.get("parallel_jobs", 1))),
            "memory_gb": table.get("job_memory_gb"), "cache_gb": table.get("job_cache_gb")}


def expand(names: list[str]) -> list[str]:
    out: list[str] = []
    for name in names:
        out += [f"phase1-c{n}" for n in lab.PHASE1 if n != 1] if name == "phase1" else [name]
    return list(dict.fromkeys(out))


def command(name: str) -> list[str]:
    return [sys.executable, str(c.ROOT / "pipeline" / "lab.py"), "run", name]


def queue(names: list[str], jobs: int | None = None, start=subprocess.Popen) -> dict[str, int]:
    share = settings()
    jobs = jobs or share["jobs"]
    names = expand(names)
    for name in names:          # fixed before any child can race for a round number
        cfg = lab.load_config(name)
        if not cfg.get("reuse"):
            lab.experiment_round(cfg)
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "TOKENIZERS_PARALLELISM": "false",
           **caps_env(share["memory_gb"], share["cache_gb"])}
    c.log(f"lab queue: {len(names)} experiments, {jobs} at a time, "
          f"{share['memory_gb']} GB each ({share['cache_gb']} GB cache)")
    waiting, running, codes = list(names), {}, {}
    while waiting or running:
        while waiting and len(running) < jobs:
            name = waiting.pop(0)
            log = lab.LAB / name / "queue.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            sink = log.open("a")
            running[name] = (start(command(name), stdout=sink, stderr=subprocess.STDOUT,
                                   env=env, cwd=str(c.ROOT)), sink)
            c.log(f"lab queue: started {name}")
        for name, (proc, sink) in list(running.items()):
            if proc.poll() is None:
                continue
            sink.close()
            codes[name] = proc.returncode
            del running[name]
            c.log(f"lab queue: {name} " + ("done" if proc.returncode == 0 else
                                           f"failed with exit {proc.returncode}; see "
                                           f"data/lab/{name}/queue.log"))
        if running:
            time.sleep(POLL)
    return codes


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("usage: lab_queue.py <experiment|phase1> [...] [--jobs N]")
    args, jobs = sys.argv[1:], None
    if "--jobs" in args:
        i = args.index("--jobs")
        jobs = int(args[i + 1])
        args = args[:i] + args[i + 2:]
    codes = queue(args, jobs)
    return 0 if all(code == 0 for code in codes.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
