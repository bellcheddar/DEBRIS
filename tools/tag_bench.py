"""How fast the corpus can be tagged on this machine, measured rather than assumed.

pipeline/tag.py tags one paper at a time with unbatched generation, a greedy pass and a
sampled pass each, which is why one pass over the corpus runs for ten hours. This times
the alternatives on one sample of the corpus, with the GPU otherwise idle:

  sequential    the current loop (greedy only), the reference for speed and for answers
  batched       continuous batching at several batch sizes
  prefix        the best batch size, with the shared system prompt computed once
  sampled       the sampled pass under the same settings, the cost of self-consistency
  logprob       whether the greedy pass's own token probabilities predict where the
                sampled pass disagrees, which would make the second pass unnecessary
  speculative   one paper at a time with a 0.5B draft model proposing tokens
  small         the lab's 1.5B adapter under the best settings, for scale

An arm is only a candidate when its greedy answers match the sequential loop's: a faster
tagger that tags differently is a different tagger. The result goes into the [tag] table
of config/tuning.toml, which tools/hwprobe.py keeps across re-probes.

  pixi run python tools/tag_bench.py            # needs the GPU to itself
  pixi run python tools/tag_bench.py --n 64 --skip speculative,small
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import tomli_w

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import common as c  # noqa: E402
from pipeline import schema  # noqa: E402
from pipeline import tag as tag_module  # noqa: E402

N = 128
SEQUENTIAL_N = 16
SEED = 47
BATCH_SIZES = (8, 16, 32, 64)
MAX_TOKENS = 480                 # tag.py's own cap, so output lengths are comparable
DRAFT_MODEL = "mlx-community/Qwen2.5-0.5B-Instruct-4bit"
SMALL = ("Qwen/Qwen2.5-1.5B-Instruct", "phase0-baseline", 600)
AGREEMENT_FLOOR = 0.95           # share of greedy answers that must match the sequential loop
TUNING = c.ROOT / "config" / "tuning.toml"
OUT = c.DATA / "manifests" / "tag_bench.json"


# --------------------------------------------------------------------------- pure helpers

def answer_key(text: str) -> str | None:
    """A tag reduced to what it says, so two runs compare on content, not whitespace.
    Confidence is left out: it is a free number the model rounds differently run to run."""
    tag = schema.extract_json(text)
    if tag is None:
        return None
    return json.dumps({k: v for k, v in tag.items() if k != "confidence"}, sort_keys=True)


def agreement(a: list[str], b: list[str]) -> float:
    """Share of papers whose two answers parse and say the same thing."""
    pairs = [(answer_key(x), answer_key(y)) for x, y in zip(a, b)]
    return round(sum(1 for x, y in pairs if x is not None and x == y) / len(pairs), 3) if pairs else 0.0


def auc(scores: list[float], positives: list[bool]) -> float | None:
    """Probability that a randomly chosen positive outscores a randomly chosen negative."""
    pos = [s for s, p in zip(scores, positives) if p]
    neg = [s for s, p in zip(scores, positives) if not p]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 3)


def is_prefix(prefix: list[int], tokens: list[int]) -> bool:
    return len(prefix) < len(tokens) and tokens[:len(prefix)] == prefix


def pick(results: dict, reference: list[str]) -> dict:
    """The fastest arm whose greedy answers match the sequential loop's."""
    candidates = [(name, r) for name, r in results.items()
                  if r.get("s_per_paper") and r.get("agreement", 0) >= AGREEMENT_FLOOR]
    if not candidates:
        return {}
    name, best = min(candidates, key=lambda kv: kv[1]["s_per_paper"])
    return {"arm": name, **best}


def gpu_busy() -> str | None:
    """A lab job or another tagger already on the GPU (D36: never bench beside one)."""
    for pattern in ("mlx_lm.lora", "lab_queue.py", "pipeline/lab.py run", "pipeline/tag.py",
                    "pipeline/ceiling.py label"):
        found = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout.split()
        if found:
            return pattern
    return None


# --------------------------------------------------------------------------- the arms

def sample(n: int) -> list[dict]:
    conn = c.connect(readonly=True)
    rows = conn.execute("""SELECT pmid, title, abstract, journal, year, mesh FROM papers
                           WHERE doi_status = 'verified' AND abstract <> ''
                           ORDER BY pmid""").fetchall()
    return [dict(r) for r in random.Random(SEED).sample(rows, min(n, len(rows)))]


def chat_tokens(tokenizer, prompt: str) -> list[int]:
    return tokenizer.apply_chat_template(
        [{"role": "system", "content": schema.SYSTEM_PROMPT},
         {"role": "user", "content": prompt}], add_generation_prompt=True)


def run_sequential(model, tokenizer, prompts: list[str], draft=None) -> dict:
    from mlx_lm import generate
    from mlx_lm.sample_utils import make_sampler

    texts, started = [], time.monotonic()
    extra = {"draft_model": draft, "num_draft_tokens": 3} if draft is not None else {}
    for p in prompts:
        text = tokenizer.apply_chat_template(
            [{"role": "system", "content": schema.SYSTEM_PROMPT},
             {"role": "user", "content": p}], add_generation_prompt=True, tokenize=False)
        texts.append(generate(model, tokenizer, prompt=text, max_tokens=MAX_TOKENS,
                              sampler=make_sampler(temp=0.0), verbose=False, **extra))
    return {"texts": texts, "s_per_paper": round((time.monotonic() - started) / len(prompts), 3)}


def run_batched(model, tokenizer, prompts: list[str], batch: int, *, prefix: bool = False,
                temperature: float = 0.0, logprobs: bool = False) -> dict:
    """One continuous-batching pass over every prompt, the way BatchGenerator refills a
    finished slot with the next paper rather than waiting for the slowest in a chunk."""
    import mlx.core as mx
    from mlx_lm.generate import BatchGenerator
    from mlx_lm.models import cache as kv
    from mlx_lm.sample_utils import make_sampler

    tokens = [chat_tokens(tokenizer, p) for p in prompts]
    caches = None
    started = time.monotonic()
    if prefix:
        head = tokenizer.apply_chat_template(
            [{"role": "system", "content": schema.SYSTEM_PROMPT}], add_generation_prompt=False)
        if not all(is_prefix(head, t) for t in tokens):
            return {"skipped": "the system prompt does not tokenise as a prefix of every prompt"}
        shared = kv.make_prompt_cache(model)
        model(mx.array(head)[None], cache=shared)
        mx.eval([s.state for s in shared])
        # BatchGenerator merges the caches it is given into new arrays and never writes
        # to them, so every prompt can start from the one shared copy.
        caches = [shared] * len(tokens)
        tokens = [t[len(head):] for t in tokens]
    if temperature:
        mx.random.seed(tag_module.SAMPLED_SEED)
    gen = BatchGenerator(model, stop_tokens=tokenizer.eos_token_ids,
                         sampler=make_sampler(temp=temperature),
                         completion_batch_size=batch, prefill_batch_size=min(batch, 16))
    uids = gen.insert(tokens, MAX_TOKENS, caches=caches)
    out = {u: [] for u in uids}
    chosen = {u: [] for u in uids}
    while responses := gen.next():
        for r in responses:
            if r.finish_reason != "stop":
                out[r.uid].append(r.token)
                if logprobs:
                    chosen[r.uid].append(r.logprobs[r.token].item())
    stats = gen.stats()
    gen.close()
    elapsed = time.monotonic() - started
    result = {"texts": [tokenizer.decode(out[u]) for u in uids],
              "s_per_paper": round(elapsed / len(prompts), 3),
              "output_tokens": round(stats.generation_tokens / len(prompts), 1),
              "generation_tps": round(stats.generation_tps, 1),
              "prompt_tps": round(stats.prompt_tps, 1),
              "peak_gb": round(stats.peak_memory, 1)}
    if logprobs:
        import math
        result["mean_prob"] = [math.exp(sum(v) / len(v)) if v else 0.0 for v in (chosen[u] for u in uids)]
        result["min_prob"] = [math.exp(min(v)) if v else 0.0 for v in (chosen[u] for u in uids)]
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Time the ways to tag the corpus (tag_bench)")
    ap.add_argument("--n", type=int, default=N)
    ap.add_argument("--skip", default="", help="comma-separated arms to leave out")
    ap.add_argument("--dry-run", action="store_true", help="measure, but leave tuning.toml alone")
    args = ap.parse_args()
    skip = set(filter(None, args.skip.split(",")))
    if busy := gpu_busy():
        raise SystemExit(f"the GPU is in use ({busy}); run the bench with it idle")
    from mlx_lm import load

    tuning = c.tuning()
    weights, adapter = tag_module.local_model_choice(None, None, tuning)
    papers = sample(args.n)
    prompts = [schema.user_prompt(p) for p in papers]
    conn = c.connect(readonly=True)
    corpus = conn.execute("SELECT count(*) FROM papers WHERE doi_status = 'verified' "
                          "AND abstract <> ''").fetchone()[0]
    c.log(f"tag bench: {len(papers)} papers, {weights}{' + ' + adapter if adapter else ''}")
    model, tokenizer = load(weights, adapter_path=adapter)
    results: dict[str, dict] = {}
    texts: dict[str, list[str]] = {}

    def keep(name: str, r: dict, reference: list[str] | None) -> None:
        if "texts" in r:
            texts[name] = r.pop("texts")
            if reference is not None:
                r["agreement"] = agreement(texts[name][:len(reference)], reference)
        r.pop("mean_prob", None), r.pop("min_prob", None)
        results[name] = r
        c.log(f"tag bench: {name} {json.dumps(r)}")

    seq = run_sequential(model, tokenizer, prompts[:SEQUENTIAL_N])
    reference = seq["texts"]
    keep("sequential", seq, reference)

    for b in BATCH_SIZES:
        try:
            keep(f"batched-{b}", run_batched(model, tokenizer, prompts, b), reference)
        except Exception as e:  # noqa: BLE001  an out-of-memory size is a result, not a crash
            keep(f"batched-{b}", {"failed": str(e)[:200]}, None)
    batched = {k: v for k, v in results.items() if k.startswith("batched-")}
    best = pick(batched, reference)
    b = int(best["arm"].split("-")[1]) if best else 8

    if "prefix" not in skip:
        keep(f"prefix-{b}", run_batched(model, tokenizer, prompts, b, prefix=True), reference)
    use_prefix = (f"prefix-{b}" in results
                  and bool(pick({f"prefix-{b}": results[f"prefix-{b}"]}, reference))
                  and results[f"prefix-{b}"]["s_per_paper"] < results[f"batched-{b}"]["s_per_paper"])

    if "logprob" not in skip:
        greedy = run_batched(model, tokenizer, prompts, b, prefix=use_prefix, logprobs=True)
        sampled = run_batched(model, tokenizer, prompts, b, prefix=use_prefix, temperature=0.7)
        differs = [answer_key(g) != answer_key(s) for g, s in zip(greedy["texts"], sampled["texts"])]
        results["logprob"] = {
            "s_per_paper_with_probs": greedy["s_per_paper"],
            "sampled_disagrees": round(sum(differs) / len(differs), 3),
            "auc_mean_prob": auc([1 - p for p in greedy["mean_prob"]], differs),
            "auc_min_prob": auc([1 - p for p in greedy["min_prob"]], differs)}
        keep("sampled", sampled, None)
        c.log(f"tag bench: logprob {json.dumps(results['logprob'])}")

    if "speculative" not in skip:
        try:
            draft, _ = load(DRAFT_MODEL)
            keep("speculative", run_sequential(model, tokenizer, prompts[:SEQUENTIAL_N], draft),
                 reference)
        except Exception as e:  # noqa: BLE001
            keep("speculative", {"failed": str(e)[:200]}, None)

    if "small" not in skip:
        from pipeline import lab
        base, experiment, iteration = SMALL
        adapters = lab.unit_dir(experiment, 0, 42) / "adapters"
        if (adapters / f"{iteration:07d}_adapters.safetensors").exists():
            del model
            small, small_tok = load(base, adapter_path=str(lab.checkpoint(adapters, iteration)))
            # Not held to the agreement floor: a different model is expected to tag differently.
            keep("small-1.5b", run_batched(small, small_tok, prompts, b, prefix=use_prefix), None)

    greedy_s = (results[f"prefix-{b}"] if use_prefix else results[f"batched-{b}"])["s_per_paper"]
    sampled_s = results.get("sampled", {}).get("s_per_paper", greedy_s)
    hours = {"current": round(corpus * results["sequential"]["s_per_paper"] * 2 / 3600, 1),
             "chosen_two_pass": round(corpus * (greedy_s + sampled_s) / 3600, 1),
             "chosen_greedy_only": round(corpus * greedy_s / 3600, 1)}
    summary = {"measured": c.now(), "papers": len(papers), "corpus": corpus, "weights": weights,
               "batch_size": b, "prefix_cache": use_prefix, "projected_hours": hours,
               "arms": results}
    OUT.write_text(json.dumps(summary, indent=1))
    c.log(f"tag bench: batch {b}, prefix cache {use_prefix}; a full pass {hours['current']} h "
          f"now, {hours['chosen_two_pass']} h with both passes, {hours['chosen_greedy_only']} h "
          f"greedy only")

    if not args.dry_run:
        tuning_doc = tomllib.loads(TUNING.read_text())
        tuning_doc["tag_batch_size"] = b
        tuning_doc["tag_batch_size_status"] = f"measured by tools/tag_bench.py {c.now()[:10]}"
        tuning_doc["tag"] = {"batch_size": b, "prefix_cache": use_prefix,
                             "s_per_paper": greedy_s, "projected_hours": hours,
                             "status": f"measured {c.now()[:10]}, see {OUT.relative_to(c.ROOT)}"}
        TUNING.write_text(tomli_w.dumps(tuning_doc))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
