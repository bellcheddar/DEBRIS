# DEBRIS tagger debris_v1

A single LoRA fine-tune of `Qwen/Qwen2.5-7B-Instruct` that turns a PubMed title, journal,
MeSH list and abstract into the DEBRIS tag JSON (spec 5.4). It is trained on the task
and the schema, not on facts: the weekly pipeline never retrains it.

## Training

| | |
|---|---|
| Base model | `Qwen/Qwen2.5-7B-Instruct` |
| Method | LoRA, 28 layers, batch size 4, 1600 iterations, learning rate 1e-5, seed 42 |
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
| relevant_f1 | 0.954 | 0.95 |
| polymers_f1 | 0.8778 | 0.85 |
| organ_systems_f1 | 0.7782 | 0.85 |
| pathways_f1 | 0.7047 | 0.75 |
| disease_categories_f1 | 0.9141 |  |
| rungs_exact | 0.8704 | 0.7 |
| rungs_within_one | 0.8827 | 0.9 |
| model_type_accuracy | 0.8636 | 0.9 |
| model_type_n | 88 |  |
| valid_json | 1.0 | 0.98 |
| seconds_per_paper | 3.38 |  |
| model | /Users/dellboy/Documents/Vibe_Coding/debris/data/adapters/debris_v1_fused |  |

## Quantised (q4) comparison

| Field | Value |
|---|---|
| n | 162 |
| relevant_f1 | 0.9497 |
| polymers_f1 | 0.8495 |
| organ_systems_f1 | 0.7633 |
| pathways_f1 | 0.6458 |
| disease_categories_f1 | 0.9141 |
| rungs_exact | 0.8642 |
| rungs_within_one | 0.8765 |
| model_type_accuracy | 0.8864 |
| model_type_n | 88 |
| valid_json | 1.0 |
| seconds_per_paper | 2.23 |
| model | /Users/dellboy/Documents/Vibe_Coding/debris/data/adapters/debris_v1_q4 |

## Acceptance

Below floor: organ_systems_f1 0.778 < 0.85; pathways_f1 0.705 < 0.75; rungs_within_one 0.883 < 0.9; model_type_accuracy 0.864 < 0.9

## Intended use and limits

DEBRIS tags literature, it does not adjudicate science. A tag records what a paper
reports: a polymer detected, an association observed in a cohort, a mechanism shown
in vitro. Nothing in the schema asserts human causation, and the evidence rungs are
deliberately ordered so that a reader can see how far from a human outcome a given
claim sits. Reviews carry no rungs. Papers the tagger is unsure about are routed to
the review queue and shown as "needs review" rather than silently published.

## Known label limits

Some fields carry more label noise than others, and the measurements behind this are in
DECISIONS.md D22 and D25. A reader of the tagged corpus should know which way each field
errs.

**Evidence rung 5 is a lower bound.** Dose-response is recorded only where the article
reports more than one exposure level, or states a dose or concentration dependent effect.
That rule removed 144 of the original 245 rung-5 labels, most of them papers reporting a
size-dependent rather than a dose-dependent effect, and left 82 instances across the
relevant training rows. The tagger's commonest rung error is leaving rung 5 off a paper
that has it, so a paper shown without rung 5 may still have demonstrated a dose response.
The error does not run the other way to any comparable degree.

**`systemic` is a soft organ label.** It carries its own vocabulary in the abstract in
29 % of instances, against 100 % for renal and 98 % for gastrointestinal, so in practice
it is a residual category for multi-organ or unlocalised work rather than a finding. It is
also the organ system the tagger most often fails to predict.

**`cell_line` and `human_in_vitro` overlap.** Gold `cell_line` names an immortalised line
(Caco-2, HepG2, A549 and the like) in 60 % of its papers and gold `human_in_vitro` in
25 %, while only 16 % of `human_in_vitro` papers mention primary or ex vivo material. The
boundary is therefore not a rule the schema states, and most model-type errors sit on it.
Read `model_type` as a broad design class and not as a precise claim about the material.

**Pathways are over-reported rather than under-reported.** Precision is the weaker side:
the tagger volunteers mechanisms that are plausible for the exposure but not measured in
the paper, and a substantial minority of its false-positive `oxidative_stress` calls have
no oxidative vocabulary anywhere in the abstract. `leachate_chemical_toxicity` is weakly
grounded in both directions. Treat a pathway on a single paper as a pointer to the
abstract rather than as a finding, and weigh the pathway hub on counts across many papers.
