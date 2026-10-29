# DEBRIS: Build Specification

**Disease Evidence from Bioaccumulated plastic Residues: Indexed Studies**

| | |
|---|---|
| Spec version | 2.0 (2026-10-28): quick automated build, two gates, reuse-first, pre-approved deploy, wandb + Hugging Face ZeroGPU |
| Owner | Marc C. Deller, D.Phil., Co-Founder and CSO, Elora Therapeutics |
| Project root | `/Users/dellboy/Documents/Vibe_Coding/debris/` |
| Serve target | `https://debris.mdeller.com` (DNS, nginx and certbot already live; **deploy is pre-approved**) |
| Wall-clock target | First deployed version within **24 hours** of launch; full corpus and weekly job within 48 |
| Hard deadline | Populated and stable by 2026-11-30; NHLBI/NIEHS workshop 2026-12-07/08 |
| Build mode | Unattended. Section 0 governs. Two gates only. |

DEBRIS is an Elora-branded web app that mines every DOI-verified PubMed article implicating PET and other micro/nanoplastics in human disease, tags each paper (polymer, organ, disease, pathway, model type, evidence rung) with a once-trained 3B LLM, and presents the corpus as a polymer Venn with an evidence ladder, a clickable body map, a pathway hub and a live papers feed. The corpus refreshes weekly with no retraining. Training is tracked in Weights & Biases; weekly inference runs on a Hugging Face ZeroGPU Space so the refresh needs neither the Studio nor a GPU on the droplet.

---

## 0. Autonomy directive

### 0.1 Build fast, decide, log

1. **Run to completion without asking.** Pick the most defensible option, write one line to `DECISIONS.md` (decision, alternative, reason, reverse-by), continue. No plan-approval pauses, no confirmations, no "shall I proceed".
2. **Ship early, then improve.** A deployed app with a partial corpus beats a perfect app on localhost. Deploy at the end of Phase 1 (harvested corpus, no tags), again after Phase 2 (tagged), and after every later phase. Each deploy is `deploy/deploy.sh`, run by the build itself.
3. **Reuse before writing.** Section 3 lists the sibling projects under `/Users/dellboy/Documents/Vibe_Coding/` whose code is to be copied. Grep them first; write new code only where nothing fits. Record every lift in `REUSE.md` (source path, destination, what changed).
4. **Fallback ladder for any failure:** retry once with a fix, then the documented alternative, then the next-best tool, then degrade (skip the item, flag `status = "failed:<reason>"`, continue). One paper, one tag, one optional service never blocks the build.
5. **Resumable.** Every stage writes `data/manifests/<stage>.jsonl`; on restart read `PROGRESS.md` and skip done items. Assume the process can be killed at any moment.
6. **Log as you go.** `BUILD_LOG.md` (timestamped lines) and `PROGRESS.md` (phase checklist with percentages, rewritten after every phase and at least every 30 minutes during compute).
7. **Never idle.** While the tag run proceeds, build the app against tagged tiers already available; backfill when manifests complete.
8. **Commit locally at each phase** (`phase N: <summary>`). No `git push`, no repo creation (public release is Marc's call, later, not a gate: just don't do it).
9. **Stay inside the project root** except package caches, the droplet paths named in `config/deploy.toml`, the wandb project and the Hugging Face repos named in `config/hf.toml`. Never `sudo` locally. On the droplet, use only the commands the existing AlphaFraud deploy already uses.
10. **Keep the Mac awake** with `caffeinate -dimsu` around any step over ten minutes.
11. **House style:** British English, no em dashes (colons or parentheses), none of groundbreaking, revolutionary, paradigm-shifting, game-changing, cutting-edge, unprecedented, seamless, leverage (verb), delve. App copy never claims human causation ("implicated", "associated", "detected", "reported").

### 0.2 Gates: exactly two

| Gate | Opens only when | Needs from Marc |
|---|---|---|
| **G1 Blocked** | A step has no fallback at all: the droplet is unreachable with the AlphaFraud credentials and `config/deploy.toml` is absent; or the project volume is under 30 GB free and nothing in `data/` is safe to prune | SSH details, or what to prune |
| **G2 Science** | The tagger misses the Phase 2 floor after the full fallback ladder **and** a gold positive control is wrong in a way that would change a headline Atlas figure | "Ship with the provisional-tags banner" or "retrain with these changes" |

Everything else is handled by a fallback, never a gate:

| Missing | Fallback (automatic) |
|---|---|
| `ANTHROPIC_API_KEY` | The build session itself writes the bootstrap labels (25 abstracts per batch, straight to JSONL). Weekly low-confidence papers go to `review_queue`, shown as "needs review" |
| `NCBI_API_KEY` | 3 requests per second with tenacity backoff |
| `WANDB_API_KEY` | `WANDB_MODE=offline`; runs stored under `wandb/` and the sync command written to `GATE_NOTES.md` (informational, not a gate) |
| `HF_TOKEN` or no ZeroGPU quota | Weekly inference runs on the Studio via launchd with the mlx model (Section 5.6, path B) |
| Qwen2.5-3B fails the smoke test | Qwen2.5-1.5B-Instruct, then 7B, then CPU |
| Playwright Chromium absent | Skip screenshots, log degraded, never `playwright install` |

**Gate protocol:** write `GATE_OPEN.md` (gate, exactly what is needed, the command that unblocks it, what is done, what happens next); `osascript -e 'display notification "<one line>" with title "DEBRIS gate <id>" sound name "Glass"'`; keep working on everything the gate does not block. The expected end state of a clean run is **zero open gates and the app live at debris.mdeller.com**.

### 0.3 Launch recipe

```bash
cd /Users/dellboy/Documents/Vibe_Coding/debris
export ANTHROPIC_API_KEY=... NCBI_API_KEY=... WANDB_API_KEY=... HF_TOKEN=...   # any may be omitted
./launch.sh          # tmux session "debris", Claude Code reads this spec and executes it
```

`.claude/settings.json` (Appendix A) and `CLAUDE.md` (Appendix B) are already in the folder.

---

## 1. Goals

1. **Coverage.** Every PubMed article (2004 to present) implicating micro/nanoplastics in a human disease state, admitted only if its DOI resolves at Crossref with a matching title.
2. **Structure.** Controlled-vocabulary tags per paper: polymers, size class, organ systems, disease category and terms, pathways, model type, evidence rungs, PET specificity, 30-word summary, confidence.
3. **PET in context.** PET's share visible in every view, never hiding the rest of the polymer field.
4. **Evidence honesty.** Per-disease evidence ladder, rung 6 "reversible on particle removal" drawn even when empty.
5. **Liveness.** Weekly refresh with no human step; new papers and new polymer-organ-pathway combinations highlighted on arrival.
6. **Durable tagger.** One fine-tune of the task and schema, never of facts; drift measured weekly; no retraining in the pipeline.
7. **Reproducible training.** Dataset versions, hyperparameters, metrics and the model card live in wandb; the model lives on the Hugging Face Hub.
8. **Workshop ready.** Atlas (Heart filter) → Body → Pathways → Papers feed in under four minutes on a shared screen.

---

## 2. Hardware

Probe, then derive; never hard-code. `tools/hwprobe.py` (copy from the most recent sibling project that has one; otherwise write it) produces `config/hardware.toml` from `sysctl` (`machdep.cpu.brand_string`, `hw.perflevel0.physicalcpu`, `hw.perflevel1.physicalcpu`, `hw.memsize`), `system_profiler SPDisplaysDataType`, `df`, and `mx.metal.is_available()`.

`config/tuning.toml`: `cpu_workers` = performance cores minus 2 (min 2); `io_workers` = 8; `model_backend` = `mlx`; `model_id` = `Qwen/Qwen2.5-3B-Instruct`; `model_instances` = 1 (one resident model, never reloaded); `tag_batch_size` = 8 (halve on Metal allocation error); `memory_headroom_gb` = 24; `MAX_COMPUTE_HOURS` = 24. Environment: `TOKENIZERS_PARALLELISM=false`, `OMP_NUM_THREADS=<cpu_workers>`.

Concurrency: IO pool (E-utilities, Crossref) → one resident mlx model (tag queue in priority tiers: gold set, human papers, cohort/tissue text hits, animal and in vitro, reviews) → CPU pool (validation, novelty, aggregate) → SQLite + static JSON. Communicate through files and manifests only. The Phase 2 smoke test times 50 abstracts and extrapolates; if the projection exceeds budget, cap the summary field tokens, then drop tier 5, then tag the rest on the ZeroGPU Space in parallel (5.6 path A) rather than stopping.

---

## 3. Reuse map (read before writing anything)

Scan `/Users/dellboy/Documents/Vibe_Coding/` at the start of Phase 1. Expected sources and what to lift; adapt the list to what is actually on disk and record it in `REUSE.md`.

| Need | Lift from | Notes |
|---|---|---|
| Weekly pipeline + always-on Flask/gunicorn sharing one SQLite on the droplet; systemd timer and service units; nginx vhost; deploy rsync script; droplet host, user and key | **AlphaFraud** (`alphafraud.mdeller.com`, live) | This is the reference architecture. Copy its `deploy/` and timer pattern wholesale; change names and paths. The droplet SSH details come from AlphaFraud's deploy config, so `config/deploy.toml` is only needed if they are not there |
| mlx-lm LoRA training scripts, chat-format JSONL preparation, fuse and quantise steps, model smoke test | **chatMCD** and **FAFFAbout / TargetTrack** | Reuse the data-prep and train wrappers; change the system prompt and schema |
| ZeroGPU Space pattern, Gradio endpoint with `@spaces.GPU`, `gradio_client` caller with retry | **SEANCE** (if its ZeroGPU fallback is built) | Otherwise write `hf/space/app.py` from the template in 5.6 |
| Flask tab layout, Plotly responsive config, Tabulator table, detail drawer, `/healthz` | **CODSWALLOP**, **AlphaFraud** | Keep the structure, swap the design system for Elora's (6.2) |
| Plotly Venn / Sankey / scatterpolar helpers, CSV export | any branded HTML app in the portfolio | Vendor the same pinned Plotly build |
| `readme_forge.py`, icon generation, favicon set script | `marcs-vibe-coding` and `marcs-vibe-icon` skill folders | Run non-interactively in Phase 4 |
| `hwprobe.py`, tenacity-wrapped fetch helpers, manifest read/write helpers | KINFOLK, GOBSMACKED or SEANCE, whichever exists | Copy, do not symlink |

Rule: copy files into `debris/`, never import across project folders, never modify a sibling project.

---

## 4. Environment

| Component | Primary | Fallback |
|---|---|---|
| Pipeline env | pixi (`osx-arm64`): `python 3.12`, `mlx-lm`, `requests`, `tenacity`, `pandas`, `pyarrow`, `duckdb`, `pydantic`, `rapidfuzz`, `tomli`, `tqdm`, `pytest`, `wandb`, `huggingface_hub`, `gradio_client` | Homebrew Python + venv, pip |
| App env (local and droplet) | uv: `flask`, `gunicorn`, `jinja2`, `requests`, `tenacity`, `gradio_client`, `pytest`, `playwright` | pip venv |
| Space env (`hf/space/requirements.txt`) | `torch`, `transformers`, `accelerate`, `gradio`, `spaces` | none needed; path B replaces it |
| Front end, vendored under `app/static/vendor/` | `plotly-2.35.2.min.js`, `d3.v7.min.js` (Venn geometry only), `tabulator 6.3.1` | CDN links |
| Fonts | Google Fonts Montserrat 400/600/700/800, IBM Plex Mono 400/500 | self-hosted woff2 |

Layout:

```
debris/
  DEBRIS_BUILD_SPEC.md CLAUDE.md DECISIONS.md REUSE.md BUILD_LOG.md PROGRESS.md FINDINGS.md README.md
  .claude/settings.json  launch.sh
  config/   hardware.toml tuning.toml vocab.toml query.toml deploy.toml hf.toml wandb.toml
  pipeline/ harvest.py verify_doi.py bootstrap_labels.py train.py tag.py validate.py novelty.py aggregate.py weekly.py drift.py
  tools/    hwprobe.py smoke_test.py
  hf/       push_model.py  space/{app.py,requirements.txt,README.md}
  data/     raw/ labels/ train/ adapters/ manifests/ debris.sqlite snapshots/
  app/      app.py templates/ static/{css,js,vendor,data,fonts} tests/
  deploy/   deploy.sh debris-gunicorn.service debris-weekly.service debris-weekly.timer nginx.debris.conf weekly.sh
  icons/
  tests/
```

---

## 5. Data and methods

### 5.1 PubMed harvest (`pipeline/harvest.py`)

Two strategies, unioned, with `hit_strategy` kept per PMID.

**A (MeSH):** `("Microplastics"[Mesh] OR "Polyethylene Terephthalates"[Mesh] OR "Polystyrenes"[Mesh] OR "Polyethylene"[Mesh] OR "Polypropylenes"[Mesh] OR "Polyvinyl Chloride"[Mesh]) AND ("Cardiovascular Diseases"[Mesh] OR "Lung Diseases"[Mesh] OR "Hematologic Diseases"[Mesh] OR "Neoplasms"[Mesh] OR "Kidney Diseases"[Mesh] OR "Liver Diseases"[Mesh] OR "Brain Diseases"[Mesh] OR "Nervous System Diseases"[Mesh] OR "Sleep Wake Disorders"[Mesh] OR "Gastrointestinal Diseases"[Mesh] OR "Pregnancy Complications"[Mesh] OR "Inflammation"[Mesh] OR "Oxidative Stress"[Mesh] OR "Thrombosis"[Mesh] OR "Metabolic Diseases"[Mesh] OR "Immune System Diseases"[Mesh]) AND 2004:3000[dp]`

**B (text-word, catches the indexing lag):** `(microplastic*[tiab] OR nanoplastic*[tiab] OR "micro-nanoplastic*"[tiab] OR "micro(nano)plastic*"[tiab] OR "plastic particle*"[tiab]) AND (disease[tiab] OR cancer[tiab] OR tumour[tiab] OR tumor[tiab] OR cardiovascular[tiab] OR atherosclero*[tiab] OR thrombo*[tiab] OR platelet*[tiab] OR lung[tiab] OR pulmonary[tiab] OR asthma[tiab] OR fibrosis[tiab] OR blood[tiab] OR an?emia[tiab] OR kidney[tiab] OR renal[tiab] OR liver[tiab] OR hepat*[tiab] OR brain[tiab] OR neuro*[tiab] OR sleep[tiab] OR circadian[tiab] OR placenta*[tiab] OR colorectal[tiab] OR intestin*[tiab] OR inflamm*[tiab] OR "oxidative stress"[tiab]) AND 2004:3000[dp]`

Never search `PET[tiab]` alone (positron emission tomography). `efetch` XML in batches of 200: PMID, title, labelled abstract, journal, year, month, authors, MeSH, publication types, DOI, `EDAT` (the weekly watermark). Write `data/raw/pubmed_<date>.jsonl`; papers without abstracts are stored but not tagged (`no_abstract`).

### 5.2 DOI verification (`pipeline/verify_doi.py`)

`GET https://api.crossref.org/works/{doi}` with `User-Agent: DEBRIS/1.0 (mailto:marc@marcdeller.com)`. Admit when 200 **and** `rapidfuzz.fuzz.token_set_ratio(pubmed_title, crossref_title) >= 90`. `doi_status` ∈ {`verified`, `unresolved`, `title_mismatch`, `missing`}. Crossref `update-to` retractions set `retracted = 1` (strike-through in the app, never deleted). Only `verified` papers count anywhere; the Papers tab has an "include unverified" switch, off by default.

### 5.3 Gold seed set and negatives

Resolve by PubMed search at run time (never hand-typed IDs), log what was found: the NEJM 2024 carotid plaque MNP cohort; the 2022 Environment International blood detection study; the 2022 Science of the Total Environment lung tissue study; the 2025 Nature Medicine brain accumulation study; the 2021 placenta detection study; two colorectal or intestinal migration/inflammation studies; one PET leachate toxicity study; one broad review. Harvest ~400 negatives: positron emission tomography oncology, marine ecology microplastics, polymer chemistry and recycling, analytical methods. These are `relevant = false` and never shown.

### 5.4 Tagging schema (`config/vocab.toml` is the single source of truth)

```json
{"relevant": true, "polymers": ["PET","PS"], "size_class": "micro",
 "organ_systems": ["cardiovascular","hematologic"], "disease_categories": ["atherosclerosis_mace","thrombosis"],
 "disease_terms": ["carotid artery disease","myocardial infarction"],
 "pathways": ["inflammasome_il1b","endothelial_dysfunction"], "model_type": "human_tissue",
 "evidence_rungs": [1,2], "pet_specific": true,
 "summary": "PET and PVC detected in carotid plaque; MNP-positive patients had higher rates of major cardiovascular events over 34 months.",
 "confidence": 0.92}
```

| Field | Values |
|---|---|
| `polymers` | `PET`, `PS`, `PE`, `PP`, `PVC`, `PA`, `PU`, `PMMA`, `PC`, `PLA`, `PTFE`, `tyre_wear`, `mixed_unspecified`, `other:<text>` |
| `size_class` | `nano` (< 1 µm), `micro` (1 µm to 5 mm), `mixed`, `unspecified` |
| `organ_systems` | `cardiovascular`, `respiratory`, `hematologic`, `neurological`, `sleep`, `gastrointestinal`, `hepatic`, `renal`, `reproductive_placental`, `endocrine_metabolic`, `immune`, `dermal`, `systemic` |
| `disease_categories` | `cancer_colorectal`, `cancer_other`, `atherosclerosis_mace`, `thrombosis`, `hypertension_arrhythmia`, `copd_asthma`, `pulmonary_fibrosis`, `anaemia_haemolysis`, `neuroinflammation_neurodegeneration`, `sleep_circadian`, `ibd_gut`, `liver_disease`, `kidney_disease`, `pregnancy_outcomes`, `metabolic_syndrome`, `immune_dysfunction`, `none` |
| `pathways` | `oxidative_stress`, `inflammasome_il1b`, `nfkb_cytokine`, `endothelial_dysfunction`, `platelet_activation_thrombosis`, `fibrosis_tgfb`, `emt_migration`, `barrier_disruption`, `mitochondrial_dysfunction`, `apoptosis_ferroptosis`, `dysbiosis`, `dna_damage_genotoxicity`, `immune_dysregulation`, `leachate_chemical_toxicity`, `other:<text>` |
| `model_type` | `human_tissue`, `human_cohort`, `human_in_vitro`, `organoid`, `animal_in_vivo`, `cell_line`, `in_silico`, `review`, `meta_analysis` |
| `evidence_rungs` | 1 detected in human tissue or fluid; 2 associated with outcome in a human cohort; 3 reproduced in vivo; 4 mechanism in vitro or ex vivo; 5 dose-response; 6 reversible on particle removal or degradation. Reviews: `[]` |

`other:` values are logged to `vocab_candidates` and listed in `FINDINGS.md`; vocabulary changes are a later human decision.

### 5.5 Bootstrap labels, wandb, and the one-time fine-tune

**Labels** (`pipeline/bootstrap_labels.py`): 1,600 abstracts (gold set, 400 negatives, 1,100 stratified by strategy, year and MeSH organ group), labelled by `claude-sonnet-4-5` with the schema and one-line vocabulary definitions in the system prompt (or by the build session itself if no key). Validate every label. Split 80/10/10 stratified on `relevant` and `model_type` into `data/train/{train,valid,test}.jsonl` in mlx-lm chat format:

```json
{"messages":[{"role":"system","content":"You are DEBRIS, a tagger for micro/nanoplastic disease literature. Return only JSON matching the schema. Vocabulary: <compact block>"},
 {"role":"user","content":"TITLE: ...\nJOURNAL: ... (2024)\nMESH: ...\nABSTRACT: ..."},
 {"role":"assistant","content":"{\"relevant\": true, ...}"}]}
```

**wandb** (`config/wandb.toml`: `project = "debris"`, `entity` = Marc's default): log the bootstrap labels as a `wandb.Table`, upload `data/train/` as a versioned Artifact (`debris-train:v1`, with the vocabulary file and the label prompt attached), log the training run (loss curves, learning rate, iterations, the smoke-test timing), log the test-split metrics table and the quantised-vs-fused comparison, and attach the model card. Use `mlx_lm.lora --wandb debris` if that flag exists in the installed version; otherwise parse the training log and log metrics with a thin wrapper. Offline mode if no key; never a gate.

**Train once** (`pipeline/train.py`, reuse the chatMCD wrapper):

```
mlx_lm.lora --model Qwen/Qwen2.5-3B-Instruct --train --data data/train --fine-tune-type lora \
  --num-layers 16 --batch-size 4 --iters 800 --learning-rate 1e-5 --adapter-path data/adapters/debris_v1 --seed 42
mlx_lm.fuse --model Qwen/Qwen2.5-3B-Instruct --adapter-path data/adapters/debris_v1 \
  --save-path data/adapters/debris_v1_fused --de-quantize
mlx_lm.convert --hf-path data/adapters/debris_v1_fused -q --mlx-path data/adapters/debris_v1_q4
```

The de-quantised fused model is plain safetensors in Hugging Face layout, loadable by `transformers` on the Space; the q4 copy is for Studio-side inference. Confirm q4 matches fused within 2 F1 points on the test split, else use fused.

**Acceptance floor** (`test.jsonl`): `relevant` F1 ≥ 0.95; `polymers` and `organ_systems` micro-F1 ≥ 0.85; `pathways` micro-F1 ≥ 0.75; `evidence_rungs` exact ≥ 0.70, within one rung ≥ 0.90; `model_type` accuracy ≥ 0.90; valid JSON first attempt ≥ 0.98. Fallback ladder: iters 800 → 1,600; `--num-layers` 32; Qwen2.5-7B; collapse pathways to the six most frequent plus `other`; then G2. The adapter is trained once; `MODEL_CARD.md` records model hash, data artifact version, metrics and wandb run URL.

### 5.6 Inference: Hugging Face ZeroGPU first, Studio second

**Path A (primary): ZeroGPU Space.** `hf/push_model.py` pushes `debris_v1_fused` to the Hub as `Dellboy/debris-tagger-v1` (private is fine) with the model card. `hf/space/app.py` is a Gradio app on ZeroGPU hardware (`Dellboy/debris-tagger`) exposing `tag(batch: list[dict]) -> list[dict]`: loads the model once in bf16, decorates generation with `@spaces.GPU(duration=120)`, runs the greedy and the sampled pass, validates JSON against the vocabulary, returns tags plus `self_consistency`. Batches of 16 abstracts per call. The caller (`pipeline/tag.py` in `--remote` mode, and `pipeline/weekly.py` on the droplet) uses `gradio_client` with tenacity retry and a 20-minute total budget per weekly run; ZeroGPU quota exhaustion is retried next hour, up to six times, then falls to path B for that week. Space creation needs `HF_TOKEN` with write scope and a ZeroGPU-eligible account; if either is missing the build logs it and runs path B, and `hf/` stays in the repo ready to deploy when the token appears.

**Path B (fallback): Studio launchd.** `deploy/com.mdeller.debris.weekly.plist` runs `caffeinate -dimsu pixi run weekly --local` Sunday 02:00 using the q4 mlx model, then `deploy/deploy.sh --data-only`. Loaded with `launchctl bootstrap gui/$(id -u)` by the build (allowed in Appendix A).

With path A live, the weekly job runs **on the droplet** as a systemd timer exactly like AlphaFraud's (harvest since the `EDAT` watermark → verify → tag via the Space → novelty → aggregate → swap the SQLite and JSON atomically → restart nothing, since the app reads at request time). The Studio is then only needed for retraining, which the pipeline never does on its own.

### 5.7 Tagging, validation, novelty, drift

Two passes per paper (greedy and temperature 0.7, fixed seed); store the greedy tag; `self_consistency` = Jaccard agreement of list fields plus rung set. Route to `review_queue` when `confidence < 0.6`, `self_consistency < 0.7`, any `other:` value, or invalid JSON after one re-prompt; with an API key those are re-tagged by the frontier model (`tag_source = "fallback_api"`).

Novelty (`pipeline/novelty.py`, no LLM): for each newly admitted paper, every `(polymer, organ_system, pathway)` triple and `(polymer, disease_category)` pair; any not previously present sets `novel = 1` and writes `novelty_events`; a new maximum rung per `(polymer, disease_category)` writes `ladder_events`.

Drift (`pipeline/drift.py`): weekly sample of 20 new papers re-tagged by the frontier model when a key is present, per-field F1 into `drift_log` and the app footer; otherwise the self-consistency distribution and review rate. Relevance F1 < 0.90 or review rate > 25 % for two weeks writes a recommendation to `FINDINGS.md`. Never retrains.

---

## 6. App

### 6.1 Architecture

Flask + Jinja + gunicorn (uv). Plotly (scatterpolar, sankey, bar), D3 for Venn circle placement only, Tabulator for the Papers table, inline SVG body map. **No request-time compute**: `pipeline/aggregate.py` writes every chart's data to `app/static/data/*.json` at ingest; Flask reads read-only SQLite only for the paginated Papers table and the detail drawer. Targets: every tab interactive within 1.5 s on the droplet, JSON bundle < 5 MB, SQLite < 150 MB. Same droplet as AlphaFraud; separate service, port and vhost.

### 6.2 Design system: Elora Therapeutics (approved own design system; replaces the marcdeller.com header)

```css
:root{--el-blue:#385098;--el-ink:#2A3C78;--el-soft:#E3E8F4;--el-tint:#F0F3FA;--el-bg:#F8F8F8;--el-fg:#1C2238;
 --el-muted:#5A6180;--el-line:#D6DAE6;--el-card:#FFFFFF;
 --pet:#C8872B;--ps:#2C8C86;--pe-pp:#B84C62;--pvc:#6E5BA6;--other:#8A93AD;--new:#C8872B;
 --display:'Montserrat',Helvetica,Arial,sans-serif;--mono:'IBM Plex Mono',Menlo,monospace}
```

Montserrat 800 uppercase, 0.08 em tracking for the DEBRIS wordmark and tab labels; 600 with 0.4 em tracking for eyebrows (the "THERAPEUTICS" treatment); mono for PMIDs, DOIs, counts, dates. 14 px top-right chamfer (`clip-path`) on cards and tabs, echoing the cut on the logo's L and T. Section numbering `01 Atlas`, `02 Body`, `03 Pathways`, `04 Papers`. Header: Elora wordmark as text linking to eloratherapeutics.com, DEBRIS title, last-updated stamp, workshop line. Footer: "Built by Marc C. Deller, D.Phil., Elora Therapeutics", marcdeller.com and eloratherapeutics.com links, verified count, last drift value. Light theme only, all colours as tokens. PET is `--pet` in every chart. Mobile: single column at 768 px, tabs as a horizontal scroll strip, SVGs scale by viewBox.

### 6.3 Tabs

**01 Atlas.** Three-set Venn (PET / PS / PE+PP) plus a small two-set Venn (PVC / other); region counts are verified papers; click a region → Papers pre-filtered. Organ chips (All, Heart, Lung, Blood, Sleep/Neuro, Brain, Gut/CRC, Liver, Kidney, Placenta) redraw it; "PET-specific only" switch. Evidence ladder: stacked horizontal bars per disease category by rung 1 to 6, PET vs all toggle, rung 6 drawn in `--pet` even when empty with the label "the rung an enzyme therapeutic can test". Year sparkline 2004 to now. KPI row: verified papers, PET papers, organ systems covered, new this week.

**02 Body.** SVG silhouette with nodes: brain, lung, heart, blood (vessel segment on the arm), liver, kidney, colon, placenta, skin. Radius ∝ √count, Elora blue, selected node `--pet`, pulsing ring (reduced-motion safe) on nodes with a `novel = 1` paper this week. Side panel: count, PET share, polymer chips, top pathways, top five papers by rung then recency, "see all". "PET only" recolours by PET density.

**03 Pathways.** Plotly Sankey polymers → pathways → disease categories, width = co-tagged count, PET ribbons in `--pet`; hover a pathway highlights, click → Papers. Spider plot per disease category across pathway axes with a PET-only trace; two categories overlayable. New edges this week dashed and listed with the paper that created each.

**04 Papers.** "New this week" cards (title, journal, year, polymer chips, rung badges, summary, DOI link, NOVEL badge), then the Tabulator table of every verified paper with column filters, search, client-side CSV export, and `/download/debris_latest.csv`. Detail drawer: abstract, MeSH, tag JSON, self-consistency, Crossref status, retraction flag. "Needs review" filter; "include unverified DOI" switch.

Routes: `/`, `/body`, `/pathways`, `/papers`, `/paper/<pmid>` (JSON), `/api/papers`, `/download/debris_latest.csv`, `/healthz` (last ingest, paper count, inference path used).

---

## 7. Data model (SQLite, read-only at serve time)

```sql
CREATE TABLE papers (pmid TEXT PRIMARY KEY, doi TEXT, doi_status TEXT, retracted INTEGER DEFAULT 0, title TEXT, abstract TEXT,
  journal TEXT, year INTEGER, month INTEGER, authors TEXT, mesh TEXT, pub_types TEXT, edat TEXT, hit_strategy TEXT,
  ingested_at TEXT, ingest_run TEXT, status TEXT);
CREATE TABLE tags (pmid TEXT PRIMARY KEY REFERENCES papers(pmid), relevant INTEGER, size_class TEXT, model_type TEXT,
  pet_specific INTEGER, summary TEXT, confidence REAL, self_consistency REAL, tag_source TEXT, tag_json TEXT,
  tagged_at TEXT, model_version TEXT);
CREATE TABLE tag_polymers (pmid TEXT, polymer TEXT, PRIMARY KEY (pmid, polymer));
CREATE TABLE tag_organs   (pmid TEXT, organ_system TEXT, PRIMARY KEY (pmid, organ_system));
CREATE TABLE tag_diseases (pmid TEXT, disease_category TEXT, disease_term TEXT);
CREATE TABLE tag_pathways (pmid TEXT, pathway TEXT, PRIMARY KEY (pmid, pathway));
CREATE TABLE tag_rungs    (pmid TEXT, rung INTEGER, PRIMARY KEY (pmid, rung));
CREATE TABLE review_queue (pmid TEXT PRIMARY KEY, reason TEXT, queued_at TEXT, resolved_at TEXT);
CREATE TABLE novelty_events (id INTEGER PRIMARY KEY, pmid TEXT, kind TEXT, key TEXT, ingest_run TEXT);
CREATE TABLE ladder_events  (id INTEGER PRIMARY KEY, pmid TEXT, polymer TEXT, disease_category TEXT, new_max_rung INTEGER, ingest_run TEXT);
CREATE TABLE ingest_runs (run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, harvested INTEGER, verified INTEGER,
  tagged INTEGER, queued INTEGER, novel INTEGER, model_version TEXT, inference_path TEXT);
CREATE TABLE drift_log (run_id TEXT, field TEXT, f1 REAL, n INTEGER);
CREATE TABLE vocab_candidates (field TEXT, value TEXT, count INTEGER, first_seen TEXT, PRIMARY KEY (field, value));
```

Index every foreign key and filter column. Build-time analytics through Parquet + DuckDB; SQLite is the serving store.

---

## 8. Phase plan (each phase ends with a commit and a deploy)

| Phase | Outputs | Acceptance | Deploy |
|---|---|---|---|
| **1 Corpus** (target ≤ 6 h) | `REUSE.md`, envs, `hwprobe`, `harvest.py`, `verify_doi.py`, gold set and negatives resolved, 1,600 bootstrap labels split and logged to wandb as `debris-train:v1`, SQLite with `papers` populated, a minimal Papers tab | ≥ 2,000 PMIDs (log the real number); verification funnel in `FINDINGS.md`; ≥ 8 gold papers found; `test_schema.py` green | Papers tab live at debris.mdeller.com with the untagged corpus and an "ingest in progress" banner |
| **2 Tagger** (≤ 12 h) | Smoke test, wandb training run, `MODEL_CARD.md`, fused + q4 models, model pushed to Hub, Space created and smoke-tested (or path B logged), full corpus tagged in tiers, `novelty.py`, `aggregate.py`, static JSON | Floor (5.5) met or G2; gold controls (Section 9) pass; ≥ 95 % of verified papers validly tagged; review rate logged | All four tabs live with tags |
| **3 App polish** (≤ 4 h) | Elora design system complete, Venn/ladder/body/Sankey/radar/feed, tests, Playwright screenshots at 1440×900 and 390×844, axe-core | All routes 200; chart totals reconcile with SQL (tests); zero serious/critical axe violations; Atlas interactive < 1.5 s | Redeploy |
| **4 Weekly + delivery** (≤ 2 h) | `weekly.py`, droplet systemd timer (path A) or launchd plist (path B) installed and enabled, `drift.py`, icons (blog mark via `marcs-vibe-icon`, Elora favicon set), README via `readme_forge.py`, `FINDINGS.md` | A dry weekly run over the last 7 days adds papers, flags novelty, rebuilds JSON, shows NEW and NOVEL badges; idempotent re-run adds nothing; timer shows next fire time | Final redeploy; `PROGRESS.md` 100 %; zero gates open |

Phases 2 and 3 overlap under rule 7.

---

## 9. Positive controls (asserted after the tag run, resolved from PubMed, never hand-typed)

Carotid plaque cohort: `polymers ⊇ {PET, PVC}`, `cardiovascular`, `human_tissue`, rungs ⊇ {1, 2}, `pet_specific = 1`. Blood detection: `hematologic`, rung 1, `PET`. Lung tissue: `respiratory`, rung 1. Brain accumulation: `neurological`, rung 1. PET-scan oncology negative and marine ecology negative: `relevant = 0`. Gold review: `review`, rungs `[]`. A failure after the 5.5 ladder opens G2 only if it changes a headline Atlas figure; otherwise log degraded and continue.

---

## 10. QC (run in Phase 3 and again in Phase 4)

`pytest` (schema, vocabulary, DOI logic with mocked HTTP, novelty on a synthetic before/after corpus, aggregate totals vs SQL, all routes, `/healthz`); Playwright with the preinstalled Chromium (never `playwright install`), every tab at both viewports, no `console.error`, click-throughs Atlas → region → Papers and Body → node → panel; axe-core zero serious/critical; science sanity (Venn regions sum to the verified total, no double counting in ladder bars, PET colour consistent, axes labelled, no causal claims in copy); performance budgets (6.1); icons (favicon independent of the blog mark, Elora blue `#385098` on off-white, legible at 16 px, opaque apple-touch-icon, 16/32/48 ico, copies at root and `app/static/`, manifest `theme_color #385098`); unattended files current; all commits local; zero gates open.

---

## 11. Deliverables

1. App live at `https://debris.mdeller.com` with the weekly refresh installed and enabled.
2. Pipeline under `pipeline/` with `pixi run harvest|verify|bootstrap|train|tag|aggregate|weekly|drift`.
3. Model: `data/adapters/debris_v1*`, `MODEL_CARD.md`, Hub repo `Dellboy/debris-tagger-v1`, Space `Dellboy/debris-tagger` (or `hf/` ready and path B active, logged).
4. wandb project `debris`: dataset artifact, training run, metrics tables, model card.
5. `deploy/`: `deploy.sh` (rsync `app/`, `data/debris.sqlite`, `app/static/data/`, units, vhost; `systemctl --user` or the AlphaFraud restart path; `--data-only` flag for weekly swaps), `debris-gunicorn.service`, `debris-weekly.service` + `.timer`, `nginx.debris.conf`, `weekly.sh`, `com.mdeller.debris.weekly.plist`.
6. `FINDINGS.md`: corpus by strategy and year, verification funnel, tagger metrics with wandb links, PET share per organ, top pathways, gold-paper tag table, vocabulary candidates, the three emptiest Venn intersections as research gaps for the workshop, inference path in use, next scheduled run.
7. README (house standard), icons, `REUSE.md`, `DECISIONS.md`.

---

## Appendix A: `.claude/settings.json` (already in the folder)

Allows pixi, uv, python, mlx_lm.*, wandb, huggingface-cli, git add/commit (not push), curl, brew, sysctl, df, osascript, caffeinate, gunicorn, flask, sqlite3, duckdb, launchctl bootstrap/enable, `ssh` and `rsync` and `scp` (deploy is pre-approved; restrict usage to the host in `config/deploy.toml`), `npx playwright test`. Denies `git push`, `gh repo create`, `sudo`, `rm -rf /`, `rm -rf ~`, `playwright install`.

## Appendix B: project `CLAUDE.md` (already in the folder)

Spec is authoritative; two gates only; deploy to debris.mdeller.com is pre-approved and runs at the end of every phase; reuse sibling projects (copy, never import or modify); never push or create repos; hardware from `config/tuning.toml`; Elora design system; tagger trained once; wandb and Hugging Face optional with logged fallbacks; British English, no em dashes, no causal claims.

## Appendix C: references to resolve via Crossref at build time

Marfella et al., NEJM 2024 (atheroma MNPs and cardiovascular events); Leslie et al., Environment International 2022 (blood); Jenner et al., Science of the Total Environment 2022 (lung); Nihart et al., Nature Medicine 2025 (brain); Ragusa et al., Environment International 2021 (placenta); two most-cited colorectal/intestinal MNP studies; one PET leachate toxicity study; one broad MNP human-health review; mlx-lm LoRA docs (ml-explore) for current CLI flags including any `--wandb` option; Hugging Face ZeroGPU docs (`spaces` package, `@spaces.GPU`, quota); NCBI E-utilities and Crossref etiquette pages.
