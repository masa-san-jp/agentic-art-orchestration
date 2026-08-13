# Initial Codex / Claude Code interface

`tools/agent_ui.py` is the repository-native entry point for the first conversational operations profile. Codex or Claude Code can call it without asking the user to identify child repositories or perform Git operations.

The command accepts structured intent and capability metadata. Raw conversational text is transient and is not an input to the persisted result. Retrieval selects the minimum relevant qualified repositories and the result keeps `repository@commit`, evidence IDs, freshness, gaps, and domain constraints.

## Safe default

The default is networkless planning:

```sh
.venv/bin/python tools/agent_ui.py --offline-fixture
.venv/bin/python tools/agent_ui.py --offline-fixture --check
```

This runs startup, retrieval, feedback routing, a Drive create-only plan, and a GitHub Issue create-only plan. It performs no remote operation, stores no Drive content, and does not create or update an Issue.

The complete initial-operations regression is:

```sh
.venv/bin/python tools/initial_operations_e2e.py --offline-fixture
.venv/bin/python tools/initial_operations_e2e.py --offline-fixture --check
```

It proves startup and pinned retrieval, one Drive CREATE followed by idempotent read-back/replay, explicit versus inferred feedback, and one Issue CREATE followed by deduplicated REUSE. Its `live_gate` remains `NOT_REQUESTED`; a real operation is a separate human-confirmed step.

The output is `data/agent-ui.json`, which is ignored by Git. It contains only structured metadata and opaque references. Do not copy raw prompts, conversation text, artifact bodies, credentials, signed URLs, or direct provider identifiers into a tracked file.

## Explicit operations

The operation boundaries are independent:

```sh
# Networkless Drive create/read proof
.venv/bin/python tools/agent_ui.py --offline-fixture --artifact-mode live --confirm-drive

# Networkless Issue create/deduplicate proof
.venv/bin/python tools/agent_ui.py --offline-fixture --issue-mode live --confirm-issue
```

For a real Drive sandbox, set `AGENTIC_ART_APPROVED_DRIVE_FOLDER_ID` and `AGENTIC_ART_GOOGLE_DRIVE_TOKEN` outside Git, review the folder retention policy, and pass `--artifact-mode live --confirm-drive`. The bridge searches the idempotency marker first, creates only a new file in the approved folder, and reads back metadata or content hash. It never updates, overwrites, deletes, moves, shares, or changes permissions.

For a real GitHub Issue, provide `GITHUB_TOKEN` or `GH_TOKEN`, review the allowlist and candidate, and pass `--issue-mode live --confirm-issue`. The adapter searches by the stable deduplication key, then creates at most one Issue. It never updates, closes, deletes, comments, labels, implements, branches, commits, opens PRs, merges, or releases.

The initial-operations qualification uses a separate sandbox lane, not the normal Issue allowlist. Set `AGENTIC_ART_APPROVED_GITHUB_SANDBOX_REPOSITORY=owner/name` and provide `GITHUB_TOKEN` or `GH_TOKEN` outside Git. Verify that the repository is dedicated, non-archived, has Issues enabled, and is not one of the production repositories. Then run:

```sh
.venv/bin/python tools/github_sandbox_live_check.py --live --confirm-live --output /tmp/github-sandbox-live-evidence.json
.venv/bin/python tools/release_check.py --version 1.4.0 --runs 3 --workspace-root <verified-child-workspace> --github-sandbox-evidence /tmp/github-sandbox-live-evidence.json
```

The sandbox command searches first, creates at most one metadata-only Issue, then retries the post-create search with the bounded policy schedule (`2s → 4s → 8s → 16s`, at most five searches) before recording reuse. It refuses production repositories and existing ambiguous matches; the evidence file contains hashes and operation metadata only. If the search index still has no single match at the bound, it remains `BLOCKED` and does not claim qualification. Do not run the command against an experiment or production repository by inference.

If startup is `READY_WITH_FINDINGS`, the answer remains pinned and read-only; external CREATE capabilities stay restricted. If startup is `BLOCKED`, affected capabilities stop and the remediation in the startup report is authoritative.
