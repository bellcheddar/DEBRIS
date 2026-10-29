"""PubMed harvest (spec 5.1 and 5.3).

Two strategies unioned (MeSH and text word), the gold seed set and the negatives,
all resolved by search at run time. efetch in batches of 200; results land in
data/raw/pubmed_<date>.jsonl and the papers table.

  pixi run harvest                 # full harvest from config/query.toml start_year
  pixi run harvest --since 7       # weekly mode: only records with EDAT in the last 7 days
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import xml.etree.ElementTree as ET

from pipeline import common as c

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def limiter() -> c.RateLimiter:
    key = c.api_key("NCBI_API_KEY")
    return c.RateLimiter(10 if key else c.tuning().get("ncbi_rate_per_second", 3))


def eutils_params(extra: dict) -> dict:
    q = c.load_toml("query.toml")
    params = {"db": "pubmed", "tool": q.get("tool_name", "DEBRIS"),
              "email": q.get("contact_email", "marc@marcdeller.com"), "retmode": "xml"}
    if key := c.api_key("NCBI_API_KEY"):
        params["api_key"] = key
    params.update(extra)
    return params


def esearch(term: str, lim: c.RateLimiter, retmax: int = 10000,
            sort: str | None = None, reldate: int | None = None) -> list[str]:
    """All PMIDs for a term, paging through retstart in 10k blocks."""
    pmids: list[str] = []
    retstart = 0
    while True:
        extra = {"term": term, "retmax": min(retmax, 10000), "retstart": retstart}
        if sort:
            extra["sort"] = sort
        if reldate:
            extra["reldate"] = reldate
            extra["datetype"] = "edat"
        resp = c.http_get(f"{EUTILS}/esearch.fcgi", eutils_params(extra), limiter=lim)
        root = ET.fromstring(resp.content)
        batch = [e.text for e in root.findall(".//IdList/Id") if e.text]
        pmids.extend(batch)
        total = int((root.findtext("Count") or "0"))
        retstart += len(batch)
        if not batch or retstart >= min(total, retmax):
            break
    return pmids


def text_of(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", "".join(node.itertext())).strip()


def parse_article(art: ET.Element) -> dict | None:
    pmid = art.findtext(".//MedlineCitation/PMID")
    if not pmid:
        return None
    citation = art.find("MedlineCitation")
    article = citation.find("Article") if citation is not None else None
    if article is None:
        return None

    # Labelled abstracts keep their section headings, which help the tagger.
    parts = []
    for ab in article.findall(".//Abstract/AbstractText"):
        label = ab.get("Label")
        body = text_of(ab)
        if body:
            parts.append(f"{label}: {body}" if label else body)
    abstract = " ".join(parts)

    pubdate = article.find(".//Journal/JournalIssue/PubDate")
    year = month = None
    if pubdate is not None:
        ytext = pubdate.findtext("Year") or ""
        if not ytext:
            medline = pubdate.findtext("MedlineDate") or ""
            m = re.search(r"(19|20)\d{2}", medline)
            ytext = m.group(0) if m else ""
        year = int(ytext) if ytext.isdigit() else None
        mtext = (pubdate.findtext("Month") or "").strip()
        months = {m: i for i, m in enumerate(
            ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
        month = int(mtext) if mtext.isdigit() else months.get(mtext[:3])

    authors = []
    for a in article.findall(".//AuthorList/Author"):
        last, initials = a.findtext("LastName"), a.findtext("Initials")
        if last:
            authors.append(f"{last} {initials}" if initials else last)
        elif coll := a.findtext("CollectiveName"):
            authors.append(coll)

    doi = None
    for eid in art.findall(".//ArticleIdList/ArticleId"):
        if eid.get("IdType") == "doi" and eid.text:
            doi = eid.text.strip().lower()
    if not doi:
        for eloc in article.findall("ELocationID"):
            if eloc.get("EIdType") == "doi" and eloc.text:
                doi = eloc.text.strip().lower()

    mesh = [text_of(d.find("DescriptorName")) for d in citation.findall(".//MeshHeadingList/MeshHeading")]
    pub_types = [text_of(p) for p in article.findall(".//PublicationTypeList/PublicationType")]

    edat = ""
    for pubmed_date in art.findall(".//PubmedData/History/PubMedPubDate"):
        if pubmed_date.get("PubStatus") == "entrez":
            y, m, d = (pubmed_date.findtext(k) or "" for k in ("Year", "Month", "Day"))
            if y:
                edat = f"{int(y):04d}-{int(m or 1):02d}-{int(d or 1):02d}"

    return {
        "pmid": pmid,
        "doi": doi,
        "title": text_of(article.find("ArticleTitle")),
        "abstract": abstract,
        "journal": article.findtext(".//Journal/ISOAbbreviation") or article.findtext(".//Journal/Title") or "",
        "year": year,
        "month": month,
        "authors": authors,
        "mesh": [m for m in mesh if m],
        "pub_types": pub_types,
        "edat": edat,
    }


def efetch(pmids: list[str], lim: c.RateLimiter, batch: int = 200) -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(pmids), batch):
        chunk = pmids[i:i + batch]
        try:
            resp = c.http_get(f"{EUTILS}/efetch.fcgi",
                              eutils_params({"id": ",".join(chunk), "rettype": "abstract"}),
                              limiter=lim, timeout=120)
            root = ET.fromstring(resp.content)
        except Exception as exc:  # degrade: one batch never blocks the harvest
            c.log(f"harvest: efetch batch {i // batch} failed ({exc}); skipped {len(chunk)} PMIDs")
            continue
        for art in root.findall(".//PubmedArticle"):
            rec = parse_article(art)
            if rec:
                out.append(rec)
        print(f"  efetch {min(i + batch, len(pmids))}/{len(pmids)}", flush=True)
    return out


def resolve_gold(lim: c.RateLimiter, conn) -> list[dict]:
    """Resolve the gold seed set by search; log what was found (spec 5.3)."""
    q = c.load_toml("query.toml")
    found = []
    for entry in q.get("gold", []):
        try:
            pmids = esearch(entry["term"], lim, retmax=5, sort=entry.get("sort"))
        except Exception as exc:
            c.log(f"harvest: gold '{entry['key']}' search failed ({exc})")
            continue
        if not pmids:
            c.log(f"harvest: gold '{entry['key']}' not found ({entry['expect']})")
            continue
        found.append({"key": entry["key"], "pmid": pmids[0], "expect": entry["expect"],
                      "candidates": pmids})
    return found


def strategy_pmids(lim: c.RateLimiter, since_days: int | None) -> dict[str, list[str]]:
    q = c.load_toml("query.toml")
    hits: dict[str, list[str]] = {}
    for name, strat in q["strategies"].items():
        pmids = esearch(strat["term"], lim, reldate=since_days)
        hits[name] = pmids
        c.log(f"harvest: strategy {strat['label']} returned {len(pmids)} PMIDs"
              + (f" (last {since_days} days)" if since_days else ""))
    return hits


def negatives_pmids(lim: c.RateLimiter) -> list[str]:
    q = c.load_toml("query.toml")
    out: list[str] = []
    for neg in q.get("negatives", []):
        pmids = esearch(neg["term"], lim, retmax=neg.get("retmax", 100))[: neg.get("retmax", 100)]
        c.log(f"harvest: negatives '{neg['key']}' returned {len(pmids)} PMIDs")
        out.extend(pmids)
    return out


def store(records: list[dict], strategies: dict[str, set[str]], negatives: set[str],
          ingest_run: str, conn) -> tuple[int, int]:
    """Insert or update papers. Returns (new, updated)."""
    new = updated = 0
    existing = {r[0] for r in conn.execute("SELECT pmid FROM papers")}
    rows = []
    for rec in records:
        pmid = rec["pmid"]
        hits = sorted(name for name, pmids in strategies.items() if pmid in pmids)
        if pmid in negatives:
            hits.append("negative")
        status = "harvested" if rec["abstract"] else "no_abstract"
        rows.append((pmid, rec["doi"], "missing" if not rec["doi"] else "pending", 0,
                     rec["title"], rec["abstract"], rec["journal"], rec["year"], rec["month"],
                     "; ".join(rec["authors"]), "; ".join(rec["mesh"]), "; ".join(rec["pub_types"]),
                     rec["edat"], ",".join(hits) or "unknown", c.now(), ingest_run, status))
        if pmid in existing:
            updated += 1
        else:
            new += 1
    with conn:
        conn.executemany(
            """INSERT INTO papers (pmid,doi,doi_status,retracted,title,abstract,journal,year,month,
                 authors,mesh,pub_types,edat,hit_strategy,ingested_at,ingest_run,status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(pmid) DO UPDATE SET
                 doi=COALESCE(excluded.doi, papers.doi), title=excluded.title,
                 abstract=excluded.abstract, journal=excluded.journal, year=excluded.year,
                 month=excluded.month, authors=excluded.authors, mesh=excluded.mesh,
                 pub_types=excluded.pub_types, edat=excluded.edat,
                 hit_strategy=excluded.hit_strategy,
                 status=CASE WHEN papers.status IN ('harvested','no_abstract')
                             THEN excluded.status ELSE papers.status END""", rows)
    return new, updated


def main() -> None:
    ap = argparse.ArgumentParser(description="Harvest PubMed for DEBRIS")
    ap.add_argument("--since", type=int, default=None,
                    help="only records entered in the last N days (weekly mode)")
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--skip-negatives", action="store_true")
    args = ap.parse_args()

    c.init_db()
    conn = c.connect()
    ingest_run = args.run_id or c.run_id("harvest")
    lim = limiter()
    key_note = "with NCBI key" if c.api_key("NCBI_API_KEY") else "no NCBI key, 3 req/s"
    c.log(f"harvest: start {ingest_run} ({key_note})")

    strategies = {name: set(pmids) for name, pmids in strategy_pmids(lim, args.since).items()}
    union = set().union(*strategies.values()) if strategies else set()

    gold = []
    negatives: set[str] = set()
    if args.since is None:
        gold = resolve_gold(lim, conn)
        with conn:
            conn.executemany(
                "INSERT INTO gold_set (key,pmid,expect,title,resolved_at) VALUES (?,?,?,'',?) "
                "ON CONFLICT(key) DO UPDATE SET pmid=excluded.pmid, resolved_at=excluded.resolved_at",
                [(g["key"], g["pmid"], g["expect"], c.now()) for g in gold])
        union |= {g["pmid"] for g in gold}
        if not args.skip_negatives:
            negatives = set(negatives_pmids(lim))
            union |= negatives
        c.log(f"harvest: gold set resolved {len(gold)}/9, negatives {len(negatives)}")

    # Resume: skip PMIDs already fetched in a previous pass of this same run.
    done = c.manifest_done("harvest", key="pmid")
    todo = sorted(union - done) if args.since is None else sorted(union)
    c.log(f"harvest: union {len(union)} PMIDs, {len(todo)} to fetch")

    records = efetch(todo, lim)
    stamp = dt.date.today().isoformat()
    c.jsonl_write(c.RAW / f"pubmed_{stamp}.jsonl", records, mode="a")
    new, updated = store(records, strategies, negatives, ingest_run, conn)
    for rec in records:
        c.manifest_write("harvest", {"pmid": rec["pmid"], "run": ingest_run, "at": c.now()})

    with conn:
        conn.execute("""INSERT INTO ingest_runs (run_id,started_at,harvested) VALUES (?,?,?)
                        ON CONFLICT(run_id) DO UPDATE SET harvested=excluded.harvested""",
                     (ingest_run, c.now(), len(records)))
    counts = dict(conn.execute("SELECT status, COUNT(*) FROM papers GROUP BY status").fetchall())
    c.log(f"harvest: done {ingest_run}: fetched {len(records)}, new {new}, updated {updated}, "
          f"table {dict(counts)}")
    print(ingest_run)


if __name__ == "__main__":
    main()
