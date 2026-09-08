# AAK-02 execution

## Purpose / Big Picture
Implement the pinned AAK specification/plan without creating a new requirements authority. External agents consume next_action through verified plans and owner persistence.

## Progress
- [x] Qualified all prerequisite owner candidates; AAK11 PR65 eight focused / 120 full / six evaluation checks PASS.
- [x] Isolated branch and canonical offline bootstrap prepared.
- [ ] Shared completion checks and bounded resumable native-owner dispatch.
- [ ] Required regression gates.
- [ ] Three modes, two real-agent runs each; synthetic continuation explicitly labelled.

## Surprises & Discoveries
The legacy worker path promotes Research COMPLETED directly to PLAN_READY. Three native stores use a bare Git root while the common profile uses a container. Preserve owner contracts through adapters.

## Decision Log
Use owner validators and immutable code/knowledge pins. No child schema or knowledge body is vendored into parent history. Keep completed stages and receipts after partial failure.

## Outcomes & Retrospective
Pending; live acceptance remains NOT_RUN.

## Context and Orientation
See pinned specification and implementation plan at b0e7c7f8d0a1f756fa708deef4fb380a62e45e0d, Issue197, owner verification reports and execution state.

## Plan of Work
Connect direct/worker completion, native store bootstrap/dispatch, and finite external-agent continuation. Validate failures, restart and actual six-run evidence.

## Concrete Steps
Run tests.test_knowledge_cycle_e2e, validator, full suite and diff check. Record each real agent run with source snapshots, validated plans, receipts and adopted reuse references.

## Validation and Acceptance
AC1/2 require live evidence; AC3/4/5 cover forged success, restart and independent statuses; AC6 forbids treating fake regression as live acceptance.

## Idempotence and Recovery
Run/profile/snapshot binding, stage hash verification, atomic state, finite lease and retry policy. Preserve native successful commits on index/other-owner failure.

## Interfaces and Dependencies
AAK05/06/07/09/11/12/13 and parent189/193/187 qualified candidates; current native commands remain authoritative. Public delivery and merge retain human gates.
