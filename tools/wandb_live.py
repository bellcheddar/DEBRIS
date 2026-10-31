"""Stream a running lab unit's loss curve to wandb while it trains.

The lab logs a unit to wandb once, after training and scoring (lab.log_unit). A 7B unit
trains for hours, so this follows its train.log and logs each point as it lands, into the
same run log_unit will later resume (the stored wandb_id), and marks the curve logged so
log_unit does not log it twice. Reads only the log; never touches the GPU.

  pixi run python tools/wandb_live.py phase6-7b [--fold 0] [--seed 42]
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import common as c  # noqa: E402
from pipeline import lab  # noqa: E402
from pipeline import train as production  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("experiment")
    ap.add_argument("--fold", type=int, default=0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--poll", type=int, default=60, help="seconds between reads of the log")
    args = ap.parse_args()

    import wandb

    cfg = lab.load_config(args.experiment)
    home = lab.unit_dir(cfg["name"], args.fold, args.seed)
    log = home / "train.log"
    round_name = lab.experiment_round(cfg)
    id_file = home / "wandb_id"
    run_id = id_file.read_text().strip() if id_file.exists() else secrets.token_hex(4)
    id_file.write_text(run_id)
    if not c.wandb_api_key():
        os.environ["WANDB_MODE"] = "offline"
    project = c.load_toml("wandb.toml")
    run = wandb.init(project=project.get("project", "debris"), entity=project.get("entity") or None,
                     id=run_id, resume="allow", job_type="lab", dir=str(c.ROOT),
                     name=f"{round_name}-f{args.fold}" + (f"-s{args.seed}" if args.seed != 42 else ""),
                     group=round_name,
                     config={**{k: v for k, v in cfg.items() if k != "switches"},
                             **{f"switch/{k}": v for k, v in cfg["switches"].items()},
                             "fold": args.fold, "seed": args.seed, "round_name": round_name})
    c.log(f"wandb live: {args.experiment} f{args.fold} s{args.seed} -> {run.url or 'offline'}")
    last = 0
    while True:
        # A step can have a validation line and a training line; merge them and log each
        # step once. The newest step may still be half written, so it waits for the next
        # read unless training has reached its end.
        merged: dict[int, dict] = {}
        for point in production.parse_training_log(log) if log.exists() else []:
            merged.setdefault(point.pop("iter"), {}).update(point)
        steps = sorted(merged)
        done = bool(steps) and steps[-1] >= cfg["iters"]
        for step in steps if done else steps[:-1]:
            if step > last:   # wandb only takes steps that move forward
                run.log({f"train/{k}": v for k, v in merged[step].items()}, step=step)
                last = step
        if done:
            run.summary["curve_logged"] = True
            break
        time.sleep(args.poll)
    run.finish()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
