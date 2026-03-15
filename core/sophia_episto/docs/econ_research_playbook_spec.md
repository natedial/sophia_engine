# Econ Research Playbook Spec

## Purpose

The econ research system should answer broad macro questions using a structured plan rather than ad hoc tool calls.

Playbooks provide reusable analysis templates for recurring question families.

They should encode:

- how to decompose a question
- which indicators usually matter
- what transforms are required
- how to detect common failure modes
- where evidence is often missing or misleading

## Design Principles

- playbooks are reusable planning assets, not final-answer templates
- playbooks should operate on economic concepts first, series second
- playbooks should be swappable and versioned
- playbooks should be measurable through eval cases

## Authoring Boundary

Canonical playbooks belong in `core/sophia_episto/src/sophia_episto/playbooks/`.

Companion skills can help author or review them, but those skills should remain advisory. They can
provide templates, checklists, and operating workflows, but they should not become the runtime
source of truth for plan structure or policy behavior.

## Playbook Interface

Each playbook should expose:

- `playbook_id`
- `name`
- `description`
- `question_signatures`
- `required_concepts`
- `candidate_indicator_families`
- `planning_rules`
- `validation_rules`
- `failure_modes`
- `lesson_tags`

Recommended Python contract:

```python
class Playbook(ABC):
    playbook_id: str
    name: str
    description: str

    @abstractmethod
    def match(self, brief: QuestionBrief) -> float: ...

    @abstractmethod
    def draft_plan(self, brief: QuestionBrief) -> ResearchPlan: ...

    @abstractmethod
    def validate_plan(self, plan: ResearchPlan) -> list[str]: ...
```

## Initial Playbook Set

### `labor_vs_growth`

Primary use:

- questions about labor-market strength relative to GDP, growth, or demand resilience

Typical concepts:

- real GDP
- payrolls
- unemployment
- claims
- openings
- participation
- wages
- productivity

Common transforms:

- monthly to quarterly harmonization
- rolling averages
- year-over-year and quarter-over-quarter changes
- turning-point comparisons

Common pitfalls:

- inferring broad labor strength from payrolls alone
- ignoring frequency mismatches
- ignoring revisions
- mixing nominal and real growth stories

### `inflation_decomposition`

### `fed_reaction_function`

### `supply_term_premium`

### `cross_market_confirmation`

These can start as placeholders but should share the same artifact shape.

## Plan Construction

The planner should not jump directly from question to specific series ids.

It should move through these stages:

1. `QuestionBrief`
2. concept decomposition
3. playbook selection
4. hypothesis generation
5. candidate indicator family selection
6. capability check
7. acquisition decisions
8. analysis execution plan

## Example: `labor_vs_growth`

Question:

`How is the labor market aligning with the GDP strength of the past few quarters?`

Expected plan shape:

- subquestion: is labor confirming or diverging from GDP resilience?
- subquestion: are labor signals lagging, concurrent, or leading?
- subquestion: is the apparent strength broad or narrow?
- indicators:
  - real GDP growth
  - payroll growth
  - unemployment rate
  - initial claims
  - job openings
  - participation
  - wage growth
- transforms:
  - convert monthly labor series to quarterly comparison windows
  - compute recent trend vs prior baseline
  - highlight divergences and revisions
- validation:
  - at least one breadth indicator beyond payrolls
  - at least one deterioration/stress measure
  - explicit note on data frequency mismatch

## Lesson Integration

Playbooks should be able to request lessons by tag and class.

Example lesson classes relevant to playbooks:

- `methodological`
- `data_quality`
- `source_selection`
- `failure_mode`
- `regime_boundary`

Example lesson tags for `labor_vs_growth`:

- `labor`
- `growth`
- `harmonization`
- `revisions`
- `breadth`

## Capability and Acquisition Hooks

Playbooks must not fetch data themselves.

Instead, they should mark:

- preferred indicator families
- required freshness level
- acceptable substitutes
- acquisition permissibility

This allows the runtime to decide:

- whether local data is enough
- whether a gap should trigger acquisition
- whether to stop and answer with limitations

## Output Requirements

A playbook-driven analysis should produce:

- explicit conclusion
- key supporting datapoints
- areas of alignment
- areas of divergence
- caveats and contradictions
- source freshness/provenance notes
- note of any newly acquired evidence

## Eval Requirements

Each playbook should have a small eval suite with:

- canonical question variants
- expected indicator families
- forbidden shortcuts
- expected caveats
- acquisition allowed / disallowed scenarios

The initial success metric is not prose quality. It is plan quality and evidence completeness.

## Implementation Guidance

Start with:

- simple Python playbook classes
- explicit tests on plan construction
- one or two playbooks only

Do not start with:

- a giant ontology
- fully dynamic playbook generation
- unbounded agent-authored playbooks

## Versioning

Playbooks should carry version ids and changelog metadata so they can be A/B tested and optimized safely.

Recommended metadata:

- `playbook_id`
- `version`
- `owner`
- `status`
- `last_reviewed_at`

This is required for future optimizer workflows.
