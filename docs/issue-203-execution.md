# Issue203 — Forward the external Self Model profile root

## Purpose / Big Picture

The now-qualified real workspace reaches signal ingestion, but the parent cannot
pass Self Model's required external profile root. Issue203 is the requirements
SSOT. Add the explicit option at the parent entry and exporter boundary so an
agent can supply an already-authorized profile. Never adopt a repository profile
or fabricate one when the option is missing.

## Progress

- [x] Read the actual Issue203, parent runtime and tests, and Self Model AGENTS §4.1.
- [x] Confirm no overlapping Issue203 PR; register the existing issue as READY.
- [x] Claim this branch's lease before implementation.
- [x] Implement forwarding and stable BLOCKED before any real exporter when missing.
- [x] Verify literal argument boundaries, no side effects on blocked reads, offline regression, and actual synthetic owner export.
- [x] Parent full595 PASS/1 environment skip (explicit Research dry-run PASS), validator/diff PASS; draft PR206, code 4f4b82226f4da828bf5f7051723658eeab2c1231.

## Surprises & Discoveries

Self Model main `a61460d4f9add36b256b2db9a860c53a98bd5fcd` requires
`self-model-profile/v1` under an explicit absolute external root. Its repository
fallback is disabled. The parent currently lacks any way to pass that root and
returns FAILED after invoking the exporter. This is independent of the trusted-base
AAK-05 registration gate; fixing the call path does not bypass that gate.

## Decision Log

Keep this parent-only. Add optional `--profile-root` to `run.py` and
`ingest_signals.py`; pass it only to Self Model. Let the owner validate profile
schema, consent and storage boundaries. Do not resolve aliases or invent a profile.
For missing input, return BLOCKED with a stable reason before exporter invocation
or run-state creation. The explicit offline path continues to use only synthetic
fixtures. Do not pass personal configuration to other owners or store it in Git.

## Outcomes & Retrospective

FOCUSED_CODE_VERIFIED: 38 focused tests PASS (2.388s). Actual owner synthetic profile exports 2 valid signals; alias/repository roots are rejected. Actual six-owner preflight reaches BLOCKED/exit2 without creating run state when profile is missing. First full suite: 595 tests, 1 error / 1 environment skip. The legacy automatic-theme fixture lacked the newly explicit profile root; supply its synthetic root without changing the guard or theme behavior. Final full verification PASS: 595 tests in 258.189s, 1 environment skip separately covered. Code 4f4b82226f4da828bf5f7051723658eeab2c1231 is in draft PR206. All four Issue203 ACs PASS; main/AAK02 integration remain NOT_RUN. Issue189's six-owner pin guard
passes. The existing AAK candidate PRs and human gates remain unchanged.

## Context and Orientation

Task `PROFILE-ROOT-FORWARD-001`, Issue203, isolated branch
`codex/issue-203-profile-root-20260906`, based on PR204 head `c81d14f`.
Files: `tools/ingest_signals.py`, `tools/run.py`, adjacent tests, README/runtime
guide, and execution records. Self Model code/data/schema are read-only.

## Plan of Work

Register -> claim -> extend CLI and boundary -> targeted positive/negative tests
-> actual owner export with its own synthetic profile fixture -> full parent
regression -> reviewable evidence and draft PR -> reevaluate eligible AAK work.

## Concrete Steps

```sh
.venv/bin/python -m unittest tests.test_ingest_signals tests.test_run -v
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/project_status.py --check-readme
git diff --check
```

Use README's canonical environment and offline bootstrap. All temporary roots
must be canonical real paths, retaining owner symlink rejection.

## Validation and Acceptance

AC1: explicit root reaches only Self Model's exporter, including literal spaces.
AC2: missing root yields BLOCKED/exit2 before exporter or output mutation.
AC3: the public run CLI carries the option through the ingest boundary.
AC4: offline fixture execution succeeds without reading any real profile.
Include an actual Self Model export from the owner's synthetic fixture; this is
code verification, not real Masa or live-agent AAK-02 acceptance.

## Idempotence and Recovery

Claim only the isolated branch. Preserve previous candidates and successful
evidence. Record code commit, acceptance and next action in state/handoff. Publish
execution SSOT normally before releasing the lease. No merge, default-branch
push, real profile migration or public projection is authorized here.

## Interfaces and Dependencies

Depends on qualified Issue189 runtime pins. Self Model owns external profile
validation; parent owns argument forwarding and early blocking. No Drive artifact
is created. Explicit feedback: authorized takeover. Inferred feedback: none.

## Updated next dependency observation

Parallel Project PR12 (`8e4c90b701c82bfe14964dbbe6a0aba62342fcef`) supersedes the old PR11 migration blocker. Native validator/catalog and 20 tests PASS, independently repeated here; actual parent/Production/Project boundary PASS (4.356s). Parent PR205 is a new main-based alternative to PR202, not an automatic replacement of this pinned AAK stack. After publication and lease release, promote/claim AAK13 using the exact qualified Project12 candidate. No migration or merge was performed by this continuation.
