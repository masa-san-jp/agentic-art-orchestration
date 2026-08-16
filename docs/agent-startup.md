# Startup capability matrix

`tools/startup.py` returns one overall startup status and a separate decision for each capability. The overall status describes the knowledge and answer lane; it does not mean that every capability shares one gate.

| Startup result / finding | Qualified read | Parent `branch` / `commit` / `pull_request` | External create | Child or update mutation | `merge` / `release` / `tag` |
| --- | --- | --- | --- | --- | --- |
| `READY` | `ALLOWED` | `ALLOWED` | `ALLOWED` | `BLOCKED` | `BLOCKED` (human gate) |
| any noncritical finding (`WARNING`) | `ALLOWED` against the qualified pin | `ALLOWED` for control-plane repair | `RESTRICTED` | `BLOCKED` | `BLOCKED` (human gate) |
| critical finding (`credential`, `PRIVATE_RAW`, `RESTRICTED`, `consent_violation`, `schema_major_mismatch`) | `BLOCKED` | `BLOCKED` | `BLOCKED` | `BLOCKED` | `BLOCKED` |

`remote_update_candidate` means that a remote default branch moved beyond the qualified snapshot. Startup never adopts that commit, changes a pin, checks out, pulls, or pushes. Any `READY_WITH_FINDINGS` report whose findings are all noncritical (`WARNING`) may use a parent control-plane branch, commit, or draft PR to repair the finding; it must continue to use the qualified snapshot and must pass the normal review gates. An explicit nonempty finding is required.

`RESTRICTED` is an explicit stop for the capability, not permission to infer or bypass a gate. Child repository mutation, Drive update/delete/share, GitHub Issue update/close/delete/comment/label, and all merge/release/tag operations remain blocked. Merge, release, and tag always require human approval.

Verify the decision with:

```sh
.venv/bin/python tools/startup.py --offline-fixture
.venv/bin/python tools/startup.py --offline-fixture --check
```

For a clean checkout, materialize the deterministic offline inputs before running the full suite:

```sh
.venv/bin/python tools/workspace.py init --offline-fixture
.venv/bin/python tools/workspace.py snapshot
.venv/bin/python tools/audit.py --offline-fixture
.venv/bin/python tools/github_issue_adapter.py --fixture --plan
.venv/bin/python tools/interaction_e2e.py --offline-fixture
```

The report is metadata-only. It must not contain credentials, raw conversation, raw remote responses, Drive content, or direct identifiers.
