# Issue 280 — Phase A theme elements

Scope: orchestration A2–A7 and the private Self Model element relay. The assigned
isolated branch is `agent/280-phase-a-theme`. The orchestrator owns all remote
writes, PR, merge and Issue closure; the implementation agent makes local commits.
No execution lease is acquired in this isolated clone.

SSOT: [element harness design](20261007-element-harness-design.md), chapters 2–4.
Reuse Issue 278's Engine, contracts, registration, answer CLI and retry mechanism.
Do not add a second inference executor or embed a model.

## Decisions

- Enumerate every nonempty content item exported in `self_model`. Consent flags,
  scope and the opaque raw voice locator are transport metadata, not materials.
  Prefer least-used materials across runs with an accepted A3 sharing the external state
  root; ties use optional intent-term overlap, then attribute, text and signal ID; retain only the normalized intent hash. Selection is frozen per run.
- Match operation terms deterministically against complete art statement,
  fixes/varies/requires and relation targets, and market statement/evidence basis.
  Read actual evidence sections and relation target labels from immutable public owner blobs when older exports carry only opaque locators; retain blob hashes and source commits. Use literal Latin words and Japanese character shingles; score their overlaps,
  break ties by signal ID. Do not use hashes to choose the theme.
- Preserve sourced draft methods as unknown-validity seeds, as in the existing method boundary; do not promote them to verified facts. Self Model unknown freshness is retained, not treated as market expiry.
- Evaluate each pair as one boolean/reason element. Within each k-sized window,
  prefer primary evidence/count, then matching order among positive connections.
  Widen only the missing domain. Preserve negative reasons and block on exhaustion.
- The native RR schema is closed and owned by Research. Keep it unchanged. Attach
  a create-only structured provenance sidecar through `source.artifact_uri` and
  `references`; the native security contract rejects file URIs/absolute paths, so name the adjacent sidecar and use its hash URN. It contains the selected material, immutable sources, both A5
  reasons and the exact A7 question. This is a source artifact, not a new RR field.
- Live production defaults to elements. Explicit offline fixture and the legacy
  bundle API retain their existing compatibility contract. They are not live
  Phase A acceptance. Owner stage B–D implementation is outside Issue 280.
- Probe the child `growth_tasks.py element --help`; unsupported old pins retain
  their native hearing. Stream supported requests as `private: true` and answers
  directly to owner stdin. Save only progression metadata. Never save packet,
  instruction, Event or hearing answer in parent state/logs.
- Synthetic integration exercises both fake and hand-authored answers against
  read-only qualified owner code. It does not establish artistic quality for the
  real owner. Owner confirmation with the real profile remains a separate unmet
  completion condition, as the supplement forbids using that data in this task.

## Verification and handoff

Run the supplied Python interpreter for the validator, README status, related
suite and complete unittest discovery. Compare all named failures/errors to exact
`origin/main` under the same generated-input conditions. Retain failure evidence;
do not label failed gates as PASS. Run native synthetic-profile ingest, resume
through A7, validate the RR with the pinned Research owner and check child Git
status before/after. Verification evidence contains no local absolute paths.

First operation after handoff: inspect `git show --stat HEAD`; review evidence and
both synthetic questions. No next implementation task is claimed. Do not mark
Issue 280 fully complete until the owner accepts a meaningful real-profile question.

Native verification found that a real public ARK URL was rejected by the pinned receiver's absolute-path rule. Alias only clean public HTTP(S) references with colon/slash in their path to a hash URN, retain the exact original/alias mapping in the structured sidecar, preserve rights status, and leave query/fragment references for native security checking. Use a new run/artifact after this fix; never overwrite the failed probe's create-only outputs. Freeze optional intent after material selection and remove its text from subsequent run reports.


## Child hearing contract integration (follow-up)

Use the finalized Self Model Issue 138 owner contract, without copying its schemas or
private state into the parent. Relay next/answer/respond/confirm/skip through the child
runtime with run-id, purpose and optional Subject. HEARING, CONFIRMATION and
SEED_REQUIRED expose one private owner question; WAITING exposes one private element.
Save only private/status/run-id/element-id/attempt. Child skip is authoritative; a
rejected operation reacquires next rather than fabricating a transition. BLOCKED
remains a resumable stop. COMPLETED or SKIPPED resumes the same run through Phase A.

The direct credential-free run entry opens/reacquires private hearing before ingest.
Write metadata before adding the transient next_action to stdout. Test the child
branch in a temporary exact-pin workspace using a temporary manifest Self Model pin;
restore the production manifest before quality gates. Original owner clones are
read-only. Record both owner question and A7 only from synthetic inputs.
