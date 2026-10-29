"""DEBRIS web app (spec section 6).

Flask + Jinja, read-only SQLite, no request-time compute: every chart reads a
static JSON bundle written by pipeline/aggregate.py. SQLite is touched only for
the paginated Papers table and the paper detail drawer.

Structure lifted from CODSWALLOP and AlphaFraud (see REUSE.md); the design system
is Elora Therapeutics (spec 6.2).
"""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import tomllib
from pathlib import Path

from flask import Flask, Response, abort, g, jsonify, render_template, request

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("DEBRIS_DB", ROOT / "data" / "debris.sqlite"))
STATIC_DATA = Path(__file__).resolve().parent / "static" / "data"

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

TABS = [("01", "Atlas", "/"), ("02", "Body", "/body"),
        ("03", "Pathways", "/pathways"), ("04", "Papers", "/papers")]


# ----------------------------------------------------------------------- plumbing

def db() -> sqlite3.Connection:
    if "db" not in g:
        if not DB_PATH.exists():
            abort(503, "database not present")
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_exc) -> None:
    if conn := g.pop("db", None):
        conn.close()


def load_bundle(name: str) -> dict:
    """Static aggregate read fresh each request: a weekly swap needs no restart."""
    path = STATIC_DATA / f"{name}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def vocab() -> dict:
    path = ROOT / "config" / "vocab.toml"
    return tomllib.loads(path.read_text()) if path.exists() else {}


def asset_version(relative: str) -> int:
    """mtime cache buster, so a changed asset refetches and the rest cache hard."""
    path = Path(app.static_folder) / relative
    return int(path.stat().st_mtime) if path.exists() else 0


@app.context_processor
def template_globals() -> dict:
    meta = load_bundle("meta")
    return {"tabs": TABS, "meta": meta, "vocab": vocab(), "asset_version": asset_version}


# -------------------------------------------------------------------------- pages

@app.route("/")
def atlas():
    return render_template("atlas.html", active="/", bundle=load_bundle("atlas"))


@app.route("/body")
def body():
    return render_template("body.html", active="/body", bundle=load_bundle("body"))


@app.route("/pathways")
def pathways():
    return render_template("pathways.html", active="/pathways", bundle=load_bundle("pathways"))


@app.route("/papers")
def papers():
    return render_template("papers.html", active="/papers", bundle=load_bundle("feed"))


# ---------------------------------------------------------------------------- api

PAPER_COLUMNS = """p.pmid, p.doi, p.doi_status, p.retracted, p.title, p.journal, p.year,
  p.hit_strategy, p.status, t.relevant, t.size_class, t.model_type, t.pet_specific,
  t.summary, t.confidence, t.self_consistency, t.tag_source"""


def paper_filters(args) -> tuple[str, list]:
    """WHERE clause shared by /api/papers and the CSV download."""
    clauses = ["p.status <> 'no_abstract' OR p.abstract <> ''"]
    params: list = []
    if args.get("unverified", "0") not in ("1", "true"):
        clauses.append("p.doi_status = 'verified'")
    # Untagged corpora (phase 1) must still list; relevance filters only once tagged.
    if args.get("include_irrelevant", "0") not in ("1", "true"):
        clauses.append("(t.relevant IS NULL OR t.relevant = 1)")
    for field, column in (("polymer", "tag_polymers.polymer"),
                          ("organ", "tag_organs.organ_system"),
                          ("disease", "tag_diseases.disease_category"),
                          ("pathway", "tag_pathways.pathway")):
        if value := args.get(field):
            table = column.split(".")[0]
            clauses.append(f"p.pmid IN (SELECT pmid FROM {table} WHERE {column} = ?)")
            params.append(value)
    # Venn click-throughs: polymers=PET|PE,PP means "has PET and has PE or PP",
    # not_polymers=PS,PVC means "has none of these". organs= is any-of.
    if groups := args.get("polymers"):
        for group in [g for g in groups.split("|") if g.strip()]:
            members = [m.strip() for m in group.split(",") if m.strip()]
            if not members:
                continue
            marks = ",".join("?" * len(members))
            clauses.append(f"p.pmid IN (SELECT pmid FROM tag_polymers WHERE polymer IN ({marks}))")
            params.extend(members)
    if excluded := args.get("not_polymers"):
        members = [m.strip() for m in excluded.split(",") if m.strip()]
        if members:
            marks = ",".join("?" * len(members))
            clauses.append(f"p.pmid NOT IN (SELECT pmid FROM tag_polymers WHERE polymer IN ({marks}))")
            params.extend(members)
    if organs := args.get("organs"):
        members = [m.strip() for m in organs.split(",") if m.strip()]
        if members:
            marks = ",".join("?" * len(members))
            clauses.append(f"p.pmid IN (SELECT pmid FROM tag_organs WHERE organ_system IN ({marks}))")
            params.extend(members)
    if rung := args.get("rung"):
        clauses.append("p.pmid IN (SELECT pmid FROM tag_rungs WHERE rung = ?)")
        params.append(int(rung))
    if args.get("pet", "0") in ("1", "true"):
        clauses.append("t.pet_specific = 1")
    if args.get("review", "0") in ("1", "true"):
        clauses.append("p.pmid IN (SELECT pmid FROM review_queue WHERE resolved_at IS NULL)")
    if args.get("new", "0") in ("1", "true"):
        clauses.append("p.ingest_run = (SELECT run_id FROM ingest_runs ORDER BY started_at DESC LIMIT 1)")
    if args.get("novel", "0") in ("1", "true"):
        clauses.append("p.pmid IN (SELECT pmid FROM novelty_events)")
    if search := (args.get("q") or "").strip():
        clauses.append("(p.title LIKE ? OR t.summary LIKE ? OR p.journal LIKE ? OR p.pmid = ?)")
        like = f"%{search}%"
        params.extend([like, like, like, search])
    return " AND ".join(f"({cl})" for cl in clauses), params


@app.route("/api/papers")
def api_papers():
    where, params = paper_filters(request.args)
    page = max(1, int(request.args.get("page", 1)))
    size = min(200, max(1, int(request.args.get("size", 50))))
    sort = request.args.get("sort", "year")
    order = "ASC" if request.args.get("dir", "desc").lower() == "asc" else "DESC"
    sort_column = {"year": "p.year", "pmid": "p.pmid", "journal": "p.journal",
                   "title": "p.title", "confidence": "t.confidence"}.get(sort, "p.year")

    conn = db()
    total = conn.execute(f"SELECT COUNT(*) FROM papers p LEFT JOIN tags t USING (pmid) "
                         f"WHERE {where}", params).fetchone()[0]
    rows = conn.execute(
        f"""SELECT {PAPER_COLUMNS} FROM papers p LEFT JOIN tags t USING (pmid)
            WHERE {where} ORDER BY {sort_column} {order}, p.pmid DESC LIMIT ? OFFSET ?""",
        params + [size, (page - 1) * size]).fetchall()
    pmids = [r["pmid"] for r in rows]
    polymers = organs = rungs = {}
    if pmids:
        marks = ",".join("?" * len(pmids))
        polymers = collect(conn, f"SELECT pmid, polymer FROM tag_polymers WHERE pmid IN ({marks})", pmids)
        organs = collect(conn, f"SELECT pmid, organ_system FROM tag_organs WHERE pmid IN ({marks})", pmids)
        rungs = collect(conn, f"SELECT pmid, rung FROM tag_rungs WHERE pmid IN ({marks})", pmids)
    data = []
    for r in rows:
        item = dict(r)
        item["polymers"] = polymers.get(r["pmid"], [])
        item["organ_systems"] = organs.get(r["pmid"], [])
        item["rungs"] = sorted(rungs.get(r["pmid"], []))
        data.append(item)
    return jsonify({"last_page": max(1, -(-total // size)), "last_row": total, "data": data})


def collect(conn, sql: str, params: list) -> dict[str, list]:
    out: dict[str, list] = {}
    for pmid, value in conn.execute(sql, params):
        out.setdefault(pmid, []).append(value)
    return out


@app.route("/paper/<pmid>")
def paper_detail(pmid: str):
    conn = db()
    row = conn.execute(
        """SELECT p.*, t.relevant, t.size_class, t.model_type, t.pet_specific, t.summary,
                  t.confidence, t.self_consistency, t.tag_source, t.tag_json, t.model_version,
                  t.tagged_at
           FROM papers p LEFT JOIN tags t USING (pmid) WHERE p.pmid = ?""", (pmid,)).fetchone()
    if not row:
        abort(404)
    item = dict(row)
    item["polymers"] = [r[0] for r in conn.execute(
        "SELECT polymer FROM tag_polymers WHERE pmid=?", (pmid,))]
    item["organ_systems"] = [r[0] for r in conn.execute(
        "SELECT organ_system FROM tag_organs WHERE pmid=?", (pmid,))]
    item["pathways"] = [r[0] for r in conn.execute(
        "SELECT pathway FROM tag_pathways WHERE pmid=?", (pmid,))]
    item["rungs"] = [r[0] for r in conn.execute(
        "SELECT rung FROM tag_rungs WHERE pmid=? ORDER BY rung", (pmid,))]
    item["diseases"] = [{"category": r[0], "term": r[1]} for r in conn.execute(
        "SELECT disease_category, disease_term FROM tag_diseases WHERE pmid=?", (pmid,))]
    item["review"] = conn.execute(
        "SELECT reason, queued_at, resolved_at FROM review_queue WHERE pmid=?", (pmid,)).fetchone()
    item["review"] = dict(item["review"]) if item["review"] else None
    item["novelty"] = [{"kind": r[0], "key": r[1]} for r in conn.execute(
        "SELECT kind, key FROM novelty_events WHERE pmid=?", (pmid,))]
    if item.get("tag_json"):
        try:
            item["tag"] = json.loads(item["tag_json"])
        except json.JSONDecodeError:
            item["tag"] = None
    return jsonify(item)


@app.route("/download/debris_latest.csv")
def download_csv():
    where, params = paper_filters(request.args)
    conn = db()
    rows = conn.execute(
        f"""SELECT p.pmid, p.doi, p.doi_status, p.retracted, p.title, p.journal, p.year,
                   t.relevant, t.size_class, t.model_type, t.pet_specific, t.confidence,
                   t.self_consistency, t.summary,
                   (SELECT GROUP_CONCAT(polymer) FROM tag_polymers WHERE pmid=p.pmid) AS polymers,
                   (SELECT GROUP_CONCAT(organ_system) FROM tag_organs WHERE pmid=p.pmid) AS organ_systems,
                   (SELECT GROUP_CONCAT(DISTINCT disease_category) FROM tag_diseases WHERE pmid=p.pmid) AS disease_categories,
                   (SELECT GROUP_CONCAT(pathway) FROM tag_pathways WHERE pmid=p.pmid) AS pathways,
                   (SELECT GROUP_CONCAT(rung) FROM tag_rungs WHERE pmid=p.pmid) AS evidence_rungs
            FROM papers p LEFT JOIN tags t USING (pmid) WHERE {where} ORDER BY p.year DESC, p.pmid""",
        params).fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    if rows:
        writer.writerow(rows[0].keys())
        writer.writerows([tuple(r) for r in rows])
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=debris_latest.csv"})


@app.route("/healthz")
def healthz():
    meta = load_bundle("meta")
    payload = {"status": "ok", "last_ingest": meta.get("last_ingest"),
               "papers": meta.get("verified_papers"), "tagged": meta.get("tagged_papers"),
               "inference_path": meta.get("inference_path"),
               "model_version": meta.get("model_version"),
               "database": DB_PATH.exists()}
    try:
        payload["papers_in_db"] = db().execute("SELECT COUNT(*) FROM papers").fetchone()[0]
    except Exception as exc:
        payload["status"] = "degraded"
        payload["error"] = type(exc).__name__
    return jsonify(payload)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5055)), debug=True)
