"""Shared helpers: paths, config, manifests, rate-limited HTTP, SQLite schema.

Manifest and tenacity-fetch patterns lifted from KINFOLK/BINMAN (see REUSE.md).
Every stage writes data/manifests/<stage>.jsonl so a killed run resumes.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import threading
import time
import tomllib
from pathlib import Path
from typing import Any, Iterable, Iterator

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
DATA = ROOT / "data"
RAW = DATA / "raw"
LABELS = DATA / "labels"
TRAIN = DATA / "train"
MANIFESTS = DATA / "manifests"
SNAPSHOTS = DATA / "snapshots"
ADAPTERS = DATA / "adapters"
DB_PATH = DATA / "debris.sqlite"
STATIC_DATA = ROOT / "app" / "static" / "data"

for _d in (RAW, LABELS, TRAIN, MANIFESTS, SNAPSHOTS, ADAPTERS, STATIC_DATA):
    _d.mkdir(parents=True, exist_ok=True)

USER_AGENT = "DEBRIS/1.0 (+https://debris.mdeller.com; mailto:marc@marcdeller.com)"


# --------------------------------------------------------------------------- config

def load_toml(name: str) -> dict:
    path = CONFIG / name
    if not path.exists():
        return {}
    return tomllib.loads(path.read_text())


def tuning() -> dict:
    return load_toml("tuning.toml")


def vocab() -> dict:
    return load_toml("vocab.toml")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def log(message: str) -> None:
    """One timestamped line to BUILD_LOG.md and to stdout."""
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"- {stamp} {message}"
    print(line, flush=True)
    with (ROOT / "BUILD_LOG.md").open("a") as fh:
        fh.write(line + "\n")


# ------------------------------------------------------------------------ manifests

def manifest_path(stage: str) -> Path:
    return MANIFESTS / f"{stage}.jsonl"


def manifest_write(stage: str, record: dict) -> None:
    with manifest_path(stage).open("a") as fh:
        fh.write(json.dumps(record, separators=(",", ":")) + "\n")


def manifest_read(stage: str) -> list[dict]:
    path = manifest_path(stage)
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def manifest_done(stage: str, key: str = "id") -> set[str]:
    """Keys already completed, so a restart skips them."""
    return {str(r[key]) for r in manifest_read(stage) if key in r}


def jsonl_write(path: Path, records: Iterable[dict], mode: str = "w") -> int:
    n = 0
    with Path(path).open(mode) as fh:
        for rec in records:
            fh.write(json.dumps(rec, separators=(",", ":"), ensure_ascii=False) + "\n")
            n += 1
    return n


def jsonl_read(path: Path) -> Iterator[dict]:
    p = Path(path)
    if not p.exists():
        return
    with p.open() as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


# ----------------------------------------------------------------------------- http

class RateLimiter:
    """Simple process-wide token spacing: NCBI allows 3/s without a key, 10/s with."""

    def __init__(self, per_second: float):
        self.interval = 1.0 / max(per_second, 0.1)
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            wait_for = self._next - time.monotonic()
            if wait_for > 0:
                time.sleep(wait_for)
            self._next = max(time.monotonic(), self._next) + self.interval


class TransientHTTP(Exception):
    pass


@retry(retry=retry_if_exception_type((TransientHTTP, requests.RequestException)),
       wait=wait_exponential(multiplier=1, min=1, max=30), stop=stop_after_attempt(5),
       reraise=True)
def http_get(url: str, params: dict | None = None, limiter: RateLimiter | None = None,
             timeout: int = 60, headers: dict | None = None) -> requests.Response:
    if limiter:
        limiter.wait()
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    resp = requests.get(url, params=params, timeout=timeout, headers=hdrs)
    if resp.status_code in (429, 500, 502, 503, 504):
        raise TransientHTTP(f"{resp.status_code} from {url}")
    return resp


def api_key(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


# --------------------------------------------------------------------------- sqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (pmid TEXT PRIMARY KEY, doi TEXT, doi_status TEXT,
  retracted INTEGER DEFAULT 0, title TEXT, abstract TEXT, journal TEXT, year INTEGER,
  month INTEGER, authors TEXT, mesh TEXT, pub_types TEXT, edat TEXT, hit_strategy TEXT,
  ingested_at TEXT, ingest_run TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS tags (pmid TEXT PRIMARY KEY REFERENCES papers(pmid), relevant INTEGER,
  size_class TEXT, model_type TEXT, pet_specific INTEGER, summary TEXT, confidence REAL,
  self_consistency REAL, tag_source TEXT, tag_json TEXT, tagged_at TEXT, model_version TEXT);
CREATE TABLE IF NOT EXISTS tag_polymers (pmid TEXT, polymer TEXT, PRIMARY KEY (pmid, polymer));
CREATE TABLE IF NOT EXISTS tag_organs   (pmid TEXT, organ_system TEXT, PRIMARY KEY (pmid, organ_system));
CREATE TABLE IF NOT EXISTS tag_diseases (pmid TEXT, disease_category TEXT, disease_term TEXT);
CREATE TABLE IF NOT EXISTS tag_pathways (pmid TEXT, pathway TEXT, PRIMARY KEY (pmid, pathway));
CREATE TABLE IF NOT EXISTS tag_rungs    (pmid TEXT, rung INTEGER, PRIMARY KEY (pmid, rung));
CREATE TABLE IF NOT EXISTS review_queue (pmid TEXT PRIMARY KEY, reason TEXT, queued_at TEXT, resolved_at TEXT);
CREATE TABLE IF NOT EXISTS novelty_events (id INTEGER PRIMARY KEY, pmid TEXT, kind TEXT, key TEXT, ingest_run TEXT);
CREATE TABLE IF NOT EXISTS ladder_events  (id INTEGER PRIMARY KEY, pmid TEXT, polymer TEXT,
  disease_category TEXT, new_max_rung INTEGER, ingest_run TEXT);
CREATE TABLE IF NOT EXISTS ingest_runs (run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT,
  harvested INTEGER, verified INTEGER, tagged INTEGER, queued INTEGER, novel INTEGER,
  model_version TEXT, inference_path TEXT);
CREATE TABLE IF NOT EXISTS drift_log (run_id TEXT, field TEXT, f1 REAL, n INTEGER);
CREATE TABLE IF NOT EXISTS vocab_candidates (field TEXT, value TEXT, count INTEGER, first_seen TEXT,
  PRIMARY KEY (field, value));
CREATE TABLE IF NOT EXISTS gold_set (key TEXT PRIMARY KEY, pmid TEXT, expect TEXT, title TEXT, resolved_at TEXT);
CREATE INDEX IF NOT EXISTS idx_papers_status    ON papers(status);
CREATE INDEX IF NOT EXISTS idx_papers_doistatus ON papers(doi_status);
CREATE INDEX IF NOT EXISTS idx_papers_year      ON papers(year);
CREATE INDEX IF NOT EXISTS idx_papers_edat      ON papers(edat);
CREATE INDEX IF NOT EXISTS idx_papers_run       ON papers(ingest_run);
CREATE INDEX IF NOT EXISTS idx_tags_relevant    ON tags(relevant);
CREATE INDEX IF NOT EXISTS idx_tags_model       ON tags(model_type);
CREATE INDEX IF NOT EXISTS idx_tags_pet         ON tags(pet_specific);
CREATE INDEX IF NOT EXISTS idx_polymers_polymer ON tag_polymers(polymer);
CREATE INDEX IF NOT EXISTS idx_organs_organ     ON tag_organs(organ_system);
CREATE INDEX IF NOT EXISTS idx_diseases_cat     ON tag_diseases(disease_category);
CREATE INDEX IF NOT EXISTS idx_diseases_pmid    ON tag_diseases(pmid);
CREATE INDEX IF NOT EXISTS idx_pathways_pathway ON tag_pathways(pathway);
CREATE INDEX IF NOT EXISTS idx_rungs_rung       ON tag_rungs(rung);
CREATE INDEX IF NOT EXISTS idx_novelty_run      ON novelty_events(ingest_run);
CREATE INDEX IF NOT EXISTS idx_ladder_run       ON ladder_events(ingest_run);
"""


def connect(path: Path | str | None = None, readonly: bool = False) -> sqlite3.Connection:
    """Open the serving database. The path is resolved at call time, not at import,
    so a test (or a weekly run against a staged copy) can point DB_PATH elsewhere."""
    path = DB_PATH if path is None else path
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(str(path), timeout=60)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: Path | str | None = None) -> None:
    conn = connect(path)
    with conn:
        conn.executescript(SCHEMA)
    conn.close()


def run_id(prefix: str = "run") -> str:
    return f"{prefix}-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def write_json(path: Path, payload: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
