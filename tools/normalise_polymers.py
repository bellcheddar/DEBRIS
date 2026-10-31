"""Map stored other:<name> polymers and tissues back to the vocabulary where the name is one.

The tagger sometimes writes a named plastic or tissue as other:<name> (other:polystyrene,
other:ovary). New tags are mapped by tag.canon_polymers and tag.canon_tissues; this applies
the same mapping to tags already in the database, in tag_polymers, tag_tissues and each
tag's JSON. Idempotent.

  pixi run python tools/normalise_polymers.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import common as c  # noqa: E402
from pipeline.tag import canon_polymers, canon_tissues  # noqa: E402


def normalise(conn, table: str, column: str, field: str, canon) -> int:
    pmids = [r[0] for r in conn.execute(
        f"SELECT DISTINCT pmid FROM {table} WHERE {column} LIKE 'other:%'")]
    changed = 0
    for pmid in pmids:
        before = [r[0] for r in conn.execute(
            f"SELECT {column} FROM {table} WHERE pmid = ? ORDER BY rowid", (pmid,))]
        after = canon(before)
        if after == before:
            continue
        conn.execute(f"DELETE FROM {table} WHERE pmid = ?", (pmid,))
        conn.executemany(f"INSERT OR IGNORE INTO {table} (pmid, {column}) VALUES (?, ?)",
                         [(pmid, v) for v in after])
        row = conn.execute("SELECT tag_json FROM tags WHERE pmid = ?", (pmid,)).fetchone()
        if row and row[0]:
            tag = json.loads(row[0])
            tag[field] = canon(tag.get(field) or [])
            conn.execute("UPDATE tags SET tag_json = ? WHERE pmid = ?",
                         (json.dumps(tag, separators=(",", ":")), pmid))
        changed += 1
    return changed


def main() -> int:
    conn = c.connect()
    with conn:
        polymers = normalise(conn, "tag_polymers", "polymer", "polymers", canon_polymers)
        tissues = normalise(conn, "tag_tissues", "tissue", "tissues", canon_tissues)
    c.log(f"normalise: {polymers} papers' polymers and {tissues} papers' tissues mapped back from other:")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
