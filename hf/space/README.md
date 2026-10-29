---
title: DEBRIS tagger
emoji: 🧫
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: 6.29.1
app_file: app.py
pinned: false
license: mit
short_description: Tags micro and nanoplastic disease literature for DEBRIS
---

# DEBRIS tagger

Inference endpoint for [debris.mdeller.com](https://debris.mdeller.com): the weekly
refresh sends batches of 16 PubMed abstracts to the `tag` endpoint and receives the
DEBRIS tag JSON (polymer, size class, organ system, disease category, pathway, model
type, evidence rungs, PET specificity, a 30-word summary and a confidence).

The model is `Dellboy/debris-tagger-v1`, one LoRA fine-tune of Qwen2.5-3B-Instruct on
1,600 labelled abstracts. It is trained on the task and the schema, not on facts, and
is never retrained by the weekly pipeline. Tags record what a paper reports: nothing
in the schema asserts human causation.

Built by Marc C. Deller, D.Phil., Elora Therapeutics.
