# Ambiguities reported by the labellers (resolved after all batches return)

## b09
- 41580100: pub type Review but abstract is a primary fish experiment; labelled review, pathways []. Rule: does pub type or abstract win?
- 41468511, 39326828, 34743871: assay run but null result (comet negative, apoptosis not induced); tagged. Rule: does a null result count?
- 25937414: PE in arthroplasty cysts, null correlation with reoperation time; labelled human_cohort, arguably human_tissue.
- 37652241: cell-free adsorption in simulated gut fluid; no model_type fits, used in_silico. 42724844 bioinformatics with one knockdown experiment, similar.

## b04 (complete, 92, clean)
- 35038536, 41771477: measured but null (immune; genotoxicity, oxidative stress, barrier); tagged.
- 38043900: cell-free assay on porcine lung surfactant; used cell_line, tissues []. 35964535 sorption/bioaccessibility in gut fluids + risk modelling; used in_silico.
- 42781772 news piece (typed Journal Article), 40600103 editorial; labelled review.
- 37734602: faecal MPs associated with aortic calcification plus rat arm; human_cohort, other:faeces, other:artery, intestine. Invertebrate/fish organs used: other:gill, other:hepatopancreas, other:hemolymph, other:digestive_gland, other:mantle. Haemolymph to blood? bivalve adductor to skeletal_muscle?
- 35167931: species not stated; inferred animal_in_vivo. 37689192, 33517056: unnamed polymer used -> mixed_unspecified.

## b07 (complete, 91, clean)
- 35236033: cell-free porcine surfactant assay; cell_line, tissues [].
- 33718875: BPA/styrene oxide on unnamed human cells, no particles; cell_line, polymers [].
- 42208884: polymers detected in the study's own air samples (PA66, NBR) tagged; in_silico for lung deposition model.
- 42808153: UK Biobank with river MP proxy; polymers []; outcome organs (liver, colon, lung) tagged as tissues. Do cohort outcome organs count?
- 39866647 editorial -> review. 37352712, 33957472, 31836230: wild-caught naturally exposed animals -> animal_in_vivo.
- Null results tagged (16966097, 33076715). Bivalve haemocytes -> blood; gill, hepatopancreas, digestive gland, head kidney, mantle as other:. Co-contaminants (Cu, Cd, DBP, parabens) not tagged as leachate.

## b00 (complete, 95, clean)
- Null results tagged (29197232, 34680075, 31139862). Vague "inflammation" not tagged as nfkb_cytokine. Unnamed nanoplastics -> mixed_unspecified.
- Neurotransmitter work tagged other:neurotransmitter_disruption (36493651, 37454885, 39708463); the 41996166 example did not tag it: inconsistent, needs a ruling or a named value.
- 40700969: PET effect only in unnamed cells + docking; atherosclerosis mice not exposed; cell_line, no tissue.
- 32504956: cell-free adsorption + risk calc -> in_silico. 32155522 wild fish -> animal_in_vivo.
- 42920511: additive ATBC only, no particles; polymers [].
- 36460160: unsexed "gonad" -> other:gonad + other:semen. Haemocytes -> blood (33865135, 32289642) but Drosophila other:hemolymph (42874708).

## b08 (complete, 93, clean)
- 35504440: pub type Review but primary carp study; labelled review, pathways [] (loses data).
- 40505392: cell-free surfactant monolayer -> in_silico, tissues [].
- 30451503, 40744315: null results tagged.
- 37944326, 32421333: heart function (zebrafish heart rate, Daphnia heartbeat) -> myocardium. Hedged results ("possibly triggering apoptosis") not tagged.
- 39923867, 37659273: additive dosed separately not tagged as leachate; tagged where chemicals came off the plastic (32207945, 24309271).
- 35295110: BEAS-2B on a chip -> organoid. 33618468 field seaworms -> animal_in_vivo; only predominant PE tagged.

## b03 (complete, 96, clean)
- 36116710: particles in human thrombi vs platelet levels -> human_cohort, platelet_activation_thrombosis, other:thrombus.
- 28802989: ex vivo trout gut sacs -> cell_line (no animal ex vivo value).
- HUVEC / EA.hy926 (34358975, 34157338, 36529175): line or primary unknown -> cell_line; invented other:umbilical_vein, other:blood_vessel. 35988336 unnamed placental cells.
- Reviews: polymers and tissues left [] (37659479).
- Transcriptomic enrichment counted as pathway evidence (42612384, 34861263). other:sputum; BALF -> lung.
- Digestive gland -> other:hepatopancreas; gills other:gill; hippocampus/cerebellum -> brain. other: pathway keys: cellular_senescence, energy_metabolism, xenobiotic_metabolism, pi3k_akt.

## b01 (complete, 92, clean)
- IL-1b in a cytokine panel -> inflammasome_il1b + nfkb_cytokine. Unnamed inflammation untagged. Gut microbiota -> tissue intestine. other:neurotransmitter_disruption. Cell line tissue only when the abstract names it. ABS -> other:abs.
- 33395930 Plasticenta: pub type Review but original detection; labelled review but kept PP and placenta (inconsistent with b03, which left reviews' polymers/tissues []).
- 39368622: ILD patients vs controls, "a tendency" -> human_cohort.
- 37703772: cell-free + docking -> in_silico.
- 41638286: in vivo arm is DBP only; plastic in vitro; labelled animal_in_vivo. Should the design be the strongest involving the plastic?
- 40602120: faecal plastics vs CRC risk: other:faeces only, not colon (b07 tagged outcome organs: inconsistent). Systemic serum markers -> blood (37981148, 42561517).

## b05 (complete, 94, clean)
- Null results tagged (35303527, 36905991, 42705372, 35978532).
- 41371138 subway air + lung deposition model + DFT -> in_silico, tissue lung. 34581385 cell-free sorption -> in_silico.
- HUVEC -> other:umbilical_vein (35622629, 35978532, 41819632). Hepatopancreas kept apart from liver (36640574, 29709883, 42766900).
- Heart rate -> myocardium (37269673, 38552772, 31951993); pericardial oedema only -> none (41534285).
- 38653734 additives in serum/urine: blood, other:urine, leachate. other:pollutant_bioaccumulation coined.
- Reviews: all [] for tissues. 41151287 primary + LNCaP -> human_in_vitro. 39947063 follicular fluid vs FSH -> human_cohort.

## b02 (complete, 94, clean)
- Cell-free -> in_silico (33691242, 37652241, 38077139, 42637432).
- Reviews tagged with their focal organ (31476381, 33933760, 34289226, 37673257, 35940544, 42508716): inconsistent with b03/b05.
- Unnamed inflammation untagged (35597345 and others).
- Fish ex vivo gut sac / anterior kidney cultures -> cell_line (37353043, 33930547).
- other:haemolymph kept apart from blood; head kidney -> kidney.
- DEHP/phthalate co-exposure tagged leachate (33321324, 42822122, 40819401, 36423728): inconsistent with b08.
- 16S gut microbiota -> intestine. Hypothalamus -> brain. Detection + in vitro -> human_tissue (40972786, 42155926).

## b06 (complete, 92, clean)
- 36253987 trial protocol, no data -> human_cohort, other:semen.
- 36931485 fibrinogen + PS cell-free -> human_in_vitro, tissues [].
- 39341155 prostate tumour vs non-tumour + clinical -> human_cohort.
- 39111678 3D liver microtissue primary cells -> human_in_vitro; 40312000 iPSC cardiomyocytes -> cell_line.
- Haemolymph/haemocytes -> blood; other:coelomic_fluid; other:blood_vessel; systemic serum markers not blood; other:gonad.
- other:neurotransmitter_disruption; other:cholinergic_disruption for AChE. Leachate only for chemicals in/from the plastic.
