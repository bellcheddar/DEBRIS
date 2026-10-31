"""Shared helpers: paths, config, manifests, rate-limited HTTP, SQLite schema.

Manifest and tenacity-fetch patterns lifted from KINFOLK/BINMAN (see REUSE.md).
Every stage writes data/manifests/<stage>.jsonl so a killed run resumes.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
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

# A paper whose only harvest strategy is `negative` was pulled in on purpose as a hard
# negative for the tagger: positron emission tomography, CT, Dacron grafts, silicone
# implants. Those are real published papers and they verify at Crossref like any other,
# so they stay in the database because validate.py proves the tagger refuses them. They
# are not part of the evidence map. The exclusion is on provenance rather than on the
# tag, so a control cannot reach the site even if the tagger wrongly calls it relevant.
# A paper that a real strategy also found keeps its place: `textword,negative` is corpus.
CORPUS_STRATEGY = "negative"


def corpus_clause(alias: str = "p") -> str:
    """The SQL every published count and listing filters on. See CORPUS_STRATEGY."""
    at = f"{alias}." if alias else ""
    return (f"{at}doi_status = 'verified' "
            f"AND COALESCE({at}hit_strategy, '') <> '{CORPUS_STRATEGY}'")


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


# What the v2 tagger can write beyond vocab.toml (D50). vocab.toml itself stays as it is,
# because the tagger's prompt is built from its lists and must not drift from training.
V2_PATHWAYS = {"lipid_metabolism": "Lipid metabolism", "er_stress_autophagy": "ER stress and autophagy",
               "endocrine_disruption": "Endocrine disruption", "other_pathway": "Other mechanisms"}
V2_FAMILIES = {"PA6": "Engineering", "PA66": "Engineering", "PBAT": "Polyesters"}
# The evidence levels as the site names them (owner, 2026-10-31: no "rungs" on the site).
EVIDENCE_LABELS = {"1": "Found in people", "2": "Linked to outcomes in people", "3": "Shown in animals", "4": "Mechanism in cells or tissue", "5": "Dose-response", "6": "Reversible"}


def display_vocab() -> dict:
    """vocab.toml with the v2 values the app has to show: PA6, PA66 and PBAT, the promoted
    pathways and the rare-pathway class, cell-free studies, and the 18 tissues."""
    v = vocab()
    v2 = load_toml("vocab_v2.toml")
    v["polymers"] = list(v2["polymers"])
    for table in ("polymer_labels", "polymer_short"):
        v[table] = {**v.get(table, {}), **v2.get(table, {})}
    v["polymer_families"] = {**v.get("polymer_families", {}), **V2_FAMILIES}
    v["pathways"] = list(v["pathways"]) + [p for p in V2_PATHWAYS if p not in v["pathways"]]
    v["pathway_labels"] = {**v.get("pathway_labels", {}), **V2_PATHWAYS}
    if "cell_free" not in v["model_types"]:
        types = [t for t in v["model_types"] if t != "not_applicable"]
        v["model_types"] = types + ["cell_free", "not_applicable"]
    v["model_type_labels"] = {**v.get("model_type_labels", {}),
                              "cell_free": "Cell-free (simulated fluids)"}
    for key in ("tissues", "tissue_labels", "tissue_system", "tissue_parent"):
        v[key] = v2.get(key, {} if key != "tissues" else [])
    v["evidence_labels"] = dict(EVIDENCE_LABELS)
    return v


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def log(message: str) -> None:
    """One timestamped line to BUILD_LOG.md and to stdout.

    DEBRIS_LOG repoints the file so a test run does not write into the real build
    log; the resolution happens per call, like DB_PATH in connect().
    """
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"- {stamp} {message}"
    print(line, flush=True)
    target = Path(os.environ.get("DEBRIS_LOG", ROOT / "BUILD_LOG.md"))
    with target.open("a") as fh:
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
    if value:
        return value
    if name == "HF_TOKEN":
        # `hf auth login` stores its token under the Hugging Face cache rather than in the
        # environment, and it is the route that keeps the secret out of a shell history or
        # a file in the repo, so honour it.
        try:
            from huggingface_hub import get_token
        except ImportError:
            return None
        return (get_token() or "").strip() or None
    return None


def wandb_api_key() -> str | None:
    """wandb's credential, from the environment or from `wandb login`.

    `wandb login` writes to ~/.netrc and wandb reads it natively, so an unset
    WANDB_API_KEY does not mean there is no credential. Treating it as one is what put
    five training runs offline when the account was reachable all along (D28).
    """
    key = api_key("WANDB_API_KEY")
    if key:
        return key
    try:
        import wandb
        return wandb.api.api_key or None
    except Exception:
        return None


ROUND_PATTERN = re.compile(r"-round(\d+)")


def model_stem(model_id: str) -> str:
    """`qwen-2.5-3b` from `Qwen/Qwen2.5-3B-Instruct`.

    The run-name convention is {project}-{model}-{ver}-{parameters}-round{NN}, so the
    family, its version and its size are separated and the instruct suffix dropped.
    Quantisation is appended by the caller when the base weights are quantised; these
    fine-tunes run on the full-precision model, so there is nothing to add.
    """
    name = model_id.rstrip("/").split("/")[-1].lower().replace("-instruct", "")
    match = re.match(r"^([a-z]+)([\d.]+)[-_]?(.*)$", name)
    if not match:
        return name
    family, version, rest = match.groups()
    return "-".join(part for part in (family, version, rest) if part)


def wandb_round(project: str, entity: str | None = None) -> int:
    """The next round number, read from the wandb project itself.

    A local counter goes wrong across machines and after a clone, and the convention is
    that a round is never reused and never restarts at 01 for a project that already has
    runs. The fallback counts what is on disk, which is the best available answer when
    the server cannot be reached.
    """
    highest = 0
    try:
        import wandb
        api = wandb.Api()
        for run in api.runs(f"{entity or api.default_entity}/{project}", per_page=100):
            for text in (run.name or "", (run.config or {}).get("round_name", "")):
                found = ROUND_PATTERN.search(text or "")
                if found:
                    highest = max(highest, int(found.group(1)))
    except Exception as exc:
        log(f"wandb: could not read the round number from the project ({type(exc).__name__}); "
            f"counting the local run directories instead")
        for path in (ROOT / "wandb").glob("*run-*"):
            found = ROUND_PATTERN.search(path.name)
            if found:
                highest = max(highest, int(found.group(1)))
    return highest + 1


def wandb_run_name(project: str, model_id: str, round_number: int) -> str:
    return f"{project}-{model_stem(model_id)}-round{round_number:02d}"


def token_expiry(token: str) -> str | None:
    """When a Hugging Face credential stops working, or None if it does not.

    An OAuth credential from a browser login carries an expiry a few days out. That is
    fine for a one-off push and useless for a timer that has to fire every Sunday, and
    the weekly runner logs a failed stage and carries on, so the symptom of an expired
    token is a site quietly serving untagged papers rather than an error (D26).
    """
    try:
        from huggingface_hub import HfApi
        auth = HfApi().whoami(token=token).get("auth", {})
    except Exception as exc:
        log(f"hf: could not check the token's expiry ({type(exc).__name__})")
        return None
    return auth.get("expiresAt")


# --------------------------------------------------------------------------- sqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (pmid TEXT PRIMARY KEY, doi TEXT, doi_status TEXT,
  retracted INTEGER DEFAULT 0, title TEXT, abstract TEXT, journal TEXT, year INTEGER,
  month INTEGER, authors TEXT, mesh TEXT, pub_types TEXT, edat TEXT, hit_strategy TEXT,
  ingested_at TEXT, ingest_run TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS tags (pmid TEXT PRIMARY KEY REFERENCES papers(pmid), relevant INTEGER,
  size_class TEXT, model_type TEXT, pet_specific INTEGER, summary TEXT, confidence REAL,
  self_consistency REAL, tag_source TEXT, tag_json TEXT, tagged_at TEXT, model_version TEXT,
  token_prob REAL);
CREATE TABLE IF NOT EXISTS tag_polymers (pmid TEXT, polymer TEXT, PRIMARY KEY (pmid, polymer));
CREATE TABLE IF NOT EXISTS tag_organs   (pmid TEXT, organ_system TEXT, PRIMARY KEY (pmid, organ_system));
CREATE TABLE IF NOT EXISTS tag_diseases (pmid TEXT, disease_category TEXT, disease_term TEXT);
CREATE TABLE IF NOT EXISTS tag_pathways (pmid TEXT, pathway TEXT, PRIMARY KEY (pmid, pathway));
CREATE TABLE IF NOT EXISTS tag_tissues (pmid TEXT, tissue TEXT, PRIMARY KEY (pmid, tissue));
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


# Columns added after a database was first built: (table, column, type).
ADDED_COLUMNS = (("tags", "token_prob", "REAL"),)   # hybrid confidence (D45)


def migrate(conn: sqlite3.Connection) -> None:
    # Tables added since a database was created (the v2 tissues, D55); every statement in
    # SCHEMA is IF NOT EXISTS.
    conn.executescript(SCHEMA)
    for table, column, kind in ADDED_COLUMNS:
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if have and column not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


def init_db(path: Path | str | None = None) -> None:
    conn = connect(path)
    with conn:
        conn.executescript(SCHEMA)
        migrate(conn)
    conn.close()


def run_id(prefix: str = "run") -> str:
    return f"{prefix}-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def write_json(path: Path, payload: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
