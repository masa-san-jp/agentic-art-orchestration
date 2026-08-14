# Startup capability matrix

`tools/startup.py` returns one overall startup status and a separate decision for each capability. The overall status describes the knowledge and answer lane; it does not mean that every capability shares one gate.

| Startup result / finding | Qualified read | Parent `branch` / `commit` / `pull_request` | External create | Child or update mutation | `merge` / `release` / `tag` |
| --- | --- | --- | --- | --- | --- |
| `READY` | `ALLOWED` | `ALLOWED` | `ALLOWED` | `BLOCKED` | `BLOCKED` (human gate) |
| only `remote_update_candidate` | `ALLOWED` against the qualified pin | `ALLOWED` for control-plane repair | `RESTRICTED` | `BLOCKED` | `BLOCKED` (human gate) |
| other noncritical finding | `ALLOWED` against the qualified pin | `RESTRICTED` | `RESTRICTED` | `BLOCKED` | `BLOCKED` (human gate) |
| critical finding (`credential`, `PRIVATE_RAW`, `RESTRICTED`, `consent_violation`, `schema_major_mismatch`) | `BLOCKED` | `BLOCKED` | `BLOCKED` | `BLOCKED` | `BLOCKED` |

`remote_update_candidate` means that a remote default branch moved beyond the qualified snapshot. Startup never adopts that commit, changes a pin, checks out, pulls, or pushes. A parent control-plane repair may create a branch, commit, or draft PR so the finding can be resolved; it must continue to use the qualified snapshot and must pass the normal review gates.

`RESTRICTED` is an explicit stop for the capability, not permission to infer or bypass a gate. Child repository mutation, Drive update/delete/share, GitHub Issue update/close/delete/comment/label, and all merge/release/tag operations remain blocked. Merge, release, and tag always require human approval.

Verify the decision with:

```sh
.venv/bin/python tools/startup.py --offline-fixture
.venv/bin/python tools/startup.py --offline-fixture --check
```

The report is metadata-only. It must not contain credentials, raw conversation, raw remote responses, Drive content, or direct identifiers.
