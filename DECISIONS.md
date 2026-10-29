# DEBRIS decisions

| Date | Decision | Alternatives | Reason | Reverse by |
|---|---|---|---|---|
| 2026-10-28 | Name DEBRIS; merge PLAQUE ladder, BOTTLE body map, LANDFILL pathway hub into one app | Four separate apps | Marc's choice | n/a |
| 2026-10-28 | Qwen2.5-3B-Instruct, one LoRA fine-tune, no retraining | Llama 3.2 3B (gated); retrain weekly | Ungated weights; tagger learns schema not facts | Train debris_v2 via pipeline/train.py |
| 2026-10-28 | Two gates only; deploy pre-approved; keys optional with fallbacks | Six-gate template | Marc asked for a quick automated build | Edit spec Section 0.2 |
| 2026-10-28 | Weekly inference on HF ZeroGPU Space, droplet-side timer (path A); Studio launchd as path B | Studio only | Removes the Studio from the weekly loop | Switch `inference_path` in config |
| 2026-10-29 | Droplet SSH target taken from `AlphaFraud/.env` (`root@45.55.102.228`), app at `/opt/debris` on port 8014 | Ask Marc for SSH details (would have opened G1) | AlphaFraud's deploy config is the documented source (spec section 3); 8011 to 8013 are already taken on the droplet | Edit `config/deploy.toml` |
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
