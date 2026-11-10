# Sophia research and causal-engine refactor plan

Date: 2026-10-07  
Status: proposed implementation plan; revised for outside-agent ownership; no runtime changes made  
Target: `/Users/ncdial/devwork/sophia_engine-causal-foundation-hardening`

## Decision and intended outcome

Reuse Sophia's Episto, Arithmos, and Oikonomia foundations. Make research and causal modeling the primary product. Check usage, then retire unrelated assistant, coding, channel, and dashboard features. Keep Analyst and Sophia entirely separate, with independent packages, storage, deployment, and release cycles. An outside agent uses their public interfaces and owns the research agenda. Do not create another world-model repository, merge Sophia into Nexus, or embed the outside agent in either system.

The product should explain what sources believe, the mechanisms they propose, where explanations differ, what observations discriminate between them, and which assessments have changed. Numerical intervention or counterfactual answers are available only when a particular model explicitly supports them.

The first deliverable is a small, inspectable workflow:

```text
Analyst public interface <── outside research agent ──> Sophia public interface
 claims + source evidence      questions, proposals,     cases + hypotheses,
                               test requests,            evidence + assessments,
                               interpretations           runs + explanations
                                                                │
                                                  Episto contracts and state
                                                  Oikonomia run coordination
                                                  Arithmos numerical methods
                                                                │
                                                  Scrivener data snapshots
```

One source of truth per record type: Analyst owns extracted author claims; Scrivener owns economic observations; Episto owns mechanism hypotheses, accepted evidence records, and assessment history; Oikonomia owns execution and publication records. The outside agent selects questions, retrieves claims, proposes mechanisms and tests, interprets results, and communicates findings. Sophia persists the research case so another agent can resume it.

The agent transports immutable, attributed evidence bundles through Sophia's source-neutral interface. Neither system imports the other's models, reads the other's database, or polls the other. Source snapshots in Sophia support reproducibility; they are not a second editable claim store. Sophia does not require Analyst to be online to inspect an existing case, and Analyst does not depend on Sophia to complete analysis.

## Findings driving the refactor

- Episto currently combines domain models, numerical methods, graph persistence, and batch execution. `causal_service.py` overlaps Oikonomia's execution responsibility.
- `causal/graph.py` repeatedly blends existing values even without new evidence. A checked initial edge changed from 0.7 to 0.56 after one empty-evidence update.
- `hypothesis/generator.py` allows `mark_validated({})` and sets confidence to 1.0. Discovery inserts edges into the active graph before generating their proposed hypotheses.
- Graph identity is `(source, target)`, preventing distinct mechanisms with the same endpoints from being represented independently.
- `causal/inference.py` correctly calls its calculations heuristic. Those calculations are still exposed through causal-effect names and percentage-style outputs.
- Episto and Arithmos both contain numerical effect-size/statistical code. Episto's package requires NumPy, SciPy, and statsmodels, and its causal exports eagerly import discovery/evaluation modules.
- Arithmos' Granger entry point can substitute a univariate test when source input is missing or malformed. That changes the question being tested and must become an explicit input error.
- The default Compose stack starts unrelated UI/agent services and defaults Tholos semantic dependencies on. Its corpus mount still refers to the old research-store layout.
- Oikonomia already provides run records, immutable model inputs, promotion reviews, and publication states. Reuse those facilities; model deployment status and epistemic support remain different concepts.

These observations describe this checkout, including its existing uncommitted changes. Deployment usage is not yet verified. Episto's current virtual environment lacks pytest; do not assume an existing green test baseline.

## 1. Set ownership and remove duplication

| Component | Disposition | Concrete change |
|---|---|---|
| `core/sophia_episto` | Keep and narrow | Own contracts, durable research cases, mechanism identity, evidence requirements, applicability, assessment history, and explanation queries. Validate agent submissions and enforce permitted uses. No research-agenda agent, statistical execution, network clients, or autonomous scheduler. |
| `services/sophia_arithmos` | Keep; consolidate numerical code here | One implementation of preprocessing, Granger/predictive tests, effect estimates, robustness checks, and optional identification methods. Importable library first; HTTP wrapper optional. |
| `services/sophia_oikonomia` | Keep as the sole test-run coordinator | Execute explicit test requests with immutable input snapshots, retries, run deduplication, method versions, and publication eligibility. Absorb Episto's execution plumbing; the outside agent chooses research questions and which tests to request. Deployment eligibility does not establish epistemic support. |
| `services/scrivener` | Keep | Supply dated observations and data vintages. Do not rebuild acquisition in Episto. |
| `services/sophia_tholos` | Retain only as needed for corpus retrieval | The outside agent owns research-source retrieval. Tholos is optional tooling for verified external consumers, never a required engine dependency or a Sophia-to-Analyst bridge. Its index is rebuildable. Retire if unused; fix legacy mounts only for retained consumers. |
| `services/sophia_pylon` | Narrow, then remove if redundant | Expose a small public Sophia command/API surface for outside agents. Retain routing only for verified consumers; do not add an Analyst-specific client or require Pylon for local evaluation. |
| Episto `world_model/`, `entities/`, `causal/edge.py` | Consolidate overlapping identities | One variable/entity catalog and one mechanism contract. Static relationships and expert priors become attributed hypothesis seeds; no parallel authoritative graph. |
| Episto `hypothesis/` | Keep concept; replace lifecycle | Evidence-based assessments and permitted-use rules replace validated/rejected certainty shortcuts. |
| Episto `causal/inference.py` | Retire from public causal-answer APIs | Keep graph traversal only for explaining proposed paths. Remove scalar path-product answers and set-value propagation from claims of causal effect. |
| Episto `optimizer/` | Remove unconnected stub after caller check | `AutoresearchAdapter` is a reserved stub, not a required research capability. No self-modification loop in this scope. |
| Episto playbooks and planner | Keep the useful small subset | Retain declarative method requirements and test-question templates that an outside agent can inspect. Retire engine-owned agenda selection and general assistant planning/intake paths after adapting existing callers. |
| Episto/Prima lessons and conversational memory | Remove from causal authority path | Migrate demonstrably useful methodological notes as attributed annotations. Personality or conversation memory never counts as empirical support. |
| Prima, Forge, Canvas, dashboard, Telegram/chat tooling | Usage check → retire | Remove from causal runtime immediately; migrate any required review/inspection workflow to CLI/structured reports before deleting consumers and deployments. |
| Kampe and Sentry | Conditional domain extensions | Preserve if another verified workflow needs curves or watches. Otherwise retire; neither is required to prove the first causal workflow. |

Before deletion, inspect imports, tests, entry points, container builds, schedules, tool registries, stored artifacts, and external consumers. Record a disposition for each surface. Use Git history for retired source rather than maintaining a duplicate archive tree. Preserve user-authored assets and data exports separately.

## 2. Replace the central contracts

Use a small number of versioned contracts, with runtime validation at ingestion boundaries. Reuse the existing Pydantic ecosystem rather than adding another schema library.

| Record | Minimum content |
|---|---|
| `ResearchCase` | Stable ID/revision, research question and scope, artifact references, proposed/pending/completed work, decisions and unresolved questions, submitting actor, and resumable history. Chat transcript is not canonical state. |
| `SourceClaimRef` | Source-system namespace, immutable document/claim revision or content hash, source claim occurrence ID, author/publisher, published and captured times, exact evidence locations, qualifications, snapshot hash, and provenance verification status. Provider-specific parser/analysis versions are optional metadata. |
| `AgentProposal` | Stable ID, case/hypothesis revision, submitting agent identity, proposed mechanism/test/interpretation, cited evidence/result IDs, assumptions, and rationale. An agent interpretation remains distinct from a source claim and from a calculated result. |
| `VariableSpec` | Stable ID, observable definition, units, geography/entity, frequency, transformations, and links to source series. Concept labels such as “policy” are not sufficient measurement definitions. |
| `MechanismHypothesis` | Stable ID/revision; cause/effect variable references; proposed sign, lag, channel, conditions/regime; alternatives; source claims; expected observations and potential falsifiers. Unknown values remain explicit. |
| `EvidenceAssessment` | Unique contribution ID, hypothesis revision, evidence type, independence group, supporting/challenging/non-diagnostic assessment, justification, method/assumptions, provenance, assessed time. |
| `EmpiricalResult` | Run ID, input snapshot/vintage/hash, time window, transformations, method/version, estimand or predictive question, signed estimate and units where applicable, uncertainty interval, diagnostics, failures, scope limitations. |
| `HypothesisAssessment` | Engine-recorded status, contributing evidence/result/proposal IDs, unresolved alternatives, applicability, revision history, allowed uses, and governing policy version. Record agent-authored judgments as such; structural validation does not turn an interpretation into a verified fact. |

Sophia validates reference integrity, required assumptions, result types, revision compatibility, and method-specific permitted uses. It cannot establish the truth of arbitrary agent reasoning merely by validating its schema. Unverified source provenance or unresolved identification assumptions remain visible and restrict promotion. Keep author agreement, predictive skill, identified causal evidence, and applicability separate. Do not combine p-values, explained variance, expert confidence, and mechanism truth into a single “probability.” Introduce a numeric belief only with a documented model and calibration procedure.

Epistemic depth is a set of justified capabilities, not a counter that rises with popularity. A hypothesis can be predictive yet causally unidentified. A reviewed qualitative mechanism can be useful without an estimated effect size.

Preserve competing channels. For example, supply pressure raising term premium and weaker growth lowering yields can coexist; opposing net forecasts do not automatically contradict both mechanisms.

## 3. Make updates durable and replayable

- Replace mutable `graph.json` as canonical state with a repository interface and durable evidence/assessment records. Use SQLite for the initial single-worker proof, consistent with Oikonomia's existing store. Keep storage injected; add a PostgreSQL adapter only when shared deployment requires it. This is not a migration of Nexus's canonical claims back to SQLite.
- Write evidence acceptance and the resulting assessment revision in one transaction. Enforce uniqueness on contribution IDs, idempotency keys, and run-input fingerprints. Replaying the same source bundle or empirical result must not strengthen or weaken a hypothesis. Require an expected case/hypothesis revision for mutations; stale concurrent proposals return a conflict instead of overwriting newer work.
- Record data revisions and claim supersession explicitly. New information creates a new assessment; it does not silently rewrite historical conclusions. Preserve both event time and when the system could have known the evidence.
- Represent mechanisms as identified records with scope and version, allowing multiple mechanisms between the same variables. Derive graph views from them.
- Separate successful computation from evidence interpretation and from eligibility to publish. A failed or unavailable test yields a typed failure/unavailable result, never an all-negative conclusion or successful validation.
- Retain `graph.json` only as an export/import format. Import old edges as `legacy_unassessed` candidates, retain original scores as legacy metadata, and do not promote them automatically.

## 4. Consolidate methods and trim libraries

| Dependency/surface | Target disposition |
|---|---|
| NumPy, SciPy, statsmodels | Arithmos owns their causal/statistical use. Remove from Episto's required dependencies after numerical code moves. Other genuine consumers retain their own explicit requirements. |
| FastAPI, uvicorn, pydantic-settings | Optional API/runtime dependencies where possible. Importing Episto contracts or running an in-process numerical method must not start or import a web app. |
| Pydantic | Shared contract-validation choice; maintain one compatible major-version policy, not a new wrapper framework. |
| DoWhy, pandas for its adapter | Optional Arithmos extra with explicit method availability. Retain only if the first scoped evaluation needs it. Remove Episto's implicit runtime import; do not silently claim a refutation ran when the dependency is absent. |
| causal-learn / PC discovery | Defer/remove from the initial supported runtime. Restore as an explicit extra only with a concrete use case, documented assumptions, and tests. It is currently imported optionally rather than declared as a required package. |
| sentence-transformers and its transitive ML stack | Retrieval extra only; turn off default semantic installation in the minimal profile. Keep only if measured retrieval benefit justifies it. No embedding stack in Episto. |
| Anthropic/Groq SDKs, Telegram, prompt-toolkit, Pillow, conversational gateway tooling | Remove with retired Prima workflows after import/consumer checks. Hypothesis proposal and interpretation providers belong to the outside agent. Sophia's engine has no mandatory LLM provider or SDK. |
| React/Vega/Amplify dashboard packages; Canvas ORM/auth/WebSocket stack | Remove with UI retirement after migrating required inspection functions. This does not remove SQLAlchemy or database clients still used by Scrivener. |
| requirements files duplicating pyproject declarations | Choose pyproject as package dependency authority; generate deployment requirements where necessary. Keep package install/test boundaries and reproducible lock files. Do not manufacture a new root application. |

Use the statsmodels implementation as the canonical Granger path. Remove duplicate numerical implementations and approximate probability fallbacks after reference tests establish parity on valid inputs. Missing or mismatched source data must fail explicitly instead of becoming an autoregression test.

Preserve timestamps, frequency, lag units, and vintages end to end. Remove fabricated dates and tail-alignment by list length. Statistical tests must declare their observation window and preprocessing. Time-series robustness checks must preserve the dependence relevant to the method; resampling paired rows is not automatically evidence of causal stability.

Optional methods fail visibly when unavailable. A two-variable refutation configured with no common causes is not a general causal-identification gate. Method-specific assumptions and unresolved confounding must appear in the result.

## 5. Outside-agent research protocol

Expose two independent surfaces. Analyst provides source-claim/evidence retrieval; Sophia provides source-neutral research-case, hypothesis, test, assessment, and explanation operations. The outside agent is the only workflow coordinator between them. Its implementation, hosting, provider, and conversation UI are outside this refactor.

Use a versioned JSON protocol with CLI commands first and an optional thin HTTP/tool adapter over the same handlers. Do not introduce a broker, autonomous feed, shared database, shared runtime-model package, or a dedicated Nexus-to-Sophia service.

| Sophia operation | Responsibility and response |
|---|---|
| `capabilities` | Enumerate available methods, input requirements, permitted question types, protocol versions, and unavailable optional dependencies. |
| `open_case` / `get_case` | Create or resume the durable question, scope, hypotheses, work state, and artifact history without requiring an agent transcript. |
| `submit_evidence` | Accept a generic source bundle; validate identity, immutable snapshot/hash and references; deduplicate contributions; return IDs and verification limitations. |
| `propose_hypothesis` | Record an agent-authored mechanism with scope, alternatives, evidence links, and falsifiers. Return a candidate, never an automatically accepted causal fact. |
| `request_test` / `get_run` | Validate a specified question, method and input snapshot; execute through Oikonomia/Arithmos; return a durable run ID, typed result, assumptions and diagnostics. |
| `propose_assessment` | Record the agent's interpretation against cited results and evidence. Apply engine-owned method/promotion rules and return the recorded status, unmet requirements, and allowed uses. No unrestricted validated/confidence setter. |
| `explain_case` | Return structured mechanisms, evidence, alternatives, applicability, permitted uses, open questions, and changes. Distinguish source statements, computed results, and agent interpretations. |

Names above describe the proposed contract, not existing commands. Mutations include protocol version, submitting actor, case/hypothesis revision and idempotency key. Responses carry stable IDs, revisions and typed errors. Long-running tests return run IDs; an agent can disconnect and another can resume without duplicating work.

The outside agent retrieves claims from Analyst, preserves their original attribution and qualifications, and submits a generic evidence bundle. Exact source passages or immutable snapshots support independent engine validation; a bare model-generated citation is not enough to establish source fidelity. If the engine cannot verify a source, it records that limitation rather than silently upgrading trust.

Existing Analyst `claim_key` is a semantic grouping key, not a unique source-claim occurrence ID. A source-side export helper or outside-agent adapter may construct a versioned occurrence reference from immutable document/analysis identity and claim location. Changed source analysis produces a new revision and supersession link. Such transport helpers contain no hypothesis policy and are not imported by Sophia.

Do not make modifications to Analyst a prerequisite for refactoring Sophia. Prove the engine contract with generic fixtures and then exercise it through an outside-agent harness against Analyst's available interfaces. Any Analyst retrieval/export improvements are separate package-owned changes. Its completion/retry defect remains an independent upstream reliability issue; an external workflow should detect missing source output rather than treating it as negative evidence.

The agent can use Sophia's explanation in a response or pass it to another downstream tool. Dispatcher integration is an optional external consumer, not an engine-owned publication workflow. The same case protocol must work with a non-Analyst evidence source.

## 6. Implementation sequence and exit criteria

| Phase | Work and principal files | Exit criterion |
|---|---|---|
| 0 — Baseline and scope | Record current uncommitted changes; inspect actual consumers/deployments; install declared dev tooling; baseline Episto/Arithmos/Oikonomia tests; inventory data, dependencies, and public entry points used by outside agents. | Keep/remove inventory names consumers and data dispositions. Failures are recorded; existing user work is preserved. |
| 1 — Contracts and dependency boundary | Refactor Episto edge/hypothesis models; add research-case, proposal, variable, source-reference, evidence, and assessment contracts; remove eager numerical exports; adapt existing callers. | Episto imports/tests without NumPy, SciPy, statsmodels, FastAPI, provider credentials, or network access. Multiple scoped mechanisms between the same endpoints are retained. |
| 2 — Evidence ledger and honest updates | Replace graph blending and certainty shortcuts; implement transactional repository and legacy importer; add assessment queries. | Empty input and replay leave assessments unchanged; crash/retry cannot duplicate evidence; old graph imports do not become validated facts. |
| 3 — One execution/method path | Move numerical methods to Arithmos; adapt Oikonomia for hypothesis-test requests; retire Episto batch runner and singleton persistence; remove numerical fallbacks. | An explicit outside request runs from immutable dated inputs to a persisted typed result with method/version/assumptions. Disconnect/retry does not duplicate execution. Failures remain visible. No implicit promotion. |
| 4 — Outside-agent vertical slice | Implement the public CLI protocol and a scripted external client; retrieve Analyst claims through its public surface, submit generic bundles, propose hypotheses/tests/assessments, and resume with a second client. | Both systems work independently. A second agent resumes without the first transcript. Every conclusion is traceable; a non-Analyst fixture works unchanged. No cross-repo imports, database access, or automatic feed. |
| 5 — Retirement and minimal deployment | Delete confirmed-unused services/features, adapters, registrations, manifests, build contexts, and schedules; migrate remaining required consumers; update docs and locks. | The research workflow runs without Prima, Forge, Canvas, dashboard, Telegram, semantic ML, PC discovery, or an engine-side LLM. Outside-agent provider choices remain independent. No dangling references to deleted services. |

Phases 1–4 establish the replacement before destructive retirement. Independent dependency isolation can happen earlier. Use small reviewable changes: contracts; ledger; computations; execution; public protocol and external-client proof; retirement. Do not mix mass deletion with a change in inferential semantics.

## Acceptance scenario and tests

First case: an outside agent retrieves attributed research from Analyst and opens a Sophia case about whether an inflation surprise changes the expected policy path. The agent proposes competing mechanisms and requests a supported test, then submits its interpretation of the returned result. Sophia records the case and enforces evidence requirements; it does not retrieve Analyst records or autonomously select the agenda. Define the jurisdiction, measure, surprise baseline, horizon, and competing growth explanation explicitly. A signed association/predictive test may be a legitimate initial result; it must remain labeled as such if causal identification is unavailable.

Exercise at least these cases:

1. Two authors cite the same release: two attributed views, one underlying evidence event for independence accounting.
2. Two opposing mechanisms act on one outcome: preserve both and distinguish mechanism disagreement from net-forecast disagreement.
3. Same input delivered twice, or the worker restarts: identical assessment and one completed contribution.
4. A revised data vintage arrives: new reproducible result and assessment history; previous as-of explanation is still retrievable.
5. A source citation is invalid or a method is unavailable: explicit unresolved/failed state with no promotion.
6. An empirical result supports predictability but leaves confounding unresolved: useful bounded explanation, no intervention claim.
7. The user asks an unsupported counterfactual: return the missing assumptions/data/model capability rather than a path-product number.
8. The agent attempts to promote a claim using persuasive prose without required evidence: retain the proposal and return unmet requirements without granting unsupported causal status.
9. The first agent stops; a second resumes from case/run IDs alone: retrieve evidence, decisions, pending runs, and unresolved questions without losing attribution or rerunning completed tests.
10. Two clients submit against different revisions: reject stale mutation explicitly; replaying a valid idempotency key returns the original result.
11. Sophia processes a generic non-Analyst evidence fixture; Analyst runs with Sophia unavailable; Sophia explains a saved case with Analyst unavailable: independent lifecycle is preserved.

Gate the first release on correct attribution, preserved conditions, evidence deduplication, reproducibility, explicit epistemic status, and reviewer usefulness versus a plain source summary. Record latency and resource use; set numeric budgets from the first representative workload rather than inventing targets now.

## Migration and rollback

Snapshot existing graph JSON, hypothesis artifacts, and relevant stores before modifying persistence or retiring services. Preserve hand-authored hypotheses and expert priors even if their old confidence values are not adopted. Re-derive cache/index views; do not delete original research or unique observations.

Keep the old command available until its required callers use the replacement, then remove it rather than maintaining two authority paths. For a failed rollout, restore the saved store/config and prior code revision. Do not reset this checkout's existing uncommitted work. Deployment shutdowns follow the Phase 0 usage inventory; no deployment changes are part of writing this plan.

## Deliberately excluded from the first release

An embedded research agent, a direct Analyst-to-Sophia feed, a shared claims database, graph-wide causal discovery, a general counterfactual simulator, automatic expert-certainty scoring, autonomous code modification, a new dashboard, a new graph database, a broker, and a new retrieval/LLM framework. Each future addition needs a concrete supported question and an evaluation showing value.

## Source references

- [Original causal-world-model proposal](2026-04-15-causal-world-model.md).
- [Episto ownership specification](../../../core/sophia_episto/docs/episto_architecture_spec.md).
- [Current graph/update implementation](../../../core/sophia_episto/src/sophia_episto/causal/graph.py).
- [Current hypothesis lifecycle](../../../core/sophia_episto/src/sophia_episto/hypothesis/generator.py).
- [Current batch/service implementation](../../../core/sophia_episto/src/sophia_episto/causal_service.py).
- [Arithmos numerical entry points](../../../services/sophia_arithmos/src/sophia_arithmos/computations/causality.py).
- [Oikonomia existing lifecycle](../../../services/sophia_oikonomia/README.md).
- Nexus ownership constraints: `/Users/ncdial/devwork/nexus/docs/phase-0-decisions-and-inventory.md` and `/Users/ncdial/devwork/nexus/docs/2026-09-20-suite-rationalization-plan.md`. Treat their deployment inventory as historical until rechecked.
