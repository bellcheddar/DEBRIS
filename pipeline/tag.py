"""Tag the corpus with the DEBRIS tagger (spec 5.6 and 5.7).

Two passes per paper (greedy, then temperature 0.7 at a fixed seed); the greedy tag
is stored and the pair gives a self-consistency score. Papers are tagged in priority
tiers so the app has the papers that matter first:

  1 gold set, 2 human tissue and cohort text hits, 3 other human hits,
  4 animal and in vitro, 5 reviews and the rest, 6 papers that never name a plastic,
  7 the deliberate negative controls

Tiers 6 and 7 are an ordering, never an exclusion: every paper is still tagged, and the
tagger's relevance head is what decides what the corpus publishes. Demoting them means
a pass that is interrupted part way through has finished the papers that matter.

  pixi run tag --local            # the mlx model on this machine (path B)
  pixi run tag --remote           # the Hugging Face ZeroGPU Space (path A)
  pixi run tag --local --limit 50 # a slice, for the smoke test
"""
from __future__ import annotations

import argparse
import json
import re
import time

from pipeline import common as c
from pipeline import schema

MODEL_VERSION = "debris_v1"
SAMPLED_TEMPERATURE = 0.7
SAMPLED_SEED = 42

TIER_PATTERNS = (
    (2, r"patient|cohort|human tissue|human blood|post-?mortem|biopsy|autops|carotid|placenta"),
    (3, r"human|volunteer|serum|plasma|urine|faec|stool|sputum"),
    (4, r"mice|mouse|rat|zebrafish|in vivo|cell line|caco-2|hepg2|a549|organoid|in vitro"),
)

PLASTICS_WORDS = re.compile(
    r"plastic|polymer|polyethylen|polystyren|terephthalat|polypropylen|polyvinyl|polyamide|"
    r"nylon|polycarbonate|polyurethane|polyurethan|pmma|acrylate|polylactic|polyester|"
    r"microbead|microfib|tyre wear|tire wear|phthalate|bisphenol|\bmnps?\b|\bmps\b|"
    r"\bpvc\b|\bhdpe\b|\bldpe\b|\bpla\b|\bpcl\b|\bps\b|\bptfe\b|\bpsnp|\bpslm")
# PE, PP, PA, PC and PU are left out on purpose: in this literature they read as pulmonary
# embolism, the posteroanterior view, protein C and so on far more often than as polymers.
# Leaving them out costs nothing, since a paper that reports a microplastic finding names
# one in full somewhere in its abstract almost without exception.
PET_ABBREVIATION = re.compile(r"\bpet\b")
# `PET` is polyethylene terephthalate in this corpus and positron emission tomography in a
# radiology journal, which is why the harvest never searches PET[tiab] on its own. Only the
# second reading arrives with a scanner attached, so that is what tells them apart.
PET_AS_IMAGING = re.compile(r"\bpet[ /-]?(ct|mri|mr\b|scan|imag)|fdg|\b18f|68ga|"
                            r"positron emission|radiotracer|psma")


def names_a_plastic(haystack: str) -> bool:
    """Whether a title and abstract mention a plastic at all, spelled out or abbreviated.

    A paper that never does cannot be reporting a microplastic finding however human its
    study design, and the MeSH strategy brings in a steady supply of them: Dacron grafts
    are polyethylene terephthalate, so the indexing is right and the paper is still about
    a vascular prosthesis. They are demoted rather than dropped, because this is a keyword
    test and keyword tests are wrong often enough that they must not be final.
    """
    if PLASTICS_WORDS.search(haystack):
        return True
    return bool(PET_ABBREVIATION.search(haystack) and not PET_AS_IMAGING.search(haystack))


def tier_of(row, gold: set[str]) -> int:
    if row["pmid"] in gold:
        return 1
    if (row["hit_strategy"] or "") == c.CORPUS_STRATEGY:
        return 7
    haystack = f"{row['title']} {row['abstract'][:1200]}".lower()
    if not names_a_plastic(haystack):
        return 6
    if re.search(r"\breview\b|meta-analysis|systematic", (row["pub_types"] or "").lower()):
        return 5
    for tier, pattern in TIER_PATTERNS:
        if re.search(pattern, haystack):
            return tier
    return 5


def pending(conn, limit: int | None, only_tier: int | None,
            retag: bool = False) -> list:
    where = "p.doi_status = 'verified' AND p.abstract <> ''"
    if not retag:
        where += " AND t.pmid IS NULL"
    rows = conn.execute(
        f"""SELECT p.pmid, p.title, p.abstract, p.journal, p.year, p.mesh, p.pub_types,
                   p.hit_strategy
            FROM papers p LEFT JOIN tags t USING (pmid) WHERE {where}""").fetchall()
    gold = {r[0] for r in conn.execute("SELECT pmid FROM gold_set WHERE pmid <> ''")}
    ordered = sorted(rows, key=lambda r: (tier_of(r, gold), -(r["year"] or 0)))
    if only_tier:
        ordered = [r for r in ordered if tier_of(r, gold) == only_tier]
    return ordered[:limit] if limit else ordered


def local_model_choice(model: str | None, adapter: str | None,
                       tuning: dict) -> tuple[str, str | None]:
    """Pick the local weights: q4 by default, fused when the q4 copy scored worse.

    train.py drops a USE_FUSED marker when q4 lost more than two F1 points against the
    fused model; honour it rather than quietly tagging the corpus with the weaker copy.
    With neither built, fall back to the base model plus the raw adapter.
    """
    names = ["debris_v1_q4", "debris_v1_fused"]
    if (c.ROOT / "USE_FUSED").exists():
        names.reverse()
    for name in names:
        if (c.ADAPTERS / name).exists():
            return model or str(c.ADAPTERS / name), adapter
    base = model or tuning.get("model_id", "Qwen/Qwen2.5-3B-Instruct")
    if adapter is None and (c.ADAPTERS / "debris_v1").exists():
        adapter = str(c.ADAPTERS / "debris_v1")
    return base, adapter


# ------------------------------------------------------------------ local (mlx)

class LocalTagger:
    """One resident mlx model, never reloaded (spec section 2)."""

    def __init__(self, model_path: str, adapter_path: str | None = None):
        from mlx_lm import load

        self.model, self.tokenizer = load(model_path, adapter_path=adapter_path)
        self.name = f"{model_path}{'+' + adapter_path if adapter_path else ''}"

    def generate(self, prompt: str, temperature: float, seed: int | None = None) -> str:
        import mlx.core as mx
        from mlx_lm import generate
        from mlx_lm.sample_utils import make_sampler

        if seed is not None:
            mx.random.seed(seed)
        messages = [{"role": "system", "content": schema.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}]
        text = self.tokenizer.apply_chat_template(messages, add_generation_prompt=True,
                                                  tokenize=False)
        return generate(self.model, self.tokenizer, prompt=text, max_tokens=480,
                        sampler=make_sampler(temp=temperature), verbose=False)

    def tag(self, paper: dict) -> tuple[dict | None, dict | None, str]:
        prompt = schema.user_prompt(paper)
        greedy_raw = self.generate(prompt, 0.0)
        greedy = schema.extract_json(greedy_raw)
        if greedy is None:
            # One re-prompt with the shape restated, then give up on this paper.
            greedy = schema.extract_json(self.generate(
                prompt + "\n\nReturn only the JSON object, no prose.", 0.0))
        sampled = schema.extract_json(self.generate(prompt, SAMPLED_TEMPERATURE, SAMPLED_SEED))
        return greedy, sampled, greedy_raw


# ----------------------------------------------------------------- remote (Space)

class RemoteTagger:
    """The ZeroGPU Space, called in batches with tenacity retry (spec 5.6 path A)."""

    def __init__(self, space: str, token: str | None, batch_size: int = 16):
        from gradio_client import Client

        # gradio_client renamed this argument from hf_token to token; accept whichever
        # the installed version takes, since the Space is reached with a token either
        # way and a private Space is unreachable without one.
        try:
            self.client = Client(space, token=token)
        except TypeError:
            self.client = Client(space, hf_token=token)
        self.batch_size = batch_size
        self.name = f"space:{space}"

    def tag_batch(self, papers: list[dict]) -> list[dict]:
        payload = [{"pmid": p["pmid"], "prompt": schema.user_prompt(p)} for p in papers]
        for attempt in range(6):
            try:
                result = self.client.predict(json.dumps(payload), api_name="/tag")
                return json.loads(result) if isinstance(result, str) else result
            except Exception as exc:
                wait = min(60 * (attempt + 1), 300)
                c.log(f"tag: Space call failed ({type(exc).__name__}); retrying in {wait}s")
                time.sleep(wait)
        raise RuntimeError("the Space did not answer after six attempts")


# ----------------------------------------------------------------------- storage

def candidates_of(tag: dict) -> set[tuple[str, str]]:
    """The out-of-vocabulary values a stored tag proposes. Only polymers and pathways
    are open fields; the closed ones drop unknown values rather than proposing them."""
    return {(field, value) for field in ("polymers", "pathways")
            for value in tag.get(field) or [] if str(value).startswith("other:")}


def store(conn, pmid: str, tag: dict, sampled: dict | None, problems: list[str],
          candidates: list[tuple[str, str]], source: str, model_version: str) -> str:
    """Write one tag and its fan-out tables. Returns the review reason, or ''."""
    consistency = schema.self_consistency(tag, sampled)
    # vocab_candidates counts papers, so a re-tag moves the paper between values
    # rather than counting it twice.
    row = conn.execute("SELECT tag_json FROM tags WHERE pmid=?", (pmid,)).fetchone()
    already = candidates_of(json.loads(row[0])) if row else set()
    proposed = set(candidates)
    reason = ""
    if tag["confidence"] < 0.6:
        reason = "low confidence"
    elif consistency < 0.7:
        reason = "passes disagree"
    elif any(v.startswith("other:") for v in tag["polymers"] + tag["pathways"]):
        reason = "out-of-vocabulary value"
    elif problems:
        reason = "; ".join(problems)[:120]

    with conn:
        conn.execute("""INSERT INTO tags (pmid,relevant,size_class,model_type,pet_specific,summary,
                          confidence,self_consistency,tag_source,tag_json,tagged_at,model_version)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(pmid) DO UPDATE SET relevant=excluded.relevant,
                          size_class=excluded.size_class, model_type=excluded.model_type,
                          pet_specific=excluded.pet_specific, summary=excluded.summary,
                          confidence=excluded.confidence, self_consistency=excluded.self_consistency,
                          tag_source=excluded.tag_source, tag_json=excluded.tag_json,
                          tagged_at=excluded.tagged_at, model_version=excluded.model_version""",
                     (pmid, int(tag["relevant"]), tag["size_class"], tag["model_type"],
                      int(tag["pet_specific"]), tag["summary"], tag["confidence"], consistency,
                      source, json.dumps(tag, separators=(",", ":")), c.now(), model_version))
        for table, column, values in (
                ("tag_polymers", "polymer", tag["polymers"]),
                ("tag_organs", "organ_system", tag["organ_systems"]),
                ("tag_pathways", "pathway", tag["pathways"])):
            conn.execute(f"DELETE FROM {table} WHERE pmid=?", (pmid,))
            conn.executemany(f"INSERT OR IGNORE INTO {table} (pmid,{column}) VALUES (?,?)",
                             [(pmid, v) for v in values])
        conn.execute("DELETE FROM tag_rungs WHERE pmid=?", (pmid,))
        conn.executemany("INSERT OR IGNORE INTO tag_rungs (pmid,rung) VALUES (?,?)",
                         [(pmid, r) for r in tag["evidence_rungs"]])
        conn.execute("DELETE FROM tag_diseases WHERE pmid=?", (pmid,))
        terms = tag["disease_terms"] or [""]
        conn.executemany("INSERT INTO tag_diseases (pmid,disease_category,disease_term) VALUES (?,?,?)",
                         [(pmid, cat, term) for cat in tag["disease_categories"]
                          for term in (terms if cat != "none" else [""])])
        conn.execute("UPDATE papers SET status='tagged' WHERE pmid=?", (pmid,))
        if reason:
            conn.execute("""INSERT INTO review_queue (pmid,reason,queued_at) VALUES (?,?,?)
                            ON CONFLICT(pmid) DO UPDATE SET reason=excluded.reason""",
                         (pmid, reason, c.now()))
        else:
            conn.execute("UPDATE review_queue SET resolved_at=? WHERE pmid=? AND resolved_at IS NULL",
                         (c.now(), pmid))
        for field, value in sorted(proposed - already):
            conn.execute("""INSERT INTO vocab_candidates (field,value,count,first_seen)
                            VALUES (?,?,1,?) ON CONFLICT(field,value)
                            DO UPDATE SET count=vocab_candidates.count+1""",
                         (field, value, c.now()))
        for field, value in sorted(already - proposed):
            conn.execute("""UPDATE vocab_candidates SET count = count - 1
                            WHERE field=? AND value=?""", (field, value))
        conn.execute("DELETE FROM vocab_candidates WHERE count <= 0")
    return reason


def mark_failed(conn, pmid: str, reason: str) -> None:
    with conn:
        conn.execute("UPDATE papers SET status=? WHERE pmid=?", (f"failed:{reason}", pmid))
        conn.execute("""INSERT INTO review_queue (pmid,reason,queued_at) VALUES (?,?,?)
                        ON CONFLICT(pmid) DO UPDATE SET reason=excluded.reason""",
                     (pmid, reason, c.now()))


def main() -> None:
    ap = argparse.ArgumentParser(description="Tag the DEBRIS corpus")
    ap.add_argument("--local", action="store_true", help="use the mlx model on this machine")
    ap.add_argument("--remote", action="store_true", help="use the Hugging Face ZeroGPU Space")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tier", type=int, default=None)
    ap.add_argument("--retag", action="store_true", help="re-tag papers that already have tags")
    ap.add_argument("--model", default=None, help="model path (default: the fused adapter)")
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--run-id", default=None)
    args = ap.parse_args()

    conn = c.connect()
    tuning = c.tuning()
    rows = pending(conn, args.limit, args.tier, args.retag)
    if not rows:
        c.log("tag: nothing to tag")
        return

    if args.remote:
        hf = c.load_toml("hf.toml")
        tagger = RemoteTagger(hf.get("space_repo", "Dellboy/debris-tagger"),
                              c.api_key("HF_TOKEN"), hf.get("batch_size", 16))
        path = "zerogpu_space"
    else:
        model_path, adapter = local_model_choice(args.model, args.adapter, tuning)
        tagger = LocalTagger(model_path, adapter)
        path = "studio_mlx"

    c.log(f"tag: {len(rows)} papers, {tagger.name}, path {path}")
    done = c.manifest_done("tag", key="pmid") if not args.retag else set()
    started = time.monotonic()
    tagged = queued = failed = 0

    for i, row in enumerate(rows, 1):
        if row["pmid"] in done:
            continue
        paper = dict(row)
        try:
            if args.remote:
                results = tagger.tag_batch([paper])
                raw = results[0].get("tag") if results else None
                sampled = results[0].get("sampled") if results else None
            else:
                raw, sampled, _ = tagger.tag(paper)
        except Exception as exc:
            mark_failed(conn, paper["pmid"], f"tagger error {type(exc).__name__}")
            failed += 1
            continue
        tag, problems, candidates = schema.validate(raw)
        sampled_tag, _, _ = schema.validate(sampled) if sampled else (None, [], [])
        if tag is None:
            mark_failed(conn, paper["pmid"], "invalid JSON after one re-prompt")
            failed += 1
            c.manifest_write("tag", {"pmid": paper["pmid"], "status": "failed", "at": c.now()})
            continue
        reason = store(conn, paper["pmid"], tag, sampled_tag, problems, candidates,
                       "debris_v1" if not args.remote else "debris_v1_space", MODEL_VERSION)
        tagged += 1
        queued += 1 if reason else 0
        c.manifest_write("tag", {"pmid": paper["pmid"], "status": "tagged",
                                 "review": reason, "at": c.now()})
        if i % 25 == 0:
            rate = i / max(time.monotonic() - started, 1e-6)
            left = (len(rows) - i) / max(rate, 1e-9) / 60
            print(f"  tagged {i}/{len(rows)} ({rate * 60:.0f}/min, ~{left:.0f} min left, "
                  f"{queued} queued for review)", flush=True)

    if args.run_id:
        with conn:
            conn.execute("""UPDATE ingest_runs SET tagged=?, queued=?, model_version=?,
                              inference_path=? WHERE run_id=?""",
                         (tagged, queued, MODEL_VERSION, path, args.run_id))
    elapsed = (time.monotonic() - started) / 60
    c.log(f"tag: done {tagged} tagged, {queued} queued for review, {failed} failed, "
          f"{elapsed:.1f} min, path {path}")


if __name__ == "__main__":
    main()
