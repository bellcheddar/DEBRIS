# 🧪 DEBRIS

> **Ten thousand papers on plastic particles and human disease, read by machine and mapped.**

![python](https://img.shields.io/badge/python-3.x-3776AB?logo=python&logoColor=white) ![shell](https://img.shields.io/badge/shell-bash/zsh-4EAA25?logo=gnubash&logoColor=white) ![author](https://img.shields.io/badge/author-Marc%20C.%20Deller,%20D.Phil.-1C244B)

<table>
<tr>
<td>🌐 <b>Website</b></td><td><a href="https://marcdeller.com" target="_blank" rel="noopener noreferrer">marcdeller.com</a></td>
<td>✉️ <b>Contact</b></td><td><a href="mailto:marc@marcdeller.com">marc@marcdeller.com</a></td>
<td>🐙 <b>GitHub</b></td><td><a href="https://github.com/bellcheddar/debris" target="_blank" rel="noopener noreferrer">bellcheddar/debris</a></td>
</tr>
</table>

---

Plastic particles small enough to cross from the gut or the lung into the bloodstream have
now been found in human blood, lung tissue, placenta, atheromatous plaque and brain, and
what that means for health is being worked out in thousands of separate papers that nobody
has read in full. DEBRIS reads them: it harvests every PubMed record putting a micro or
nanoplastic particle inside a human disease, checks each one is a real published paper, and
has a small language model read the abstract and write down what that paper actually
reports, which plastic, which organ, which biological mechanism, what kind of study, and
how close the finding sits to an effect in a living person. The result is a map of the
evidence rather than another reading list.

Why it matters: the question people actually ask, what do we know about plastic particles and human disease, has no single answer anywhere, because the evidence is spread across toxicology, cardiology, obstetrics and environmental science journals that rarely cite one another and is growing every week. Asking the same questions of every abstract turns that scattered literature into something a person can see at once, including the parts of it that are empty. It is useful for: finding the papers behind a claim, telling what has been shown in people apart from what has only been shown in cells, and seeing which plastic and organ combinations nobody has studied yet.

Live at [debris.mdeller.com](https://debris.mdeller.com).

## Why read the literature by machine

There are around ten thousand papers in scope and the number grows every week. No
clinician, regulator or journalist can keep up with that, and the findings are scattered
across toxicology, cardiology, obstetrics, gastroenterology and environmental science
journals that rarely cite one another. So the obvious question, what do we actually know
about plastic particles and human disease, has no single answer anywhere: it is distributed
across a literature too large to hold in one head.

Reading all of it the same way, with the same questions asked of every abstract, makes the
shape of that evidence visible. Three things fall out that no individual paper shows.

**What has been shown in people, and what has only been shown in cells.** A finding in a
human cohort and a finding in a dish are both real results and they are not the same
claim. DEBRIS records which it is for every paper, so the distinction survives.

**Which combinations nobody has studied.** Fourteen mechanisms, thirteen polymers and
sixteen organ systems make a grid with a great many empty squares. An empty square is an
open research question, and it is invisible unless the whole corpus is tagged the same way.

**Absence of evidence, stated as such.** An empty region is an absence of published work,
not a finding of safety. Saying so plainly is more useful than leaving a gap unmentioned.

This is a literature mining project, not a toxicology study. DEBRIS records what papers
report and nothing in it asserts that plastics cause disease in people.

## What a tag records

A tag is a reading of one paper, not a verdict on the science. For each abstract the
tagger records the polymers named, the particle size class, the organ systems involved,
the disease categories and the authors' own disease terms, the mechanisms reported, the
kind of study, and which rungs of the evidence ladder the paper reaches.

### The evidence ladder

| Rung | Meaning |
|---|---|
| 1 | Detected in human tissue or fluid |
| 2 | Associated with outcome in a human cohort |
| 3 | Reproduced in vivo |
| 4 | Mechanism in vitro or ex vivo |
| 5 | Dose-response |
| 6 | Reversible on particle removal or degradation |

The rungs are not a ranking of journals or of authors. They record how far a given claim
sits from a human outcome, so that a reader can see the shape of the evidence without
taking anyone's word for it. A detection in tissue is rung 1 whether it appears in a case
series or in the Lancet. Reviews carry no rungs.

## The four tabs

- **Atlas**: a Venn of PET against PS and PE/PP, with a second Venn for PVC and the rest.
  Every region is a link into the Papers tab with that polymer combination applied. Below
  it, the evidence ladder as disease category by rung, and the corpus by year.
- **Body**: an SVG silhouette. Click an organ and the panel gives the polymers reported in
  it, the pathways, the highest rung reached and the papers behind it.
- **Pathways**: polymer to pathway to disease as a Sankey, plus a radar of mechanism
  coverage per organ system.
- **Papers**: the whole verified corpus in a sortable table, with the polymer, organ,
  pathway, rung and year filters the other tabs link into, and a drawer per paper. NEW
  marks a paper added by the last weekly run; NOVEL marks the first paper to connect a
  polymer and an organ, or to reach a rung a disease category had not reached before.

Unverified papers are hidden behind a switch that is off by default. Retracted papers are
struck through and never deleted.

## How a paper gets in

1. **Harvest** (`pipeline/harvest.py`). Two PubMed strategies, unioned: one on MeSH terms,
   one on title and abstract words to catch the indexing lag. Each PMID keeps the
   strategies that found it. `PET[tiab]` is never searched on its own, because it returns
   positron emission tomography. Papers without abstracts are stored but never tagged.
2. **Verify** (`pipeline/verify_doi.py`). A paper is admitted when Crossref resolves its
   DOI and `token_set_ratio` between the PubMed and Crossref titles, case-folded, is at
   least 90. A Crossref `update-to` retraction sets a flag.
3. **Tag** (`pipeline/tag.py`). Two passes per paper, greedy and then sampled at a fixed
   seed. The greedy tag is stored; the pair gives a self-consistency score. Papers are
   tagged in priority tiers, so the gold set and the human tissue and cohort work are
   done first. Low confidence, disagreement between passes or a value outside the
   controlled vocabulary routes the paper to the review queue and the app shows it as
   needing review rather than publishing the tag.
4. **Novelty** (`pipeline/novelty.py`). First polymer and organ pairings, and first time a
   disease category reaches a rung, recorded as events.
5. **Aggregate** (`pipeline/aggregate.py`). Static JSON bundles under
   `app/static/data/`. The app does no computation at request time.

## 🤗 The language model

Reading ten thousand abstracts against a fixed schema is the one part of this that cannot
be done with rules. Abstracts say the same thing a dozen different ways, and the
distinction that matters most here, whether an effect was observed in a person or in a cell
line, is carried by phrasing rather than by any keyword.

So DEBRIS uses a small model trained for exactly this task, not a large general one behind
an API. That is a deliberate choice: a 3B model fine-tuned on the schema runs the whole
corpus overnight on one desktop machine, costs nothing per paper, and gives the same answer
for the same abstract next year, which an API that silently changes underneath you does
not. Reproducibility is the point.

### 🎓 Training

| | |
|---|---|
| Base model | [`Qwen/Qwen2.5-3B-Instruct`](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct) |
| Method | LoRA adapter, 32 layers, 1,600 iterations, learning rate 1e-5, fixed seed |
| Training data | 1,600 labelled abstracts, split 1,277 train / 161 validation / 162 test, stratified on relevance and study design |
| Trained | Once. The weekly refresh never retrains it |
| Tracked | Every run in Weights & Biases, with the loss curve, the config and the held-out metrics |

The model is trained on the task and the schema, not on facts about plastics. It learns to
read an abstract and fill in a form; it does not learn what the answers should be. That
matters, because it means the model cannot invent a finding the paper does not contain, and
a wrong tag is a misreading rather than a fabrication.

The split is frozen, so the test set holds the same 162 papers across every training run
and the numbers are comparable. Performance per field, the acceptance threshold each must
clear, and an honest account of which fields the labels themselves limit, are all in
[MODEL_CARD.md](MODEL_CARD.md).

### 🤗 The models

| Resource | Where |
|---|---|
| Fine-tuned tagger | [`Dellboy/debris-tagger-v1`](https://huggingface.co/Dellboy/debris-tagger-v1) |
| Inference Space (ZeroGPU) | [`Dellboy/debris-tagger`](https://huggingface.co/spaces/Dellboy/debris-tagger) |
| Base model | [`Qwen/Qwen2.5-3B-Instruct`](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct) |

Inference runs one of two ways, and both write the same tables. Path A is the Hugging Face
ZeroGPU Space, which is what the weekly refresh on the server uses. Path B is a quantised
copy of the model on the local machine, driven by a timer, which is what the first full
pass over the corpus uses because it is far larger than a weekly batch.

## ▶️ Running it

The pipeline runs in a pixi environment; the app runs in a uv virtual environment with
only Flask and gunicorn, which is what the droplet installs.

| Task | What it does |
|---|---|
| `pixi run probe` | Read the hardware and write `config/tuning.toml` |
| `pixi run harvest` | Harvest PubMed |
| `pixi run verify` | Verify DOIs at Crossref |
| `pixi run bootstrap all` | Select, label, ingest and split the bootstrap set |
| `pixi run train` | Fine-tune, fuse, quantise and score; resumes where it stopped |
| `pixi run tag --local` | Tag the corpus with the local model |
| `pixi run tag --remote` | Tag the corpus through the Space |
| `pixi run novelty --run` | Record novelty events |
| `pixi run validate` | Check the gold controls and the negatives |
| `pixi run aggregate` | Rebuild the JSON bundles |
| `pixi run weekly` | The whole refresh, last seven days |
| `pixi run drift` | Weekly drift check; never retrains |
| `pixi run findings` | Regenerate `FINDINGS.md` |
| `pixi run qc` | Drive the app through Chromium and axe-core |
| `pixi run test` | The test suite |

Every stage is resumable: each writes a manifest under `data/manifests/` and checks for
its own output before doing the work again.

### 🛠️ Configuration

Nothing about the machine is hard-coded. `tools/hwprobe.py` writes `config/hardware.toml`
and `config/tuning.toml`, and the pipeline reads batch sizes and model paths from there.
`config/vocab.toml` holds the controlled vocabulary and every display label, and the
charts are built from it, so a vocabulary change moves the app. `config/query.toml` holds
the PubMed strategies, `config/deploy.toml` the host, `config/hf.toml` and
`config/wandb.toml` the optional services.

All four API keys are optional. Without `NCBI_API_KEY` the harvest runs at three requests
a second. Without `ANTHROPIC_API_KEY` the bootstrap labels are written by hand. Without
`WANDB_API_KEY` the run logs offline under `wandb/`. Without `HF_TOKEN` inference takes
path B. Each fallback is logged rather than silent.

## The weekly refresh

One timer, either a systemd timer on the droplet or a launchd job on the Studio, runs
`pipeline/weekly.py`: harvest the last seven days by `EDAT`, verify, tag the new papers,
score novelty, rebuild the bundles, push the data and run the drift check. It is
idempotent, so a second run over the same week adds nothing. It never retrains. If
relevance F1 falls below 0.90 or the review rate stays above 25 % for two runs, the drift
check appends a recommendation to `FINDINGS.md` and stops there.

## Deploying

`deploy/deploy.sh` rsyncs the app and the data to the host in `config/deploy.toml`,
installs the uv environment from `requirements.txt`, and restarts gunicorn behind nginx.
`--data-only` pushes the database and the bundles without touching the code;
`--provision` sets up a bare droplet.

## Quality

`pixi run test` covers the schema and its repair path, DOI verification against mocked
HTTP, the aggregate totals against the same numbers computed in SQL, novelty, the
priority tiers, the vocabulary candidate accounting and every app route.

`pixi run qc` starts gunicorn on a spare port and drives the preinstalled Chromium
through all four tabs at 1440x900 and 390x844, checking that each route returns 200, that
there are no console errors or failed requests, that axe-core reports no serious or
critical violations, that the Atlas is interactive inside 1.5 s, and that the Atlas region
and body node click-throughs work. Screenshots and a JSON summary land in `qc/`.

## Limits

DEBRIS indexes what the literature reports. It does not adjudicate the science, and
nothing in the schema or the app asserts that plastics cause disease in people. An empty
region of the Venn is an absence of published work, not evidence of safety. Tags are
produced by a 3B model and the ones it is unsure about are marked as needing review
rather than hidden. Papers are read from their abstracts, so a paper whose full text says
more than its abstract is tagged on the abstract.

## Project files

| File | What it holds |
|---|---|
| `DEBRIS_BUILD_SPEC.md` | The specification this was built from |
| `MODEL_CARD.md` | The tagger, its training and its metrics |
| `FINDINGS.md` | The corpus, the funnel, the gaps; generated |
| `config/vocab.toml` | The controlled vocabulary: every polymer, organ, mechanism and label |

---

## 👤 Author

**Marc C. Deller, D.Phil.**  
Structural biologist & drug discovery scientist  

<table>
<tr>
<td>🌐</td><td><a href="https://marcdeller.com" target="_blank" rel="noopener noreferrer">marcdeller.com</a></td>
<td>✉️</td><td><a href="mailto:marc@marcdeller.com">marc@marcdeller.com</a></td>
<td>🐙</td><td><a href="https://github.com/bellcheddar/debris" target="_blank" rel="noopener noreferrer">github.com/bellcheddar/debris</a></td>
</tr>
</table>
