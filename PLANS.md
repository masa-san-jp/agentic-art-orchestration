# Execution Plans

ExecPlanは、複数repo・複数セッションにまたがる変更を、会話履歴なしの別エージェントが引き継げる自己完結型計画である。

## 使用条件

- 2つ以上のrepoまたは3ファイル以上を変更する。
- schema、CLI、状態機械、adapter、migration、外部連携を変更する。
- 1セッションで終わらない可能性がある。
- 失敗時に複数repoの回復手順が必要になる。

## 必須セクション

- Purpose / Big Picture
- Progress
- Surprises & Discoveries
- Decision Log
- Outcomes & Retrospective
- Context and Orientation
- Plan of Work
- Concrete Steps
- Validation and Acceptance
- Idempotence and Recovery
- Interfaces and Dependencies

## 実行規則

1. 計画全体と各子repoの規則を読む。
2. Progress、queue、state、実際のGit状態を照合する。
3. 次の未完了milestoneだけを実装する。
4. repo単位で検証・commitし、親の記録commitと混ぜない。
5. 発見と決定を即時に計画へ戻す。
6. 受入条件を満たすまで完了にしない。
7. 終了時にrepo、branch、SHA、dirty状態、次の1commandを残す。

## Current M15/M16 continuation

目的ギャップの実装順、Issue SSOT、対象repo、terminal、依存関係は親Issue [#107](https://github.com/masa-san-jp/agentic-art-orchestration/issues/107) と `execution/task-queue.yaml` を正本とする。

- [x] M15: v1.4 sandbox evidence、child preflight、pin/provenance reconciliation、queue/state progress SSOTを実装する。進捗表示は`execution/task-queue.yaml`と`execution/state.yaml`を正本に[project status](tools/project_status.py)で生成する。
- [x] M16: inspiration、self export/diversity、intent ranking、research/production/viewer evidence、autonomous runner、batch、新規テーマE2Eを依存順に閉じる。`PURPOSE-BATCH-100-001`と`PURPOSE-E2E-001`のnetworkless/live-private実装・検証が完了した。単一作家の1アンカーは`PASS_LIMITED_DIVERSITY`として受理し、Research `496a2e2`のfresh 6repo exact-pin gateとlive-private PLAN_READYを確認した。

旧M14の資格記録に残る期限切れleaseや過去の外部credential名は履歴情報であり、現在の再開点ではない。merge、tag、releaseは引き続きhuman gateとする。

project statusの確認は `.venv/bin/python tools/project_status.py --check-readme`、validatorの最初の操作は `.venv/bin/python tools/validate.py --check` とする。

## HARNESS-BOOTSTRAP-001 ExecPlan — completed

### Purpose / Big Picture

Issue #113に従い、fresh cloneの外部エージェントがシステムPythonやセッション記憶に依存せず、READMEを唯一の正準入口としてvalidatorとfull suiteへ到達できる状態にする。GitHub認証が無い場合でも、unique offline fixture rootによるnetworkless検証へ進める。

### Progress

- [x] READMEにlocal venvの逐語4行、前提条件、live/offlineの分岐を追加した。
- [x] AGENTS.mdとoperator runbookからREADMEを参照し、verification command notationを`.venv/bin/python`へ統一した。
- [x] fresh cloneで必要な生成物をmaterializeするoffline sequenceをREADMEへ追加した。
- [x] 文書回帰テスト、validator、focused/full suite、snapshot、diffを実行した。
- [x] state、handoff、queueへ結果と次の再開点を記録した。

### Surprises & Discoveries

- `.venv`を用意してvalidatorはPASSするが、生成物を持たないclean cloneのfull suiteは`snapshot.json`等を参照するため失敗する。これはREADMEにoffline materializationを明記して解消した。
- 共有の既定offline fixture rootには古いbranch remoteが残り得るため、fresh verificationでは毎回uniqueな`FIXTURE_ROOT`を使う必要がある。子repoや既存生成物は変更していない。

### Decision Log

- allowed pathsを越えてCLIや生成物の挙動を変更せず、Issueの文書・テスト範囲でbootstrap手順を修正した。
- task-queue.yamlに残る歴史的な`python3` check表記は書き換えず、利用者向けのREADME、AGENTS、runbookだけを修正した。
- live GitHub/Drive操作は行わず、認証不要のoffline fixture経路を正準の代替として明示した。

### Outcomes & Retrospective

- Acceptanceは3/3。fresh cloneのvenv/pip/validator、offline materialization、materialized full suite `379/379 PASS`を観測した。
- 親repoの文書focused testsは`7/7 PASS`、親full suiteは`380/380 PASS`、validator、snapshot check、diff checkもPASSした。
- 子repo、Issue、Drive、CI、merge、release、pushは変更していない。親実装・初回record commitは`887d043`である。

### Context and Orientation

- Issue SSOT: https://github.com/masa-san-jp/agentic-art-orchestration/issues/113
- canonical bootstrap: `README.md#ブートストラップ検証`
- related instructions: `AGENTS.md`, `docs/operator-runbook.md`
- regression test: `tests/test_docs.py::DocumentationTests.test_fresh_clone_bootstrap_is_canonical_and_venv_based`

### Plan of Work

1. READMEのbootstrapと前提条件を修正する。
2. AGENTS/runbookの参照とcommand notationを修正する。
3. 文書回帰テストを追加する。
4. fresh cloneをunique offline fixture rootで検証し、親state/handoff/queueへ記録する。

### Concrete Steps

~~~bash
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest tests.test_docs -v
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/workspace.py snapshot --check
.venv/bin/python tools/project_status.py --check-readme
git diff --check
~~~

### Validation and Acceptance

- READMEに指定4行が逐語で存在し、AGENTS/runbookがREADMEを参照する。
- 文書focused `7/7 PASS`がbare `python3` verification回帰を検出する。
- fresh cloneでvenv作成、依存関係導入、offline materialization、validator、full suiteがPASSする。
- 親full suite `380/380 PASS`、validator、snapshot、diffがPASSする。

### Idempotence and Recovery

READMEのoffline列は毎回新しい一時fixture rootを作るため、古いremote branchを再利用しない。子repo、GitHub、Driveを変更しない。途中停止時は`execution/state.yaml`のlease/checkpointとこのhandoffのNext exact actionから再開する。

### Interfaces and Dependencies

READMEが正準bootstrap契約、AGENTS/runbookが参照層、`tools/workspace.py`がnetworkless materialization、`tools/validate.py`とunittestが検証層である。次の依存タスクは`HARNESS-INTAKE-001`（Issue #114）。

## HARNESS-INTAKE-001 ExecPlan — completed

### Purpose / Big Picture

Issue #114に従い、READYも依存完了済みBACKLOGも無いときに、外部エージェントがopen Issueを安全に観測し、SSOT品質を満たすIssueだけをqueueへ登録できる常設経路を作る。Issue本文全文や推定feedbackを親へ取り込まず、登録と実装を分離する。

### Progress

- [x] AGENTS.mdへ空queueの第三ルールとIssue SSOT最低要件を追加した。
- [x] metadata-onlyの`issue-intake-report/v1` schemaとread-only CLIを追加した。
- [x] fixtureで38件のopen Issue観測を再現し、#117だけをqualified unqueuedとして特定した。
- [x] `HARNESS-PR-TRIAGE-001`を#117へ一度だけ登録し、16件を`UNQUEUED_NEEDS_SSOT`として残した。
- [x] focused/full tests、validator、diff、report byte determinismを実行した。

### Surprises & Discoveries

- queueには既存のIssue SSOTが多数あるため、intakeは番号の重複ではなくcanonical Issue URLで`ALREADY_QUEUED`を判定する必要がある。
- GitHubのread-only APIが実行時にネットワーク unavailableとなったため、取得済みの番号・タイトル・URLと#117のSSOT見出しをfixtureで固定した。本文未取得のIssueは保守的に`UNQUEUED_NEEDS_SSOT`へ分類し、コメントで不足を補わなかった。

### Decision Log

- Issue品質は観測可能な受入条件、対象repository、検証コマンド、human gateの有無の4点だけで判定し、domain内容の採否は判定しない。
- `REGISTER_BACKLOG`候補を自動昇格せず、依存関係を人間可読に確認したqueue commitで登録する。今回の#117は次の実装taskへ分離した。
- Issue本文のコピー、Issueコメント、Issue close、GitHub/Drive write、child repo操作は行わない。

### Outcomes & Retrospective

- Acceptanceは4/4。intake focused `6/6 PASS`、docs+intake `13/13 PASS`、親full suite `386/386 PASS`、validator、diff checkがPASSした。
- 事前reportは38件、qualified unqueuedは#117、登録後reportは22件queued・16件`UNQUEUED_NEEDS_SSOT`で、最終queue反映後report SHA-256は`cbbd7142c0be8d659b4f53b1367bdef48818bc3785a378f07967b919ff352861`、queue SHA-256は`869a6d365f1b1adbedc1fb866381090e91157e41d828719f0fdf63ce32fc3389`。
- 子repo、Issue/Drive、merge、release、push、credential、raw inputは変更していない。親実装・初回record commitは`a631040`である。

### Context and Orientation

- Issue SSOT: https://github.com/masa-san-jp/agentic-art-orchestration/issues/114
- report schema: `schemas/issue-intake-report.schema.json`
- tool: `tools/issue_intake.py`
- operator entry: `docs/operator-runbook.md` の `空queue時のIssue intake`
- fixture/test: `tests/fixtures/issue-intake/current-open-issues.json`, `tests/test_issue_intake.py`

### Plan of Work

1. Task selectionとSSOT最低要件を文書化する。
2. queue比較付きのmetadata-only report contractを実装する。
3. fixtureで決定論・privacy・read-only境界を検証する。
4. 現行open Issueを観測し、qualified候補だけを依存関係付きでqueueへ登録する。

### Concrete Steps

~~~bash
.venv/bin/python tools/issue_intake.py --fixture tests/fixtures/issue-intake/current-open-issues.json --check
.venv/bin/python -m unittest tests.test_issue_intake -v
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/project_status.py --check-readme
git diff --check
~~~

### Validation and Acceptance

- open Issue reportはschema valid、2回のCLI実行でbyte一致、queue bytes不変である。
- AGENTS.mdのTask selectionは第三ルールを持ち、4つのSSOT最低要件を説明する。
- #117は重複なく`HARNESS-PR-TRIAGE-001`として登録され、依存は`HARNESS-REALCHAIN-REBASE-001`である。
- 本文未取得Issueは16件の`UNQUEUED_NEEDS_SSOT`として出力され、正常値へ丸められない。

### Idempotence and Recovery

intakeはqueueをread-onlyで読み、Issue URLの集合だけを比較する。`--check`は同一入力を再評価し、同じJSON bytesを要求する。登録commit後に中断した場合はstate/handoffのreport SHAとqueue statusから再開し、同じIssueを二重登録しない。

### Interfaces and Dependencies

`gh issue list` JSONまたはfixture → `issue_intake.py` → `issue-intake-report/v1` → 人間確認付きqueue registration → 次の実装task、という一方向の境界である。#117の実装は`HARNESS-PR-TRIAGE-001`、次に実行可能なtaskは`HARNESS-SSOT-PUSH-001`（Issue #115）。

## REPO-USABILITY-001 — completed review and docs PRs

利用者が初見で各repoの目的・入口・保存境界を理解できるかを6repoのfresh cloneで監査した。親READMEは目的別入口とviewer-response-notesを追加し、viewerの実際のGitHub default branch `feat/viewer-response-contracts`をmanifestへ反映した。child READMEは各repoの正本・利用手順・privacy/output境界に限定して改善し、childごとに分離commitとdraft PRを作成した。self-modelのstale生成物は正本から再生成した。

### 結果

- child PR: self-model #76、art-history #385、marketing #85、Research #82、Production #51、viewer #3。viewer #3は`feat/viewer-response-contracts`へmerge済み、他5件は保留。
- child checks: self-model 136/136、Research 278/278、Production 71/71 + evaluation、viewer 12/12、marketing graph/audit PASS。art-historyはgraph/context PASS、129 tests中126 PASSで、3件はPython 3.14とrepo要件3.12の不一致。
- GitHub Description: self-model、Research、Production、viewerを更新。art-historyとmarketingは既存値を維持。
- 親検証: validator PASS、focused 31/31 PASS、full 379/379 PASS、workspace 6/6 clean、snapshot check PASS、security PASS、project-status README check PASS。auditは既存のmarketing stale warning 1件を保持。
- 親commit: `21be012`（未push）。
- ユーザー依頼でviewer-response-notes PR #3を`feat/viewer-response-contracts`へsquash merge（`205eeeb8`）。他PRはREADME競合またはGitHub checks failureのため保留。
- 再監査で6repoの現在のdefault branch READMEとDescriptionが正確で利用可能と確認。重複PRは作成せず、validator/project-status/snapshot/workspaceを再確認した。
- 既存のdirty child checkout、会話全文、機微情報、Drive artifact、親push、merge、releaseは変更していない。

## PURPOSE-BATCH-100-001 ExecPlan — blocked (historical attempt)

### Purpose / Big Picture

Issue #71の100件バッチについて、qualified immutable child pinsからG1–G6を実測し、未実行の作業を完了扱いにしない。今回の試行では、実行前提と入口の不整合を証拠化して停止する。

### Progress

- [x] manifest固定の6repoを一時detached workspaceへmaterializeし、clean・pin一致を確認した。
- [x] 6repoの宣言quality gate 16/16を実行し、全てPASSした。
- [x] art-history 96件、marketing-trends 60件、self-model旧aggregateを読み取り専用で観測した。
- [x] 親`run.py`、Research acceptor、Production materializerにbatch入口がないことを確認した。
- [x] G1–G6はNOT_RUNとして記録し、queue/state/handoffをBLOCKEDへ戻してleaseをreleaseした。

### Surprises & Discoveries

- Issue #71は5repo前提だが、現在のmanifestはviewer-response-notesを含む6repoである。
- manifest pinのself-modelは`urn:self-model-notes:research-signals:v1`のlegacy aggregateで、seek 1、tension 1、recurring-pattern 0である。3 recordの`research-signal-export/v1`は別commitで観測済みだが、manifest pinではない。
- `tools/batch_status.py`はread-only集計器であり、JSONL appendや100件のproject completionを駆動しない。

### Decision Log

- 100件のproject、Production plan、batch-report.jsonlは生成しない。存在しないG1–G6を推測で埋めると、provenanceとterminal evidenceの受入条件に反する。
- 子repoのpin更新、親コード追加、Issue/PR/Drive書込みは、このtaskの範囲を越えるため実行しない。

### Outcomes & Retrospective

- Acceptanceは0/6。preflightのchild quality gate 16/16 PASSは、batch acceptanceの達成とは分離して記録した。
- 変更は親のqueue/state/PLANS/handoffと生成README statusだけ。子repo、`repos/`、Issue、Drive、production output、batch reportは変更していない。
- 次に必要なのは、batch driver・child completion contract・self export pin adoptionを明示する別の実装taskである。

### Context and Orientation

- batch issue: https://github.com/masa-san-jp/agentic-art-orchestration/issues/71
- parent batch entry: `tools/run.py`
- child request entry: `agentic-art-research/tools/accept_research_request.py`
- child production entry: `agentic-art-production/tools/new_production.py`
- read-only status aggregator: `tools/batch_status.py`

### Plan of Work

1. 別Issueでbatch driverと子の完了・export契約を定義する。
2. self-modelの3 record exportを含む候補pinをread-only qualificationし、manifest採用は別human-reviewed操作として扱う。
3. fresh exact-pin preflight後にだけ100件runを開始し、各projectのJSONL eventとG1–G6を記録する。

### Concrete Steps

~~~bash
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/project_status.py --check-readme
git diff --check
~~~

### Validation and Acceptance

- child preflight: 6/6 repositories, 16/16 gates PASS。
- G1–G6: 全てNOT_RUN。100件のterminal evidenceは存在しないため、batch acceptance 0/6。
- block解除条件: deterministic batch driver、compatible child completion/export contract、fresh exact-pin qualificationの3条件が揃うこと。

### Idempotence and Recovery

生成物を作っていないため、再開時は現在のqueue/stateを読み、別taskの最初のvalidatorから開始する。今回の一時workspaceと外部preflight reportは親Gitへ取り込まず、report hashだけをstateに記録した。

### Interfaces and Dependencies

`PURPOSE-E2E-001`はこのtaskに依存しているため、現在は実行しない。次taskは未登録のbatch implementation taskであり、最初の操作はIssue/queueの再baseline後に`.venv/bin/python tools/validate.py --check`を実行すること。

## PURPOSE-BATCH-100-001 ExecPlan — completed

### Purpose / Big Picture

Issue #71の受入条件を、qualified exact-pin workspace上のnetworkless batch driverで100件実測する。各候補のsource commit、selection hash、project locator、plan/brief/decision hashをGit外部stateへ保持し、Production childのcanonical planを変更せず、親側のplan projectionだけをcreate-onlyで出力する。

### Progress

- [x] self-modelの3件`research-signal-export/v1`、art-history 96件、marketing-trends 60件をmanifest pinとsource commit一致で受理した。
- [x] self diversity不足を`INSUFFICIENT_SELF_DIVERSITY`として保持し、候補水増しをせず100件のsignal tuple一意性を確認した。
- [x] 6repoのexact-pin qualificationを再実行し、3件の更新pin（self-model、Research、Production）をcandidate hash一致で親manifestへ採用した。6/6 repositories、16/16 child gatesはPASSした。
- [x] 4並列・retry上限付きbatch、Research/Production exchange、append-only JSONL report、G1–G6をGit外部rootで実行した。

### Surprises & Discoveries

- 初回batchは全件がResearch handoff前に旧fixture project ID参照で停止した。既存runを再利用せず、原因を単独runで`research-handoff-build/CHILD_COMMAND_FAILED`として観測し、fixtureのcanonical project IDだけを新slugへ整合させた。
- Research全suiteの180秒上限は過小だったため、child gate timeout時にprocess groupを終端化する親修正を入れ、失敗を隠さずqualificationを再実行した。
- `production-plan.yaml`にchild側の構造化briefがないため、child canonical planとResearch briefをhash付きの親projectionへ組み合わせた。Production childのHUMAN authorityを含むprototype/review全体は最終batch outputへ持ち込まず、plan projectionだけを保持した。

### Decision Log

- self diversityは0 anchorのみ`INSUFFICIENT_SELF_DIVERSITY`で停止し、1〜2 anchorは`PASS_LIMITED_DIVERSITY`、3 anchor以上は`PASS`として扱う。合成anchorを作らず、1〜2 anchorで完全な多様性を主張しない。

### Single-author self-diversity policy correction

ユーザー明示要件として、作家数は一人を基本とし、self-modelの適格アンカーは1個でも実行可能、3個以上なら通常の多様性制御を適用することを確定した。親repoのself-diversity判定を、0個のみ`INSUFFICIENT_SELF_DIVERSITY`、1〜2個を`PASS_LIMITED_DIVERSITY`、3個以上を`PASS`へ変更した。self-modelへ架空のアンカーを追加せず、既存のlive export（3 records、eligible anchor 1）を限定実行として扱う。Researchの最新tip品質ゲートとfresh 6repo exact-pin gateは別の未解決条件として保持する。
- child checkout、handoff、result、stagingはGit外部の独立rootに置き、親Gitにはsummaryとコード契約だけを保存した。child repo、remote、Drive、Issueは変更していない。
- batch outputはcreate-onlyとし、失敗run `/PURPOSE-BATCH-100-001`は保持して別run ID `PURPOSE-BATCH-100-001-run-2`を採用した。

### Outcomes & Retrospective

- Acceptance: 6/6。100/100 projects completed、production plan 100件、research decision log 100件、report 300 events、失敗0・retry0、duration 359.823秒を観測した。
- G1–G6は全てPASS。G4はfinal production plan projectionを対象にHUMAN authority 0件、G5は決定的sample 10件すべて`agent-recommended`、G6はappend-only report集計で起動100/完了100/失敗0を確認した。
- Parent validationとfull testを完了後に再実行する。childは6/6・16/16 gate PASSのqualification reportを再利用し、child working treeの変更はない。
- sensitive data、raw conversation、PRIVATE_RAW、RESTRICTED、credential、直接識別子、外部artifactは追加していない。explicit/inferred feedbackは扱っていない。

### Context and Orientation

- batch driver: `tools/batch_run.py`
- batch contract: `schemas/batch-run.schema.json`
- exchange boundary: `tools/production_exchange.py`
- pin qualification: `tools/qualify_pin_update.py`
- external summary locator: `run://PURPOSE-BATCH-100-001-run-2/batch-run.json`
- external report locator: `run://PURPOSE-BATCH-100-001-run-2/batch-report.jsonl`

### Validation and Acceptance

- qualification report: status `PASSED`、candidate manifest hash `c0f35de0290502967df17b6386fd6b60582d7e8b84ff4d0b1b73904e64238a2f`、child quality `6/6` repositories PASS、production exchange PASS。
- batch summary SHA-256: `62361b07e00a646db6bc176b128ec399297fe8e58d6910d2da1da3d3b4fef414`。selection hash `439e637a26fd53b65f85a0126d2175f81d26eb052fd09d0b7869fad5840b496f`、candidate space hash `c3386d5aa5267c9d5b9c6478a5ea9c3b576b50351647daffefa572f5c5749066`、gate report hash `e4039d32cecfe0e85e47f3c8d51f4b8307169245ca1a99341d9381b44f17d0bb`。
- Parent checks: `.venv/bin/python tools/validate.py --check`、`.venv/bin/python -m unittest discover -s tests -v`、workspace status、audit、`git diff --check`を完了後に実行する。

### Idempotence and Recovery

summaryが存在するrunは`ALREADY_COMPLETED`として再利用し、partial stateや既存outputは新runなしに上書きしない。各eventはevent IDとcanonical bytesで重複を拒否し、child outputはproduction plan projectionへ必要なmetadataだけをコピーする。

### Interfaces and Dependencies

`PURPOSE-E2E-001`は実装とnetworkless証跡を完了したが、queueではBLOCKEDである。self-modelのeligible personal anchorは1件だが、単一作家ポリシーにより`PASS_LIMITED_DIVERSITY`として受理する。Researchの修正commit `496a2e2`では直接gateが通ったが、最新main `d6293ca`の全テストは別のrelease-checkで300秒超停止したため、parent manifestへのpin採用には6repoのfresh exact-pin reportが必要である。最初の再開操作は、Research qualified pin候補で`.venv/bin/python tools/validate.py --check`を実行し、child gatesとlive-privateを再実行することである。

## PURPOSE-E2E-001 — blocked evidence record

`tools/purpose_e2e.py`、閉じた`schemas/purpose-e2e-evidence.schema.json`、focused test、runbookを追加した。networkless fixtureは3回のcanonical evidence hashが一致し、`PLAN_READY`、intent ranking、fixture-only self diversity、Research/Production metadata-only plan、conservative viewer、same-run resume、forbidden operation 0を確認した。canonical hashは`f1b16d2d1e67ec9aa7bc27ce2ab83118a9df7a8b2c253c607110c38c7099b257`である。

live-privateはcleanかつmanifest exact-pinの6 child workspaceで実行したが、self-model commit `1864fa92dde2bc8f25756bd5e5885268fa4b38fc`のexport 3件中、eligible anchorが1件だけだったため`INSUFFICIENT_SELF_DIVERSITY`でfail closedした。fixture anchorの追加や個人事実の合成は行わない。別途、旧pinのchild quality gatesは15/16 PASSでResearch unittestがtimeoutしたが、新Research main `496a2e2`ではcompile、validate、255 unittestがPASSした。新pin採用前の6repo fresh reportとself-model解消が必要であり、未実行・未達のResearch/Production live planを成功扱いにしない。

## PURPOSE-E2E-001 — completed live-private evidence

`PURPOSE-E2E-001`は、qualified exact-pin workspaceでlive-private laneを完了した。Research pin `07f8cf5`から`496a2e2`への更新は、candidate manifest hash `472eeb0a8826bc23d46ea624655dcea78672ccccbbc1f519b43ae77fcaf49abd`の6repo qualificationがPASSした後、親manifest commit `f591bff`で採用した。

- Acceptance: 12/12。`PLAN_READY`、zero human prompts、intent reached selection、self-diversity `PASS_LIMITED_DIVERSITY`（eligible anchor 1）、Research traceability、Production derived fields、conservative viewer `UNKNOWN`、resume reuse、child quality gates、zero forbidden external effects、privacy boundaryを確認した。
- Evidence: attempt `PURPOSE-E2E-001-live-private-496`、canonical evidence SHA-256 `537c917f83b2c4f33d9709eca14b4ff4b7f54b519b698d21671e90a4cc07f895`、evidence file SHA-256 `83db0f55db357186182444d7bca6d1ccf5b1410b7078f8f5f504fd5a9ad48f2a`。出力はGit外部stagingに置き、親Gitへ本文を保存していない。
- Child qualification: 6/6 repositories、16/16 commands PASSED。詳細report SHA-256 `dc0ac341b9e6663318edcc29ad6cc8327061475ff148ed051ac1b8c697047632`、qualification report SHA-256 `d787d9ce7d2cd64c8788c64aaf9e4ad37ac1ff9d8d03200d26d92a941e8f604f`。Researchの255 testsは630.194秒で完走した。
- Source pins: self-model `1864fa9`、art-history `b831f4c`、marketing-trends `ff3adca`、Research `496a2e2`、Production `63a1ddf`、viewer `cf41108`。6repoすべてclean・exact-pin MATCHED、child canonical tree/remote/Issue/Driveは変更していない。
- Privacy and external effects: theme、会話全文、credential、PRIVATE_RAW、RESTRICTED、artifact bodyは保存していない。external operations、child mutations、physical production、Drive create、Issue create、merge、tag、releaseは0/未実行。Researchの不足は`COMPLETE_WITH_GAPS`として保持した。
- Feedback: explicit feedbackは「作家は基本一人、1または3 anchorを許容」。inferred feedbackはnone。残る未解決はM16を阻害しないhuman-gated releaseとstale historical CI taskのみである。
- Parent checks: validator PASS、focused regression 62/62 PASS、full parent tests 379/379 PASS、project status PASS、snapshot `--check` PASS、workspace 6/6 clean/main/ahead0/behind0、auditは既知の非blocking finding 1件、security PASS、diff check PASS。

## PURPOSE-AUTONOMOUS-RUNNER-001 ExecPlan

### Purpose / Big Picture

Issue #103の契約として、`tools/run.py`が返す`RESEARCH_PENDING`を、provider-neutral workerの
一回実行とGit外checkpointへ接続する。workerが完了した研究結果を閉じたmetadata-only result
として受理でき、同じrun-idを再実行しても重複受理せず`PLAN_READY`へ到達できる状態を作る。

### Progress

- [x] `agent-action/v1`、`agent-result/v1`、`autonomous-run/v1` schemaと`human-gates/v1`を追加した。
- [x] `tools/autonomous_runner.py`へargv worker、atomic supervisor state、lease、response replay、human gate、retry fingerprint、privacy boundaryを実装した。
- [x] `tools/run.py`へ`RESEARCH_PENDING`とmetadata-only structured next actionを追加した。
- [x] focused/full gate、state/handoff記録、commitを完了する。

### Outcomes & Retrospective

- `tests.test_run tests.test_autonomous_runner tests.test_runtime_recovery`は14/14、親全体は364/364でPASSした。fake workerは`RESEARCH_PENDING`から`PLAN_READY`へ進み、同一run-id再実行はworkerを再呼出ししない。
- 同時lease競合、worker契約/privacy違反、human gate、同一fingerprintの失敗3回再試行と4回目`FAILED_RETRY_EXHAUSTED`をnetworkless fixtureで観測した。validator、security、diffもPASSした。
- runnerが管理するstateはGit外の明示rootに限定し、merge/release等のhuman operation、worker stdout/stderr、raw conversation、credential、PRIVATE_RAW、RESTRICTEDは実行・保存しない。

### Surprises & Discoveries

- 既存の`tools/run.py`はresearch candidateの同期結果を返すが、workerへ渡す実行契約は存在しなかった。新契約を既存selectionへ混ぜず、`next_action`を追加する境界にした。
- retry上限の文言は「失敗3回までは再試行、4回目をterminal」と明記されているため、同一fingerprintのworker呼出しを4回目で`FAILED_RETRY_EXHAUSTED`へ遷移させる。

### Decision Log

- supervisor state、request、response、leaseは明示された外部state-rootへ保存し、親Gitの`data/`や会話ログへ保存しない。
- human operationは固定7種をconfigの正本に置き、workerの要求を検出しても実行しない。merge、release、公開、同意拡張、破壊Git、超過費用、物理作業は人間へ返す。
- worker stdout/stderrは診断fingerprintの入力にせず、stateにはexit分類とhashだけを残す。raw conversation、credential、PRIVATE_RAW、RESTRICTED、direct identifierを受理しない。

### Context and Orientation

- synchronous pipeline: `tools/run.py`
- runner: `tools/autonomous_runner.py`
- contracts: `schemas/agent-action.schema.json`, `schemas/agent-result.schema.json`, `schemas/autonomous-run.schema.json`
- human boundary: `config/human-gates.yaml`
- tests: `tests/test_autonomous_runner.py`, `tests/test_run.py`, `tests/test_runtime_recovery.py`

### Plan of Work

1. closed schemaと固定human gateを追加し、validatorからversion・unknown field・operation vocabularyを検査する。
2. `run.py`からraw intentを漏らさずstructured next actionを返す。
3. external state-rootのrun-id directoryにrequest/response/supervisorをatomicに保存し、同時lease、resume、accepted-result replayを実装する。
4. worker responseのschema・check・changed pathをfail closedで検証し、human/external/retryableを別terminal stateへ分類する。
5. networkless fake workerで成功、停止再開、同時lease、human gate、retry exhaustion、privacy rejectionを検証する。

### Concrete Steps

~~~bash
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest tests.test_run tests.test_autonomous_runner tests.test_runtime_recovery -v
.venv/bin/python -m unittest discover -s tests -v
git diff --check
~~~

### Validation and Acceptance

- fake workerの初回呼出しは`RESEARCH_PENDING`から`PLAN_READY`へ進み、accepted result digestを1件だけ保持する。
- 同じrun-idの再実行はworkerを再呼出しせず、supervisor bytesとhistoryを維持する。
- active lease競合を拒否し、worker停止後に残ったresponseは同じrun-idで受理する。
- 同一stage・error fingerprintの失敗は3回まで再試行し、4回目を`FAILED_RETRY_EXHAUSTED`にする。
- human operation要求は実行せず`BLOCKED_HUMAN`、変更path逸脱は`BLOCKED_EXTERNAL`にする。
- action/state/resultはclosed schemaで、raw conversation、credential、PRIVATE_RAW、RESTRICTEDを拒否する。

### Idempotence and Recovery

`supervisor.json`は同じrun-idの正本で、terminal stateは再実行時にそのまま返す。request/response
が残ったprocess interruptionはresponse digestを一度だけhistoryへ追加する。lease lockはatomic
createし、期限切れ以外は他processに譲らない。途中stateはworker再実行前にcheckpointを保存し、
workerが作ったGit/外部effectはrunnerが作らない。

### Interfaces and Dependencies

`run.py`の`next_action` → `agent-action/v1` → provider-neutral worker → `agent-result/v1` →
`autonomous-run/v1`という一方向境界である。runnerは既存`tools/runtime.py`のwork-item状態機械を
変更せず、autonomous run専用の外部stateを管理する。次taskは`PURPOSE-BATCH-STATUS-001`。

## PURPOSE-BATCH-STATUS-001 ExecPlan

### Purpose / Big Picture

Issue #70の契約として、複数プロジェクトのresearch state、Production handoff/plan、workspace Git
差分を一つのread-onlyコマンドで観測し、batch driverのappend-only JSONLを完了レポートへ集計できる
状態を作る。未計測値や認識不能な状態を正常値へ変換せず、入力の相対locatorとhashで再確認できるようにする。

### Progress

- [x] `batch-report-event/v1` closed schemaと親validator接続を追加した。
- [x] `tools/batch_status.py`へ決定的な5段階project status、repoのHEAD/origin差分、JSONL集計、
  `未計測`表示、duplicate/privacy-safe read-only境界を実装した。
- [x] fixture五状態、report集計、unknown event、duplicate event、read-only tree hashをテストする。
- [x] queue/state/handoff/README、full gate、commit、draft PR記録を完了する。

### Plan of Work

1. research stateをproject単位に走査し、handoff/planの存在・status・readinessを固定stageへ射影する。
2. workspace直下のGit repoからbranch、HEAD、dirty、`HEAD..origin/main`をread-onlyで取得する。
3. closed JSONL eventを検証し、起動・完了・失敗・再試行・所要・tokenを集計する。
4. 同一入力のbyte一致、未知状態の保持、入力tree不変、親validator/full testを確認する。

### Validation and Acceptance

- 5つのfixtureが`NOT_STARTED`、`IN_PROGRESS`、`TERMINAL`、`HANDOFF`、`PLANNED`へ一意に分類される。
- project/repositoryのsource locatorとSHA-256、task進捗、Git remote差分が出力され、同一入力は決定的である。
- 集計が起動、完了、失敗、再試行、所要、tokenを区別し、未提供値を`未計測`として表示する。
- unknown/duplicate/closed-schema違反を拒否し、scan前後でworkspace treeが変化しない。

### Outcomes & Retrospective

focused 5/5、親全体369/369、validator、README status、JSON CLI assertion、diff checkがPASSした。
実装commitは`aee287f`。子repo変更、外部artifact、Issue/Drive操作、merge、tag、releaseはない。
child-owned stateの未対応・未知語彙は`state_quality=UNKNOWN`として保持し、batch driverのappend自体は
このread-only toolの責務に含めなかった。次taskは`PURPOSE-BATCH-100-001`。

## HARNESS-SSOT-PUSH-001 ExecPlan — completed

### Purpose / Big Picture

Issue #115に従い、実行SSOTをremote cloneから再開可能にするため、lease解放前のfast-forward pushを
正準手順へ追加し、親branchの未push状態を監査でnon-blockingかつUNKNOWN保持で観測する。

### Progress

- [x] AGENTS.mdとoperator runbookに、実行SSOTのpush、force/default-branch禁止、remote確認不能時の停止を記録した。
- [x] `tools/audit.py`にlocal tracking refのread-only観測と`PARENT_SSOT_UNPUSHED` findingを追加した。
- [x] ahead状態とnetwork UNKNOWN、文書規則、入力非変更・非blockingをfocused testsで検証した。
- [x] Issueで明示されたworking branchをpushし、draft PR #42のHEAD一致をread-only確認した。

### Surprises & Discoveries

- 現在のparent branchは`origin/agent/issues-38-41-pipeline`に対してahead 4。監査はremote fetchを行わず、local tracking ref比較と`network_status=UNKNOWN`を分離して保持する。
- parent full suiteは389/389 PASS。child repositoryの品質gateは対象外で、child checkoutを変更していない。

### Decision Log

- auditはnetworkを暗黙に成功扱いせず、remote headをfetchしないread-only設計にした。比較不能時は`PARENT_SSOT_UNPUSHED`の`status=UNKNOWN`を出力する。
- push対象はIssue #115で明示された`agent/issues-38-41-pipeline`だけとし、merge、ready化、default branch push、force pushは行わない。

### Validation and Acceptance

- Acceptanceは3/3。focused `tests.test_audit`/`tests.test_docs`は15/15、parent full suiteは389/389、validator、audit check、diff checkはPASS。`HEAD == origin/agent/issues-38-41-pipeline == PR #42 headRefOid`を確認した。

### Idempotence and Recovery

- Gitの通常pushはnon-fast-forwardなら失敗する。force push、reset、rebase、mergeを代替操作にしない。失敗時は未push事実とremote UNKNOWNをstate/handoffへ残す。

### Next exact action

1. `HARNESS-REALCHAIN-REBASE-001`をclaimし、`.venv/bin/python tools/validate.py --check`からIssue #116の再ベースライン作業を開始する。

## HARNESS-REALCHAIN-REBASE-001 ExecPlan — completed

### Purpose / Big Picture

Issue #116に従い、現行6 child構成に対するreal-chain CIを、credential未設定時にcheckout前で
fail-closedするread-only qualificationとして再ベースラインする。secret設定とremote greenは人間gateのまま残す。

### Progress

- [x] 現行workflowとmanifestを照合し、5 child checkout、viewerの宣言済みdefault branch、secret preflightを観測した。
- [x] `validate.yml`を6 child、`MISSING_EXTERNAL_SECRET`、full-history、`persist-credentials: false`、no `--apply`へ更新した。
- [x] `tests/test_real_chain_ci.py`を6 child、preflight順序、secret非出力、pin非採用の契約へ更新した。
- [x] 旧`ISSUE-38-REAL-CHAIN-CI-001`をIssue #116へ付替え、target repositoryとterminalを補完した。
- [x] 親検証、commit、remote runのfail-closed観測、state/handoff最終記録を完了した。

### Surprises & Discoveries

- viewer-response-notesの正本branchはmanifestで`feat/viewer-response-contracts`と宣言されている。したがって「main固定」ではなくmanifest観測値を使う。空のmainを参照すると現行pin検証を壊す。
- parent workflowのsecret preflightはcheckoutより先に存在したが、既存runのログ・secret状態はこのローカル実行から推定せず、remote runで明示確認する。

### Decision Log

- secret値は作成・取得・出力せず、Actions secretの存在だけをshell条件で確認する。
- qualificationは`--apply`を含めず、checkoutとchild gateをread-onlyで行う。旧BLOCKED taskはremote green evidenceが得られるまでDONEにしない。

### Validation and Acceptance

- Acceptanceは3/3。focused testは3/3、parent full suiteは390/390、validator、diff checkはPASS。remote run `33481638691`はsecret未設定のため`MISSING_EXTERNAL_SECRET`でcheckout前停止し、親・6 child checkoutとqualificationをskipした。secret設定とgreen runはhuman gateとして残る。

### Next exact action

1. `HARNESS-PR-TRIAGE-001`をclaimし、`.venv/bin/python tools/validate.py --check`からIssue #117のread-only PR triage作業を開始する。

## HARNESS-PR-TRIAGE-001 ExecPlan — completed

### Purpose / Big Picture

Issue #117に従い、各repositoryのopen PRを人間が安全に短時間で確認できるread-only triage evidenceを追加した。自動mergeは導入せず、checks・競合・変更クラス・Issue SSOT・経過日数を同じreportへ束ねる。

### Progress

- [x] `tools/pr_triage.py`と閉じた`pr-triage-report/v1` schemaを追加した。
- [x] fixtureで5 recommendationと4 change class、入力非変更、byte determinism、metadata-only境界を検証した。
- [x] `config/human-gates.yaml`へ4 change classを追加し、全て`auto_merge: false`・`human_approval_required: true`へ固定した。
- [x] operator runbookへ`MERGE_CANDIDATE`から開始する人間の確認経路と、各recommendationの再観測条件を追加した。
- [x] 7repositoryのlive open PRをread-only観測し、state/handoffへreport hashと集計を記録した。

### Surprises & Discoveries

- GitHub APIは通常のPython子プロセスではネットワーク遮断となったが、read-onlyのsandbox外実行で観測を完了した。reportには認証情報を含めていない。
- Issue起票時の「18件」からlive観測時点では17件だった。liveの固定観測値17件を採用し、PR状態の時間変動を推測で補正していない。
- 親PR #42は現時点でconflictがあり`NEEDS_REBASE`、childを含む他PRもchecks/mergeableの観測値に従って分類した。superseded候補は0件だった。

### Decision Log

- path classは`config/human-gates.yaml`のprefixを正本にし、mixed changeはcontractを優先する。schemas、manifest/config、CI workflowはcontract、tools/testsはcode、executionはrecord、docs/README等はdocsとした。
- checksまたはconflictが`UNKNOWN`の場合は`HUMAN_JUDGMENT`へ留め、greenやmergeableへ正規化しない。conflictとCI failureが同時なら`NEEDS_REBASE`を先に示す。
- supersededはhead/base SHA一致、または入力で明示されたDONE taskへのlater-commit包含だけを候補化し、PR closeやmergeは行わない。

### Validation and Acceptance

- Issue #117 acceptanceは3/3（決定論的fixture、7repositoryのlive観測、人間merge gate保持）。focused `tests.test_pr_triage`は6/6、parent full suiteは396/396、validator、diff checkはPASS。
- Fixture reportは6 PR・7 repositoryで5 recommendationと4 classを再現し、live reportは7 repository・17 open PRを`READ`のみで観測した。live report SHA-256は`b77e80381c30bfaa455e906747a2e91658e912c9f09d2359299fa92f3886b301`。
- live集計: `CLASS_RECORD 0 / CLASS_DOCS 4 / CLASS_CODE 8 / CLASS_CONTRACT 5`; `MERGE_CANDIDATE 6 / NEEDS_REBASE 8 / NEEDS_CI_FIX 2 / SUPERSEDED_CANDIDATE 0 / HUMAN_JUDGMENT 1`。

### Idempotence and Recovery

fixtureまたは同一live payloadの再生成はbyte一致する。toolはGitHub PR/Issue、Git、Driveへ書き込まず、途中停止時は同じ固定observed_atと入力fixtureで再実行できる。live report本体はGit外`/tmp`にのみ置いた。

### Next exact action

1. 現在eligibleなREADY/BACKLOG taskはないため、`.venv/bin/python tools/issue_intake.py --fixture tests/fixtures/issue-intake/current-open-issues.json --check`で新規Issue SSOT候補をread-only確認する。merge/releaseと#116のsecret設定は人間承認後に別途扱う。

## HARNESS-AUTO-PLAN-001 ExecPlan — completed

### Purpose / Big Picture

Issue #1の「エージェントが自律的に制作プランを出力する」入口を、利用者がテーマ・slug・titleを
与えない場合にも成立させる。manifestのpin済みchild workspaceをread-onlyで確認し、gateを通過した
候補から作業テーマと安定したproject identityを導出してResearchへ渡す。会話全文やraw/private dataを
保存せず、研究実行と外部human gateは既存の境界を維持する。

### Progress

- [x] `tools/run.py`のfull orchestrationで`--intent`、`--slug`、`--title`、`--run-id`、`--requested-at`を省略可能にした。
- [x] run-idから衝突しないslug/titleを導出し、Research requestのcandidate-derived `creative_question`を`REPOSITORY_DERIVED` theme proposalとしてrun reportへ出す。
- [x] child export前に全manifest repositoryのclean・branch・upstream・exact observed pinをread-only検査し、失敗時は`BLOCKED`で停止する。
- [x] 最小指示、実行前提、ResearchからPLAN_READYまでの継続方法をruntime guideとREADMEへ記載した。
- [x] 親検証、全suite、PR/CI、merge、最終確認を完了する。

### Surprises & Discoveries

- ローカル`repos/`はcleanでもoffline fixture remoteと旧HEADを持つ生成workspaceで、現行manifest pinのverified workspaceではなかった。export tool不足をテーマ生成の成功として扱わず、preflightでBLOCKEDへ分類する。
- 既存の`PURPOSE-E2E-001`は「ユーザーがテーマを入力しない」意味ではなく、fixture内のthemeがevidenceへraw保存されない意味であった。今回の入口はその意味を混同せず、候補から導出したquestionをResearch requestから明示する。

### Decision Log

- テーマ未指定時のsourceは`gate-passing-candidate`に固定し、候補が持たないcreative questionを推測で補わない。
- project identityはrun-idとSHA-256から決定し、ユーザーに命名を質問しない。explicit intentは候補順位のoverrideに限る。
- verified workspaceの欠落・dirty・detached・upstream欠如・pin mismatchはchild export前に`BLOCKED`へし、checkout/reset/fetch/pin更新を自動実行しない。
- Research request、run report、production planはGit外で扱い、親Gitへ会話全文、PRIVATE_RAW、RESTRICTED、credential、Drive本文を保存しない。

### Outcomes & Retrospective

テーマなしCLIの引数契約、候補由来theme proposal、安定identity、exact-pin preflight、Research request、
失敗時のBLOCKED境界を確認した。networkless run `AUTO-PLAN-OFFLINE-001`はテーマ未指定で候補を選び、
`REPOSITORY_DERIVED` proposalとGit外RR001 requestを出して`AT_EDGE`へ到達した。Research以降はagent
actionのnext_actionとして明示され、制作planを捏造していない。PR/CI/mergeと最終確認は別途記録した。

### Context and Orientation

- Issue SSOT: https://github.com/masa-san-jp/agentic-art-orchestration/issues/1
- parent entry: `tools/run.py --offline-fixture` または verified workspaceを渡した `tools/run.py`
- input contract: `config/repositories.yaml`, `data/snapshot.json`, `tools/ingest_signals.py`
- downstream contracts: `tools/build_research_request.py`, `agentic-art-research`, `agentic-art-production`
- focused tests: `tests/test_auto_plan.py`, `tests/test_run.py`, `tests/test_docs.py`

### Plan of Work

1. 引数なしfull orchestrationとproject identity/theme proposalを実装する。
2. verified child workspace preflightを追加し、invalid workspaceはchild export前にBLOCKEDへする。
3. docs/tests/READMEを同期し、validator、focused/full suite、workspace/auditを実行する。
4. task/state/handoffを結果で更新し、branch PRのrequired checksを通してmerge後に再検証する。PR #122はrequired checks 3/3 PASSで`fb94a77aee296fd7fc208a4af8ebe2c49f85ddc1`へmerge済み。

### Concrete Steps

~~~bash
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest tests.test_run tests.test_auto_plan tests.test_docs -v
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/project_status.py --check-readme
.venv/bin/python tools/workspace.py status --json
.venv/bin/python tools/audit.py --check
git diff --check
~~~

### Validation and Acceptance

- テーマ、slug、titleを与えないCLI呼び出しがparseされ、候補由来の`REPOSITORY_DERIVED` proposalと安定slugを出す。
- exact pin・clean workspaceのpreflightをchild export前に通し、違反時は`BLOCKED`で解除条件を示す。
- Research requestはchild-owned schema、source commit、candidate references、raw data禁止を満たす。
- explicit intentは任意のranking overrideとして働き、未指定時のv1 selection互換を壊さない。
- parent validator、focused tests 33/33、full suite 464/464、project status、audit、diff check、remote required checksがPASSする。

### Idempotence and Recovery

同じrun-id、同じpin、同じrequest入力ではproject identityと候補選択が一致する。Research未完了時は
`RESEARCH_PENDING`のnext actionを返し、同じrun-idで再開する。workspace preflight失敗時はchildと
既存checkoutを変更せず、観測された最初の解除条件から人間が修復して再実行する。

### Interfaces and Dependencies

`config/repositories.yaml` → workspace preflight → child exporter → normalized signals → candidate/gate/
selection → `build_research_request.py` → Research acceptance → Production handoff/planという一方向の
境界である。merge、release、外部CREATE、child repository mutationはこのtaskの自動範囲外である。

### Next exact action

1. 新しいqualified Issue SSOTが登録されるまで、queue/state/handoffから再開する作業はない。

## HARNESS-ISSUE-INTAKE-LIVE-001 ExecPlan — completed

### Purpose

Issue #114のlive intakeを、GitHub CLI/APIのbody field差異や親repoの作業ディレクトリに依存せず、全manifest repositoryから再現可能に観測できるようにする。

### Progress and Decision Log

- [x] `gh issue list`は番号・タイトル・URLだけをrepository scope付きで取得する。
- [x] 本文は各Issueについてrepository scope付き`gh issue view`で取得し、Issue番号の誤repo解決を拒否する。
- [x] fixture回帰テストに加えて、metadata/body command scopeのfocused testを追加した。
- [x] 全7 manifest repositoryのlive reportをread-onlyで生成し、同一観測の`--check`でbyte一致を確認した。

### Outcome

2026-09-02T14:36:12Zのlive観測は43 open Issues、23 queued、2 qualified unqueued（親#124、Production#52）、18 `UNQUEUED_NEEDS_SSOT`。focused test 7/7 PASS、validator PASS、live check PASS、report SHA-256は`af32e8c9c13ba922cb52ec3f80f7c7a8fd06ea6f36cd2afeedabb7d007671688`。

### Safety and Recovery

intakeはIssue、Git、queueをremoteから変更しない。本文はreportへ保存せず、レポートはGit外に置いた。sandbox内Python subprocessの外部通信拒否は、read-only権限付き実行で切り分けた。次はqualified unqueuedのProduction#52を先に実装する。

### Next exact action

1. `PURPOSE-PRODUCTION-VISUAL-PACKAGE-001`をclaimし、Production Issue #52の正本と実repoのREADME/AGENTSを読んでからchild branchで実装する。

## M28-M29 actionable Issue registration — pending

### Purpose

Issue intake identified three qualified parent-repository Issue SSOTs: #148 (configured output destinations), #150 (fresh-clone workspace bootstrap), and #149 (human-gated public projection). Their missing autonomous-execution requirements were decomposed into a dependency-ordered task DAG in `execution/task-queue.yaml`.

### Registration result

- `OUTPUT-DESTINATIONS-CONTRACT-001` and `WORKSPACE-BOOTSTRAP-CONTRACT-001` are independent `READY` tasks after `HARNESS-RESEARCH-PIN-85-001`; the lowest ID is the next task.
- The remaining ten tasks are `BACKLOG` with explicit dependencies, acceptance, checks, stop conditions, target repositories, and terminal states.
- #149 is deliberately downstream of the complete #148 lane because public projection must consume the configured, Git-external output boundary.
- Self-model #81 is separately scoped to SM-031..034; #82 is a human-gated n=1 profile migration and is not an autonomous implementation task.

### Safety boundary

All examples remain placeholders or synthetic fixtures. No user absolute path, credential, private profile, raw conversation, child schema/data, public target, or external artifact body is registered in the parent. Merge, release, live profile migration, and public projection remain human-gated.

### Next exact action

1. Claim `OUTPUT-DESTINATIONS-CONTRACT-001`, read Issue #148 and the nearest schemas/tests, then implement the contract and shared resolver in an isolated branch.

## OUTPUT-DESTINATIONS-CONTRACT-001 — completed

- Parent PR #152 merged to `main` as `cf8f53ee111a4363ace75481e837b3cc7c455a09`; implementation commit was `a47a94b6515d035b144eff231efba39a1b872856`.
- Added closed `output-destinations/v1` and `destination-resolution/v1` schemas, a placeholder-only profile, and one deterministic resolver. It enforces direct CLI > explicit profile file > `AGENTIC_ART_DESTINATIONS_FILE` > legacy precedence, role provenance, config hashes, repository/child/symlink/overlap guards, safe derived paths, and create-only checks.
- Acceptance evidence: focused tests `7/7 PASS`; parent full suite `490/490 PASS` with one expected checkout skip; validator, py_compile, and diff check PASS. Remote jobs were billing-blocked before steps and are retained as an environment observation, not a test pass.
- Safety: no runtime command was rewired yet, no child repository or manifest pin changed, and no user path, credential, private data, raw conversation, public target, or external artifact body was written.

### Next exact action

1. Claim `WORKSPACE-BOOTSTRAP-CONTRACT-001`, inspect Issue #150 and `tools/workspace.py`, then add the closed bootstrap result contract and deterministic offline parser.
