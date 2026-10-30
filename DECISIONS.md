# DEBRIS decisions

| Date | Decision | Alternatives | Reason | Reverse by |
|---|---|---|---|---|
| 2026-10-28 | Name DEBRIS; merge PLAQUE ladder, BOTTLE body map, LANDFILL pathway hub into one app | Four separate apps | Marc's choice | n/a |
| 2026-10-28 | Qwen2.5-3B-Instruct, one LoRA fine-tune, no retraining | Llama 3.2 3B (gated); retrain weekly | Ungated weights; tagger learns schema not facts | Train debris_v2 via pipeline/train.py |
| 2026-10-28 | Two gates only; deploy pre-approved; keys optional with fallbacks | Six-gate template | Marc asked for a quick automated build | Edit spec Section 0.2 |
| 2026-10-28 | Weekly inference on HF ZeroGPU Space, droplet-side timer (path A); Studio launchd as path B | Studio only | Removes the Studio from the weekly loop | Switch `inference_path` in config |
| 2026-10-29 | Droplet SSH target taken from `AlphaFraud/.env` (the host recorded in `config/deploy.toml`), app at `/opt/debris` on port 8014 | Ask Marc for SSH details (would have opened G1) | AlphaFraud's deploy config is the documented source (spec section 3); 8011 to 8013 are already taken on the droplet | Edit `config/deploy.toml` |
| 2026-10-29 | Self-host Montserrat and IBM Plex Mono as woff2 under `app/static/fonts/` | Google Fonts CDN links | No third-party request per page load and no layout shift; the CODSWALLOP font script already does it | Swap `fonts.css` for the Google `<link>` |
| 2026-10-29 | Fold case before the Crossref title match | Case-sensitive `token_set_ratio` | PubMed and Crossref disagree on title case often enough to fail real papers at the 90 floor | Drop `.casefold()` in `verify_doi.normalise` |
| 2026-10-29 | Flask added to the pixi env as well as `requirements.txt` | Two separate test commands | One `pixi run test` then covers the pipeline and the app; the droplet still installs only `requirements.txt` | Remove from `pixi.toml` and run app tests under `.venv` |
| 2026-10-29 | Four keys all absent at launch: the build session writes the bootstrap labels, wandb runs offline, NCBI at 3 req/s, weekly inference on path B (Studio launchd) | Wait for keys (would have stalled the build) | Every fallback is the one the spec names in 0.2; `hf/` is still written so path A needs only a token | Export the keys and re-run `pixi run bootstrap api`, `wandb sync`, `hf/push_model.py` |
| 2026-10-29 | Venn region click-through implemented as `polymers=A|B&not_polymers=C,D` on `/api/papers` | A region id understood only by the app | The query is readable, shareable and testable, and the CSV download honours it unchanged | Replace with a region parameter |
| 2026-10-29 | Bulk polymer devices and implants, monomer or additive exposure with no particles, and drugs merely carrying a polymer name (sodium polystyrene sulfonate) are all `relevant = false` | Admit anything the MeSH polymer terms return | The MeSH strategy sweeps in Dacron grafts, PVC occupational chemistry and Kayexalate; DEBRIS is about micro and nanoplastic particles and their leachates. Particulate wear debris from an implant stays relevant | Edit `LABEL_INSTRUCTIONS` in `pipeline/schema.py` and re-label |
| 2026-10-29 | Carotid plaque positive control asserts `polymers ⊇ {PE, PVC}`, not `{PET, PVC}`, and does not assert `pet_specific` | Follow spec section 9 as written | Marfella et al. (NEJM 2024) report polyethylene and a smaller proportion of polyvinyl chloride in carotid atheroma; they do not report PET. Asserting PET would have trained and tested the tagger against the paper | Restore the spec's expectation in `pipeline/validate.py` if the spec is corrected |
| 2026-10-29 | Wildlife surveys and trophic-transfer studies (particle counts in whales, seabirds, fish) are `relevant = false`; controlled exposure experiments with a pathology, oxidative stress, immune or genotoxic endpoint are `relevant = true` in any species | Admit all animal work, or reject all non-mammalian work | Keeps ecological monitoring out of a disease corpus while keeping the mechanistic evidence that rungs 3 to 5 are built from | Edit `LABEL_INSTRUCTIONS` and re-label |

## D11. Label terms canonicalised against config/vocab.toml (2026-10-29)

Late bootstrap batches drifted into near-miss terms that are not in the controlled
vocabulary (`human_observational`, `respiratory_disease`, `atherosclerosis_cvd`,
`reproductive_dysfunction`, `gi_disease`, `ocular`, `musculoskeletal` and others).
`validate()` silently drops unknown values in closed fields, so those labels would have
trained the tagger on empty slots. All 1,600 session labels were rewritten in place with
an explicit mapping: `human_observational -> human_cohort`; `atherosclerosis_cvd ->
atherosclerosis_mace`; `thrombosis_coagulation -> thrombosis`; `gi_disease -> ibd_gut`;
`autoimmune -> immune_dysfunction`; `neurodevelopmental ->
neuroinflammation_neurodegeneration`; `congenital_developmental -> pregnancy_outcomes`;
`respiratory_disease -> pulmonary_fibrosis` where the terms mention fibrosis, interstitial
disease or emphysema, otherwise `copd_asthma`; `heart_failure_fibrosis`,
`musculoskeletal_disease`, `reproductive_dysfunction` and `endocrine_disruption` (as a
disease category) have no home in the 17 categories and became `none`, with the detail
kept in `disease_terms`; organ `ocular -> neurological` (retina is neural tissue) and
`musculoskeletal -> systemic`. Pathways and polymers are open fields, so
`er_stress_autophagy`, `lipid_metabolism`, `endocrine_disruption`, `protein_corona`,
`insulin_resistance`, `epigenetic_change`, `PHA` and `PCL` were written as `other:<term>`
and now surface through `vocab_candidates` for the FINDINGS.md vocabulary section.
The vocabulary itself was not widened: spec 6.x fixes the Venn, body map and pathway hub
on those 14 pathways and 17 disease categories.

## D12. wandb Run.get_url() replaced with Run.url (2026-10-29)

wandb 0.23 removed `Run.get_url()`; `pipeline/bootstrap_labels.py` and `pipeline/train.py`
now read `getattr(run, "url", None) or "offline"` before `finish()`, which also works in
offline mode where no URL exists.

## D13. transformers pinned to the 4.x line (2026-10-29)

`pixi install` had resolved transformers 5.21.0, where `apply_chat_template` returns a
`BatchEncoding` instead of a list of token ids. mlx-lm 0.29.1 feeds that return value
straight into its batcher, so `mlx_lm.lora` died on the first iteration with
`TypeError: int() argument must be ... not 'tokenizers.Encoding'`. Generation was
unaffected, which is why the smoke test passed and only training broke.
`pixi.toml` now pins `transformers = ">=4.48,<5"` (resolved 4.57.6), the line mlx-lm
targets. Alternative considered and rejected: rewriting the splits into mlx-lm's `text`
format so the buggy code path is skipped, which would have hidden the version conflict
from the droplet and weekly runs.

## D14. UI QC harness and the five defects it found (2026-10-29)

`tools/qc_ui.py` starts gunicorn on a spare port, drives the preinstalled Chromium
(`~/Library/Caches/ms-playwright/chromium-1248`, never `playwright install`), and records
route status, console errors, failed requests, axe-core violations, the Atlas interactive
time and the two click-throughs, writing screenshots and `qc/qc_ui.json`. Playwright and
axe-core-python live in `requirements-qc.txt` so the droplet venv never installs them.

The first run found five real defects, all fixed:

1. Venn regions carried only the count glyphs as their hit area, and the backdrop circles
   swallowed clicks aimed anywhere else. Each region now has an invisible 24 px hit circle
   and the circles and set labels are `pointer-events="none"`.
2. `data-query` was written into `innerHTML` unescaped, so `&not_polymers=` was parsed as
   the `&not;` entity and the Atlas link read `polymers=PET¬_polymers=...`. Every region
   query now goes through `DEBRIS.esc`.
3. The interactive SVGs declared `role="img"`, which forbids focusable descendants; they
   are now `role="group"`, which allows them.
4. The paper drawer was hidden with `aria-hidden="true"` while its close button stayed
   focusable. It now uses `inert` alone, and the CSS open state keys off `:not([inert])`.
5. Contrast: the nav numerals used `--other` (3.06:1 on white) and the New badge was white
   on PET amber (3.02:1). The numerals now use `--el-muted` (6.08:1) and the badge uses
   `--el-fg` on the same amber (5.21:1), so no polymer colour changed.

Also: Tabulator 6.3 nests `role="rowgroup"` inside `role="rowgroup"`, which trips
`aria-required-children` and `aria-required-parent`. The wrapper is marked
`role="presentation"` after every render rather than patching the vendored library.

## D15 Cleared 1,981 orphaned files from the pixi environment

`mlx_lm.fuse` died immediately after the fine-tune with
`ImportError: cannot import name 'PreTrainedConfig'`, raised from a file called
`transformers/models/encoder_decoder/configuration_encoder_decoder 2.py`. The downgrade
in D13, from transformers 5.21.0 to the 4.x line, had not replaced the 5.x modules: it
had written the 4.x ones alongside them under Finder-style " 2" names. transformers 4.57
builds its lazy import map by listing the files in each model directory, so it picked up
the 5.x copy and imported it against the 4.x `configuration_utils`.

1,981 such files were present across `transformers` (1,760), `huggingface_hub` (107),
`tokenizers` (16) and `gradio_client` (1). None appeared in any package `RECORD`, which
confirms they were orphans rather than shipped files, so all were deleted. The app
`.venv` was checked and is clean. The environment is regenerable from `pixi.lock`, so
nothing is lost if it needs rebuilding.

The fine-tune itself had completed before the crash, 800 iterations in 53.5 minutes,
validation loss 0.813 to 0.765, with the adapter saved. Rather than repeat it,
`pipeline/train.py` now checks for each stage's output first: the fine-tune is skipped
when `data/adapters/debris_v1/adapters.safetensors` exists and the fuse is skipped when
the fused model exists. `--retrain` forces both. This matches the resumability the build
instructions ask of every other stage.

## D16 `mlx_lm.fuse --dequantize`, not `--de-quantize`

Spec line 199 gives the fuse command as `--de-quantize`. mlx-lm 0.29.1 spells the flag
`--dequantize` and rejects the hyphenated form, so the code uses the spelling the
installed CLI accepts. The intent, a de-quantised fused model in Hugging Face layout so
transformers can load it on the Space, is unchanged. The spec file is left as written.

## D17 `vocab_candidates.count` counts papers, once each

The first FINDINGS.md draft listed `other:lipid_metabolism` against 32 papers when only 16
labels carried it. Both writers added to the stored count. `bootstrap_labels.py ingest`
re-reads every label file on each run, so its tally is already absolute and the second
ingest doubled it; `tag.py store()` added one per tagging pass, so a re-tag would count
the same paper again.

The ingest now sets the count instead of adding to it, and `store()` takes the difference
against the paper's previous tag: a value the paper has stopped proposing is decremented
and rows that reach zero are deleted. The spec's schema is unchanged. The stored counts
were repaired by re-running the ingest, and five tests cover the accounting.

## D18 `tools/findings.py` generates FINDINGS.md

Spec 6 item 6 lists ten things FINDINGS.md must carry, all of them numbers that live in
the database. Writing them by hand would date the moment the corpus moved, so the
document is generated: `pixi run findings`. Each section reads `data/debris.sqlite`,
`data/train/metrics.json` or the launchd plist, and the Venn gap section calls
`aggregate.venn_counts` on the same population the Atlas chart draws from, so the
document and the chart cannot disagree.

Drift recommendations are appended to FINDINGS.md by `pipeline/drift.py` (spec 5.7).
Regeneration keeps everything from the first `## Drift recommendation` heading onwards,
so a generated refresh never discards them.

## D19 The gold controls are pinned, and three of the nine were the wrong paper

Probing the nine gold controls against the trained model showed `brain_accumulation`
tagged as not relevant. The model was right: that slot held PMID 41233598, a Letter
titled "Reply to: Challenges in studying microplastics in human brain", with no abstract
at all. Two more were wrong. `blood_detection` held a Letter commenting on Leslie et al.
rather than Leslie et al. `pet_leachate` held a nuclear medicine paper about
`[177Lu]Lu-DOTAGA` and the CXCR4 axis, because its query contained the one term the spec
forbids, bare `PET[tiab]`, and `NOT "positron emission"[tiab]` does not exclude a paper
that writes PET/CT.

The resolver took the first search hit on trust. A letter about a landmark paper carries
the same words and a later date, so it wins a date sort; a review carries them all and
wins a relevance sort. Three changes:

1. A control must have an abstract, since a paper without one is never tagged, and must
   not be a Letter, Comment, Editorial, Erratum or News item. `prefer = "review"` wants a
   review and anything else wants a primary study, but the preference ranks rather than
   rejects: PubMed types Ragusa's placenta paper as a Review, and a hard filter lost that
   control entirely.
2. Two consecutive resolves of the same relevance-sorted term returned different first
   hits, once putting a study of organ damage in a fish into the PET slot. A control that
   moves between harvests is not a control, so the seven entries that name a specific
   paper now pin its PMID. The two that ask for "the most-cited" or "a broad review" keep
   their search and gain a `title_must_match` pattern that rejects a wrong record.
3. The `pet_leachate` term names the polymer in full and requires a biological system in
   the record, since a toxicity word alone ranked a thermo-oxidative materials paper
   first.

`harvest.py --gold-only` re-resolves the controls without re-running the whole harvest.
All nine now resolve to the intended paper, each with an abstract, and the title found is
recorded in `gold_set.title`, which was previously always written empty.

## D20 The stored DOI was sometimes a cited paper's

Two of the corrected gold papers came back `title_mismatch`: Crossref returned a
commission report for the Nihart brain paper and an African catfish study for the PET
Drosophila paper. Neither DOI belonged to the paper it was stored against.

`parse_article` read the DOI with `art.findall(".//ArticleIdList/ArticleId")`. That is a
descendant search over the whole `PubmedArticle`, and `PubmedData/ReferenceList` carries
an `ArticleIdList` for every citation that has one. The loop kept overwriting, so the
stored DOI was the last DOI anywhere in the record: usually the paper's own, but a cited
paper's whenever the publisher deposited references. It now reads
`PubmedData/ArticleIdList` only and takes the first DOI, with `ELocationID` as the
fallback.

This matters beyond two papers: `title_mismatch` was 23 % of the corpus and only verified
papers are counted anywhere, so an unknown share of that funnel was a parsing artefact
rather than an unverifiable DOI. The corpus was re-harvested with `--refetch`, the upsert
now resets `doi_status` to `pending` when a paper's DOI changes, and verification was run
again. A regression test parses a record whose reference list carries two other DOIs.

## D21 - fuse and quantise are separate resumable stages

The 1,600-iteration retrain spent 107 minutes on the fine-tune, fused the adapter, and
then died on `mlx_lm.convert`, which refuses to write into a directory that already
exists. The 800-iteration q4 copy was still sitting in `data/adapters/debris_v1_q4`.

`fuse_and_quantise()` ran both commands together and `main()` guarded the pair on the
presence of the fused model, so a resume would have skipped the quantise it still owed.
They are now `fuse()` and `quantise()`, each checking for its own output and each
clearing its target directory before writing, so a retrain replaces the previous weights
instead of failing on them or leaving a stale shard behind. The fine-tune did not have
to be repeated: the fused model on disk was the 1,600-iteration one.

`USE_FUSED` is also cleared now when the quantised copy scores within two F1 points of
the fused model. It was written on the 800-iteration run, where q4 lost 0.151, and
without this a later good q4 copy would still have been ignored in favour of the 6 GB
fused weights.

## D22 - two of the labelled fields were not functions of the abstract

The second rung of the spec 5.5 ladder changed almost nothing: 1,600 iterations scored
relevant_f1 0.9385, polymers 0.8324, organ_systems 0.7379, pathways 0.6416,
rungs_within_one 0.8086, model_type 0.8642, against 0.9438 / 0.8316 / 0.7095 / 0.6095 /
0.7963 / 0.8457 at 800. Validation loss bottomed at iteration 800 (0.765) and drifted up
to 0.790 by 1,600 while training loss fell, so the model had stopped learning from the
data rather than run out of passes over it. Climbing to 32 layers and then to 7B would
have spent most of a day to find the same thing out, so the predictions were broken down
by field first (`pixi run errors`, written for this purpose).

Two findings, both mine and neither the model's:

**`model_type` was arbitrary on every irrelevant paper.** The enum had no value for a
paper with no design worth recording, so the labelling filled it in anyway: `in_silico`
on 316 of the 732 irrelevant labels, `human_cohort` on 188, `animal_in_vivo` on 93. That
is 36 % of the training rows teaching a design that is not in the abstract, and it taught
`in_silico` as a bin for off-topic work: of the 22 model_type errors in the test split, 8
involved `in_silico`, including a dairy-cow rumen study and a river-plastic review. Every
other field was already emptied for an irrelevant paper. `not_applicable` is now part of
the vocabulary, `validate()` forces it whenever `relevant` is false, and `polymers` is
emptied there too for the same reason. This is a divergence from the nine values the
spec's schema table gives at line 176: a tenth value, used only where the spec's own
rule that an irrelevant paper carries no findings already applies.

The metric follows: `model_type_accuracy` is measured only where the gold says the paper
is relevant. On the rest the field now just restates the relevance call that
`relevant_f1` already scores, so including it would pad the accuracy with 46 % of the
split at no cost. Measured that way the 1,600-iteration model scored 0.8810 rather than
0.8642, against the same 0.90 floor.

**Rung 5 was labelled on abstracts that report no dose at all.** Rung 5 is a demonstrated
dose-response. Dose phrasing, or a second stated exposure level, appeared in 37 % of the
labels carrying rung 5 and in 21 % of those without it: a 16-point difference, which is
no basis for a label. 16 of the 22 rung-set errors were `[3, 5] -> [3]`, the model
predicting the modal set and leaving 5 off. A sample of the labels showed why: studies
described as size-dependent had been read as dose-dependent. `tools/repair_labels.py`
removed rung 5 from the 144 labels whose abstract reports no dose information, leaving
101. The rule only removes: an abstract that does state a concentration is left as
labelled, because stating one is not the same as demonstrating a response to it. The
prompt now carries the rule, so the tagger is asked for what the abstract can support.

Rung 5 in the corpus is therefore a lower bound, restricted to papers whose abstract
reports more than one exposure level. That belongs in FINDINGS.md and the model card
rather than being left for a reader to discover.

**The split is frozen.** Both repairs change the strata the split was drawn on, so the
test set would have moved underneath the comparison. `data/train/split_assignment.json`
holds the assignment as first drawn and `split()` reuses it, with `--resplit` to force a
new draw. Papers labelled later are drawn among themselves and added. The repaired splits
hold the same 1,277 / 161 / 162 papers as before, 693 and 88 of them relevant, so the
before and after numbers are measured on the same papers.

Pre-repair metrics and predictions are kept in
`data/adapters/debris_v1_iters1600_prerepair/`. The labels were backed up before the
repair ran. Organ systems and pathways were left alone, and the check that says so is worth
recording. For each value, how often does the labelled paper's abstract contain that
value's own vocabulary? Organ systems: 87 % over 1,282 label instances, from 100 % for
renal and 98 % for gastrointestinal down to 71 % for respiratory. Pathways: 83 % over
1,270, from 100 % for fibrosis and endothelial dysfunction down to 60 % for the NF-kB and
cytokine pathway. Against rung 5's 37 % those are sound labels: the paper says what it
was given. Their train and test frequencies match closely too, so the gap at
organ_systems 0.74 and pathways 0.64 is the difficulty of a thirteen and a twenty-value
multi-label task read from an abstract, and the remaining ladder rungs are the right
answer to it rather than more label work.

Two soft spots the model card should name. `systemic` carries its own words in only 29 %
of the 96 papers labelled with it: it is the organ value for a study that reports whole
animal effects, so it is a judgement rather than a reading, and it accounts for about a
seventh of the organ errors. `other:` pathway values are a free field by design and the
review queue is where they are meant to surface.

## D23 - one timer, and the droplet's was the wrong one

`deploy/provision.sh` enabled `debris-weekly.timer` on the droplet as part of every
provision. That timer is path A: it tags through the Hugging Face Space. There is no
`HF_TOKEN`, and the droplet has neither a GPU nor mlx, so the tag stage cannot run there
at all. The weekly runner logs a failed stage and continues by design, so the droplet
would have harvested and verified new papers every Sunday at 02:15 UTC, left them
untagged and rebuilt its own bundles, until the Studio's run overwrote the lot hours
later with `deploy.sh --data-only`.

The spec asks for one timer. With inference on path B the Studio's launchd job is it, so
provisioning now enables the droplet timer only when the droplet's `.env` carries an
`HF_TOKEN` and otherwise installs the unit and leaves it stopped. Switching to path A
later is one `systemctl enable --now` after the token is in place.

The droplet as it runs today was provisioned before the fix, and disabling the live
timer is a remote shell write, which this session is not permitted to make. Raised as
G1 in GATE_OPEN.md with the single command it needs. The build continues: nothing else
depends on it, and the consequence is a half-refreshed site for part of one Sunday
rather than any loss of data.

The Studio side is installed and enabled: `~/Library/LaunchAgents/com.mdeller.debris.weekly.plist`,
bootstrapped into `gui/$(id -u)`, next firing Sunday 2026-11-01 02:00 local. `plutil
-lint` passes and `launchctl print` shows the calendar interval registered.

## D24 - choose the checkpoint on the fields, not on the loss

The repaired labels moved five of the eight floor metrics up: relevant_f1 0.9385 to
0.9600, which clears its floor, rungs_exact 0.778 to 0.815, rungs_within_one 0.809 to
0.858, organ_systems 0.738 to 0.759, pathways 0.642 to 0.664. The rung errors are
symmetric now, 7 the model leaving rung 5 off and 4 adding it, where before 16 of 22 were
the same omission, and `in_silico` has gone from 8 of the 22 model_type errors to none
that matter: the commonest confusion left is cell line against human primary cells, which
is a real boundary rather than a bin for off-topic work.

**Validation loss is the wrong signal, and the first version of this decision used it.**
Both the 1,600-iteration runs reached their lowest validation loss near iteration 700
(0.774 this time) and then drifted up to 0.808 by 1,600 while the training loss kept
falling. mlx-lm writes a checkpoint every 100 iterations but leaves `adapters.safetensors`
pointing at the last one, so both runs fused the worse of the two models. `train.py` now
reads the validation losses out of its own log, takes the lowest whose checkpoint is still
on disk, and copies that over `adapters.safetensors`, keeping the final adapter beside it
as `adapters_last.safetensors`. A tie goes to the earlier iteration, which is the less
overfitted one. Stale checkpoints from a previous, longer run are cleared before a
retrain, because this run's validation losses say nothing about them.

Fusing the iteration-700 checkpoint and scoring it answered that: it was worse on every
field. Relevant F1 0.9492 against 0.9600, polymers 0.8021 against 0.8152, organ systems
0.7327 against 0.7591, pathways 0.6031 against 0.6644, rungs within one 0.8457 against
0.8580. Six points of pathways F1 for a checkpoint with 0.034 less validation loss.

Cross-entropy over the JSON string is not agreement field by field. It counts every token
of a 300-character object, so it is dominated by the summary text and the key names, and
a model can write a more probable sentence while naming one organ fewer. Choosing on it
optimises the wrong quantity.

So the choice is made on the fields themselves. `train.py --select-every N` scores every
Nth checkpoint on the **validation** split, ranks them by how many acceptance floors each
clears and then by the mean of its metric-to-floor ratios capped at one, and fuses the
winner. The cap stops a metric already over its floor from paying for one still under it.
The test split is never used to choose: it is what the floor is measured over. The choice
is recorded in `data/train/checkpoint_choice.json`, and the final adapter is kept beside
the chosen one as `adapters_last.safetensors`. Each candidate costs about five minutes
over the 161 validation papers.

The iteration count in the spec's ladder is therefore a budget rather than a target, which
is the right reading of it, but which checkpoint inside that budget is best has to be
measured and cannot be inferred from the loss curve.

## D25 Adapter capacity was the binding constraint, and two fields are label-limited

The spec's second ladder rung (`--num-layers 32`, 1,600 iterations) moved the tagger from
three of the eight 5.5 floors to four, on the frozen 162-paper test split:

| metric | floor | 16 layers | 32 layers |
|---|---|---|---|
| relevant_f1 | 0.95 | 0.9600 | 0.9711 |
| polymers_f1 | 0.85 | 0.8152 | **0.8701** |
| organ_systems_f1 | 0.85 | 0.7591 | 0.8043 |
| pathways_f1 | 0.75 | 0.6644 | 0.6332 |
| rungs_exact | 0.70 | 0.8148 | 0.8457 |
| rungs_within_one | 0.90 | 0.8580 | 0.8642 |
| model_type_accuracy | 0.90 | 0.8523 | 0.8523 |
| valid_json | 0.98 | 1.0 | 1.0 |

The fine-tune took 133.9 minutes against 107, and the 4-bit copy is now close enough to
the fused weights to be a real option (relevance gap +0.023 against +0.148), though it
still loses 13 points of organ F1, so `USE_FUSED` stays.

Doubling the adapted layers bought polymers and organs, which says capacity was binding
rather than the labels. Two of the four remaining shortfalls are not capacity, though, and
the measurements say so:

**`model_type` cannot reach 0.90 on these labels.** Seven of the thirteen errors sit on the
`cell_line` / `human_in_vitro` boundary, and that boundary is not a rule the prompt could
state: gold `cell_line` names an immortalised line (Caco-2, HepG2, A549 and the rest) in
60 % of 88 papers, and gold `human_in_vitro` names one in 25 % of 55, while mentioning
primary or ex vivo material in only 16 %. The two classes overlap on the single cue that
would separate them, so writing a definition into the prompt would document a convention
the labels do not follow. Clarifying the prompt was the obvious cheap fix and the
measurement ruled it out.

**`pathways` is two different defects.** Precision is now the worse side (0.598 against
recall 0.673). Checking each predicted pathway against cue vocabulary in its own abstract:
true-positive `oxidative_stress` has a cue in 91 % of 34 cases but the 23 false positives
in only 60 %, and `leachate_chemical_toxicity` carries a cue in just 50 % of its true
positives, so that label is weakly grounded in both directions. Against that,
`barrier_disruption` false negatives carry the cue in 72 % of 11 cases while its false
positives carry it in none, which is a recall failure on a clear signal. So part of the
pathway gap is a model that volunteers plausible mechanisms and part is genuine missed
signal, and only the second part can be expected to yield to capacity.

**Rung 5 is thin.** The label repair left 82 instances across 693 relevant training rows,
and the dominant rung error is now `[3,5] -> [3]` nine times. `rungs_within_one` needs
every gold rung matched within one, and 3 is two away from 5, so those nine failures are
most of that metric's 0.036 shortfall.

Next is therefore the spec's third rung, Qwen2.5-7B-Instruct at 32 layers, with checkpoints
scored every 400 iterations rather than every 200 to keep the selection pass near an hour.
If organs and `rungs_within_one` clear there, the two label-limited metrics go to G2 with
this evidence rather than to the pathway collapse, which would fold eight of the fourteen
pathway terms into `other` and cost the Pathways tab most of its content.

## D26 - the weekly timer belongs on the droplet, so path A is the serving route

Asked for directly: the timer is wanted on the droplet rather than the Studio. That is
path A in spec 5.6, and it is the better arrangement for the reason that matters, which is
that the droplet is always on and the Mac Studio is not. A launchd job on a desktop that
happens to be asleep, or busy, or rebooted, refreshes nothing.

The droplet timer was disabled earlier today under the previous G1, for a reason that
still holds: it was enabled by an old provision, pointed at path A, and had no token, so
every Sunday it would have harvested and published untagged papers. Turning it back on is
the right end state, but only once the Space it tags through actually exists.

Three consequences worth writing down.

**The first full tagging stays local.** `config/hf.toml` budgets the Space at twenty
minutes a week, which fits a weekly delta of roughly fifty papers. All 9,685 verified
papers need ten to twenty hours of inference depending on which model wins the ladder, and
putting that through ZeroGPU would exhaust the quota and take days. So the corpus is tagged
once on the Studio, and the droplet handles every week after that. Path A is the steady
state, not the bootstrap.

**Only one timer runs at a time.** When the Space is proven, `debris-weekly.timer` is
enabled on the droplet and `com.mdeller.debris.weekly` is disabled on the Studio in the
same step, not before and not after.

**An expiring credential is not a credential.** The only Hugging Face token on this machine
is an OAuth one in the CLI cache that expires 2026-11-03, with the sibling projects holding
an empty `HF_TOKEN=` line and two `hf_xxxx` placeholders. Pushing with the OAuth token
would work today and fail silently next week, and because the weekly runner logs a failed
stage and carries on, the symptom would be a site quietly serving untagged papers. That is
precisely the failure the earlier gate existed to prevent, so path A waits for a token with
write scope that does not expire. Raised as the new G1.

## D27 - the Space is private, and the token is fine-grained

The `debris` token is in place: fine-grained, no expiry, scoped to the `Dellboy`
namespace with `repo.write`, `repo.content.read`, `repo.contribute.write` and the
inference permissions. Verified by creating the private model repo
`Dellboy/debris-tagger-v1`, and written to `/opt/debris/.env` on the droplet over stdin
rather than on a command line, with the file tightened from 644 to 600 since it now holds
a secret. G1 is closed.

`hf/push_model.py` created the Space with no `private` argument, which on the Hub means
public. That is now `private_space = true` in `config/hf.toml`. The weekly run is the only
caller, `gradio_client` reaches a private Space with the same token, and ZeroGPU quota is
finite: a public Space would let anyone spend the quota the droplet's timer depends on,
which would show up as a weekly refresh that silently tagged nothing. The Space code is
not the sensitive part, the quota is.

The timer stays disabled until the Space answers a real abstract correctly. Enabling it
before then would recreate the failure the first G1 was raised over, only with a token
present to make it look configured.

## D28 - the training runs were offline because I checked for the wrong things, twice

Asked why the runs were not on wandb. Two separate faults, both mine, and both the same
mistake: deciding a capability was absent by looking for one particular spelling of it.

**The credential was there all along.** `pipeline/train.py` forced `WANDB_MODE=offline`
whenever the `WANDB_API_KEY` environment variable was unset. But `wandb login` writes to
`~/.netrc`, which wandb reads natively, and that entry has been present throughout:
`wandb.api.api_key` resolves it and the account is `dellboy`, entity `dellboy-none`. So
seven runs were written to `wandb/offline-run-*` while the server was reachable. There is
now `c.wandb_api_key()`, which asks wandb rather than guessing from the environment, and
the seven runs have been synced to `dellboy-none/debris`.

**mlx-lm's own reporting was never switched on.** `lora_supports_wandb()` searched the
`mlx_lm.lora` help text for `--wandb`. Version 0.29.1 spells it `--report-to wandb` with a
separate `--project-name`, so the check returned false every time and the fine-tune
streamed nothing live. The only curve that reached wandb was the one replayed from the log
after the run finished, which is why nothing appeared while training was in progress.
`lora_report_args()` now handles both spellings and passes whichever exists.

**A third thing, found while checking the first two.** The acceptance metrics were logged
only inside a `wandb.Table`, and a table cannot be sorted or charted across runs, which is
the entire reason for tracking a ladder. Each metric now also goes into the run summary as
a scalar, with `floor_gap/<field>` and a `floors_met` count. The already-synced runs were
backfilled from the tables they carry, so nothing was inferred from a file name: the ladder
now reads 2/8 and 3/8 and 2/8 for the three 16-layer runs against 4/8 for the 32-layer one.

The 7B run in flight was launched before this fix and holds the old module in memory, so it
will write offline and needs one `wandb sync` when it finishes. Restarting it to gain live
logging would cost the hours already spent, which is not a trade worth making for a chart.

## D29 - wandb run names follow the account convention

The runs were named `debris_v1` and `bootstrap-labels`, which the vibe-coding skill rules
out explicitly: the account convention is
`{project}-{model}-{ver}-{parameters}-round{NN}`, matching
`faffabout-llama-3.1-8b-8bit-round01` and `binman-qwen-2.5-3b-4bit-round01`. Five training
runs sharing one name are indistinguishable in a project list, which is most of why the
ladder was being tracked in DECISIONS.md by hand instead of being read off the project.

`c.model_stem()` derives `qwen-2.5-3b` from `Qwen/Qwen2.5-3B-Instruct` (verified against the
account's llama example, which it renders `llama-3.1-8b`). No quantisation suffix here: these
fine-tunes run on full-precision base weights, unlike BINMAN's 4-bit run. `c.wandb_round()`
reads the next round from the project rather than a local counter, so it survives a clone and
another machine, with the local run directories as the offline fallback.

The seven runs already on the forge were renamed through `display_name`, since assigning
`.name` is silently ignored, and given groups, job types, tags, notes and round numbers.
Ordering came from the offline directory names, which carry the real start time: `created_at`
on the server is the sync time, so every run reads 15:56 and cannot order them.

Two judgements inside that:

**The checkpoint evaluation is not a round.** Round 03's iteration-700 checkpoint was scored
in its own run, and it is an evaluation of round 03's training rather than a training stage of
its own, so it is `debris-qwen-2.5-3b-round03-eval-ckpt700` inside round 03's group instead of
consuming round 04. The convention's one-round-per-stage rule is about training stages.

**The label runs take no round.** A dataset run has no model, so the pattern does not apply:
they are `debris-bootstrap-labels` and `debris-bootstrap-labels-split`.

Each fine-tune now produces two runs in one group, which is the shape the convention describes
for a multi-stage experiment: mlx-lm's own `sft` run carries the live curve, named through
`WANDB_NAME` in the subprocess environment because mlx-lm has no run-name flag and would
otherwise name it after the adapter directory, and the scoring pass follows as `...-eval` with
the acceptance metrics. Round 01 was backfilled from its archive, so the ladder now reads off
the project: round01 2/8, round02 2/8, round03 3/8, round04 4/8.

The 7B run in flight was launched before this and will arrive as `debris_v1` offline; it gets
synced and renamed to round 05 when it lands.

### D27 addendum, 2026-10-29: both Hugging Face repos go public

Asked for directly, which overrides the quota reasoning above. `config/hf.toml` now records
`private_model = false` and `private_space = false` so the declared state matches the
intended one. The flip on the live repos needs doing by hand: both
`HfApi.update_repo_settings(private=False)` and the equivalent through the CLI are refused
in this session by the auto mode classifier as a public-surface change, and working around
that is not appropriate even with the instruction in hand.

The quota consequence from the original decision still stands and is worth watching rather
than worrying about: a public ZeroGPU Space can be invoked by anyone, and the weekly run
needs it for roughly twenty minutes a week. The existing retry ladder in `pipeline/tag.py`
already covers exhaustion, six attempts with a growing wait and then path B for that week,
so the failure mode is a late refresh rather than a wrong one.

## D30 - the Space is verified, and one headline control fails on the model not the Space

Path A works. The Space answered three gold papers in 11.6 seconds through `gradio_client`,
with valid JSON, sensible tags and self-consistency between 0.82 and 0.91. Getting there
took four real faults, each found by running the thing rather than reading it:

1. `torch==2.4.0` is not a version ZeroGPU supports (it names 2.8.0 as its oldest).
2. The Space parsed the vocabulary with `tomllib`, which Python 3.10 does not have. The
   vocabulary now travels as JSON, generated from `config/vocab.toml` at push time.
3. `gradio==4.44.1` could not render its own page against the image's newer jinja2
   (`TypeError: unhashable type: 'dict'`). The SDK version now matches the client.
4. That bump exposed a conflict rather than a stale pin: `transformers==4.46.3` requires
   `huggingface-hub<1.0` and gradio 6 requires `>=1.16.0`. transformers 5.20.2 resolves it.

And one fault in this repo that would have broken every path A weekly run silently:
`gradio_client` renamed its `hf_token` argument to `token`, so `RemoteTagger.__init__`
raised `TypeError` before reaching the Space at all. Found by calling it.

**The failing control is the model's doing.** `carotid_plaque_cohort`, the Marfella NEJM
cohort, wants `{PE, PVC}` and gets `mixed_unspecified`. The local model returns exactly the
same thing for that paper, in both the round 03 and round 04 prediction files, so the Space
is faithful and the error is in the tagger. This is the single most consequential paper in
the corpus and its abstract names polyethylene and polyvinyl chloride outright, so it is
also the clearest case yet that polymer extraction is the weak field, even at 0.8701 F1.
Whether round 05 fixes it goes into the comparison when it lands.

**What I could not establish, and the fix for that.** The prediction records held only the
post-validation tag, so there was no way to tell whether the model named
`mixed_unspecified` or named nothing and `validate()` filled it in, which it does for any
relevant paper with an empty polymer list. Those are different failures: one is a
misreading, the other is the schema making a claim on the model's behalf. `score()` now
records the raw parsed output and the list of repairs beside each prediction.

**One change deliberately deferred.** That fill is probably wrong: `mixed_unspecified`
means the study reported particles without identifying the polymer, which is a finding, and
a model that names nothing is not evidence of it. Changing it would be a one-line edit, and
I am not making it yet, because `validate()` also shaped the 1,600 training labels, so
changing it mid-ladder would alter the training data and break the frozen comparison
between rounds that the whole acceptance exercise depends on. It is the first thing to
revisit once the ladder closes.

**A self-inflicted one, recorded so it is not repeated.** Asking the local model for its raw
output while the 7B fine-tune held the GPU returned
`[METAL] Insufficient Memory` and killed the query. The fine-tune survived, but the hardware
rules in the build spec say one resident model at a time for exactly this reason, and a
diagnostic is not an exception to that.

## D31 - DEBRIS listed on the mdeller.com launcher

Asked for directly, which is also the one thing in this build that reaches outside the
project root: `CLAUDE.md` says never modify a sibling, and `mdeller-landing/apps.json` is a
sibling. Done on instruction, as one entry plus a deploy, with no change to any other app.

The launcher is driven entirely by `apps.json`, so health, hits and caching are three
separate mechanisms rather than three fields:

**Health** follows from `status: "live"`: `mdeller-stats.py` fetches every live app on a
five-minute cron and records a real response time. DEBRIS answered in 56 ms on the first
poll. The app's own `/healthz` route stays what `deploy.sh` verifies after a deploy; the
launcher probes the site itself.

**Hits** needed a judgement. The beacon must be a request a rendering engine makes after the
page loads and never the HTML, which every scanner fetches. DEBRIS injects its JSON bundles
server-side, so there is no post-render API call to use, which leaves a subresource, and the
beacon is `^/static/css/theme\.css\b`. Two checks before settling on it. The stats script
warns that an app whose vhost redirects or disables its access log reads a flat zero while
its beacon fires perfectly, 28 uncounted address-days in ButtFold's case, so I confirmed
against the live log that DEBRIS sets no `access_log` of its own, that its lines reach the
shared log in the `vhost` format, and that all fourteen `theme.css` lines carry
`"debris.mdeller.com"` as the host field the parser attributes on. It read 4 hits, 4 unique
within a minute of the deploy.

The known cost of a stylesheet beacon is that the year-long immutable cache stops repeat
visitors re-requesting it, so the count is first view per asset version per browser rather
than every view. Five of the eighteen existing apps count the same way, and matching them
keeps the numbers on one page comparable, which is worth more here than making DEBRIS
uniquely accurate.

**Caching** needed nothing: the vhost already serves `/static/` with
`max-age=31536000, immutable`, which is safe because every asset URL carries `?v=<mtime>`,
so a changed file refetches while the 4.6 MB Plotly bundle and the fonts cache hard.

Two follow-ups. The description says what the tagger records rather than claiming the corpus
is tagged, because it is not yet; it wants a sentence with real tagged counts once the full
pass finishes. And `index.html` is a build artifact and gitignored in that repo, so the
commit there is `apps.json` alone.

## D32 The negative controls were in the published corpus, and no keyword filter replaces the tagger

Marc spotted positron emission tomography and CT papers in the Papers feed, including the
most recent entry, and asked for them to be filtered out up front. Two separate problems
sat behind that, and only one of them was a defect.

**The defect.** Every one of those papers carries `hit_strategy = negative`. They are the
402 hard negatives the harvest collects on purpose so that `validate.check_negatives` can
show the tagger refusing them, and PET/CT is the trap they exist for, because `PET` means
polyethylene terephthalate here and positron emission tomography in a radiology journal.
They verify at Crossref like any other paper and nothing in the app, the aggregate or the
counts filtered on provenance, so 362 of them were being published as corpus. The headline
figure of 9,685 verified papers was 9,323 corpus papers plus 362 controls. The architecture
was already most of the way there: `paper_filters` carries `(t.relevant IS NULL OR
t.relevant = 1)`, so the controls would have dropped out of the feed by themselves the
moment tagging ran. They were visible only because nothing is tagged yet, and that
`IS NULL` accommodation is what keeps the Papers tab populated during phase 1.

Relying on it would still have been wrong. A control must not reach the site because of
what it is, not because the tagger happened to agree, so the exclusion is on provenance:
`common.corpus_clause()`, one definition, interpolated through every published query, and
inlined once in `app/app.py` with a comment saying why, because the app venv holds only
Flask and gunicorn and cannot import from the pipeline. A paper the real strategies also
found keeps its place: `textword,negative` is corpus, and 34 papers are in that position.
`meta` now reports `control_papers` alongside `verified_papers` so the funnel still adds up.

The suite had no test for any of this, which is how it shipped. There are nine now, and I
checked they fail without the fix: seven do, including the untagged control that reproduces
what Marc saw and a control the tagger has wrongly called relevant, which must stay out
regardless. The two that pass without it are invariants that do not depend on it.

**The thing that was not a defect.** A filter on imaging terms would have been a mistake.
Nine corpus papers mention a scanner and seven of them name a plastic as well: polystyrene
tracked through an asthmatic mouse lung by PET, the in vivo fate of inhaled nanoplastics,
PLA toxicokinetics by radiotracer, polyethylene renal dysfunction by SPECT. Imaging is the
method in those papers, not the subject, and they are among the most mechanistically useful
work in the corpus. Three more are sodium polystyrene sulfonate, which is Kayexalate, a
polystyrene resin given as a drug: whether a Kayexalate crystal is a microplastic is a
scientific judgement, and a keyword filter would have had to make it blind and would have
been wrong either way. That judgement belongs to the relevance head, which is the one
metric comfortably clear of its floor at 0.9711.

**What the measurement did turn up.** 970 corpus papers never name a plastic anywhere in
title or abstract, 919 of them from the MeSH strategy alone. They are Dacron grafts,
silicone implants, ceramic hip replacements, hemoperfusion cartridges and wheelchair
propulsion studies. The MeSH indexing is not wrong: Dacron genuinely is polyethylene
terephthalate. They are simply medical devices rather than environmental exposure, and
because they carry words like `patient` and `cohort` they were being sorted into tier 2 and
tagged ahead of the real corpus.

So the demotion is on ordering, not admission. Tier 6 is a paper that never names a plastic,
tier 7 a deliberate control, and both are still tagged: a wrongly demoted paper is tagged
later, never dropped, which is the only safe failure mode for a keyword test. 14.2 % of the
corpus moves to the back, so a tagging pass that dies at hour six has finished the papers
that matter. I sampled 22 of the 970 and every one was a graft, a prosthesis or unrelated.
`PE`, `PP`, `PA`, `PC` and `PU` are deliberately not in the polymer vocabulary, because in
this literature they read as pulmonary embolism, the posteroanterior view and protein C far
more often than as polymers; a paper reporting a microplastic finding names one in full
somewhere in its abstract almost without exception, and `PS` and bare `PET` are in.

`tools/screen.py` (`pixi run screen`) prints the tier split, lists the nine imaging papers
with whether each names a plastic, and after tagging reports what the tagger said per tier.
A tier 7 that comes back relevant is a tagger mistake by construction; a tier 6 that does is
worth reading. The precision question is now measured rather than argued about.

**Reversing it.** Drop the clause from `corpus_clause`, or widen `CORPUS_STRATEGY`, and the
controls return to the corpus. The tiers are ordering only, so removing tiers 6 and 7
changes the sequence of a tagging run and nothing about its output.

## D33 The tagging pass needed a circuit breaker, and the tests were writing to the real manifests

One pass over the corpus runs for ten hours or more, so the failure worth defending against
is not a crash. A crash already resumes: `pending()` excludes papers that have tags, the
manifest records what is done, and `store()` writes each paper in one transaction, so a kill
between two papers costs nothing and a kill inside one leaves no half-written tag.

The failure that was not handled is the tagger dying part way through and staying dead. A
single exception marked a paper `failed:` and moved on, so an outage at hour two, a Space
that stops answering or a model file that goes missing, would have marked all nine thousand
remaining papers failed, put every one of them in the review queue, logged `done 0 tagged,
9,000 failed` and exited zero. That reads as a tagging problem rather than an outage, and
the review queue would have been the whole corpus.

Two changes. Each paper now gets one retry after a twenty-second pause, because a cold Space
or a dropped connection costs the paper nothing if we simply ask again, and a paper that
fails twice keeps no manifest line so a later run picks it up. And twenty-five consecutive
failures stop the run with a non-zero exit and a message saying it is an outage, how many
papers were tagged, and that the same command resumes. Both are tested, including that the
breaker leaves the rest of the corpus for the next run rather than consuming it.

Writing those tests turned up something worse. The autouse fixture redirects `BUILD_LOG.md`
but not `data/manifests/`, so a test that tags anything appended to the project's real
`tag.jsonl`. It had already written one line by the time I noticed, and the second run of
the same test then skipped that paper because the manifest said it was done. A manifest is
how every stage decides what to skip, so a test that writes one tells the next real run that
work it has never done is already finished: on a full corpus pass that is silently missing
papers. `c.MANIFESTS` is now redirected to a temporary directory for every test, and the
stray line is removed. Nothing else had been affected, because no stage had run since.

## D34 The Atlas and the Body rebuilt as four and three linked panels

Marc picked four of the ten concepts for the Atlas (cluster, chemistry packing, pair matrix,
exact combinations) and three for the Body (the pinned figure as the feature, the ranked rail
and the tissue cards), asked for real organ artwork rather than a bare silhouette, and asked
that the panels on each tab drive one another.

**Why the Venn had to go.** Three sets give seven regions, four need ellipses, and the eleven
named polymers in the vocabulary would need 2,047. The old code drew a fixed three-set Venn of
PET, PS and PE+PP and a two-set Venn of PVC against everything else, with the sets written into
`aggregate.py` as `MAIN_SETS` and `SECONDARY_SETS`. That is not a diagram that grows. The four
panels each keep a different part of what a Venn does: overlap as position, as hierarchy, as a
cell, and as an explicit row. Only the last of them can state a three-way combination
truthfully, which is why it is on the tab beside the cluster rather than instead of it.

**One selection across a tab.** Picking a polymer anywhere sets one piece of state and every
panel repaints from it: the cluster raises that circle and draws its overlap lenses with their
counts, the packing lifts its chemical family, the matrix lights its row and column, the bars
mark every combination containing it. A matrix cell or a cluster lens selects a pair instead,
which narrows the bars to the combinations holding both. The same on the Body: a tissue chosen
in any of the three panels lights its organ on the figure, raises its pin above its neighbours,
marks its rail row and brings its card forward. Selection is a filter, not a navigation: a
selection bar states what is selected, how many papers it stands for, and offers the link into
the Papers tab, which keeps a single click from throwing the reader off the page.

**Everything is now data.** `aggregate.py` sends polymer rows, every pair that has any papers,
and the exact combinations; the old membership-code `venn_counts` is gone. The body map used to
carry nine sites with their coordinates written into the Python; they are now `[[body_nodes]]`
in `config/vocab.toml`, each with its anchor, its organ systems, its body region and the organ
drawing it belongs to. Colours moved the same way: a `--poly-<key>` token per polymer in
theme.css rather than a map of five in JavaScript. Going to the 11 polymers and 18 tissues of
the paper Marc linked is an edit to the vocabulary and nothing else.

Writing that roster turned up an omission: `systemic` had no anatomical site, so papers tagged
to it were missing from the body map entirely rather than merely absent. It has a node now,
drawn against the whole figure. `endocrine_metabolic` and `immune` had no site either, and now
do. `tests/test_roster.py` holds the line: every organ system has a site, every site points at
a drawing that exists, every drawing belongs to a site, every anchor lands on the figure, every
polymer has a family, a short name and a colour token, and a tissue the code has never heard of
still reaches the bundle correctly counted.

**The artwork.** `_anatomy.html` draws brain, thyroid, lungs and airway, heart, lymph nodes,
liver, stomach, kidneys, gut, vessels, placenta and skin on the same 360 x 720 space the
anchors use, each group tagged `data-art` so the renderer lights an organ without knowing its
shape. Anatomical tints sit at rest and the data lives in the pins: the drawing says where, the
pins say how much, and colour never has to mean two things at once. One transform in `body.js`
places both the drawing and the pins, so they cannot drift apart when the figure is scaled.

**Built against synthetic tags.** Nothing is tagged yet, so all four Atlas panels and every pin
would have read zero. Rather than ship a visualisation I had never seen with data in it, a
throwaway copy of the corpus was filled with plausible tags from a fixed seed, a realistic long
tail rather than flat counts so no layout got flattered, and the panels were rendered against
it. That is what turned up the label pile-up in the cluster, the family names buried under the
next family's ring, the clipped thirteenth card and the rail labels running off the left edge.
`DEBRIS_STATIC_DATA` exists for that preview and defaults to the real bundles.

Which left the empty state, the one state that actually ships tonight: four blank frames that
read as a broken page. Each panel now says what will appear there and why it is empty, and the
body figure needed nothing because the anatomy and the labelled pins carry it on their own.

**Reversing it.** The panels are independent renderers over two bundles; removing one is
deleting its figure and its block in the JavaScript. The rosters reverse by editing
`config/vocab.toml`.

## D35 Round 05: the 7B buys pathways and nothing else we can measure, and the test split cannot see small effects

The 7B rung of the ladder (Qwen2.5-7B-Instruct, all 28 layers, 1,600 iterations, checkpoint
1200 chosen on the validation split with five floors there) clears four of eight floors on
the frozen test split, the same count as the 3B 32-layer model of round 04. By the rule set
before it ran, that sends the shortfalls to G2 rather than buying the 7B: it did not clear
organ systems or rungs within one.

A paired bootstrap over the 162 test papers (2,000 resamples, the same papers drawn for both
models) says more than the point estimates do. Only one difference is real: pathways,
+0.071, 95 % interval [+0.010, +0.134]. Relevance (-0.017), organ systems (-0.026), rungs
within one (+0.019), model type (+0.011) and polymers (+0.008) all have intervals straddling
zero. The organ result is the clearest case: the 7B was 5.6 points ahead on validation and
2.6 points behind on test, and both are noise.

That changes how the next experiments have to be judged. On a split of this size the 95 %
interval on a single model's score is roughly plus or minus five points for most fields and
plus or minus seven for polymers and model type, the latter scored on only the 88 relevant
papers. An experiment that improves a field by two or three points cannot be told apart from
one that does nothing. It also means a floor met at 0.954 against 0.95 and a floor missed at
0.946 are the same result, which matters for how G2 reads the shortfalls.

Two smaller findings. The quantised 7B lost 5.9 pathway points against the fused model, which
is the size of the 7B's one real gain, but `train.py` cleared USE_FUSED because the relevance
gap alone was within tolerance; that rule should look at every field. And the round 05 loss
curve was not lost as feared: the streaming `run()` captured it in the training log and the
eval stage logged it, so the synced wandb run (`debris-qwen-2.5-7b-round05`) has all 81 steps.
Validation loss bottoms around iteration 500 to 700 and climbs to 0.829 by 1600 while the
field metrics keep improving, which is D24 again: the loss is computed over the prompt as well
as the answer, so it mostly measures how well the model reproduces text it was given.

The chosen adapter is archived at `data/adapters/debris_v1_7b_round05`, since the 7B fused and
q4 directories replaced the 3B's. Round 04's adapter is still at `debris_v1_32layer1600`.

## D36 Two MLX processes on one GPU need memory caps; Phase 0 was knocked over finding that out

While Phase 0 was scoring fold 0, I ran a short benchmark training beside it to see whether
the GPU had room for more than one job. It did for compute and did not for memory: Phase 0's
scoring process died with `[METAL] Command buffer execution failed: Insufficient Memory`.
Fold 0's training had finished and its adapters were saved, so only the checkpoint-200
scoring in progress was lost; the run resumed from the saved adapters. Running GPU work beside
a live experiment without a memory cap was a mistake, and it should not be repeated.

What it measured is still worth having. The benchmark trained at 0.34 to 0.42 iterations a
second beside the scoring, against 0.35 to 0.39 for the same iterations of fold 0 alone, so a
single 1.5B job does not saturate the GPU. The limit is memory: MLX reports a recommended
working set of 115.4 GB, but each process grows its own buffer cache as if it had all of it,
and nothing coordinates two processes. Fold 0 alone peaked at 34.7 GB of active arrays, before
its cache. Any concurrent lab jobs therefore need an explicit per-process memory and cache
limit (`mx.set_memory_limit`, `mx.set_cache_limit`), set from config/tuning.toml rather than
hard-coded, and measured alone on the GPU before the lab relies on them.

## D37 Phase 0 result: the lab model passes the exit test, and the lab trains to 600 iterations

The baseline recipe on Qwen2.5-1.5B (round 07, three folds, 1,438 papers each scored once)
reaches a floor mean of 0.764 ± 0.014 at 800 iterations. Against round 04 (the 3B, 32 layers,
frozen test split) it sits 10 points lower on relevance, 11 on polymers, 14 on organ systems,
7 on pathways, 11 on exact rungs, 7 on rungs within one and 13 on model type, with valid JSON
at 1.000. Every field is inside the plan's 15-point window, so the 1.5B stays the lab model.
The comparison is across different evaluation sets, so it is a sanity check, not a ranking.

The fold 0 learning curve gives a floor mean of 0.746, 0.775, 0.787 and 0.778 at 200, 400, 600
and 800 iterations. Organ systems (+0.04) and pathways (+0.07) are still improving between 400
and 600 and nothing improves after it, so the plan's rule ("the shortest count at which the
fields stop improving") gives 600. Phase 1 and the seed check train to 600, and the baseline is
reported at 600, with folds 1 and 2 scored from their saved 600 checkpoints rather than retrained.
That rescoring is not logged to wandb again (WANDB_MODE disabled), to avoid duplicate runs.

The seed check runs on fold 0 rather than fold 1 as LAB_PLAN.md says: fold 0 already has seed
42 scored at 600 from the curve, and the report compares on it. Which fold carries the check
does not change what it measures. Reverse by setting `folds = [1]` in config/lab/phase0-seeds.toml.

The concurrent scheduler is `pipeline/lab_queue.py` (`pixi run lab-queue phase1`). Each
experiment is its own `lab.py run` process under the caps in the tuning [lab] table, rounds
are fixed in the parent before any child starts, and a failure is logged without stopping the
queue. How many run at once comes only from `tools/lab_bench.py`.

## D38 One lab job at a time; and the label ceiling says pathways and organs are definition problems

**Benchmark (tools/lab_bench.py, GPU otherwise idle, every job capped).** One 1.5B training
ran at 0.513 iterations a second; two together totalled 0.536 (1.04x); a training beside a
scoring slowed 14 % while the scoring slowed from 0.451 to 1.871 s a paper. No memory failure.
Both pre-set rules fail (1.25x for two jobs, under 10 % for overlap), so `parallel_jobs = 1`
and `overlap_scoring = false`. D36's observation that a training did not slow beside scoring
was a few noisy iterations; measured properly, one training uses nearly the whole GPU. The
queue still applies the caps and runs experiments back to back. Reverse by rerunning the bench
if the model or batch size changes.

**Label ceiling (pipeline/ceiling.py, 150 papers, Qwen2.5-32B 4-bit, zero-shot, the first
labeller's exact view and instructions).** Agreement with the training labels: relevant 0.903,
polymers 0.759, organ systems 0.567 [0.469, 0.658], pathways 0.452 [0.383, 0.517], disease
categories 0.850, rungs exact 0.753, within one 0.833, model type 0.778, valid JSON 1.000,
floor mean 0.756. All 150 answers parsed.

The fine-tuned 1.5B agrees with the labels more than this second labeller does on organ
systems (0.662) and pathways (0.563). A model trained on the labels learns the first
labeller's conventions; an independent careful reader, given the same written instructions,
does not reproduce them. So on those two fields the instructions underdetermine the answer,
and the floors (0.85 and 0.75) sit well above what two readers agree on. The ceiling is
pessimistic (the 32B is zero-shot and quantised), so this is not proof that the floors are
out of reach, but it moves the weight of the plan: the formatting ideas in Phase 1 cannot fix
a field whose labels are inconsistent, and Phase 2's sharper definitions (pathways measured,
not mentioned; organs from an explicit tissue list) are where those two fields can move.
Phase 1 runs as planned, because its factors target model type, rungs and the composite.
