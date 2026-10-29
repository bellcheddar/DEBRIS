"""The weekly refresh (spec 5.6 and section 8, phase 4).

Harvest since the EDAT watermark, verify the new DOIs, tag the admitted papers,
score novelty, rebuild the aggregates, then record the run. Every stage is
resumable and a failure in one leaves last week's database serving untouched.

  python -m pipeline.weekly --remote   # tag through the Hugging Face Space (path A)
  python -m pipeline.weekly --local    # tag with the local mlx model (path B)
  python -m pipeline.weekly --dry-run  # the same, but roll the ingest back at the end
"""
from __future__ import annotations

import argparse
import datetime as dt
import shutil
import subprocess
import sys

from pipeline import common as c

LOOKBACK_DAYS = 10  # a little over a week, so a missed run still catches up


def stage(name: str, argv: list[str]) -> int:
    """Run one pipeline stage in this interpreter's environment."""
    cmd = [sys.executable, "-m", f"pipeline.{name}"] + argv
    c.log(f"weekly: {name} {' '.join(argv)}")
    proc = subprocess.run(cmd, cwd=str(c.ROOT))
    if proc.returncode != 0:
        c.log(f"weekly: {name} exited {proc.returncode}; continuing with what is in the database")
    return proc.returncode


def watermark(conn) -> int:
    """Days to look back: from the newest EDAT in the corpus, with a safety margin."""
    row = conn.execute("SELECT MAX(edat) FROM papers WHERE edat <> ''").fetchone()
    if not row or not row[0]:
        return LOOKBACK_DAYS
    try:
        newest = dt.date.fromisoformat(row[0])
    except ValueError:
        return LOOKBACK_DAYS
    return max(LOOKBACK_DAYS, (dt.date.today() - newest).days + 2)


def main() -> None:
    ap = argparse.ArgumentParser(description="DEBRIS weekly refresh")
    ap.add_argument("--remote", action="store_true", help="tag on the ZeroGPU Space (path A)")
    ap.add_argument("--local", action="store_true", help="tag with the local mlx model (path B)")
    ap.add_argument("--dry-run", action="store_true",
                    help="run everything, then remove this run's papers again")
    ap.add_argument("--since", type=int, default=None)
    args = ap.parse_args()

    c.init_db()
    conn = c.connect()
    run = c.run_id("weekly")
    since = args.since or watermark(conn)
    started = c.now()
    c.log(f"weekly: start {run}, looking back {since} days")

    with conn:
        conn.execute("""INSERT INTO ingest_runs (run_id,started_at,harvested) VALUES (?,?,0)
                        ON CONFLICT(run_id) DO NOTHING""", (run, started))

    snapshot = None
    if args.dry_run:
        snapshot = c.SNAPSHOTS / f"pre_{run}.sqlite"
        conn.commit()
        shutil.copy(c.DB_PATH, snapshot)
        c.log(f"weekly: dry run; database copied to {snapshot.name}")

    stage("harvest", ["--since", str(since), "--run-id", run])
    stage("verify_doi", ["--run", run])
    mode = "--remote" if args.remote or not args.local else "--local"
    stage("tag", [mode, "--run-id", run])
    stage("novelty", ["--run", run, "--reset"])
    stage("drift", ["--run", run])
    stage("aggregate", [])

    row = conn.execute("""SELECT harvested, verified, tagged, queued, novel
                          FROM ingest_runs WHERE run_id=?""", (run,)).fetchone()
    with conn:
        conn.execute("UPDATE ingest_runs SET finished_at=? WHERE run_id=?", (c.now(), run))
    c.log(f"weekly: done {run}: {dict(row) if row else {}}")

    if snapshot:
        conn.close()
        shutil.move(str(snapshot), str(c.DB_PATH))
        c.log("weekly: dry run rolled back; the database is as it was")
        stage("aggregate", [])


if __name__ == "__main__":
    main()
