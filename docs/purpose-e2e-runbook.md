# Purpose E2E runbook

This runbook verifies the final purpose boundary: one new, non-sensitive theme can be carried through selection, research handoff, autonomous supervision, and a production plan without an unrecorded human choice or external side effect.

The theme used by this run is `透明な境界を往復する光`. It is a synthetic input only. The literal theme is hashed at the intent boundary and is not stored in evidence, Git, self-model, Drive, or the conversation archive.

## Networkless qualification

First produce a fresh child-gate report against a clean, exact manifest-pinned workspace. The gate runner uses temporary immutable clones and never writes to a child checkout:

```bash
python3 tools/child_quality_gates.py \
  --manifest config/repositories.yaml \
  --workspace-root <verified-child-workspace> \
  --python-root <child-environment-root> \
  --timeout 300 \
  --run-id PURPOSE-E2E-001:child-gates \
  --output /tmp/purpose-e2e-child-gates.json
```

The report must have `PASSED` for every repository. A `NOT_RUN`, `ENV_UNSATISFIED`, `FAILED`, dirty, stale, or mismatched result is retained as a blocker and cannot be converted to a pass.

Run the deterministic fixture three times with separate Git-external state roots. Reusing a validated gate report is explicit:

```bash
python3 tools/purpose_e2e.py --offline-fixture \
  --attempt-id fixture-1 \
  --quality-gates-report /tmp/purpose-e2e-child-gates.json \
  --output /tmp/purpose-e2e-fixture-1.json
python3 tools/purpose_e2e.py --offline-fixture \
  --attempt-id fixture-2 \
  --quality-gates-report /tmp/purpose-e2e-child-gates.json \
  --output /tmp/purpose-e2e-fixture-2.json
python3 tools/purpose_e2e.py --offline-fixture \
  --attempt-id fixture-3 \
  --quality-gates-report /tmp/purpose-e2e-child-gates.json \
  --output /tmp/purpose-e2e-fixture-3.json
```

`--check` validates an already written evidence file. The canonical hashes must match after excluding only runtime timestamps and attempt-scoped IDs. The fixture's personal anchors are labelled fixture-only; they must never be copied into the live lane.

Each successful production output now includes the child-owned visual package beside `production-plan.yaml`: a viewable `visual-reference-board.svg`, a conceptual/simulated `concept-mockup.svg`, and `visual-package.yaml`. The parent evidence keeps only the package metadata, source repository and commit, opaque run locators, media type, content hashes, and rights/safety states. It verifies both relative links from `production-plan.md` and the file hashes. Missing files, broken links, tampered hashes, missing provenance, or unknown rights/safety stop the run; SVG bodies remain in the explicitly supplied Git-external output root.

## Live-private qualification

Use a clean workspace whose six repository heads exactly match `config/repositories.yaml`. The workspace and per-child Python environments are supplied by the operator; no checkout is repaired by this tool:

```bash
python3 tools/purpose_e2e.py --live-private \
  --attempt-id live-1 \
  --workspace-root <verified-child-workspace> \
  --child-python <production-child-python> \
  --quality-gates-report /tmp/purpose-e2e-child-gates.json \
  --confirm-private-run \
  --output /tmp/purpose-e2e-live-1.json
```

The live lane exports only the child-defined normalized signal contracts, creates a new research project in Git-external staging, and retains only hashes and opaque run locators in parent evidence. It does not publish, submit, send, purchase, contract, create Drive artifacts, create GitHub Issues, merge, release, or physically produce anything.

If the actual self export has no eligible `tensions`/`recurring_patterns` anchor, or selection rejects all candidates, the lane stops with the observed reason. One or two eligible anchors are accepted as `PASS_LIMITED_DIVERSITY`; three or more receive full diversity controls. Do not add synthetic anchors to make live evidence pass. Resolve a zero-anchor condition in the self-model/research source of truth, obtain a new pinned commit through the normal qualification flow, and rerun with a new attempt ID.

## Required final checks

```bash
python3 -m unittest tests.test_purpose_e2e tests.test_run tests.test_autonomous_runner -v
python3 tools/validate.py --check
python3 -m unittest discover -s tests -v
python3 tools/workspace.py status
python3 tools/audit.py
```

Inspect each repository's Git status and the child-gate report separately. A successful terminal is `PLAN_READY`; merge, tag, release, and any external artifact remain human-approved operations outside this run.
