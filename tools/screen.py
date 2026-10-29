"""What the corpus admits, and what the tagger then did with it.

The harvest trades precision for recall on purpose: two PubMed strategies are unioned, and
the MeSH one indexes implant materials, so Dacron grafts and silicone implants arrive
alongside the environmental exposure work. A paper is never dropped for a keyword, because
keyword tests are wrong often enough that they must not be final. Instead this screen puts
a number on each suspect class before tagging and checks what the tagger said about it
after, so a precision problem is visible rather than inferred.

  pixi run screen
"""
from __future__ import annotations

from collections import Counter

from pipeline import common as c
from pipeline import tag

TIER_LABELS = {1: "gold set", 2: "human tissue and cohort", 3: "other human",
               4: "animal and in vitro", 5: "reviews and the rest",
               6: "never names a plastic", 7: "deliberate control"}

# The ambiguity this project is named around: these words mean a scanner, not a polymer.
IMAGING = ("positron emission", "pet/ct", "pet-ct", "18f-", "68ga", "radiotracer", "fdg")


def rows_with_tiers(conn) -> list[tuple]:
    rows = conn.execute("""SELECT pmid, title, abstract, journal, year, mesh, pub_types,
                                  hit_strategy
                           FROM papers WHERE doi_status = 'verified' AND abstract <> ''"""
                        ).fetchall()
    gold = {r[0] for r in conn.execute("SELECT pmid FROM gold_set WHERE pmid <> ''")}
    return [(r, tag.tier_of(r, gold)) for r in rows]


def imaging_papers(conn) -> list[dict]:
    """Every corpus paper that mentions a scanner, with whether it also names a plastic.

    Nine of them, and five are real microplastics work that used PET or SPECT imaging to
    track particles in a living animal. That is why there is no imaging filter.
    """
    out = []
    for row in conn.execute(f"SELECT pmid, title, abstract, hit_strategy FROM papers "
                            f"WHERE {c.corpus_clause('')}"):
        haystack = f"{row['title']} {row['abstract'] or ''}".lower()
        if any(word in haystack for word in IMAGING):
            out.append({"pmid": row["pmid"], "title": row["title"],
                        "names_a_plastic": tag.names_a_plastic(haystack)})
    return out


def tagger_verdicts(conn) -> dict:
    """How the tagger ruled on each tier, once there are tags to read."""
    verdicts: dict[int, Counter] = {}
    tagged = {r[0]: r[1] for r in conn.execute("SELECT pmid, relevant FROM tags")}
    if not tagged:
        return {}
    for row, tier in rows_with_tiers(conn):
        if row["pmid"] in tagged:
            verdicts.setdefault(tier, Counter())["relevant" if tagged[row["pmid"]]
                                                else "refused"] += 1
    return verdicts


def main() -> int:
    conn = c.connect()
    tiers = Counter(tier for _, tier in rows_with_tiers(conn))
    total = sum(tiers.values())
    print(f"{total:,} verified papers with an abstract\n")
    for tier in sorted(tiers):
        print(f"  tier {tier}  {tiers[tier]:>5,}  {TIER_LABELS[tier]}")
    demoted = tiers[6] + tiers[7]
    print(f"\n  demoted to the back of the queue: {demoted:,} ({demoted / total:.1%}), "
          f"tagged all the same")

    imaging = imaging_papers(conn)
    kept = [p for p in imaging if p["names_a_plastic"]]
    print(f"\n{len(imaging)} corpus papers mention a scanner, of which {len(kept)} also name "
          f"a plastic:")
    for paper in imaging:
        mark = "plastic" if paper["names_a_plastic"] else "no plastic"
        print(f"  [{mark:>10}] {paper['pmid']}  {paper['title'][:78]}")

    verdicts = tagger_verdicts(conn)
    if not verdicts:
        print("\nNo tags yet, so the tagger's side of this is not measurable.")
    else:
        print("\nWhat the tagger said, by tier:")
        for tier in sorted(verdicts):
            counts = verdicts[tier]
            n = sum(counts.values())
            print(f"  tier {tier}  {counts['relevant']:>5,} relevant  "
                  f"{counts['refused']:>5,} refused   {TIER_LABELS[tier]}")
        # The classes we expect to be refused almost entirely. A tier 7 marked relevant is
        # a tagger mistake by construction; a tier 6 marked relevant is worth reading.
        for tier in (6, 7):
            counts = verdicts.get(tier)
            if counts and counts["relevant"]:
                n = sum(counts.values())
                print(f"\n  tier {tier}: {counts['relevant']} of {n} came back relevant "
                      f"({counts['relevant'] / n:.1%}). Worth reading before they publish.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
