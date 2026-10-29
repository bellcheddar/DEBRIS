# DEBRIS lab plan

A systematic test of the ideas for improving the tagger, run on a small model so that each
round takes minutes rather than hours, with the winners confirmed once on the production
model. Written and committed before any lab result exists, so that the rules for adopting an
idea cannot drift towards whatever the results turn out to say.

## What we already know

- Round 04 (Qwen2.5-3B, 32 layers) and round 05 (Qwen2.5-7B) both clear four of the eight
  floors. Short in both: organ systems, pathways, rungs within one, model type (D25, D35).
- On the 162-paper test split a single model's score carries about plus or minus five points
  for most fields and seven for polymers and model type. A paired bootstrap found only one
  real difference between the 3B and the 7B: pathways, +0.071 (D35).
- Training does not mask the prompt. About 88 % of each example's tokens are prompt (a
  388-token system prompt identical on all 1,277 rows, plus the paper) and the loss is spent
  mostly on reproducing them. It is also why validation loss is a poor checkpoint signal (D24).
- The labeller saw PubMed publication types (`TYPES:`) and the full MeSH list; the tagger sees
  neither types nor MeSH beyond 600 characters. 74 of the 79 papers labelled review or
  meta-analysis carry "Review" in PubMed's own types.
- The training set mirrors the corpus rather than the question: of 693 relevant papers, 439
  are animal studies, 18 human tissue, 17 human cohort, and 28 name PET. 52 % carry
  `oxidative_stress`. Several classes have under ten examples.
- D25 found model type and pathways limited by the labels themselves: the `cell_line` /
  `human_in_vitro` boundary is not held consistently, and pathways are over-predicted where
  the abstract mentions a mechanism without measuring it.
- The extended roster comes from Liu et al., *Tissue-specific microplastic burdens in
  humans: an intra-individual mapping of 18 tissue types*, J Hazard Mater 518:144001 (2026),
  doi 10.1016/j.jhazmat.2026.144001, PMID 42933105, which is already in the corpus. Its
  abstract names six of the 18 tissues (adipose, brain, adrenal, liver, thyroid, blood) and
  three of the 11 polymers quantified by Py-GC/MS (PE, PA66, PVC); the full lists are in the
  methods. The plan does not guess the rest.
- Those 18 are anatomical tissues. The current `organ_systems` field is a functional grouping
  (`endocrine_metabolic` covers both adrenal and thyroid; adipose has no home at all), and it
  is the field furthest below its floor. Polymers there are also finer than ours: PA66 rather
  than PA.

## Rules fixed before the first run

1. **One question per phase, one target metric per idea**, declared below before the idea
   runs. Every other floor metric is a guardrail.
2. **Adopt an idea** when the paired bootstrap 95 % interval of its target-metric effect
   excludes zero **and** no guardrail metric's interval lies wholly below zero.
3. **The test split stays frozen** until Phase 5. Every lab number comes from cross-validation
   over the train and validation papers.
4. **Labels are never edited in place.** Every data variant is built from the canonical labels
   by a recorded, deterministic transform, so any round can be rebuilt exactly.
5. **A change to a definition is Marc's decision**, not the lab's. The lab measures what a new
   model-type rule or a new pathway rule does; it does not put either into the app.
6. **Every round is logged** to wandb as `debris-qwen-2.5-1.5b-roundNN`, grouped by experiment,
   and to `LAB_REPORT.md`, including rounds that change nothing.

## How each idea is measured

**Lab model.** Qwen2.5-1.5B-Instruct, LoRA on 16 layers, learning rate 1e-5 held fixed, fixed
seed per fold. The iteration count is set in Phase 0 from the learning curve.

**Three-fold cross-validation** over the 1,438 train and validation papers, stratified on
relevance and model type as the original split was. Each configuration trains three times,
once per fold, and every paper is scored exactly once by a model that never saw it. That
gives 1,438 scored papers per configuration instead of 161, which should narrow the interval
from about plus or minus five points to about plus or minus two, and the three trainings
average over seed noise for free. Folds are assigned once, written to `data/lab/folds.json`,
and never change.

**Scoring.** Greedy decoding only, straight from the adapter with no fuse or quantise, using
the same field functions `train.py` uses (imported, not copied). Each round stores every
paper's prediction, so any two rounds can be compared paper by paper.

**Paired bootstrap.** 2,000 resamples of papers, the same papers drawn for both sides, as in
D35. Every comparison in `LAB_REPORT.md` is an effect with its interval, never two bare scores.

**The label ceiling.** A model cannot agree with the labels more often than two careful
labellers agree with each other. Phase 0 measures that ceiling field by field on a sample, so
that a shortfall can be read as either a model problem or a definition problem, and so that G2
can see which floors are reachable at all.

## Phase 0: calibration

*Question: is the lab fast enough, sensitive enough and quiet enough to be worth using?*

- Baseline (the current recipe) on all three folds, saving every 100 iterations to 800, each
  checkpoint scored on its fold. Sets the iteration count: the shortest at which the fields
  stop improving.
- Two further seeds on fold 1 at that iteration count. Measures training noise separately
  from sampling noise.
- **Label ceiling:** 100 papers drawn across the fields, labelled a second time blind to the
  existing labels. The second labeller is open (see Decisions); whichever it is, agreement is
  reported per field with its interval.
- **Exit test:** the 1.5B baseline must sit within about 15 points of round 04 on most fields.
  If it is far below, it cannot respond to the ideas and the lab moves to the 3B at 16 layers,
  slower but still four to five times faster than a production run.

Runs: 5 trainings. Estimated time 1.5 to 2 hours (estimate; Phase 0 replaces it).

## Phase 1: input and output format

*Question: which of four cheap changes improve the tagger, and do they interact?*

None of these touches a label, so every configuration is scored against the same gold. They
run as a half-fraction factorial: eight configurations instead of sixteen, in which every run
informs every factor's estimate. Each main effect is the mean of four configurations against
the other four, so it rests on twelve trainings a side rather than one.

| factor | change | target metric |
|---|---|---|
| A | mask the prompt in the loss (`--mask-prompt`) | all floor metrics |
| B | add `TYPES:` and the full MeSH list to the prompt, at training and at scoring | model type |
| C | answer order: `relevant`, `model_type`, `evidence_rungs` first, `summary` last | rungs within one |
| D | drop `confidence` from the answer (the labeller's number, not a fact about the paper) | guardrails only |

| config | A | B | C | D |
|---|---|---|---|---|
| 1 (current recipe) | off | off | off | off |
| 2 | on | off | off | on |
| 3 | off | on | off | on |
| 4 | on | on | off | off |
| 5 | off | off | on | on |
| 6 | on | off | on | off |
| 7 | off | on | on | off |
| 8 | on | on | on | on |

D is set as the product of A, B and C, so main effects are clear of two-way interactions and
the two-way interactions are paired with each other (AB with CD and so on). If A turns out to
dominate, its interaction with B or C is the first thing to look at.

Runs: 8 configurations by 3 folds, 24 trainings. Estimated 6 to 7 hours, one overnight run.

**Transfer check, before any labelling is spent.** The Phase 1 winner against the current
recipe, once each on the 3B at 16 layers, scored on the validation split. If the effect points
the same way, the lab's rankings carry over and Phase 2 proceeds. If it does not, the plan
stops and the lab model is reconsidered. 2 trainings, about 2 hours.

## Phase 2: one relabelling pass, then a switch per definition

*Question: which new definitions make a field both more consistent and more learnable?*

Every definitional change needs every paper read again, so they are done together in one pass
rather than four. Each paper gets a second label set, v2, beside the original v1, which is
kept untouched. The lab then tests each change as a switch: train and score a field on v1 or
on v2, everything else held at the Phase 1 recipe. Labelling once and testing many times is
what keeps this affordable.

| switch | v2 definition | target metric |
|---|---|---|
| 2a model type | an immortalised line is `cell_line`; primary cells, explants and ex vivo tissue are `human_in_vitro`; a list of named lines pre-flags the easy cases | model type |
| 2b pathways | tag a pathway only where the abstract reports an assay, a marker or a result for it, not where it is named as background | pathways |
| 2c polymers, the 11 | the 11 types Liu et al. quantify, arranged as a hierarchy: a paper is labelled with the finest type its abstract states, and every fine type rolls up to its parent (PA66 to PA), so "nylon" is still a valid answer | polymers, scored at both levels |
| 2d tissues, the 18 | a new `tissues` field: the anatomical sites a paper samples, reports or studies, from Liu et al.'s 18. Organ systems then come from a fixed tissue-to-system map in `config/vocab.toml`, with `organ_systems` still tagged directly for papers that name no tissue | organ systems |

A definitional change moves the yardstick: scoring a v2 model against v1 gold would penalise
it for following the new rule. So each switch is judged against v2 gold, on two things
together: the label ceiling under the new rule, from double labelling, and the model's
agreement with the new labels. A rule is better when the ceiling rises and the model's score
rises with it.

**2d is the one with the most riding on it.** The hypothesis is that "the abstract names the
thyroid" is a literal reading two labellers agree on, while "this is endocrine and metabolic"
is an abstraction they apply differently, and that organ systems derived from literal tissue
labels will beat organ systems tagged directly. Three policies are scored side by side on the
same predictions: organ systems tagged, organ systems derived from tissues, and the union.
Tissues are also reported per class, since 18 values across about 1,400 papers leaves some,
adrenal and adipose most likely, with very few examples; Phase 3 enrichment aims at those.

Runs: 4 switches by 3 folds, 12 trainings, about 4 hours, after the labelling.
Labelling: every one of the 1,438 cross-validation papers plus the 162 test papers, about
1,600, on four fields. This is the largest single cost in the plan.

## Phase 3: what the model trains on

*Question: does training on more of what the project is about lift the fields that are short?*

The scored folds stay representative of the corpus; only the training side changes. Each idea
also reports recall on the classes it is aimed at, since an overall micro F1 can hide a gain on
a class with 17 examples.

| idea | change | target metric |
|---|---|---|
| 3a | about 300 more labelled papers aimed at human tissue, cohort, PET, the rare pathways and the sparsest of the 18 tissues, found with keyword screens in the untagged corpus | rungs within one, recall on rungs 1 and 2 and on the rare tissues |
| 3b | 150 of the 360 negative controls (positron emission tomography, CT, implants) added as irrelevant; labels are free because they are controls by construction. The other 210 stay out, so `validate.check_negatives` still measures papers the tagger has never seen | relevant |

Runs: 6 trainings, about 2 hours, plus the labelling for 3a.

## Phase 4: the rest of the vocabulary

*Question: does what is left of the label space still cost us?*

Once the 11 and the 18 are in, two smaller changes remain: promote the `other:` pathway values
that recur (`lipid_metabolism` 14, `er_stress_autophagy` 12, `endocrine_disruption` 8), and
merge the pathway classes too sparse to learn (`emt_migration` 2,
`platelet_activation_thrombosis` 5). These can ride on the Phase 2 labelling pass at almost no
extra cost, then run as one more switch. Target metric: pathways. Runs: 3 trainings, about 1
hour.

## Phase 5: confirmation

*Question: does the winning recipe beat round 04 on the production model?*

The adopted recipe trained once on the 3B (and on the 7B only if pathways is still the one
short field), scored on the frozen test split, compared with round 04 by paired bootstrap.
Fields whose definition changed are scored against the relabelled test gold and reported
beside the old numbers, never silently in place of them. This is the point at which floors
are judged and G2 is written, with each shortfall labelled as a model limit or a label limit
from the Phase 0 ceiling. Then the corpus is tagged once.

If 2c and 2d are adopted, the app follows from the vocabulary alone: the body map already
reads its sites from `config/vocab.toml` (D34), so the 18 tissues become 18 pins, and the
Atlas panels already draw however many polymers the vocabulary lists. Liu et al. itself, a
rung 1 human tissue paper naming PE, PA66 and PVC across 18 tissues, is the natural new gold
control for both fields.

Estimated 3 to 4 hours, then 6 to 9 hours of tagging.

## Infrastructure

- `pixi run lab <experiment>` reads `config/lab/<experiment>.toml` (model, layers, iterations,
  seed, folds, and the factor switches), builds the variant data under `data/lab/<experiment>/`,
  trains with `mlx_lm.lora`, scores each fold, and writes `data/lab/results/<experiment>.json`
  with every paper's prediction.
- `pixi run lab-report` rebuilds `LAB_REPORT.md`: one table per phase, each effect with its
  paired bootstrap interval, and the adopt or reject call under the rules above.
- Nothing under `data/train/` or `data/adapters/` is touched. The production pipeline is
  unaffected until Phase 5.
- Resumable through `data/manifests/lab.jsonl`, like every other stage.
- Tests: fold assignment never leaks a test-split paper, each transform is deterministic, and a
  variant with every switch off reproduces the current training rows byte for byte.

## Decisions needed from Marc

1. **The full roster.** The 18 tissues and 11 polymers exactly as Liu et al. list them, from
   the paper's methods or tables: the abstract gives six and three, and the plan will not
   guess the rest. Phase 2 cannot start without them; Phases 0 and 1 can.
2. **Labelling capacity.** The current labels were written by this build session, because no
   Anthropic API key was set. Phases 2 and 3a need about 1,300 papers labelled.
   - With an `ANTHROPIC_API_KEY`, a current Claude model labels them in about an hour, and
     it is a genuinely independent second labeller for the ceiling. With the 18 tissues
   and the polymer hierarchy added, the pass touches about 1,600 papers on four fields,
   which makes this the decision that most changes the timetable.
   - Without one, the session labels in batches, which is slower and is the same labeller
     that wrote the labels being tested.
   - A middle path: the Qwen2.5-32B already cached here, run locally as the second
     labeller for the ceiling only.
3. **Definitions.** Approval to put a new model-type rule, a new pathway rule, the polymer
   hierarchy, the tissue field or other vocabulary changes into the app, if the lab says
   they help. The lab only measures.
4. **Gold control.** Adding Liu et al. (PMID 42933105) to the pinned gold set (D19).
5. **Optional, and worth more than it costs:** 40 papers on the three contested fields
   (model type, pathways, organs) checked by Marc. That anchors the ceiling to the judgement
   the site is actually meant to reflect.

Phase 0, Phase 1 and the transfer check need none of these, so they can start now.

## Risks

- **Transfer.** A gain on 1.5B may not appear on 3B, most likely for organ systems, where the
  7B showed capacity matters. The transfer check after Phase 1 exists to find that out before
  any labelling is spent.
- **Learning rate.** Masking the prompt changes what the gradient is made of, and 1e-5 may no
  longer be the right rate. Held fixed in Phase 1 so the factorial stays clean; if A wins
  clearly, a short rate sweep on the winning recipe follows.
- **Multiple comparisons.** About a dozen ideas at 95 % means roughly one may pass by chance.
  Phase 5 is where a false positive gets caught.
- **Granularity.** Finer labels are only learnable if abstracts state them. Many say
  "polyamide" or "nylon" and never PA66, and many mechanism papers in cell lines name no
  tissue at all. The hierarchy and the tissue-or-system fallback exist for exactly that, and
  the per-class recall in Phase 2 will show where the abstracts simply do not carry the detail.
- **Labelling bias.** Relabels written by the same labeller that wrote the originals may agree
  with themselves more than with the truth. This is why the second labeller matters.

## Estimated budget

| phase | trainings | compute | waiting on |
|---|---|---|---|
| 0 calibration | 5 | 1.5 to 2 h | nothing |
| 1 format factorial | 24 | 6 to 7 h | nothing |
| transfer check | 2 | about 2 h | nothing |
| 2 definitions, 11 polymers, 18 tissues | 12 | about 4 h | the roster, labelling, then Marc |
| 3 training data | 6 | about 2 h | labelling for 3a |
| 4 rest of the vocabulary | 3 | about 1 h | Marc |
| 5 confirmation | 1 to 2 | 3 to 4 h | everything above |

Roughly two and a half days of compute, most of it unattended, plus the labelling.
