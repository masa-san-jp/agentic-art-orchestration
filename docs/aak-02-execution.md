# AAK-02 execution

## Purpose / Big Picture
Implement the pinned AAK specification/plan without creating a new requirements authority. External agents consume next_action through verified plans and owner persistence.

## Progress
- [x] Qualified all prerequisite owner candidates; AAK11 PR65 eight focused / 120 full / six evaluation checks PASS.
- [x] Isolated branch and canonical offline bootstrap prepared.
- [x] Shared completion checks and bounded resumable native-owner dispatch implemented; final qualification in progress.
- [x] Required regression gates: f940 full602 PASS, one Research environment skip independently PASS; focused13 and validator PASS.
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

## Integration observations (2026-09-08)

Native bootstrap/query passed all eight real owner CLIs with explicit synthetic profile/catalog inputs. Fixed code-source vs destination boundary and exact single-repo staging. The parent native index must be rebuilt before querying an empty store. First parent full run: 600 tests, four old worker-status assumptions failed and two environment skips. Those status assumptions now preserve Research completion separately, and real private plan validation joins the owner verifier. No live-agent acceptance is claimed by these regressions.

Parent candidate 2057ccca19a6bc9ae5ce86863abaf0aad811f211 passed 602 full tests (one Research environment skip independently passed against the actual candidate). A native Marketing prepare probe reproduced FUTURE_OBSERVATION with the initial run clock and VALID with the actual write clock. The integration now records immutable per-operation write clocks separately from the initial search clock; requalify this delta before final acceptance.

Frozen f940 runtime is executing three actual LLM-agent pairs under `/private/tmp/aak02-live-20260908`. PR208 preserves the implementation. AC1/2 remain unqualified until the six native plans and knowledge-adoption traces are inspected.

Actual agents found a Research role-authoring dead end, local locator conflict and derived-output snapshot cycle. Separate owner PR97 at465aa4c940aa93912739d22de2c994a4ba342f4b repairs only those contracts. Owner full311/55focused and native gates PASS. All original attempts are retained; qualified-one/two runs start with actual-source Art History setup knowledge and the explicit repaired pin. Parent runtime remains frozen atf940.
