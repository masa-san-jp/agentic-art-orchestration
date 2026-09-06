# Issue193 execution checkpoint

## Purpose / Big Picture

Require Production attestation/v1 and its pinned owner validator for automatic
projection/v2. Preserve exact Markdown/attestation/assets and stable ID/revision.
No Production headings or semantic schema is copied into the parent.

## Progress

Current qualification: `4b41f6da2b73e23de1c0a439aebc77f8d78c8247`, standalone
588 tests PASS/1 independently covered skip; combined downstream595 PASS.
Native Project reader failure was reproduced, then fixed with unwrapped scalar
output. PR205 delta is retained; actual Git binary history checks remain intact.
Production63 + Project13 are the current owner candidates. Exact input refs and
log hashes: `execution/issue-193-integration-verification.json`.
Earlier observations below are historical, including Project11 migration failures.


Historical start: PUBLIC-PROJECTION-ATTESTATION-001, branch
agent/issue-193-attested-projection, parent candidate ecfa00f71957c4c04e052ea3a7574f042c8ab6f0.
Native intake qualified the actual Issue after mechanical heading synchronization;
registration was committed separately. Production PR63 code
d323b92ffef34fc80b2e0c47daa1b8acff40368a is fixed in an exact isolated checkout,
with 104 full tests, 11 focused tests and validator/evaluation PASS.

## Surprises & Discoveries

Project #6 PR11 passes six synthetic receiver tests but its existing public
records require authorized migration; it is not fully qualified. Current run and
batch producers do not expose owner attestation refs. Missing clearance must
block projection while retaining the internal plan, not synthesize approval.

## Decision Log

Use existing automatic producer authority and destination resolution. Reuse target
transaction/CAS rollback code. Keep private output and code checkout paths out of
public records. Owner validation executes only from explicit qualified checkout.
Actual Project records, public writes, merge and release remain gated.

## Outcomes & Retrospective

Issue193 synthetic acceptance: owner validation and Project receiver boundary PASS;
34 focused tests PASS (6.539s), including actual Production CLI and Project code,
eight negative owner-source cases, byte equality, replay, revision conflict,
stable IDs, reserved IDs, 100-record ordering and transactional rollback.
Final code: local 8bcbbb78475fa4ac03896839c48395aaacc53721, remote
2b1787a3bfd995582075a4723747528781a18df2, identical full tree
9b41d0797e957388a81331ef22d3d4dced7a6c24. Draft PR202.
Final full suite: 587 PASS, zero skips, 126.520s; validator/diff PASS.
Full log SHA256 b2c53cfc1d11d9cb1a097c34c27b42c969ea2ce9f16cb18ae796d35446c23245.
Actual owner fixture input: Production local f904c70 (remote evidence tree alias
69567e88131e3f033d010791fb5849e1b2ebff8d), Project local 70ccaa6 (remote
939411c72aa8cdc77a4831170f2d049126e24b4f). Both were clean dedicated checkouts.
The 100-record transaction regression explicitly uses a synthetic owner boundary;
it is not live agent acceptance. Full prequalification: 587 tests PASS, one skip,
123.518s after the README networkless fixture setup. No real public projection,
migration or AAK-02 live run performed.

## Context and Orientation

The source schema and renderer remain Production-owned. Project's receiver checks
the attestation envelope, public metadata and assets without copying headings.

## Plan of Work

Extend tools/public_projection.py, canonical run/batch reports, owner invocation
and closed v2 metadata. Test summary/tamper/rights, revision, replay and transaction
failure against synthetic temporary targets and owner-verified source fixtures.

## Concrete Steps

python3 tools/validate.py --check; python3 -m unittest discover -s tests -v;
git diff --check. Use the repository's existing runtime preflight. Preserve failed
checks and per-acceptance evidence; no fake qualifies as live AAK-02 acceptance.

## Validation and Acceptance

Run `AAK_PRODUCTION_CODE_ROOT=<clean qualified owner checkout>
AAK_PROJECT_CODE_ROOT=<receiver checkout> .venv/bin/python -m unittest
tests.test_canonical_plan_projection tests.test_public_projection -v` for the
owner/receiver integration fixture. The separate 3-mode, 2-run real-agent
acceptance belongs to AAK-02 and remains NOT_RUN.

Request requires contract_version=v2, mode=AUTOMATIC_PLAN,
canonical_artifact=production-plan.md, body_transform=none, and source refs binding
identity, revision, owner repository/commit, run ID, body/attestation hashes and
asset path/hash/MIME/rights. Metadata/index repeat these values; their assets field
is a JSON string for the receiver's native flat YAML parser. Result refs retain
the same provenance. No path to an internal checkout is stored publicly.

The full owner project for batch validation is retained in internal
canonical-production, separately from the batch reporting aggregate. No public
review is synthesized. Missing review/attestation returns BLOCKED_POLICY while
keeping the internal plan. Higher revisions remove only previously attested,
unchanged assets within the same rollback transaction; unrelated files block.

## Idempotence and Recovery

Same identity/revision/hash replays; same revision/different content conflicts;
higher revision updates the same P ID; rollback is rejected without migration.
Preflight all files, apply one target transaction and restore only its changes.

## Interfaces and Dependencies

Owner attestation: Production63. Receiver: Project11 (synthetic code only; real
migration incomplete). AAK-02 live integration remains NOT_RUN. No circular
dependency is added; source/receiver implementation precedes combined acceptance.
