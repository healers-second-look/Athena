# Literature Review: Positioning Athena Against the Oncology CDS Landscape

Source: Comparative search conducted via Consensus.app (Consensus NLP, Inc.), 8 research areas, ~40 papers screened (2018–2026), synthesized against Athena's built architecture (`Concept.md`, `IMPLEMENTATION_PLAN.md`, `NEW_SUBSYSTEMS.md`, `Subsystems.md`) and its in-progress MVP scope (issues #121–#125). Raw search exports retained at `lit_review/` (repo root, gitignored).

## 0. Why this review, and how to read it

Athena makes four architectural bets that are each, individually, testable against a body of prior work: (1) retrieval-grounded, narrow-domain LLM synthesis over broad general-purpose querying; (2) a hard citation-verification gate rather than trusting prompt-level source markers; (3) deterministic, non-agentic decision logic (Signal Generators, Diff Engine) with LLM synthesis confined to explanation/summarization, rather than autonomous multi-agent deliberation; (4) an event-sourced, append-only, diff-first case memory where the change-review screen — not chat — is the primary clinical interface. This review checks each bet against the literature, not to justify decisions already made, but to locate exactly where Athena is executing a validated pattern versus where it is making a genuinely novel and unvalidated claim. That distinction matters for the eventual paper: reviewers will accept "we applied known-good patterns to oncology" readily; "we invented an unstudied interaction paradigm" needs its own evaluation section to survive review.

The one-line finding, stated up front: **Athena's design choices are well aligned with where the literature is strongest** — narrow-domain retrieval grounding, deterministic/hybrid control, and verification-first architecture are all independently supported. **The one component with almost no direct precedent is the event-sourced, append-only, clinician-facing diff-based case memory** — which is either Athena's weakest evidentiary foundation or its most publishable novel contribution, depending on execution.

## 1. Oncology-specific RAG/LLM clinical decision support

The base rate question: does retrieval-augmented generation, scoped to oncology and to a single cancer type, actually outperform general-purpose LLM querying? Six systems bear directly on this.

| System / paper | Approach | Documented limitation |
|---|---|---|
| MEREDITH (Lammert et al., 2024, *JCO Precision Oncology*) | Gemini Pro + RAG + chain-of-thought over PubMed, trial data, drug approval status, guidelines; refined against molecular tumor board (MTB) feedback | High concordance with MTB recommendations (94.7%), but evaluated on only 10 fictional cases and partly on a proprietary institutional-access corpus |
| Context-augmented precision oncology LLM (Jun et al., 2026, *Cancer Cell*) | RAG-LLM using the MOAlmanac database + structured augmentation for biomarker-driven therapy retrieval | Strong synthetic (95%) and real-world (93%) accuracy, but authors frame it as deployment guidance rather than proof of clinical safety or outcome benefit |
| Breast-cancer open-source RAG benchmark (Park et al., 2026, *JCO Clinical Cancer Informatics*) | HTML-structure-preserving chunking over 1,356 ASCO breast guideline documents; tested GPT-4-turbo, GPT-3.5, Qwen2.5-14B, LLaMA3-8B, OpenBioLLM-8B with/without RAG | Small open-source models with RAG approached but did not match GPT-4 (rubric 3.77 vs 3.96); performance degraded sharply past top-5 retrieved contexts; human raters were more conservative than LLM-judge scores |
| Guideline-anchored gynecologic oncology benchmark (Dukes et al., 2026, *Gynecologic Oncology*) | GPT-5 + NCCN-anchored RAG vs. baseline GPT-5 and literature-only RAG | Guideline-anchored RAG outperformed both baselines, but the study is benchmark-only — no clinical safety or outcome evidence |
| DLBCL oncology RAG model (Soong et al., 2023, *PLOS Digital Health*) | Domain-specific RAG answering lymphoma biology/treatment questions vs. GPT-3.5/4 and Microsoft Prometheus | RAG model had higher accuracy/relevance; GPT-3.5/4 produced more nonexistent references and inaccurate answers, but the evaluation set was only 19 questions |

**Where Athena stands.** This is the strongest-supported bet in the whole architecture. Every paper in this area finds the same shape of result: retrieval grounded in a curated, domain-scoped corpus beats bare LLM querying, and the effect holds even for small open-weight models once retrieval is tight (Park et al., 2026) — directly validating both the single-cancer-type MVP decision (issue #121) and the open-source LLM plan (issue #122). The recurring caveat across all five studies — small case counts, benchmark-only evaluation, no prospective clinical outcome data — is not a criticism unique to Athena; it is the state of the entire field, and it means Athena's own eventual evaluation (the pre-committed gold set required by #121) would already be more rigorous than most published comparators if it includes real clinician review rather than LLM-judge scoring alone.

## 2. Citation hallucination and source-attribution failure

This is the literature base for the Citation Verification Gate (issue #9, extended by #124).

| System / paper | Approach | Documented limitation |
|---|---|---|
| McGowan et al., 2023, *Psychiatry Research* | Tested ChatGPT and Bard on citation generation for psychiatry literature search | Of 35 generated citations, only 2 were real in one test run — "spontaneous citation fabrication" |
| Chelli et al., 2024, *Journal of Medical Internet Research* | Compared GPT-3.5, GPT-4, Bard against 11 human-conducted systematic reviews (471 references) | Precision 9.4–13.4% (0% for Bard); hallucination rates 28.6–91.4%; concluded LLMs are not recommendable as primary systematic-review tools |
| Linardon et al., 2025, *JMIR Mental Health* | GPT-4o generating literature reviews across topics of varying visibility/specialization | 19.9% of 176 citations fully fabricated, 45.4% of "real" citations contained errors; fabrication risk rose specifically for less visible, more specialized topics |
| Gupta et al., 2024 (TREC 2024 BioGen Track), *arXiv* | Structured benchmark track for biomedical reference attribution | LLMs "often fail to reference relevant sources," especially on lay-user-phrased questions — unsupported statements framed as the primary barrier to health-domain LLM use |
| Med-V1 (Jin et al., 2026), *arXiv* | 3B-parameter model purpose-built for zero-shot biomedical evidence attribution/verification | Comparable to GPT-5 on attribution tasks at much lower cost, but citation validity remains sensitive to output-format instructions, and misattribution still occurs in guideline-adjacent high-stakes text |

**Where Athena stands.** The literature's finding that fabrication risk rises specifically in "less visible or specialized" topics (Linardon et al., 2025) is the single most load-bearing citation for Athena's whole premise: rare cancers, uncommon biomarkers, and off-label access questions are exactly that regime. This directly strengthens the argument already made in issue #124 — that #107/#108's `SOURCE_MARKER`/`CONTEXT_MARKER` fix is a prompt-level hint a real generative model can still ignore, and that a structural, enforced post-hoc check (`citation_gate.py` verifying against `Turn.sources`, not just trusting the prompt) is the architecturally correct response, consistent with what Gupta et al. (2024) and Jin et al. (2026) both converge on: verification has to be a separate, checkable step, not a property hoped for from prompting alone.

## 3. Multi-agent / "AI tumor board" systems

This is the literature that bears directly on the tumor-board decision already made this session (T–AF marked non-blocking, #73 comment, subsystems T–AF tracked as background research only).

| System / paper | Approach | Documented limitation |
|---|---|---|
| EvoMDT (Liu et al., 2026, *NPJ Digital Medicine*) | Self-evolving multi-agent system: domain agents + consensus protocol + retrieval scope that updates from expert feedback | Comparable decision quality to human MDTs, 30–40% faster, but authors themselves note it "remains a complex architecture whose real-world governance burden is part of the problem it tries to solve" |
| Tumor-board multi-agent LLM for HCC (Saenz et al., 2026, *Journal of Clinical Oncology*) | Three specialist personas (hepatology/oncology/radiology) + supervisor agent, RAG over AASLD/EASL/ESMO/BSG guidelines | Accuracy improved over single-call inference (+6.1 to +9.4 pts), but prospective validation on efficiency, guideline adherence, and patient outcomes is explicitly unstudied |
| MDAT gynecologic oncology (Kuerbanjiang et al., 2025, preprint) | Fixed-size multidisciplinary agent teams for complex cases | Structured consensus beat adversarial prompting, but prompt-strategy choice materially changed rankings — benchmarking was intentional, limiting deployment conclusions |
| Oncology MTB preparation study (Li et al., 2026, *CHI*) | Compared off-the-shelf assistant vs. task-specific multi-agent system, with oncologists in the loop | Oncologists preferred the task-specific system, but source links and agent reasoning trajectories failed to calibrate trust — summaries "still induced overconfidence" |
| OncoAgents + OncoGraph (Loaiza-Bonilla et al., 2026, *ESMO Real World Data and Digital Oncology*) | Neuro-symbolic multi-agent trial matching with deterministic graph checks, 3,804-patient prospective evaluation | Strong prospective results, but the benefit is attributed largely to separating LLM extraction from deterministic eligibility logic — not to free-form multi-agent deliberation itself |

**Where Athena stands.** This is the section that most directly vindicates the reversal made mid-session this project: the goal restated by the user ("only judgment and experience should remain the doctor's job — the system should remove memory burden") is in real tension with a multi-persona debate system, and the literature agrees for a different reason. Every gain reported for multi-agent oncology systems is attributed by the authors themselves to structure imposed *around* the agents — guideline retrieval, deterministic eligibility graphs, consensus protocols with fixed weights — not to the free-form multi-persona debate itself (most explicit in Loaiza-Bonilla et al., 2026, and echoed by EvoMDT's own authors). Li et al. (2026) is the sharpest warning: even when a multi-agent system performs well, exposing its reasoning trajectory to clinicians did not fix overconfidence — it can still mislead calibrated trust. This is the literature-grounded version of the argument already made informally: Athena's deterministic Signal Generator Layer (#6) plus Access Pathway Registry (#11) is functionally "the part of a tumor board that works" (structured, retrieval-grounded, auditable), without the part that doesn't (autonomous persona debate as the primary decision mechanism).

## 4. Deterministic vs. agentic clinical decision support

The architecture-level question underneath §3: when should an LLM's output be allowed to directly drive a clinical decision, versus constrained by a deterministic layer?

| System / paper | Approach | Documented limitation |
|---|---|---|
| KRD (Zhang & Chen, 2026, *Journal of Intelligent Medicine and Healthcare*) | Fact extraction + compiled knowledge + handwritten rule layer + decision interface, short-circuiting on hard safety violations | Reached the "hard-safety ceiling" with better evidence-trace completeness and lower reviewer burden than lighter hybrids, but the evidence gate was inert on this benchmark and failures clustered in the extraction step |
| AnemiaCare HD (Arriola-Montenegro et al., 2025, *Frontiers in AI*) | Deterministic prompt logic for protocol-bound anemia management | Loosely structured prompting reached only 32% protocol adherence; deterministic encoding reached 100% on simulated cases — but real-world/prospective validation is still missing |
| CPGPrompt (Deng et al., 2026, *JAMIA*) | Guideline narratives translated into decision trees traversed by structured yes/no LLM queries, fully logged | Binary referral decisions were strong; multiclass pathway assignment dropped, with negation and temporal reasoning as the key failure modes |
| Medi-Gemma (Quadri et al., 2026, *arXiv*) | Deterministic EMR analytics + RAG + intent routing + ground-truth-state injection + safety verifier | Built specifically to fix temporal inconsistency and structured-data hallucination in conventional RAG, but prospective multi-site validation remains future work |
| Neuro-symbolic report extraction (Prenosil et al., 2025, *Communications Medicine*) | GPT-4 candidate extraction + rule-based expert-system verification | Hybrid system matched physicians and intercepted residual identifiers — supports deterministic verification layers for sensitive workflows |

**Where Athena stands.** The consistent finding — a deterministic layer reaching near-100% adherence where loose LLM prompting reaches ~32% (Arriola-Montenegro et al., 2025) — is the direct empirical justification for keeping the Diff Engine (#5) and Signal Generator Layer (#6) fully deterministic rather than migrating any of that logic into LLM judgment calls, which nothing in this session's design has proposed but which is worth stating explicitly as a design constraint going forward. The recurring failure mode across CPGPrompt and KRD — errors clustering in extraction/negation/temporal reasoning, not in the deterministic core — also directly validates why Automated Case Intake (#19) treats extraction as strictly human-confirmed rather than auto-committed, and reinforces that the logged-but-not-built raw-document de-identification gap in #19 sits exactly at this failure-prone extraction boundary.

## 5. Event-sourced / diff-based clinical records — the sparse area

This is the literature underneath Case Memory (#4) and the Diff Engine (#5), and it is, honestly, thin.

| System / paper | Approach | Documented limitation |
|---|---|---|
| MedBeads (Nakajima, 2026, preprint) | Immutable "beads," patient-rooted Merkle DAG, reconstructable clinical links, append-only pods | Closest conceptual match to Athena found in this search; engineering feasibility tested only on synthetic data, no test of hallucination reduction or clinical outcomes |
| Noteless collaborative EMR (Steinkamp et al., 2020, *JMIR Formative Research*) | Single dynamic workspace organized by clinical problem, with granular version history | Demonstrates feasibility of non-note longitudinal state and change tracking, but is not an explicit append-only event-sourced architecture |
| Event-sourced systems schema-evolution study (Overeem et al., 2021, *Journal of Systems and Software*) | Cross-industry empirical study of 19 event-sourced systems | Core challenges: evolution, steep learning curve, tooling, rebuilding projections, privacy — but this is general systems literature, not clinician-facing oncology CDS |
| Baseline (Edwards & Petříček, 2025, *arXiv*) | Operation-based data version control with high-fidelity differencing across schema changes | Relevant for diff fidelity and schema evolution generally, but not clinical, and not focused on bedside review workflows |
| CQRS/event-sourcing architecture studies (Palamakula, 2026; Lytvynov & Hruzin, 2024/2025/2026) | Compliance-oriented and snapshot-centric CQRS/ES variants for audit and regulatory reporting | Articulate audit/replay trade-offs, but emphasize engineering complexity, causal ordering, and performance-maintenance trade-offs rather than clinician-facing diff UX |

**Where Athena stands — and this is the finding to lead the paper's contribution claim with.** There is essentially no literature on a clinician-facing interface where the *primary interaction loop* is reviewing a computed diff over patient state and evidence, as opposed to a chronological note timeline (Steinkamp et al.) or a backend audit log (Overeem et al.; Lytvynov & Hruzin). MedBeads (Nakajima, 2026) is the nearest analog and remains untested on real clinical outcomes or hallucination reduction. This means the design law already written into `RESEARCH_DIRECTION.md` — "chat hides the diff; the diff is the product" — is not validated prior art being applied to oncology; it is close to a novel interaction paradigm for this domain. That cuts both ways for the eventual paper: it is the strongest available novelty claim, but it also means Athena cannot cite precedent for "diff-first review improves clinician error detection" — that claim has to be earned by Athena's own evaluation, not borrowed from the literature. This should be treated as a first-class open research question in the paper, not a background assumption.

## 6. Open-source / self-hostable medical LLMs

Direct evidentiary base for issue #122.

| System / paper | Approach | Documented limitation |
|---|---|---|
| BioMistral (Labrak et al., 2024, preprint) | Open-source biomedical pretraining on PMC full text, multilingual benchmark release | Strong among open medical models, but frontier proprietary models still lead on many open-ended and reasoning tasks |
| MEDITRON-70B (Chen et al., 2023, *arXiv*) | Open 7B/70B Llama-2 adaptation with guidelines + PubMed pretraining | Competitive with GPT-4-class models but stays within ~5% of GPT-4 and ~10% of Med-PaLM 2 rather than surpassing them |
| PMC-LLaMA (Wu et al., 2024, *JAMIA*) | Open-source medical adaptation using 4.8M papers, textbooks, instruction tuning | Strong QA benchmark results, but benchmark gains don't guarantee oncology workflow safety or current-knowledge performance |
| Fully Open Meditron (Theimer-Lienhard et al., 2026, *arXiv*) | Fully open end-to-end pipeline, clinician-audited corpus, reproducible training | Fixes open-weight opacity, but is early-stage and mostly benchmark-based rather than evidence of oncology-specific deployment |
| Cross-model oncology benchmark studies (Longwell et al., 2024, *JAMA Network Open*; Warner et al., 2026, *arXiv*) | Cross-model benchmarks on oncology board-exam-style questions and clinical reasoning | Best proprietary models still outperform best open models on oncology exams; incorrect oncology answers carry "moderate-to-severe harm potential" |

**Where Athena stands.** The pattern here is a genuine trade-off, not a clean win: open-weight biomedical models (BioMistral, MEDITRON) are close enough to frontier proprietary performance to be viable for privacy-preserving, self-hosted deployment (directly supporting the `LLMClient` Protocol's model-agnostic design in `llm_client.py`), but "close" is not "equal" — Longwell et al. (2024) and Warner et al. (2026) both find open models still trail on oncology-specific reasoning, and incorrect answers there carry real harm potential. This is the strongest argument in the whole review for why Athena's open-source LLM should sit *behind* the Citation Verification Gate and Diff Engine rather than generate unconstrained clinical text — the deterministic scaffolding is not just an architectural preference, it is compensating for a documented, unresolved capability gap in the exact model class Athena plans to deploy.

## 7. Chat-first vs. structured-review-first clinical interfaces

Human-factors evidence for the App.jsx routing fix (issue #123) and for keeping chat secondary to the change-review screen generally.

| System / paper | Approach | Documented limitation |
|---|---|---|
| GutGPT / LLM-augmented CDSS trial (Rajashekar et al., 2024, *CHI*; Chan et al., 2023, *arXiv*) | Compared dashboard+LLM vs. dashboard+search in simulation | Improved ease-of-use, sometimes improved trust/mastery, but acceptance effects were mixed, not uniformly positive |
| Conversational XAI vs. dashboard (He et al., 2025, *IUI*) | Compared conversational explanation interfaces with dashboards | Understanding and trust improved, but over-reliance remained, and LLM-agent enhancements specifically *amplified* over-reliance |
| Automation-bias literature review (Romeo & Conti, 2025, *AI & Society*; Jovchevski et al., 2026, *Philosophy & Technology*) | Synthesis of overreliance experiments in AI-supported decisions | Explanations alone often fail to improve accuracy or mitigate automation bias — increased verification effort and "epistemic friction" are more promising interventions |
| Clinician trust / copilot studies (Stevens & Stetson, 2023, *JBI*; Zhu et al., 2026, *CHI*) | Trust instruments + interactive, visualization-first copilot studies | Trust is built through verification and interpretable visualization, favoring interfaces that support adversarial checking over passive acceptance |
| Direct automation-bias trial with physicians (Qazi et al., 2025) | Randomized physicians to correct vs. flawed ChatGPT-4o recommendations | Erroneous chat-style recommendations reduced diagnostic reasoning accuracy by 14 points, *even in AI-trained physicians* |

**Where Athena stands.** This is the direct evidentiary backing for issue #123, and it raises the stakes on it: Qazi et al. (2025)'s 14-point accuracy drop from erroneous chat-style advice, in physicians already trained on AI tools, is not a hypothetical risk — it is close to a description of what a chat-first landing page invites. He et al. (2025)'s finding that LLM-agent enhancements specifically *amplify* over-reliance (rather than being neutral) sharpens the case further: Athena's chat surface is exactly the kind of enhancement that risks that effect if it is the first thing a clinician sees, rather than a secondary, citation-gated layer reached from within a case's diff review. The literature's proposed mitigation — "epistemic friction" and interfaces built for adversarial verification rather than passive acceptance (Romeo & Conti, 2025; Stevens & Stetson, 2023) — is a good design lens to apply to the change-review screen's actual layout, not just its route priority.

## 8. Trial matching and access-pathway systems

Evidentiary base for the Access Pathway Registry (#11).

| System / paper | Approach | Documented limitation |
|---|---|---|
| TrialGPT (Jin et al., 2023, *Nature Communications*) | End-to-end LLM framework for patient-to-trial retrieval, criterion matching, ranking | Strong retrieval/ranking on synthetic cohorts with real screening-time reduction, but no prospective real-world oncology deployment in the original evaluation |
| TrialMatchAI (Abdallah et al., 2025, *Nature Communications*) | Open-source RAG + fine-tuned open LLMs + criterion-level eligibility reasoning | 92% of oncology patients had a relevant trial in the top 20, >90% criterion-level accuracy — but still requires expert assessment, and focuses on trials more than expanded-access pathways specifically |
| Australian lung-cancer trial matching (Alexander et al., 2020, *JAMIA Open*) | AI eligibility matching against clinician gold standard | Efficient and accurate prescreening, but clinician oversight remained necessary throughout |
| OncoAgents/OncoGraph prospective platform (Loaiza-Bonilla et al., 2026, *ESMO Real World Data and Digital Oncology*) | Multi-agent extraction + deterministic oncology knowledge graph, 3,804 patients | High F1 and efficiency gains, but strength attributed to neuro-symbolic constraint + clinician review, not autonomous LLM recommendation |
| Off-label/expanded-access frameworks: BELIEVE (Ishimaru et al., 2023, *Int. J. Clinical Oncology*), DRUP-style genomics-guided off-label (Verkerk et al., 2026, *Nature*), MTB frameworks (Rolfo et al., 2018, *ESMO Open*) | Structured, protocolized programs for post-standard-option access | Address the "no standard options remain" problem directly, but benefit is modest overall and works best in systematic programs, not ad hoc off-label use |

**Where Athena stands.** This is the section that most directly validates a specific, previously under-examined part of Athena's design: the *access-pathway* half of #11 (as distinct from ordinary trial matching) has real precedent in BELIEVE, DRUP, and MTB-framework literature, but that precedent consistently warns that benefit is "modest overall" and works best inside systematic, protocolized programs — not as an ad hoc recommendation surfaced by a general system. This is a meaningful scoping signal: Athena's Access Pathway Registry should be evaluated (and probably described in the eventual paper) as a *structured, protocol-anchored* pathway-matching tool in the lineage of BELIEVE/DRUP, not as a generic "find me options" feature — the literature's caution about ad hoc off-label suggestion applies directly to how permissive this subsystem should be by default.

## 9. Cross-cutting synthesis

Three patterns recur across all eight sections independently of which subsystem they bear on:

1. **Retrieval grounding, scoped narrowly, is the single most consistent source of measured improvement** across oncology LLM systems (§1, §6, §8) — and the effect holds even for small open-weight models once the retrieval corpus is tightly curated (Park et al., 2026), which is the strongest available justification for the MVP's single-cancer-type decision over broad multi-cancer coverage.
2. **No oncology system in this review relies on a bare LLM.** Every system that reports strong results combines retrieval with either structured metadata, ontology normalization, or deterministic logic that constrains what the model is permitted to say or do (Lammert et al., 2024; Loaiza-Bonilla et al., 2026; Quadri et al., 2026; Deng et al., 2026). Athena's Signal Generators, Diff Engine, and Citation Verification Gate are this exact pattern, applied consistently rather than partially.
3. **Citation fabrication risk is not a solved problem and is worse exactly where Athena's use case lives** — specialized, lower-visibility topics (Linardon et al., 2025), and the literature's own preferred mitigation is combined retrieval-plus-verification-plus-human-review (Basu & Huynh, 2026), not prompt-level fixes alone — directly supporting #124's argument that #107/#108's marker-based fix needs a structural, enforced backstop.

## 10. Design implications already reflected in this session's decisions

Two decisions made earlier in this project's issue-restructuring work turn out to have direct literature support that wasn't available at decision time:

- **Rejecting a multi-agent "AI tumor board" as the primary shipped mechanism** (tracked as non-blocking background research in #73, #75–#87) is supported, not just by the internal tension the user identified between a multi-persona board and the "remove memory burden, keep only judgment" goal, but independently by the literature: every multi-agent oncology system's measured gains are attributed by its own authors to added structure (retrieval, graphs, consensus protocols) rather than to free-form deliberation itself (§3), and at least one study found multi-agent reasoning trajectories failed to correct clinician overconfidence even when exposed (Li et al., 2026).
- **Making the change-review/diff screen the primary route, chat secondary** (issue #123) is supported by direct evidence that chat-style advice measurably degrades physician diagnostic accuracy when wrong (Qazi et al., 2025: −14 points, even in AI-trained physicians) and that LLM-agent-style interfaces specifically amplify over-reliance relative to plainer dashboards (He et al., 2025) — this is not just an internal design-law violation (`RESEARCH_DIRECTION.md`), it is a shipped configuration the literature would flag as a measurable risk factor.

## 11. Gaps and positioning — what to claim in the paper

**The single sparsest area, and the one to lead the contribution section with, is §5: event-sourced, append-only, clinician-facing diff-based case memory.** Adjacent literature exists (immutable clinical context graphs, general event-sourcing/CQRS architectures, non-note longitudinal EMR designs) but essentially nothing directly studies a clinical decision-support interface where reviewing a computed diff over patient state and evidence is the primary interaction loop. That sparsity should be treated as the paper's actual novelty claim — not "we built an oncology LLM system" (crowded, §1/§6/§8 show dozens of comparable projects), but "we applied a diff-first, event-sourced review paradigm — validated in software engineering but never in clinician-facing CDS — to oncology, with citation-gated LLM synthesis and deterministic decision logic behind it."

**The honest caveat that belongs in the paper's limitations section:** because §5 is sparse, Athena cannot cite precedent for its central UX claim ("diff-first review improves clinician error detection or trust calibration versus chat or dashboard review") the way it can for retrieval grounding or citation verification. That claim needs to be an explicit, first-class hypothesis tested in Athena's own evaluation (the pre-committed gold set required by #121), not an assumption inherited from related work. Everything else in the architecture — narrow retrieval, deterministic control, hard citation verification, structured access-pathway matching, open-weight models behind a verification gate — has direct, multi-paper support and can be cited as applying established best practice to a new domain rather than needing to be independently proven from first principles.

## References

Abdallah, M., Nakken, S., Georges, M., Bierkens, M., Galvis, J., Groppi, A., Karkar, S., Meiqari, L., Rujano, M. A., Canham, S., Dienstmann, R., Fijneman, R., Hovig, E., Meijer, G., & Nikolski, M. (2025). TrialMatchAI: An end-to-end AI-powered clinical trial recommendation system to streamline patient-to-trial matching. *Nature Communications, 17*. https://doi.org/10.1038/s41467-026-70509-w

Alexander, M., Solomon, B., Ball, D., Sheerin, M., Dankwa-Mullan, I., Preininger, A., Jackson, G., & Herath, D. (2020). Evaluation of an artificial intelligence clinical trial matching system in Australian lung cancer patients. *JAMIA Open, 3*, 209–215. https://doi.org/10.1093/jamiaopen/ooaa002

Arriola-Montenegro, J., Thongprayoon, C., Bizer, B., Miao, J., Ordaya-Gonzales, K., Craici, I. M., & Cheungpasitporn, W. (2025). A deterministic large language model (LLM) framework for safe, protocol-adherent clinical decision support: Application in hemodialysis anemia management (AnemiaCare HDs). *Frontiers in Artificial Intelligence, 8*. https://doi.org/10.3389/frai.2025.1728320

Basu, S., & Huynh, B. Q. (2026). Mitigating hallucinations in healthcare AI: A systematic review of evidence-based strategies. *BMC Health Services Research, 26*. https://doi.org/10.1186/s12913-026-14851-1

Chan, C. E., You, K., Chung, S., Giuffré, M., Saarinen, T., Rajashekar, N., Pu, Y., Shin, Y. E., Laine, L., Wong, A. H., Kizilcec, R. F., Sekhon, J. S., & Shung, D. (2023). Assessing the usability of GutGPT: A simulation study of an AI clinical decision support system for gastrointestinal bleeding risk. *arXiv, abs/2312.10072*. https://doi.org/10.48550/arxiv.2312.10072

Chelli, M., Descamps, J., Lavoué, V., Trojani, C., Azar, M., Deckert, M., Raynier, J., Clowez, G., Boileau, P., & Ruetsch-Chelli, C. (2024). Hallucination rates and reference accuracy of ChatGPT and Bard for systematic reviews: Comparative analysis. *Journal of Medical Internet Research, 26*. https://doi.org/10.2196/53164

Chen, Z., Cano, A. H., Romanou, A., Bonnet, A., Matoba, K., Salvi, F., Pagliardini, M., Fan, S., Kopf, A., Mohtashami, A., Sallinen, A., Sakhaeirad, A., Swamy, V., Krawczuk, I., Bayazit, D., Marmet, A., Montariol, S., Hartley, M.-A., Jaggi, M., & Bosselut, A. (2023). MEDITRON-70B: Scaling medical pretraining for large language models. *arXiv, abs/2311.16079*. https://doi.org/10.48550/arxiv.2311.16079

Deng, R., Martin, G., Wang, T., Zhang, G., Liu, Y., Weng, C., Wang, Y., Rousseau, J. F., & Peng, Y. (2026). CPGPrompt: Translating clinical guidelines into large language model-executable decision support. *Journal of the American Medical Informatics Association, 33*, 855–862. https://doi.org/10.1093/jamia/ocag026

Dukes, D., Yost, C., Wang, R., Diagne, Y. F., Garr, L., Yost, M., Owaka, J., York, M., Kang, P., Sookram, J., Huh, W., Loaiza, A., & Farley, J. (2026). Guideline-anchored retrieval-augmented generation outperforms baseline and literature-only configurations in gynecologic oncology decision support: A pre-integration benchmark. *Gynecologic Oncology, 211*, 224–230. https://doi.org/10.1016/j.ygyno.2026.07.005

Edwards, J., & Petříček, T. (2025). Baseline: Operation-based evolution and versioning of data. *arXiv, abs/2512.09762*. https://doi.org/10.48550/arxiv.2512.09762

Gupta, D., Demner-Fushman, D., Hersh, W. R., Bedrick, S., & Roberts, K. (2024). Overview of TREC 2024 Biomedical Generative Retrieval (BioGen) Track. *arXiv, abs/2411.18069*. https://doi.org/10.48550/arxiv.2411.18069

He, G., Aishwarya, N., & Gadiraju, U. (2025). Is conversational XAI all you need? Human-AI decision making with a conversational XAI assistant. *Proceedings of the 30th International Conference on Intelligent User Interfaces*. https://doi.org/10.1145/3708359.3712133

Hruzin, D., & Lytvynov, O. (2026). Engineering of software systems based on snapshot-centric CQRS with event sourcing architecture. *KPI Science News*. https://doi.org/10.20535/kpisn.2026.1.350992

Ishimaru, S., Shimoi, T., Sunami, K., Nakajima, M., Ando, Y., Okita, N., Nakamura, K., Shibata, T., Fujiwara, Y., & Yamamoto, N. (2023). Platform trial for off-label oncology drugs using comprehensive genomic profiling under the universal public healthcare system: The BELIEVE trial. *International Journal of Clinical Oncology, 29*, 89–95. https://doi.org/10.1007/s10147-023-02439-2

Jin, Q., Fang, Y., He, L. J., Yang, Y., Xiong, G., Wang, Z., Wan, N., Chan, J., Comeau, D. C., Leaman, R., Floudas, C., Zhang, A., Chiang, M. F., Peng, Y., & Lu, Z. (2026). Med-V1: Small language models for zero-shot and scalable biomedical evidence attribution. *arXiv, abs/2603.05308*. https://doi.org/10.48550/arxiv.2603.05308

Jin, Q., Wang, Z., Floudas, C., Sun, J., & Lu, Z. (2023). Matching patients to clinical trials with large language models. *Nature Communications, 15*. https://doi.org/10.1038/s41467-024-53081-z

Jovchevski, P., Buijsman, S., & Neerincx, M. A. (2026). What is wrong with automation bias? *Philosophy & Technology, 39*. https://doi.org/10.1007/s13347-026-01090-9

Jun, H., Tanaka, Y., Johri, S., Camp, S., Bao, E. L., Carvalho, F. L. F., Gui, D., Jordan, A. C., Labaki, C., Martin, S. A., Nagy, M., O'Meara, T. A., Pappa, T., Pimenta, E., Saad, E., Yang, D. D., Gillani, R., Tewari, A. K., Reardon, B., & Van Allen, E. V. (2026). A context-augmented large language model for accurate precision oncology medicine recommendations. *Cancer Cell, 44*, 676–685.e4. https://doi.org/10.1016/j.ccell.2025.12.017

Kanithi, P., Christophe, C., Pimentel, M. A. F., Raha, T., Saadi, N., Javed, H. A., Maslenkova, S., Hayat, N., Rajan, R., & Khan, S. (2024). MEDIC: Comprehensive evaluation of leading indicators for LLM safety and utility in clinical applications. *Transactions on Machine Learning Research, 2026*. https://doi.org/10.48550/arxiv.2409.07314

Kuerbanjiang, W., Wang, X., Jiamaliding, Y., Maimaitiaili, M., & Yi, Y. (2025). Multidisciplinary large language model agent teams for precision oncology enhance complex gynecologic oncology decision support. https://doi.org/10.1101/2025.10.30.25339199

Küper, A., Lodde, G., Livingstone, E., Schadendorf, D., & Krämer, N. (2024). Psychological factors influencing appropriate reliance on AI-enabled clinical decision support systems: Experimental web-based study among dermatologists. *Journal of Medical Internet Research, 27*. https://doi.org/10.2196/58660

Labrak, Y., Bazoge, A., Morin, E., Gourraud, P., Rouvier, M., & Dufour, R. (2024). BioMistral: A collection of open-source pretrained large language models for medical domains. *arXiv, abs/2402.10373*. https://doi.org/10.48550/arxiv.2402.10373

Lammert, J., Dreyer, T., Mathes, S., Kuligin, L., Borm, K., Schatz, U. A., Kiechle, M., Lörsch, A., Jung, J., Lange, S., Pfarr, N., Durner, A., Schwamborn, K., Winter, C., Ferber, D., Kather, J., Mogler, C., Illert, A. L., & Tschochohei, M. (2024). Expert-guided large language models for clinical decision support in precision oncology. *JCO Precision Oncology, 8*. https://doi.org/10.1200/po-24-00478

Li, J., Hall, A. K., Zhong, R., Everett, S., Unell, A., Xu, H., Blondeel, M., Carlson, J., Claveau, K., Jose, T., Naumann, T., Rhew, D., Sangani, N., Tuan, F., Weinstein, J., Mishra, V., Mynatt, E. D., Saponas, S., Qiu, H., ... Horvitz, E. (2026). Exploring the future of AI in clinical collaboration: A study on tumor board case preparation. *Proceedings of the 2026 CHI Conference on Human Factors in Computing Systems*. https://doi.org/10.1145/3772318.3790448

Linardon, J., Jarman, H. K., McClure, Z., Anderson, C., Liu, C., & Messer, M. (2025). Influence of topic familiarity and prompt specificity on citation fabrication in mental health research using large language models: Experimental study. *JMIR Mental Health, 12*. https://doi.org/10.2196/80371

Liu, Q., Hu, Z., Huang, T., Niu, Y., Zhang, X. S., Lin, C., Huat, G. K., Kwon, H. E., Gao, F., Sun, X., Ying, Z., & Qiang, G. (2026). EvoMDT: A self-evolving multi-agent system for structured clinical decision-making in multi-cancer. *NPJ Digital Medicine, 9*. https://doi.org/10.1038/s41746-025-02304-8

Loaiza-Bonilla, A., Yost, C., Kurnaz, S., Tuysuz, E., Thaker, N., Giritlioğlu, D., & Meza, J. N. P. (2026). Transforming oncology clinical trial matching through neuro-symbolic, multi-agent AI and an oncology-specific knowledge graph: A prospective evaluation in 3804 patients. *ESMO Real World Data and Digital Oncology, 12*. https://doi.org/10.1016/j.esmorw.2026.100706

Longwell, J. B., Hirsch, I., Binder, F., Conchas, G. A., Mau, D., Jang, R., Krishnan, R., & Grant, R. C. (2024). Performance of large language models on medical oncology examination questions. *JAMA Network Open, 7*. https://doi.org/10.1001/jamanetworkopen.2024.17641

Lytvynov, O., & Hruzin, D. (2024). Critical causal events in systems based on CQRS with event sourcing architecture. *Radio Electronics, Computer Science, Control*. https://doi.org/10.15588/1607-3274-2024-3-11

Lytvynov, O., & Hruzin, D. (2025). Decision-making on command query responsibility segregation with event sourcing architectural variations. *Technology Audit and Production Reserves*. https://doi.org/10.15587/2706-5448.2025.337168

Mayerhofer, K., Capra, R., & Elsweiler, D. (2025). Blending queries and conversations: Understanding tactics, trust, verification, and system choice in web search and chat interactions. *arXiv, abs/2504.05156*. https://doi.org/10.48550/arxiv.2504.05156

McGowan, A., Gui, Y., Dobbs, M., Shuster, S., Cotter, M., Selloni, A., Goodman, M., Srivastava, A., Cecchi, G., & Corcoran, C. (2023). ChatGPT and Bard exhibit spontaneous citation fabrication during psychiatry literature search. *Psychiatry Research, 326*, 115334. https://doi.org/10.1016/j.psychres.2023.115334

Nakajima, T. (2026). MedBeads: An AI-native clinical context graph built from immutable beads and reconstructable clinical links. https://doi.org/10.48550/arxiv.2602.01086

Öğdü, Ç. U., Arslanoğlu, K., & Karaköse, M. (2025). An adaptive multi-agent LLM-based clinical decision support system integrating biomedical RAG and web intelligence. *IEEE Access, 13*, 167390–167404. https://doi.org/10.1109/access.2025.3613340

Osama, M., Amjad, M., Mustansar, Z., Shaukat, A., & Khan, M. U. (2026). Trust but verify: Mitigating medical hallucinations via post-hoc adversarial auditing and multi-agent feedback loops. *arXiv, abs/2606.14149*. https://doi.org/10.48550/arxiv.2606.14149

Overeem, M., Spoor, M., Jansen, S., & Brinkkemper, S. (2021). An empirical characterization of event sourced systems and their schema evolution — Lessons from industry. *Journal of Systems and Software, 178*, 110970. https://doi.org/10.1016/j.jss.2021.110970

Palamakula, S. N. (2026). Unified event-sourced CQRS architecture for continuous compliance monitoring and automated regulatory reporting. *International Journal on Science and Technology*. https://doi.org/10.71097/ijsat.v17.i1.10094

Park, C., Park, I., Kim, M., Jang, Y., Lim, H., & Hur, Y. (2026). Can small open-source language models with retrieval-augmented generation match GPT-4 performance in breast cancer clinical decision support? *JCO Clinical Cancer Informatics, 10*. https://doi.org/10.1200/cci-25-00361

Prenosil, G., Weitzel, T., Bello, S., Mingels, C., Manzini, G., Meier, L., Shi, K., Rominger, A., & Afshar-Oromieh, A. (2025). Neuro-symbolic AI for auditable cognitive information extraction from medical reports. *Communications Medicine, 5*. https://doi.org/10.1038/s43856-025-01194-x

Qazi, I., Ali, P. A., Asad, P., Khawaja, U., Akhtar, M. J., Sheikh, M. A., Muhammad, M., & Alizai, H. (2025). Automation bias in large language model assisted diagnostic reasoning among AI-trained physicians. https://doi.org/10.1101/2025.08.23.25334280

Qiu, P., Wu, C., Liu, S., Fan, Y., Zhao, W., Chen, Z., Gu, H., Peng, C., Zhang, Y., Wang, Y., & Xie, W. (2025). Quantifying the reasoning abilities of LLMs on clinical cases. *Nature Communications, 16*. https://doi.org/10.1038/s41467-025-64769-1

Quadri, M. S. A., Xue, Y., Ady, J. W., & Roshan, U. (2026). Medi-Gemma: A hybrid clinical decision support system integrating deterministic EMR analytics and retrieval-augmented generation. *arXiv, abs/2607.04907*. https://doi.org/10.48550/arxiv.2607.04907

Rajashekar, N., Shin, Y. E., Pu, Y., Chung, S., You, K., Giuffrè, M., Chan, C. E., Saarinen, T., Hsiao, A., Sekhon, J. S., Wong, A. H., Evans, L. V., Kizilcec, R. F., Laine, L., Mccall, T., & Shung, D. (2024). Human-algorithmic interaction using a large language model-augmented artificial intelligence clinical decision support system. *Proceedings of the 2024 CHI Conference on Human Factors in Computing Systems*. https://doi.org/10.1145/3613904.3642024

Rolfo, C., Manca, P., Salgado, R., Van Dam, P., Dendooven, A., Rutten, A., Lybaert, W., Vermeij, J., Gevaert, T., Weyn, C., Lefebure, A., Metsu, S., Peeters, M., & Pauwels, P. (2018). Multidisciplinary molecular tumour board: A tool to improve clinical practice and selection accrual for clinical trials in patients with cancer. *ESMO Open, 3*. https://doi.org/10.1136/esmoopen-2018-000398

Romeo, G., & Conti, D. (2025). Exploring automation bias in human-AI collaboration: A review and implications for explainable AI. *AI & Society, 41*, 259–278. https://doi.org/10.1007/s00146-025-02422-7

Roustan, D., & Bastardot, F. (2025). The clinicians' guide to large language models: A general perspective with a focus on hallucinations. *Interactive Journal of Medical Research, 14*. https://doi.org/10.2196/59823

Saenz, E., Rodriguez-Mora, S., Daza, J., Arenas, S., Saavedra-Chacón, M., Espinoza-Herrera, Y. P. P., Turnes, J., Gómez-Aldana, A., & Teufel, A. (2026). Tumor board-based multi-agent LLMs with guideline retrieval and consensus deliberation: Implications for hepatocellular carcinoma clinical reasoning. *Journal of Clinical Oncology*. https://doi.org/10.1200/jco.2026.44.16_suppl.e16015

Salimparsa, M., Sedig, K., Lizotte, D., Abdullah, S. S., Chalabianloo, N., & Muanda, F. (2025). Explainable AI for clinical decision support systems: Literature review, key gaps, and research synthesis. *Informatics, 12*, 119. https://doi.org/10.3390/informatics12040119

Soong, D., Sridhar, S., Si, H., Wagner, J., Sá, A. C. C., Yu, C. Y., Karagoz, K., Guan, M., Hamadeh, H. K., & Higgs, B. W. (2023). Improving accuracy of GPT-3/4 results on biomedical data using a retrieval-augmented language model. *PLOS Digital Health, 3*, e0000568. https://doi.org/10.1371/journal.pdig.0000568

Steinkamp, J. M., Sharma, A., Bala, W., & Kantrowitz, J. J. (2020). A fully collaborative, noteless electronic medical record designed to minimize information chaos: Software design and feasibility study. *JMIR Formative Research, 5*. https://doi.org/10.2196/23789

Stevens, A. F., & Stetson, P. D. (2023). Theory of trust and acceptance of artificial intelligence technology (TrAAIT): An instrument to assess clinician trust and acceptance of artificial intelligence. *Journal of Biomedical Informatics, 148*, 104550. https://doi.org/10.1016/j.jbi.2023.104550

Theimer-Lienhard, X., El-Amin, M., Elhassan, F., Vaidya, S., Cartier-Negadi, V., Sasu, D., Klein, L., & Hartley, M. B. (2026). Fully Open Meditron: An auditable pipeline for clinical LLMs. *arXiv, abs/2605.16215*. https://doi.org/10.48550/arxiv.2605.16215

Verkerk, K., Spiekman, A. C., Verbeek, F. A. J., Timmer, H., Zeverijn, L., Geurts, B., Roepman, P., Jansen, A., Gelderblom, H., Verheul, H., & Voest, E. E. (2026). Prospective evaluation of genomics-guided off-label treatment. *Nature, 653*, 558–566. https://doi.org/10.1038/s41586-026-10405-x

Wang, J., Ning, H., Peng, Y., Wei, Q., Tesfai, D., Mao, W., Zhu, T., & Huang, R. (2024). A survey on large language models from general purpose to medical applications: Datasets, methodologies, and evaluations. *arXiv, abs/2406.10303*. https://doi.org/10.48550/arxiv.2406.10303

Wang, S., Tang, Z., Yang, H., Gong, Q., Gu, T., Wang, Y., Sun, W., Lian, Z., Mao, K., Jiang, Y., Huang, Z. L., Shen, W., Ji, Y., Tan, Y., Wang, C., Gao, Y., Ye, Q., ... Wu, J. (2025). A novel evaluation benchmark for medical LLMs illuminating safety and effectiveness in clinical domains. *NPJ Digital Medicine, 9*. https://doi.org/10.1038/s41746-025-02277-8

Warner, B., Grandhi, R. S., Kieffer, M., Ouraq, A., Panigrahi, S., Ambwani, G., Bagga, K., Khandekar, N., Hariharan, A., Mishra, N., Ram, M., Yang, S. S. Z., Essouaied, A., Moyondafoluwa, A. J., Scholz, R., Huang, B., Beavers, M., Gureja, S., Mahishi, A., ... Abraham, T. M. (2026). Medmarks: A comprehensive open-source LLM benchmark suite for medical tasks. *arXiv, abs/2605.01417*. https://doi.org/10.48550/arxiv.2605.01417

Wu, C., Lin, W., Zhang, X., Zhang, Y., Xie, W., & Wang, Y. (2024). PMC-LLaMA: Toward building open-source language models for medicine. *Journal of the American Medical Informatics Association*. https://doi.org/10.1093/jamia/ocae045

Zhang, B., & Chen, G. (2026). Knowledge-Rule-Decision: A loosely-coupled architecture for auditable high-stakes clinical decision support. *Journal of Intelligent Medicine and Healthcare*. https://doi.org/10.32604/jimh.2026.084876

Zhu, Y., Sui, D., Wang, Z., Hu, X., Gu, L., Qi, Y., Wu, T., Wang, L., Wei, Y., Tang, W., Cui, Z., Wang, Y., Yu, L., Harrison, E. M., Gao, J., & L. (2026). Augmenting clinical decision-making with an interactive and interpretable AI copilot: A real-world user study with clinicians in nephrology and obstetrics. *Proceedings of the 2026 CHI Conference on Human Factors in Computing Systems*. https://doi.org/10.1145/3772318.3791458
