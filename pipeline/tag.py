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
import math
import re
import time
from pathlib import Path

from pipeline import common as c
from pipeline import schema

MODEL_VERSION = "debris_v1"
SAMPLED_TEMPERATURE = 0.7
SAMPLED_SEED = 42
MAX_TOKENS = 480
CHUNK = 256      # papers per batched call: an interruption costs at most one chunk
# One pass over the corpus runs for ten hours or more, so the thing to defend against is
# not a crash (the run resumes from the manifest and from the tags already written) but the
# tagger dying quietly part way through. Without a breaker the loop would mark every
# remaining paper failed, finish with an exit code of zero, and leave a review queue the
# size of the corpus looking like a tagging problem rather than an outage.
RETRY_PAUSE = 20
CONSECUTIVE_FAILURE_LIMIT = 25

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


# ------------------------------------------------------------------------ recipes

def canon_tissues(values: list[str]) -> list[str]:
    """Map other:<name> back to a named tissue when the name is one (other:ovary is ovary)."""
    from pipeline import labels_v2 as L

    out = []
    for v in values:
        if isinstance(v, str) and v.startswith("other:"):
            v = L.canonical(v[6:], L.V2["tissues"], L.V2["synonyms"]["tissues"]) or v
        if v not in out:
            out.append(v)
    return out


def canon_polymers(values: list[str]) -> list[str]:
    """Map other:<name> back to the vocabulary when the name is a known plastic or synonym."""
    from pipeline import labels_v2 as L

    synonyms = {**L.V1["synonyms"]["polymers"], **L.V2["synonyms"]["polymers"]}
    out = []
    for v in values:
        if isinstance(v, str) and v.startswith("other:"):
            v = L.canonical(v[6:], L.V2["polymers"], synonyms) or v
        if v not in out:
            out.append(v)
    return out


class Recipe:
    """What the tagger was trained to read and write. v1 is the original schema; v2 is the
    owner's adopted recipe (D50), exactly as the lab trained and scored it: the lab's
    system prompt with the v2 vocabulary, the same user prompt, v2 cleaning, a tissues
    field and rare pathways as one class. The prompt must match training to the byte, so
    it is built by the lab's own functions rather than copied."""

    V2 = {"mask_prompt": True, "model_type_v2": True, "pathways_v2": True,
          "polymers_v2": True, "tissues": True}

    def __init__(self, name: str = "v1"):
        from pipeline import lab_v2

        self.name = name
        self.switches = self.V2 if name == "v2" else {}
        self.system = lab_v2.system_prompt(self.switches)
        self.model_version = "debris_v2" if name == "v2" else MODEL_VERSION

    def validate(self, raw) -> tuple[dict | None, list[str], list[tuple[str, str]]]:
        tag, problems, candidates = schema.validate(raw)
        if tag is None or self.name != "v2":
            return tag, problems, candidates
        from pipeline import lab_v2

        tag, problems = lab_v2.validate(raw, self.switches)
        # The specific rare pathway the tagger named is kept as a note on the tag.
        tag["pathway_notes"] = [v for v in (raw.get("pathways") or [])
                                if isinstance(v, str) and v.startswith("other:")]
        # other:polystyrene is PS: a named plastic written as "other" is mapped back.
        tag["polymers"] = canon_polymers(tag["polymers"])
        tag["tissues"] = canon_tissues(tag.get("tissues") or [])
        tag.setdefault("tissues", [])
        candidates = [(f, v) for f in ("polymers", "pathways", "tissues")
                      for v in tag.get(f) or [] if str(v).startswith("other:")]
        return tag, problems, candidates


# ------------------------------------------------------------------ local (mlx)

class LocalTagger:
    """One resident mlx model, never reloaded (spec section 2)."""

    def __init__(self, model_path: str, adapter_path: str | None = None,
                 recipe: Recipe | None = None):
        from mlx_lm import load

        self.recipe = recipe or Recipe("v1")
        self.model, self.tokenizer = load(model_path, adapter_path=adapter_path)
        self.name = f"{model_path}{'+' + adapter_path if adapter_path else ''}"

    def generate(self, prompt: str, temperature: float, seed: int | None = None) -> str:
        import mlx.core as mx
        from mlx_lm import generate
        from mlx_lm.sample_utils import make_sampler

        if seed is not None:
            mx.random.seed(seed)
        messages = [{"role": "system", "content": self.recipe.system},
                    {"role": "user", "content": prompt}]
        text = self.tokenizer.apply_chat_template(messages, add_generation_prompt=True,
                                                  tokenize=False)
        return generate(self.model, self.tokenizer, prompt=text, max_tokens=MAX_TOKENS,
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


def generate_many(model, tokenizer, prompts: list[str], batch: int, *, prefix: bool = True,
                  temperature: float = 0.0, seed: int | None = None,
                  system: str | None = None) -> list[tuple[str, float]]:
    """Answers for many papers in one continuous batch, each with the mean probability of
    the tokens it chose (D45).

    Reading the prompt is most of the cost on the 7B (tag_bench, D45), and the system
    prompt is the same for every paper, so it is read once and shared: the batch
    generator merges the caches it is given into new arrays and never writes to them.
    """
    import math

    import mlx.core as mx
    from mlx_lm.generate import BatchGenerator
    from mlx_lm.models import cache as kv
    from mlx_lm.sample_utils import make_sampler

    system = system or schema.SYSTEM_PROMPT
    tokens = [tokenizer.apply_chat_template(
        [{"role": "system", "content": system},
         {"role": "user", "content": p}], add_generation_prompt=True) for p in prompts]
    caches = None
    if prefix:
        head = tokenizer.apply_chat_template(
            [{"role": "system", "content": system}], add_generation_prompt=False)
        if all(len(head) < len(t) and t[:len(head)] == head for t in tokens):
            shared = kv.make_prompt_cache(model)
            model(mx.array(head)[None], cache=shared)
            mx.eval([s.state for s in shared])
            caches = [shared] * len(tokens)
            tokens = [t[len(head):] for t in tokens]
    if seed is not None:
        mx.random.seed(seed)
    gen = BatchGenerator(model, stop_tokens=tokenizer.eos_token_ids,
                         sampler=make_sampler(temp=temperature),
                         completion_batch_size=batch, prefill_batch_size=min(batch, 16))
    try:
        uids = gen.insert(tokens, MAX_TOKENS, caches=caches)
        out = {u: [] for u in uids}
        logp = {u: [] for u in uids}
        while responses := gen.next():
            for r in responses:
                if r.finish_reason != "stop":
                    out[r.uid].append(r.token)
                    logp[r.uid].append(r.logprobs[r.token].item())
    finally:
        gen.close()
    return [(tokenizer.decode(out[u]),
             round(math.exp(sum(logp[u]) / len(logp[u])), 4) if logp[u] else 0.0) for u in uids]


def least_confident(probs: list[float], fraction: float) -> set[int]:
    """Indices of the papers that get the sampled pass: the given share with the lowest
    token probability, rounded up, so a fraction above zero always samples someone."""
    if fraction <= 0 or not probs:
        return set()
    k = min(len(probs), math.ceil(len(probs) * fraction))
    return set(sorted(range(len(probs)), key=lambda i: (probs[i], i))[:k])


class BatchedTagger(LocalTagger):
    """The local tagger for a whole corpus: batched, with hybrid confidence (D45)."""

    def __init__(self, model_path: str, adapter_path: str | None, tag_cfg: dict,
                 recipe: Recipe | None = None):
        super().__init__(model_path, adapter_path, recipe)
        self.batch = int(tag_cfg.get("batch_size", 8))
        self.prefix = bool(tag_cfg.get("prefix_cache", True))
        self.fraction = float(tag_cfg.get("sampled_fraction", 0.33))

    def tag_many(self, papers: list[dict]) -> list[dict]:
        """For each paper: the greedy JSON (re-prompted once if unparsable), its token
        probability, and the sampled JSON for the least confident share, else None."""
        prompts = [schema.user_prompt(p) for p in papers]
        greedy = generate_many(self.model, self.tokenizer, prompts, self.batch, prefix=self.prefix,
                                  system=self.recipe.system)
        parsed = [schema.extract_json(text) for text, _ in greedy]
        retry = [i for i, g in enumerate(parsed) if g is None]
        if retry:
            again = generate_many(self.model, self.tokenizer,
                                  [prompts[i] + "\n\nReturn only the JSON object, no prose." for i in retry],
                                  self.batch, prefix=self.prefix,
                                  system=self.recipe.system)
            for i, (text, _) in zip(retry, again):
                parsed[i] = schema.extract_json(text)
        probs = [p for _, p in greedy]
        chosen = sorted(least_confident(probs, self.fraction))
        sampled: dict[int, dict | None] = {}
        if chosen:
            texts = generate_many(self.model, self.tokenizer, [prompts[i] for i in chosen],
                                  self.batch, prefix=self.prefix, system=self.recipe.system,
                                  temperature=SAMPLED_TEMPERATURE, seed=SAMPLED_SEED)
            sampled = {i: schema.extract_json(t) for i, (t, _) in zip(chosen, texts)}
        return [{"raw": parsed[i], "sampled": sampled.get(i), "sampled_run": i in sampled,
                 "token_prob": probs[i]} for i in range(len(papers))]


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
          candidates: list[tuple[str, str]], source: str, model_version: str,
          token_prob: float | None = None, sampled_run: bool = True,
          recipe: Recipe | None = None) -> str:
    """Write one tag and its fan-out tables. Returns the review reason, or ''.

    Under hybrid confidence (D45) a paper the tagger was sure of skips the sampled pass:
    its self-consistency is NULL rather than a score it never earned, and its token
    probability says why."""
    consistency = schema.self_consistency(tag, sampled) if sampled_run else None
    # vocab_candidates counts papers, so a re-tag moves the paper between values
    # rather than counting it twice.
    row = conn.execute("SELECT tag_json FROM tags WHERE pmid=?", (pmid,)).fetchone()
    already = candidates_of(json.loads(row[0])) if row else set()
    proposed = set(candidates)
    reason = ""
    if tag["confidence"] < 0.6:
        reason = "low confidence"
    elif consistency is not None and consistency < 0.7:
        reason = "passes disagree"
    elif any(v.startswith("other:") for v in tag["polymers"] + tag["pathways"]):
        reason = "out-of-vocabulary value"
    elif problems:
        reason = "; ".join(problems)[:120]

    with conn:
        conn.execute("""INSERT INTO tags (pmid,relevant,size_class,model_type,pet_specific,summary,
                          confidence,self_consistency,token_prob,tag_source,tag_json,tagged_at,
                          model_version)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(pmid) DO UPDATE SET relevant=excluded.relevant,
                          size_class=excluded.size_class, model_type=excluded.model_type,
                          pet_specific=excluded.pet_specific, summary=excluded.summary,
                          confidence=excluded.confidence, self_consistency=excluded.self_consistency,
                          token_prob=excluded.token_prob,
                          tag_source=excluded.tag_source, tag_json=excluded.tag_json,
                          tagged_at=excluded.tagged_at, model_version=excluded.model_version""",
                     (pmid, int(tag["relevant"]), tag["size_class"], tag["model_type"],
                      int(tag["pet_specific"]), tag["summary"], tag["confidence"], consistency,
                      token_prob, source, json.dumps(tag, separators=(",", ":")), c.now(), model_version))
        for table, column, values in (
                ("tag_polymers", "polymer", tag["polymers"]),
                ("tag_organs", "organ_system", tag["organ_systems"]),
                ("tag_pathways", "pathway", tag["pathways"])):
            conn.execute(f"DELETE FROM {table} WHERE pmid=?", (pmid,))
            conn.executemany(f"INSERT OR IGNORE INTO {table} (pmid,{column}) VALUES (?,?)",
                             [(pmid, v) for v in values])
        conn.execute("DELETE FROM tag_tissues WHERE pmid=?", (pmid,))
        conn.executemany("INSERT OR IGNORE INTO tag_tissues (pmid,tissue) VALUES (?,?)",
                         [(pmid, v) for v in tag.get("tissues") or []])
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


def tag_once(tagger, paper: dict, *, remote: bool) -> tuple:
    """One tagging attempt, greedy plus sampled, whichever path is in use."""
    if remote:
        results = tagger.tag_batch([paper])
        return (results[0].get("tag") if results else None,
                results[0].get("sampled") if results else None)
    raw, sampled, _ = tagger.tag(paper)
    return raw, sampled


def mark_failed(conn, pmid: str, reason: str) -> None:
    with conn:
        conn.execute("UPDATE papers SET status=? WHERE pmid=?", (f"failed:{reason}", pmid))
        conn.execute("""INSERT INTO review_queue (pmid,reason,queued_at) VALUES (?,?,?)
                        ON CONFLICT(pmid) DO UPDATE SET reason=excluded.reason""",
                     (pmid, reason, c.now()))


def main() -> int:
    ap = argparse.ArgumentParser(description="Tag the DEBRIS corpus")
    ap.add_argument("--local", action="store_true", help="use the mlx model on this machine")
    ap.add_argument("--remote", action="store_true", help="use the Hugging Face ZeroGPU Space")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tier", type=int, default=None)
    ap.add_argument("--retag", action="store_true", help="re-tag papers that already have tags")
    ap.add_argument("--model", default=None, help="model path (default: the fused adapter)")
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--recipe", choices=["v1", "v2"], default=None,
                    help="the tag schema the weights were trained on (default: [tag] recipe)")
    ap.add_argument("--db", default=None,
                    help="tag a copy of the database (a shadow re-tag, D68); its manifest is kept apart")
    args = ap.parse_args()

    if args.db:
        c.DB_PATH = Path(args.db).resolve()
        c.MANIFESTS = c.DB_PATH.parent / f"manifests_{c.DB_PATH.stem}"
        c.MANIFESTS.mkdir(parents=True, exist_ok=True)
    conn = c.connect()
    tuning = c.tuning()
    rows = pending(conn, args.limit, args.tier, args.retag)
    if not rows:
        c.log("tag: nothing to tag")
        return 0

    if args.remote:
        hf = c.load_toml("hf.toml")
        tagger = RemoteTagger(hf.get("space_repo", "Dellboy/debris-tagger"),
                              c.api_key("HF_TOKEN"), hf.get("batch_size", 16))
        path = "zerogpu_space"
    else:
        tag_cfg = tuning.get("tag", {})
        recipe = Recipe(args.recipe or tag_cfg.get("recipe", "v1"))
        if recipe.name == "v2":
            model_path = args.model or tag_cfg["model"]
            adapter = args.adapter or tag_cfg.get("adapter")
        else:
            model_path, adapter = local_model_choice(args.model, args.adapter, tuning)
        tagger = BatchedTagger(model_path, adapter, tag_cfg, recipe)
        path = "studio_mlx"

    c.log(f"tag: {len(rows)} papers, {tagger.name}, path {path}")
    c.migrate(conn)
    recipe = getattr(tagger, "recipe", Recipe("v1"))
    version = recipe.model_version
    # A named adapter (data/adapters/debris_v3) names the tags it writes.
    if not args.remote and adapter and Path(adapter).name.startswith("debris_v"):
        version = Path(adapter).name
    if args.retag:
        # A re-tag resumes too: papers already carrying this model's tags are done.
        done = {r[0] for r in conn.execute("SELECT pmid FROM tags WHERE model_version = ?", (version,))}
    else:
        done = c.manifest_done("tag", key="pmid")
    todo = [dict(r) for r in rows if r["pmid"] not in done]
    source = version if not args.remote else f"{version}_space"
    started = time.monotonic()
    counts = {"tagged": 0, "queued": 0, "failed": 0}

    def record(paper: dict, raw, sampled, token_prob=None, sampled_run=True) -> None:
        tag, problems, candidates = recipe.validate(raw)
        sampled_tag, _, _ = recipe.validate(sampled) if sampled else (None, [], [])
        if tag is None:
            mark_failed(conn, paper["pmid"], "invalid JSON after one re-prompt")
            counts["failed"] += 1
            c.manifest_write("tag", {"pmid": paper["pmid"], "status": "failed", "at": c.now()})
            return
        reason = store(conn, paper["pmid"], tag, sampled_tag, problems, candidates, source,
                       version, token_prob=token_prob, sampled_run=sampled_run)
        counts["tagged"] += 1
        counts["queued"] += 1 if reason else 0
        c.manifest_write("tag", {"pmid": paper["pmid"], "status": "tagged",
                                 "review": reason, "at": c.now()})

    def progress(n: int) -> None:
        rate = n / max(time.monotonic() - started, 1e-6)
        left = (len(todo) - n) / max(rate, 1e-9) / 60
        print(f"  tagged {n}/{len(todo)} ({rate * 60:.0f}/min, ~{left:.0f} min left, "
              f"{counts['queued']} queued for review)", flush=True)

    def outage(n_failed: int, exc: Exception) -> int:
        c.log(f"tag: {n_failed} papers in a row failed, the last with "
              f"{type(exc).__name__}. Stopping rather than marking the rest "
              f"of the corpus failed: this is an outage, not a tagging result. "
              f"{counts['tagged']} tagged this run, resume with the same command.")
        conn.close()
        return 1

    consecutive = 0
    if not args.remote:
        # A chunk at a time, so the batch stays full and an interruption costs one chunk.
        for start in range(0, len(todo), CHUNK):
            chunk = todo[start:start + CHUNK]
            try:
                results = tagger.tag_many(chunk)
            except Exception as exc:
                c.log(f"tag: a chunk of {len(chunk)} failed ({type(exc).__name__}), retrying once")
                time.sleep(RETRY_PAUSE)
                try:
                    results = tagger.tag_many(chunk)
                except Exception:
                    # One paper the batch cannot take, or the GPU gone: one at a time tells
                    # the two apart, and the breaker counts papers, not chunks.
                    c.log(f"tag: the chunk failed again, tagging its {len(chunk)} papers one at a time")
                    for paper in chunk:
                        try:
                            raw, sampled, _ = tagger.tag(paper)
                        except Exception as one_exc:
                            mark_failed(conn, paper["pmid"], f"tagger error {type(one_exc).__name__}")
                            counts["failed"] += 1
                            consecutive += 1
                            if consecutive >= CONSECUTIVE_FAILURE_LIMIT:
                                return outage(consecutive, one_exc)
                            continue
                        consecutive = 0
                        record(paper, raw, sampled)
                    progress(start + len(chunk))
                    continue
            consecutive = 0
            for paper, r in zip(chunk, results):
                record(paper, r["raw"], r["sampled"], r["token_prob"], r["sampled_run"])
            progress(start + len(chunk))
    else:
        for i, paper in enumerate(todo, 1):
            try:
                raw, sampled = tag_once(tagger, paper, remote=True)
            except Exception as exc:
                # A cold Space or a dropped connection costs the paper nothing if we simply
                # ask again. A second failure is recorded, and the paper keeps no manifest
                # line, so a later run picks it up again.
                c.log(f"tag: {paper['pmid']} failed ({type(exc).__name__}), retrying once")
                time.sleep(RETRY_PAUSE)
                try:
                    raw, sampled = tag_once(tagger, paper, remote=True)
                except Exception as retry_exc:
                    mark_failed(conn, paper["pmid"], f"tagger error {type(retry_exc).__name__}")
                    counts["failed"] += 1
                    consecutive += 1
                    if consecutive >= CONSECUTIVE_FAILURE_LIMIT:
                        return outage(consecutive, retry_exc)
                    continue
            consecutive = 0
            record(paper, raw, sampled)
            if i % 25 == 0:
                progress(i)
    tagged, queued, failed = counts["tagged"], counts["queued"], counts["failed"]

    if args.run_id:
        with conn:
            conn.execute("""UPDATE ingest_runs SET tagged=?, queued=?, model_version=?,
                              inference_path=? WHERE run_id=?""",
                         (tagged, queued, version, path, args.run_id))
    elapsed = (time.monotonic() - started) / 60
    c.log(f"tag: done {tagged} tagged, {queued} queued for review, {failed} failed, "
          f"{elapsed:.1f} min, path {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
