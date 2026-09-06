# Issue #189 — Research pin qualification and interrupted AAK takeover

## Purpose / Big Picture

Resume the explicitly authorized AAK implementation from parent candidate
`b107b6db84c58e2fed4a952b7cf693211c7cf377`. Fix the existing Research pin
prerequisite without changing the pinned AAK specification or claiming final
live-agent acceptance. Requirements remain parent Issue #189 and AAK-SPEC/PLAN
at `b0e7c7f8d0a1f756fa708deef4fb380a62e45e0d`.

## Progress

- [x] Clone the complete remote history to a separate checkout and branch.
- [x] Register the existing #189 prerequisite and restore valid restart metadata.
- [x] Push registration `1c9b826` normally; preserve the old branch and its lease.
- [x] Install canonical repository-local dependencies and generate offline fixtures.
- [x] Qualify the exact Research candidate with the native pin qualification runner.
- [x] Apply qualified runtime pin changes, preserving historical evidence.
- [x] Parent repaired baseline: 588 tests PASS, 1 existing sibling-path skip (364.824s); the unchanged Research dry-run test also passed with an explicit real checkout.
- [x] Actual Production -> parent -> Project synthetic boundary PASS with canonical temporary paths.
- [x] Verify adopted real-workspace guards and final pin-sensitive regression (588 PASS, 2 environment skips; explicit owner checks run separately).
- [x] Publish implementation/evidence as stacked draft PR204; remote verified at 7110c1f07d0196a679d4aa6af17e5c75b1270839 before lease release.

## Surprises & Discoveries

The saved `project_status.py` entry point failed even though `validate.py` passed:
the resume task was absent from queue, the active task was DONE, and AAK-05/07
had no `blocker` field. The inherited README/handoff also preceded the latest
AAK work. Complete-history scanning crashed on a non-UTF-8 historical blob;
subprocess decoding now preserves undecodable bytes, with a real-Git negative
fixture proving credential-pattern detection is not skipped. macOS default
temporary aliases fail explicit non-symlink boundaries; checks use canonical
`TMPDIR=/private/tmp`, retaining those guards. Production requires PyYAML 6.0.2
and Art History Python 3.12; independent pre-provisioned environments preserve
each native requirement. Existing code verification is not reclassified as live integration.
GitHub process liveness is not observable through repository metadata. The user
explicitly transferred work; this continuation owns a separate branch and does
not clear or overwrite the old branch's lease. Network and keyring access work
outside the restricted shell; no credential value is persisted in evidence.

## Decision Log

Use canonical `qualify_pin_update.py` before adoption, not an unchecked pin
replacement. Check the whole declared manifest and Production exchange, with
Research at observed main and initially all other repositories at their existing pins.
Live guard observation then found three additional stale runtime pins (Self Model,
Production, Viewer); the canonical configured-branch candidate now qualifies those four
necessary updates together. Viewer follows the manifest-declared
`feat/viewer-response-contracts` branch, not an implicit switch to main. Art History and Marketing pins remain unchanged.
Keep the last qualified pin when any required gate fails. Keep canonical domain
content in its owner. All checks use isolated code or synthetic outputs.

## Outcomes & Retrospective

CODE_VERIFIED; AC1..3 PASS. Final pin-sensitive parent suite: 588 tests PASS (252.583 seconds), 2 environment-dependent skips. Exact child checks are run separately with explicit checkouts. First parent full run: 587 tests, 1 failure/30 errors/2 skips;
29 errors and the failure were canonical-temp boundary rejections, one error was
non-UTF-8 history decoding. After repairs: 588 tests PASS with one existing
sibling-path skip. Related AAK/profile/status checks: 44 PASS; binary history
positive/negative and real-history checks: 2 PASS. All first failures are retained
in external logs; no gate is skipped to manufacture a pass.

First child qualification: Research, Self Model, Marketing and Viewer PASS;
Production dependency preflight rejected shared PyYAML 6.0.3; Art History
rejected Python 3.14 (requires 3.12). Dedicated environments repair those
requirements. Production full tests exceeded the default 300 seconds; the
previous owner full-suite measurement is 490.816 seconds, so its targeted retry
has a finite 600-second command budget. Production retry passed (full suite 520.295 seconds; evaluation 103.055 seconds). All 16 native gates now PASS. Other successful gates are preserved.
Research/Production exchange at the configured-branch candidate is PASS.
The canonical adopted manifest passes the actual six-repository pin guard. The real run then reproduces existing Issue #203 (PROFILE_ROOT_REQUIRED); it is not reported PLAN_READY. Current task and precise restart action are in execution/state.yaml.
AAK-05 requires trusted-base registration; AAK-07 requires closed upstream
acceptance or a formally synchronized native contract. Project #6 requires
human-authorized real record migration. AAK-02 remains NOT_RUN.

## Context and Orientation

Parent #189; task `ISSUE-189-PIN-QUALIFICATION`; branch
`codex/aak-takeover-issue-189-20260906`, stacked on PR #202. Research source:
`masa-san-jp/agentic-art-research@71bfec77ea0d189186b8248565d340c124b81eab`.
The exact six-owner configured-branch candidate and four changed pins are captured by the native
qualification report; no AAK feature candidate is relabeled as main.

## Plan of Work

Observe candidate -> immutable child gates and exchange -> guarded adoption ->
parent regression -> reviewable evidence. The old AAK functional candidates are
preserved. Blocked owner work is not silently promoted or bypassed.

## Concrete Steps

Use README bootstrap/offline preparation, then:

```sh
.venv/bin/python tools/qualify_pin_update.py --workspace-root <isolated-workspace> --output <external-report> --run-id ISSUE-189-TAKEOVER-20260906
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/project_status.py --check-readme
git diff --check
```

## Validation and Acceptance

AC1: Research manifest pin matches read-only remote main observation.
AC2: Real Research checkout passes the run pin guard; report other-owner blockers
separately and never call a blocked whole workspace ready.
AC3: Required native child qualification/exchange and parent checks pass.
Record PASS/FAIL/NOT_RUN against the exact commits, not PR existence.

## Idempotence and Recovery

Preserve completed candidates, successful evidence and the old branch. No reset,
force push, merge, deletion, real data migration or public projection. Publish
execution SSOT by normal push before releasing this branch's lease. If blocked,
keep the pin unchanged and record the exact failed command and remediation.

## Interfaces and Dependencies

`tools/qualify_pin_update.py`, `tools/child_quality_gates.py`, `tools/run.py`,
`tools/project_status.py`, parent manifest and retrieval fixture. Child code is
read-only. No Drive artifacts are created; opaque artifact references: none.
Explicit feedback: implement the authorized takeover. Inferred feedback: none.
