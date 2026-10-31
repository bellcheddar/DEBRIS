"""Map stored other:<name> polymers back to the vocabulary where the name is a known plastic.

The tagger sometimes writes a named plastic as other:<name> (other:polystyrene, other:pet).
New tags are mapped by tag.canon_polymers; this applies the same mapping to tags already in
the database, in tag_polymers and in each tag's JSON. Idempotent.

  pixi run python tools/normalise_polymers.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import common as c  # noqa: E402
from pipeline.tag import canon_polymers  # noqa: E402


def main() -> int:
    conn = c.connect()
    pmids = [r[0] for r in conn.execute(
        "SELECT DISTINCT pmid FROM tag_polymers WHERE polymer LIKE 'other:%'")]
    changed = 0
    with conn:
        for pmid in pmids:
            before = [r[0] for r in conn.execute(
                "SELECT polymer FROM tag_polymers WHERE pmid = ? ORDER BY rowid", (pmid,))]
            after = canon_polymers(before)
            if after == before:
                continue
            conn.execute("DELETE FROM tag_polymers WHERE pmid = ?", (pmid,))
            conn.executemany("INSERT OR IGNORE INTO tag_polymers (pmid, polymer) VALUES (?, ?)",
                             [(pmid, v) for v in after])
            row = conn.execute("SELECT tag_json FROM tags WHERE pmid = ?", (pmid,)).fetchone()
            if row and row[0]:
                tag = json.loads(row[0])
                tag["polymers"] = canon_polymers(tag.get("polymers") or [])
                conn.execute("UPDATE tags SET tag_json = ? WHERE pmid = ?",
                             (json.dumps(tag, separators=(",", ":")), pmid))
            changed += 1
    c.log(f"normalise polymers: {changed} papers had a named plastic written as other:")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
