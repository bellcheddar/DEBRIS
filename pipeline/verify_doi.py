"""Crossref DOI verification (spec 5.2).

A paper is admitted only when its DOI returns 200 from Crossref and the Crossref
title matches the PubMed title at token_set_ratio >= 90. Crossref `update-to`
retraction notices set retracted = 1; retracted papers are kept and struck
through in the app, never deleted.

  pixi run verify                  # every pending paper
  pixi run verify --run <run_id>   # only papers from one ingest run (weekly mode)
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import re

from rapidfuzz import fuzz

from pipeline import common as c

CROSSREF = "https://api.crossref.org/works/"
MATCH_FLOOR = 90


def normalise(title: str) -> str:
    """Strip markup, trailing full stops and bracketed translations before matching.

    Case is folded too: rapidfuzz's token_set_ratio is case-sensitive, and PubMed
    and Crossref disagree about title case often enough to cost real papers.
    """
    t = re.sub(r"<[^>]+>", " ", title or "")
    t = t.replace("’", "'").strip().rstrip(".")
    t = re.sub(r"^\[(.*)\]$", r"\1", t).strip()
    return re.sub(r"\s+", " ", t).casefold()


def check(pmid: str, doi: str | None, pubmed_title: str,
          lim: c.RateLimiter) -> tuple[str, str, int, str]:
    """Returns (pmid, doi_status, retracted, note)."""
    if not doi:
        return pmid, "missing", 0, "no DOI in PubMed record"
    try:
        resp = c.http_get(CROSSREF + doi, limiter=lim, timeout=45,
                          headers={"Accept": "application/json"})
    except Exception as exc:
        return pmid, "unresolved", 0, f"crossref error {type(exc).__name__}"
    if resp.status_code == 404:
        return pmid, "unresolved", 0, "404 at Crossref"
    if resp.status_code != 200:
        return pmid, "unresolved", 0, f"HTTP {resp.status_code}"
    try:
        msg = resp.json()["message"]
    except Exception:
        return pmid, "unresolved", 0, "unparseable Crossref payload"

    titles = msg.get("title") or []
    cr_title = normalise(titles[0]) if titles else ""
    score = fuzz.token_set_ratio(normalise(pubmed_title), cr_title) if cr_title else 0

    # A retraction notice carries update-to with type "retraction"; the retracted
    # work itself carries an "update-to" relation in the other direction.
    retracted = 0
    for upd in msg.get("update-to", []) or []:
        if "retract" in (upd.get("type") or "").lower():
            retracted = 1
    if "retract" in (msg.get("type") or "").lower():
        retracted = 1

    if score >= MATCH_FLOOR:
        return pmid, "verified", retracted, f"title match {score}"
    return pmid, "title_mismatch", retracted, f"title match {score} < {MATCH_FLOOR}"


def main() -> None:
    ap = argparse.ArgumentParser(description="Verify DOIs at Crossref")
    ap.add_argument("--run", default=None, help="limit to one ingest run")
    ap.add_argument("--recheck", action="store_true", help="recheck unresolved papers too")
    args = ap.parse_args()

    conn = c.connect()
    where = "doi_status IN ('pending','missing')" if not args.recheck \
        else "doi_status IN ('pending','missing','unresolved','title_mismatch')"
    params: list = []
    if args.run:
        where += " AND ingest_run = ?"
        params.append(args.run)
    rows = conn.execute(f"SELECT pmid, doi, title FROM papers WHERE {where}", params).fetchall()

    done = c.manifest_done("verify", key="pmid")
    todo = [r for r in rows if r["pmid"] not in done or args.recheck]
    c.log(f"verify: {len(todo)} papers to check at Crossref (polite pool, 10 req/s)")

    lim = c.RateLimiter(10)  # Crossref etiquette for the public pool with a mailto
    results: list[tuple[str, str, int, str]] = []
    workers = c.tuning().get("io_workers", 8)
    with futures.ThreadPoolExecutor(max_workers=workers) as pool:
        jobs = [pool.submit(check, r["pmid"], r["doi"], r["title"], lim) for r in todo]
        for i, job in enumerate(futures.as_completed(jobs), 1):
            res = job.result()
            results.append(res)
            c.manifest_write("verify", {"pmid": res[0], "status": res[1], "note": res[3],
                                        "at": c.now()})
            if i % 250 == 0:
                print(f"  verified {i}/{len(todo)}", flush=True)
                with conn:
                    conn.executemany("UPDATE papers SET doi_status=?, retracted=? WHERE pmid=?",
                                     [(s, r, p) for p, s, r, _ in results])
                results = []
    with conn:
        conn.executemany("UPDATE papers SET doi_status=?, retracted=? WHERE pmid=?",
                         [(s, r, p) for p, s, r, _ in results])

    funnel = dict(conn.execute("SELECT doi_status, COUNT(*) FROM papers GROUP BY doi_status").fetchall())
    retracted = conn.execute("SELECT COUNT(*) FROM papers WHERE retracted=1").fetchone()[0]
    verified = funnel.get("verified", 0)
    if args.run:
        with conn:
            conn.execute("UPDATE ingest_runs SET verified=? WHERE run_id=?",
                         (conn.execute("SELECT COUNT(*) FROM papers WHERE ingest_run=? AND doi_status='verified'",
                                       (args.run,)).fetchone()[0], args.run))
    c.log(f"verify: funnel {funnel}, retracted {retracted}, verified total {verified}")


if __name__ == "__main__":
    main()
