"""DEBRIS tagger on ZeroGPU (spec 5.6 path A).

A Gradio app exposing one endpoint, `tag`, that takes a JSON list of
{"pmid": ..., "prompt": ...} and returns a JSON list of
{"pmid": ..., "tag": {...}, "sampled": {...}, "self_consistency": float}.

The model is loaded once at import in bf16; only generation is decorated with
@spaces.GPU, so the Space holds no GPU between calls and the weekly run fits inside
the free ZeroGPU quota. Validation against config/vocab.toml happens here too, so a
malformed generation never reaches the caller.

Pattern lifted from chatMCD/space/app.py (see REUSE.md).
"""
from __future__ import annotations

import json
import os

import gradio as gr
import spaces
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_ID = os.environ.get("DEBRIS_MODEL", "Dellboy/debris-tagger-v1")
MAX_NEW_TOKENS = 480
BATCH_LIMIT = 16

VOCAB_PATH = os.path.join(os.path.dirname(__file__), "vocab.toml")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.py")

# vocab.toml and schema.py are copied into the Space by hf/push_model.py, so the
# Space validates against exactly the vocabulary the tagger was trained on.
import schema  # noqa: E402  (sits beside this file in the Space repo)

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, token=os.environ.get("HF_TOKEN"))
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID, torch_dtype=torch.bfloat16, device_map="cuda",
    token=os.environ.get("HF_TOKEN"))
model.eval()


def build(prompt: str) -> str:
    return tokenizer.apply_chat_template(
        [{"role": "system", "content": schema.SYSTEM_PROMPT},
         {"role": "user", "content": prompt}],
        add_generation_prompt=True, tokenize=False)


@spaces.GPU(duration=120)
def generate(prompts: list[str], temperature: float, seed: int | None = None) -> list[str]:
    if seed is not None:
        torch.manual_seed(seed)
    batch = tokenizer([build(p) for p in prompts], return_tensors="pt",
                      padding=True, padding_side="left").to(model.device)
    with torch.no_grad():
        output = model.generate(
            **batch, max_new_tokens=MAX_NEW_TOKENS,
            do_sample=temperature > 0, temperature=temperature or None,
            top_p=0.95 if temperature > 0 else None,
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id)
    generated = output[:, batch["input_ids"].shape[1]:]
    return tokenizer.batch_decode(generated, skip_special_tokens=True)


def tag(payload: str) -> str:
    """The endpoint the weekly run calls through gradio_client."""
    try:
        papers = json.loads(payload) if isinstance(payload, str) else payload
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"payload is not JSON: {exc}"})
    if not isinstance(papers, list):
        return json.dumps({"error": "payload must be a list"})
    papers = papers[:BATCH_LIMIT]
    prompts = [p.get("prompt", "") for p in papers]

    greedy_texts = generate(prompts, 0.0)
    sampled_texts = generate(prompts, 0.7, seed=42)

    out = []
    for paper, greedy_text, sampled_text in zip(papers, greedy_texts, sampled_texts):
        greedy, problems, candidates = schema.validate(schema.extract_json(greedy_text))
        sampled, _, _ = schema.validate(schema.extract_json(sampled_text))
        out.append({
            "pmid": paper.get("pmid"),
            "tag": greedy,
            "sampled": sampled,
            "self_consistency": schema.self_consistency(greedy, sampled) if greedy else 0.0,
            "problems": problems,
            "candidates": candidates,
        })
    return json.dumps(out)


with gr.Blocks(title="DEBRIS tagger") as demo:
    gr.Markdown(
        "# DEBRIS tagger\n\n"
        "Tags micro and nanoplastic disease literature against the DEBRIS schema "
        "(polymer, size class, organ system, disease category, pathway, model type, "
        "evidence rung). The weekly refresh behind "
        "[debris.mdeller.com](https://debris.mdeller.com) calls the `tag` endpoint "
        "with batches of 16 abstracts."
    )
    payload_in = gr.Textbox(label="Batch JSON: [{\"pmid\": ..., \"prompt\": ...}]", lines=8)
    payload_out = gr.Textbox(label="Tags JSON", lines=14)
    gr.Button("Tag").click(tag, inputs=payload_in, outputs=payload_out, api_name="tag")

if __name__ == "__main__":
    demo.queue(max_size=8).launch()
