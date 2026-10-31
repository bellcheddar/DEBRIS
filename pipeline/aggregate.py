"""Aggregate every chart's data to app/static/data/*.json (spec 6.1).

The app does no request-time compute: this script is the only thing that reads the
whole corpus. It is safe to run on an untagged corpus (phase 1), when it writes the
counts the Papers tab needs and leaves the tagged views empty.

  pixi run aggregate
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt

from pipeline import common as c

V = c.display_vocab()
CORPUS = c.corpus_clause()
CORPUS_ANY = c.corpus_clause("")


def latest_run(conn) -> str | None:
    row = conn.execute("""SELECT run_id FROM ingest_runs WHERE harvested > 0
                          ORDER BY started_at DESC LIMIT 1""").fetchone()
    return row[0] if row else None


def verified_pmids(conn, pet_only: bool = False, organs: list[str] | None = None) -> set[str]:
    sql = ["SELECT p.pmid FROM papers p LEFT JOIN tags t USING (pmid)",
           f"WHERE {CORPUS} AND (t.relevant IS NULL OR t.relevant = 1)"]
    params: list = []
    if pet_only:
        sql.append("AND t.pet_specific = 1")
    if organs:
        marks = ",".join("?" * len(organs))
        sql.append(f"AND p.pmid IN (SELECT pmid FROM tag_organs WHERE organ_system IN ({marks}))")
        params.extend(organs)
    return {r[0] for r in conn.execute(" ".join(sql), params)}


def facet_map(conn, sql: str) -> dict[str, set]:
    """pmid to the set of values one tagged field holds, from a two-column query."""
    out: dict[str, set] = collections.defaultdict(set)
    try:
        for pmid, value in conn.execute(sql):
            out[pmid].add(value)
    except Exception:   # a database from before the field existed (tag_tissues, D55)
        pass
    return out


def facet_kpis(pmids: set[str], pet_pmids: set[str], facets: dict[str, dict]) -> dict:
    """The Atlas headline figures for one set of papers: how many, how many PET-specific
    or human, and how much of each tagged field they cover."""
    covered = {name: set().union(*(m.get(p, set()) for p in pmids)) if pmids else set()
               for name, m in facets.items()}
    covered["models"].discard("not_applicable")
    return {"verified": len(pmids), "pet": len(pmids & pet_pmids),
            "human": sum(1 for p in pmids if facets["rungs"].get(p, set()) & {1, 2}),
            "polymer_count": len({v for v in covered["polymer_set"] if v in VOCAB_POLYMERS}),
            "organs": len(covered["organs"]),
            "tissues": len({t for t in covered["tissues"] if t in VOCAB_TISSUES}),
            "pathways": len({v for v in covered["pathways"] if v in VOCAB_PATHWAYS}),
            "models": len(covered["models"])}


def polymer_map(conn) -> dict[str, set[str]]:
    out: dict[str, set[str]] = collections.defaultdict(set)
    for pmid, polymer in conn.execute("SELECT pmid, polymer FROM tag_polymers"):
        out[pmid].add(polymer)
    return out


# Controlled polymers only. A tagger may propose `other:<text>`, and an uncontrolled
# value cannot be a set in a diagram whose sets come from the vocabulary.
VOCAB_POLYMERS = set(V["polymers"])
VOCAB_TISSUES = set(V.get("tissues", []))
VOCAB_PATHWAYS = set(V["pathways"])
COMBO_LIMIT = 24


def polymer_rows(pmids: set[str], polymers: dict[str, set[str]],
                 pet_pmids: set[str]) -> list[dict]:
    """One row per polymer: papers naming it, and how many of those are PET-specific."""
    counts: collections.Counter = collections.Counter()
    pet: collections.Counter = collections.Counter()
    for pmid in pmids:
        for polymer in polymers.get(pmid, ()):
            if polymer in VOCAB_POLYMERS:
                counts[polymer] += 1
                if pmid in pet_pmids:
                    pet[polymer] += 1
    return [{"k": key, "n": counts[key], "pet": pet[key]}
            for key in V["polymers"] if counts[key]]


def polymer_pairs(pmids: set[str], polymers: dict[str, set[str]]) -> list[dict]:
    """Papers naming both polymers, for every pair that has any. A pair with none is
    left out rather than sent as a zero: the matrix panel draws absence from the gap."""
    pair: collections.Counter = collections.Counter()
    for pmid in pmids:
        named = sorted(p for p in polymers.get(pmid, ()) if p in VOCAB_POLYMERS)
        for i, a in enumerate(named):
            for b in named[i + 1:]:
                pair[(a, b)] += 1
    return [{"a": a, "b": b, "n": n} for (a, b), n in pair.most_common()]


def polymer_combos(pmids: set[str], polymers: dict[str, set[str]]) -> list[dict]:
    """Exact combinations. A paper counts once, for the precise set of polymers it names
    and nothing else, which is the one reading a Venn region actually has."""
    combo: collections.Counter = collections.Counter()
    for pmid in pmids:
        named = tuple(sorted(p for p in polymers.get(pmid, ()) if p in VOCAB_POLYMERS))
        if named:
            combo[named] += 1
    return [{"k": list(keys), "n": n} for keys, n in combo.most_common(COMBO_LIMIT)]


def ladder_rows(conn, pet_only: bool) -> list[dict]:
    """Papers per disease category by rung, in vocabulary order, rung 6 always present."""
    pet_clause = "AND t.pet_specific = 1" if pet_only else ""
    rows = conn.execute(f"""
        SELECT d.disease_category AS cat, r.rung AS rung, COUNT(DISTINCT p.pmid) AS n
        FROM papers p
        JOIN tags t USING (pmid)
        JOIN tag_diseases d ON d.pmid = p.pmid
        JOIN tag_rungs r ON r.pmid = p.pmid
        WHERE {CORPUS} AND t.relevant = 1 {pet_clause}
        GROUP BY d.disease_category, r.rung""").fetchall()
    grid: dict[str, list[int]] = {}
    for row in rows:
        grid.setdefault(row["cat"], [0] * 6)[row["rung"] - 1] = row["n"]
    out = []
    for cat in V["disease_categories"]:
        if cat == "none":
            continue
        rungs = grid.get(cat, [0] * 6)
        if sum(rungs) == 0 and cat not in grid:
            continue
        out.append({"key": cat, "label": V["disease_labels"].get(cat, cat), "rungs": rungs,
                    "total": sum(rungs)})
    out.sort(key=lambda d: -d["total"])
    return out


def atlas_bundle(conn) -> dict:
    polymers = polymer_map(conn)
    chips = V["organ_chips"]
    facets = {"polymer_set": polymers,
              "organs": facet_map(conn, "SELECT pmid, organ_system FROM tag_organs"),
              "tissues": facet_map(conn, "SELECT pmid, tissue FROM tag_tissues"),
              "pathways": facet_map(conn, "SELECT pmid, pathway FROM tag_pathways"),
              "models": facet_map(conn, "SELECT pmid, model_type FROM tags WHERE relevant = 1"),
              "rungs": facet_map(conn, "SELECT pmid, rung FROM tag_rungs")}
    cells: dict[str, dict] = {}
    for chip in chips:
        organs = chip["organs"]
        cells[chip["key"]] = {}
        for variant, pet_only in (("all", False), ("pet", True)):
            pmids = verified_pmids(conn, pet_only=pet_only, organs=organs or None)
            pet_pmids = verified_pmids(conn, pet_only=True, organs=organs or None)
            cells[chip["key"]][variant] = {
                **facet_kpis(pmids, pet_pmids, facets),
                "polymers": polymer_rows(pmids, polymers, pet_pmids),
                "pairs": polymer_pairs(pmids, polymers),
                "combos": polymer_combos(pmids, polymers),
            }
    entered = [{"day": r["day"], "pet": r["pet"],
                "polymers": [x for x in (r["polys"] or "").split(",") if x in VOCAB_POLYMERS]}
               for r in conn.execute(f"""
        SELECT substr(p.edat, 1, 10) AS day, COALESCE(t.pet_specific, 0) AS pet,
               (SELECT group_concat(tp.polymer) FROM tag_polymers tp WHERE tp.pmid = p.pmid) AS polys
        FROM papers p LEFT JOIN tags t USING (pmid)
        WHERE {CORPUS} AND p.edat IS NOT NULL AND p.edat <> ''
          AND (t.relevant IS NULL OR t.relevant = 1)""")]
    return {
        "cells": cells,
        "organ_map": {chip["key"]: chip["organs"] for chip in chips},
        "polymer_order": V["polymers"],
        "polymer_labels": V["polymer_labels"],
        "polymer_short": V["polymer_short"],
        "polymer_families": V["polymer_families"],
        "ladder": {"all": ladder_rows(conn, False), "pet": ladder_rows(conn, True)},
        "rung_labels": dict(V["evidence_labels"]),
        "trend": trailing_year(entered),
    }


def trailing_year(rows, today: dt.date | None = None) -> list[dict]:
    """Papers entered in PubMed over the trailing twelve months, at each month end and at
    today, in all and by polymer. PubMed's entry date is never in the future and the last point is today, so the
    series has no cliff from a partial year or from issues dated ahead of print."""
    today = today or dt.date.today()
    days = sorted((dt.date.fromisoformat(r["day"]), bool(r["pet"]), tuple(r.get("polymers") or ()))
                  for r in rows if r["day"] and dt.date.fromisoformat(r["day"]) <= today)
    if not days:
        return []
    ends, d = [], dt.date(days[0][0].year + 1, days[0][0].month, 1)
    while d <= today:
        ends.append(d - dt.timedelta(days=1))
        d = dt.date(d.year + d.month // 12, d.month % 12 + 1, 1)
    if not ends or ends[-1] != today:
        ends.append(today)
    out = []
    for end in ends:
        start = end - dt.timedelta(days=365)
        window = [(pet, polys) for day, pet, polys in days if start < day <= end]
        by = collections.Counter(x for _, polys in window for x in polys)
        out.append({"date": end.isoformat(), "n": len(window),
                    "pet_n": sum(pet for pet, _ in window), "by": dict(by)})
    return out


def body_bundle(conn) -> dict:
    run = latest_run(conn)
    nodes = []
    for site in V["body_nodes"]:
        key, label, organs = site["key"], site["label"], site.get("organs", [])
        tissues = site.get("tissues", [])
        base = {"key": key, "label": label, "organs": organs, "tissues": tissues,
                "x": site["x"], "y": site["y"], "region": site["region"], "art": site["art"]}
        # A site counts papers by organ system, or (tissue pins, owner 2026-10-31) by tissue.
        column, table, values = (("tissue", "tag_tissues", tissues) if tissues
                                 else ("organ_system", "tag_organs", organs))
        marks = ",".join("?" * len(values))
        pmids = [r[0] for r in conn.execute(
            f"""SELECT DISTINCT p.pmid FROM papers p JOIN tags t USING (pmid)
                JOIN {table} o ON o.pmid = p.pmid
                WHERE {CORPUS} AND t.relevant=1
                  AND o.{column} IN ({marks})""", values)]
        if not pmids:
            nodes.append({**base, "count": 0, "pet_count": 0, "polymers": [], "pathways": [],
                          "mix": [], "max_rung": None, "novel": False, "papers": []})
            continue
        pm = ",".join("?" * len(pmids))
        pet_count = conn.execute(
            f"SELECT COUNT(*) FROM tags WHERE pet_specific=1 AND pmid IN ({pm})", pmids).fetchone()[0]
        polys = conn.execute(
            f"""SELECT polymer, COUNT(*) n FROM tag_polymers WHERE pmid IN ({pm})
                GROUP BY polymer ORDER BY n DESC""", pmids).fetchall()
        paths = conn.execute(
            f"""SELECT pathway, COUNT(*) n FROM tag_pathways WHERE pmid IN ({pm})
                GROUP BY pathway ORDER BY n DESC LIMIT 6""", pmids).fetchall()
        novel = bool(run) and conn.execute(
            f"""SELECT COUNT(*) FROM novelty_events WHERE ingest_run = ? AND pmid IN ({pm})""",
            [run] + pmids).fetchone()[0] > 0
        top = conn.execute(
            f"""SELECT p.pmid, p.title, p.journal, p.year, p.doi, t.summary,
                       (SELECT MAX(rung) FROM tag_rungs WHERE pmid=p.pmid) AS max_rung
                FROM papers p JOIN tags t USING (pmid) WHERE p.pmid IN ({pm})
                ORDER BY max_rung DESC NULLS LAST, p.year DESC LIMIT 5""", pmids).fetchall()
        highest = conn.execute(
            f"SELECT MAX(rung) FROM tag_rungs WHERE pmid IN ({pm})", pmids).fetchone()[0]
        # The polymer mix is a share of the site's own papers, so two tissues with very
        # different totals can still be compared band for band on the cards panel.
        named = sum(r["n"] for r in polys if r["polymer"] in VOCAB_POLYMERS) or 1
        nodes.append({
            **base,
            "count": len(pmids), "pet_count": pet_count, "max_rung": highest,
            "mix": [{"k": r["polymer"], "n": r["n"], "share": round(r["n"] / named, 4)}
                    for r in polys if r["polymer"] in VOCAB_POLYMERS][:8],
            "polymers": [{"key": r["polymer"], "n": r["n"]} for r in polys],
            "pathways": [{"key": r["pathway"], "label": V["pathway_labels"].get(r["pathway"], r["pathway"]),
                          "n": r["n"]} for r in paths],
            "novel": novel,
            "papers": [dict(r) for r in top],
        })
    return {"nodes": nodes,
            "polymer_labels": V["polymer_labels"],
            "polymer_order": V["polymers"],
            "polymer_short": V["polymer_short"],
            "regions": list(dict.fromkeys(n["region"] for n in nodes)),
            "max_count": max([n["count"] for n in nodes] or [0])}


SANKEY_POLYMERS, SANKEY_PATHWAYS, SANKEY_DISEASES, SANKEY_MIN = 8, 10, 10, 5
SANKEY_SHORT = {
    "neuroinflammation_neurodegeneration": "Neurodegeneration", "atherosclerosis_mace": "Atherosclerosis",
    "ibd_gut": "Gut inflammation", "immune_dysfunction": "Immune dysfunction",
    "pregnancy_outcomes": "Pregnancy", "metabolic_syndrome": "Metabolic syndrome",
    "copd_asthma": "COPD and asthma", "cancer_other": "Other cancers", "liver_disease": "Liver disease",
    "kidney_disease": "Kidney disease", "nfkb_cytokine": "NF-kB and cytokines",
    "apoptosis_ferroptosis": "Cell death", "inflammasome_il1b": "Inflammasome",
    "mitochondrial_dysfunction": "Mitochondria", "immune_dysregulation": "Immune response",
    "er_stress_autophagy": "ER stress", "dysbiosis": "Dysbiosis", "barrier_disruption": "Barrier disruption",
    "lipid_metabolism": "Lipid metabolism", "oxidative_stress": "Oxidative stress",
    "dna_damage_genotoxicity": "DNA damage", "endocrine_disruption": "Endocrine disruption",
    "fibrosis_tgfb": "Fibrosis",
}


def counts_by(conn, table: str, column: str, labels: dict, exclude: set) -> list[dict]:
    """Relevant papers per value of one tagged field, with the PET-specific share."""
    rows = conn.execute(f"""
        SELECT x.{column} AS k, COUNT(DISTINCT p.pmid) AS n,
               COUNT(DISTINCT CASE WHEN t.pet_specific = 1 THEN p.pmid END) AS pet
        FROM papers p JOIN tags t USING (pmid) JOIN {table} x ON x.pmid = p.pmid
        WHERE {CORPUS} AND t.relevant = 1 GROUP BY x.{column}""").fetchall()
    return sorted(({"key": r["k"], "label": labels.get(r["k"], r["k"]), "n": r["n"], "pet": r["pet"]}
                   for r in rows if r["k"] not in exclude and not str(r["k"]).startswith("other:")),
                  key=lambda r: -r["n"])


def pathways_bundle(conn) -> dict:
    """Sankey polymers to pathways to disease categories, plus the per-category radar."""
    # Legible by construction (owner, 2026-10-31, "tame them"): the busiest named values
    # of each column keep their own node; everything else in that column (the catch-all,
    # unspecified polymers, one-off names and the smaller named values) folds into one
    # "Other" node that the page pins to the bottom in grey. No ribbon under SANKEY_MIN.
    poly_path = conn.execute(f"""
        SELECT pl.polymer AS a, pa.pathway AS b, COUNT(DISTINCT p.pmid) AS n
        FROM papers p JOIN tags t USING (pmid)
        JOIN tag_polymers pl ON pl.pmid = p.pmid
        JOIN tag_pathways pa ON pa.pmid = p.pmid
        WHERE {CORPUS} AND t.relevant=1
        GROUP BY pl.polymer, pa.pathway HAVING n > 0""").fetchall()
    path_dis = conn.execute(f"""
        SELECT pa.pathway AS a, d.disease_category AS b, COUNT(DISTINCT p.pmid) AS n
        FROM papers p JOIN tags t USING (pmid)
        JOIN tag_pathways pa ON pa.pmid = p.pmid
        JOIN tag_diseases d ON d.pmid = p.pmid
        WHERE {CORPUS} AND t.relevant=1 AND d.disease_category <> 'none'
        GROUP BY pa.pathway, d.disease_category HAVING n > 0""").fetchall()

    def busiest(rows, side, allowed, k):
        totals = collections.Counter()
        for r in rows:
            if r[side] in allowed:
                totals[r[side]] += r["n"]
        return {key for key, _ in totals.most_common(k)}

    named_polymers = {p for p in V["polymers"] if p != "mixed_unspecified"}
    named_pathways = {p for p in V["pathways"] if p != "other_pathway"}
    top = {"polymer": busiest(poly_path, "a", named_polymers, SANKEY_POLYMERS),
           "pathway": busiest(path_dis, "a", named_pathways, SANKEY_PATHWAYS),
           "disease": busiest(path_dis, "b", set(V["disease_categories"]) - {"none"}, SANKEY_DISEASES)}
    OTHER = "_other"
    fold = lambda kind, key: key if key in top[kind] else OTHER

    # Every figure counts distinct papers, as the Papers tab does: a ribbon is the papers
    # linking its two ends, and a node's figure is the papers carrying that value. Summing
    # pair counts instead counted a paper once per pairing, so "Other" nodes overstated.
    values: dict[str, dict] = {"polymer": collections.defaultdict(set),
                               "pathway": collections.defaultdict(set),
                               "disease": collections.defaultdict(set)}
    for kind, table, column, extra in (("polymer", "tag_polymers", "polymer", ""),
                                       ("pathway", "tag_pathways", "pathway", ""),
                                       ("disease", "tag_diseases", "disease_category",
                                        "AND x.disease_category <> 'none'")):
        for pmid, value in conn.execute(f"""
                SELECT x.pmid, x.{column} FROM {table} x
                JOIN tags t ON t.pmid = x.pmid JOIN papers p ON p.pmid = x.pmid
                WHERE {CORPUS} AND t.relevant = 1 {extra}"""):
            values[kind][pmid].add(fold(kind, value))
    pairs: dict[tuple, set] = collections.defaultdict(set)
    for pmid, polys in values["polymer"].items():
        for a in polys:
            for b in values["pathway"].get(pmid, ()):
                pairs[("polymer", a, "pathway", b)].add(pmid)
    for pmid, paths in values["pathway"].items():
        for a in paths:
            for b in values["disease"].get(pmid, ()):
                pairs[("pathway", a, "disease", b)].add(pmid)
    flows = {k: len(v) for k, v in pairs.items()}
    papers_with = {(kind, key): 0 for kind in values for key in top[kind] | {OTHER}}
    for kind, by_pmid in values.items():
        for keys_ in by_pmid.values():
            for key in keys_:
                papers_with[(kind, key)] = papers_with.get((kind, key), 0) + 1

    # Short names for the flows only: the panel is half the page wide, so the longest
    # disease and mechanism names would run into each other.
    label_of = {"polymer": {**V["polymer_labels"], **V.get("polymer_short", {})},
                "pathway": {**V["pathway_labels"], **SANKEY_SHORT},
                "disease": {**V["disease_labels"], **SANKEY_SHORT}}
    other_label = {"polymer": "Other polymers", "pathway": "Other mechanisms",
                   "disease": "Other diseases"}
    labels: list[str] = []
    index: dict[str, int] = {}
    colours: list[str] = []
    kinds: list[str] = []
    keys: list[str] = []

    def node(key: str, kind: str) -> int:
        token = f"{kind}:{key}"
        if token not in index:
            index[token] = len(labels)
            labels.append(other_label[kind] if key == OTHER else label_of[kind].get(key, key))
            colours.append("#B9BFD0" if key == OTHER else "#C8872B" if key == "PET"
                           else {"polymer": "#385098", "pathway": "#2A3C78", "disease": "#5A6180"}[kind])
            kinds.append(kind)
            keys.append(key)
        return index[token]

    links = []
    for (k1, a, k2, b), n in sorted(flows.items(), key=lambda kv: -kv[1]):
        if n < SANKEY_MIN:
            continue
        links.append({"source": node(a, k1), "target": node(b, k2), "value": n,
                      "pet": a == "PET", "other": OTHER in (a, b)})

    radar: dict[str, dict] = {}
    axes = V["pathways"]
    by_size = conn.execute(f"""SELECT d.disease_category, COUNT(DISTINCT p.pmid) AS n
                               FROM papers p JOIN tags t USING (pmid) JOIN tag_diseases d ON d.pmid = p.pmid
                               WHERE {CORPUS} AND t.relevant = 1 GROUP BY 1""").fetchall()
    size = {r[0]: r[1] for r in by_size}
    for cat in sorted(V["disease_categories"], key=lambda k: -size.get(k, 0)):
        if cat == "none":
            continue
        all_counts, pet_counts = [], []
        for pathway in axes:
            all_counts.append(conn.execute(f"""
                SELECT COUNT(DISTINCT p.pmid) FROM papers p JOIN tags t USING (pmid)
                JOIN tag_diseases d ON d.pmid=p.pmid JOIN tag_pathways pa ON pa.pmid=p.pmid
                WHERE {CORPUS} AND t.relevant=1 AND d.disease_category=?
                  AND pa.pathway=?""", (cat, pathway)).fetchone()[0])
            pet_counts.append(conn.execute(f"""
                SELECT COUNT(DISTINCT p.pmid) FROM papers p JOIN tags t USING (pmid)
                JOIN tag_diseases d ON d.pmid=p.pmid JOIN tag_pathways pa ON pa.pmid=p.pmid
                WHERE {CORPUS} AND t.relevant=1 AND t.pet_specific=1
                  AND d.disease_category=? AND pa.pathway=?""", (cat, pathway)).fetchone()[0])
        if sum(all_counts) == 0:
            continue
        radar[cat] = {"label": V["disease_labels"].get(cat, cat), "all": all_counts,
                      "pet": pet_counts}

    run = latest_run(conn)
    new_edges = []
    if run:
        for row in conn.execute("""
                SELECT n.key, n.kind, n.pmid, p.title, p.journal, p.year
                FROM novelty_events n JOIN papers p USING (pmid)
                WHERE n.ingest_run = ? AND n.kind = 'triple' LIMIT 40""", (run,)):
            new_edges.append(dict(row))
    return {"sankey": {"labels": labels, "keys": keys, "colours": colours,
                       "kinds": kinds, "links": links,
                       "papers": [papers_with.get((k, key), 0) for k, key in zip(kinds, keys)]},
            "radar": radar, "axis_labels": [SANKEY_SHORT.get(a) or V["pathway_labels"].get(a, a) for a in axes],
            "axes": axes, "new_edges": new_edges,
            "diseases": counts_by(conn, "tag_diseases", "disease_category", V["disease_labels"], {"none"}),
            "pathways": counts_by(conn, "tag_pathways", "pathway", V["pathway_labels"], set())}


# "New this month" (owner, 2026-10-31): papers PubMed entered within a month either side
# of today, the same window the Papers tab's new=1 filter uses.
NEW_WINDOW = ("substr(p.edat, 1, 10) BETWEEN date('now', '-1 month') AND date('now', '+1 month')"
              " AND (p.status <> 'no_abstract' OR p.abstract <> '')")   # as /api/papers lists


def feed_bundle(conn) -> dict:
    run = latest_run(conn)
    rows = conn.execute(f"""
        SELECT p.pmid, p.title, p.journal, p.year, p.doi, p.retracted, t.summary,
               (SELECT GROUP_CONCAT(polymer) FROM tag_polymers WHERE pmid=p.pmid) AS polymers,
               (SELECT GROUP_CONCAT(rung) FROM tag_rungs WHERE pmid=p.pmid) AS rungs,
               (SELECT COUNT(*) FROM novelty_events WHERE pmid=p.pmid) AS novel
        FROM papers p LEFT JOIN tags t USING (pmid)
        WHERE {NEW_WINDOW} AND {CORPUS}
          AND (t.relevant IS NULL OR t.relevant=1)
        ORDER BY novel DESC, p.edat DESC LIMIT 36""").fetchall()
    feed = []
    for r in rows:
        feed.append({"pmid": r["pmid"], "title": r["title"], "journal": r["journal"],
                     "year": r["year"], "doi": r["doi"], "retracted": r["retracted"],
                     "summary": r["summary"] or "",
                     "polymers": sorted(set((r["polymers"] or "").split(","))) if r["polymers"] else [],
                     "rungs": sorted({int(x) for x in (r["rungs"] or "").split(",") if x}),
                     "novel": bool(r["novel"])})
    return {"new_this_month": feed, "ingest_run": run,
            "polymer_class": {"PET": "pet", "PS": "ps", "PE": "pepp", "PP": "pepp", "PVC": "pvc"}}


def meta_bundle(conn) -> dict:
    run = latest_run(conn)
    verified = conn.execute(f"SELECT COUNT(*) FROM papers WHERE {CORPUS_ANY}").fetchone()[0]
    # Reported so the funnel still adds up: the controls are harvested, verified and
    # tagged, they are simply not corpus. See common.CORPUS_STRATEGY.
    controls = conn.execute(f"""SELECT COUNT(*) FROM papers WHERE doi_status = 'verified'
                                AND COALESCE(hit_strategy, '') = '{c.CORPUS_STRATEGY}'"""
                            ).fetchone()[0]
    tagged = conn.execute(f"""SELECT COUNT(*) FROM tags t JOIN papers p USING (pmid)
                             WHERE {CORPUS}""").fetchone()[0]
    relevant = conn.execute(f"""SELECT COUNT(*) FROM tags t JOIN papers p USING (pmid)
                               WHERE {CORPUS} AND t.relevant=1""").fetchone()[0]
    pet = conn.execute(f"""SELECT COUNT(*) FROM tags t JOIN papers p USING (pmid)
                          WHERE {CORPUS} AND t.relevant=1
                            AND t.pet_specific=1""").fetchone()[0]
    organs = conn.execute(f"""SELECT COUNT(DISTINCT organ_system) FROM tag_organs
                             WHERE pmid IN (SELECT pmid FROM papers
                             WHERE {CORPUS_ANY})""").fetchone()[0]
    new_this_month = conn.execute(f"""SELECT COUNT(*) FROM papers p LEFT JOIN tags t USING (pmid)
                                     WHERE {NEW_WINDOW} AND {CORPUS}
                                       AND (t.relevant IS NULL OR t.relevant = 1)""").fetchone()[0]
    novel = conn.execute("SELECT COUNT(DISTINCT pmid) FROM novelty_events WHERE ingest_run=?",
                         (run,)).fetchone()[0] if run else 0
    queued = conn.execute("SELECT COUNT(*) FROM review_queue WHERE resolved_at IS NULL").fetchone()[0]
    first_year = conn.execute(f"""SELECT MIN(year) FROM papers WHERE {CORPUS_ANY}
                                 AND year IS NOT NULL""").fetchone()[0]
    row = conn.execute("""SELECT model_version, inference_path, finished_at, started_at
                          FROM ingest_runs WHERE run_id=?""", (run,)).fetchone() if run else None
    drift = conn.execute("""SELECT f1 FROM drift_log WHERE field='relevant'
                            ORDER BY rowid DESC LIMIT 1""").fetchone()
    model_version = conn.execute("""SELECT model_version FROM tags WHERE model_version IS NOT NULL
                                    ORDER BY tagged_at DESC LIMIT 1""").fetchone()
    stamp = (row["finished_at"] or row["started_at"]) if row else None
    return {
        "generated_at": c.now(),
        "last_ingest": stamp,
        "last_ingest_date": (stamp or "")[:10] or dt.date.today().isoformat(),
        "verified_papers": verified, "control_papers": controls,
        # What the tagger can read: an abstract, and not given up on after a re-prompt.
        "taggable_papers": conn.execute(f"""SELECT COUNT(*) FROM papers p WHERE {CORPUS}
                                            AND p.abstract <> ''
                                            AND COALESCE(p.status, '') NOT LIKE 'failed:%'""").fetchone()[0],
        "tagged_papers": tagged, "relevant_papers": relevant,
        "pet_papers": pet, "organ_systems_covered": organs, "new_this_month": new_this_month,
        "human_papers": conn.execute(f"""SELECT COUNT(DISTINCT r.pmid) FROM tag_rungs r
                                         JOIN tags t USING (pmid) JOIN papers p USING (pmid)
                                         WHERE {CORPUS} AND t.relevant = 1 AND r.rung IN (1, 2)""").fetchone()[0],
        "novel_this_week": novel, "review_queue": queued, "first_year": first_year,
        "model_version": (model_version[0] if model_version else None),
        "inference_path": row["inference_path"] if row else None,
        "drift_f1": drift[0] if drift else None,
        "provisional_tags": bool((c.ROOT / "PROVISIONAL_TAGS").exists()),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Write the app's static aggregates")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    conn = c.connect(readonly=False)
    bundles = {
        "meta": meta_bundle(conn),
        "atlas": atlas_bundle(conn),
        "body": body_bundle(conn),
        "pathways": pathways_bundle(conn),
        "feed": feed_bundle(conn),
    }
    total = 0
    for name, payload in bundles.items():
        path = c.STATIC_DATA / f"{name}.json"
        c.write_json(path, payload)
        total += path.stat().st_size
    if not args.quiet:
        c.log(f"aggregate: wrote {len(bundles)} bundles, {total / 1024:.0f} kB total; "
              f"verified {bundles['meta']['verified_papers']}, "
              f"tagged {bundles['meta']['tagged_papers']}")


if __name__ == "__main__":
    main()
