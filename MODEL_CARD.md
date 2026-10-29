# DEBRIS tagger debris_v1

A single LoRA fine-tune of `Qwen/Qwen2.5-3B-Instruct` that turns a PubMed title, journal,
MeSH list and abstract into the DEBRIS tag JSON (spec 5.4). It is trained on the task
and the schema, not on facts: the weekly pipeline never retrains it.

## Training

| | |
|---|---|
| Base model | `Qwen/Qwen2.5-3B-Instruct` |
| Method | LoRA, 16 layers, batch size 4, 1600 iterations, learning rate 1e-5, seed 42 |
| Data | `debris-train:v1` (1277 train, 161 valid, 162 test), stratified on relevance and model type |
| Vocabulary | `config/vocab.toml` schema version 1.0 |
| Labels | build session (no ANTHROPIC_API_KEY) |
| wandb | offline |
| Fused model | `data/adapters/debris_v1_fused` (de-quantised safetensors, Hugging Face layout) |
| Quantised | `data/adapters/debris_v1_q4` |

## Test-split metrics

| Field | Value | Acceptance floor |
|---|---|---|
| n | 162 |  |
| relevant_f1 | 0.9492 | 0.95 |
| polymers_f1 | 0.8021 | 0.85 |
| organ_systems_f1 | 0.7327 | 0.85 |
| pathways_f1 | 0.6031 | 0.75 |
| disease_categories_f1 | 0.8492 |  |
| rungs_exact | 0.8148 | 0.7 |
| rungs_within_one | 0.8457 | 0.9 |
| model_type_accuracy | 0.8523 | 0.9 |
| model_type_n | 88 |  |
| valid_json | 0.9938 | 0.98 |
| seconds_per_paper | 1.8 |  |
| model | /Users/dellboy/Documents/Vibe_Coding/debris/data/adapters/debris_v1_fused |  |

## Quantised (q4) comparison

| Field | Value |
|---|---|
| n | 162 |
| relevant_f1 | 0.87 |
| polymers_f1 | 0.6758 |
| organ_systems_f1 | 0.6398 |
| pathways_f1 | 0.3885 |
| disease_categories_f1 | 0.8098 |
| rungs_exact | 0.5741 |
| rungs_within_one | 0.7222 |
| model_type_accuracy | 0.7727 |
| model_type_n | 88 |
| valid_json | 1.0 |
| seconds_per_paper | 1.33 |
| model | /Users/dellboy/Documents/Vibe_Coding/debris/data/adapters/debris_v1_q4 |

## Acceptance

Below floor: relevant_f1 0.949 < 0.95; polymers_f1 0.802 < 0.85; organ_systems_f1 0.733 < 0.85; pathways_f1 0.603 < 0.75; rungs_within_one 0.846 < 0.9; model_type_accuracy 0.852 < 0.9

## Intended use and limits

DEBRIS tags literature, it does not adjudicate science. A tag records what a paper
reports: a polymer detected, an association observed in a cohort, a mechanism shown
in vitro. Nothing in the schema asserts human causation, and the evidence rungs are
deliberately ordered so that a reader can see how far from a human outcome a given
claim sits. Reviews carry no rungs. Papers the tagger is unsure about are routed to
the review queue and shown as "needs review" rather than silently published.
