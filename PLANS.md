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
- [ ] M16: inspiration、self export/diversity、intent ranking、research/production/viewer evidence、autonomous runner、batch、新規テーマE2Eを依存順に閉じる。`PURPOSE-BATCH-100-001`まで完了し、次は`PURPOSE-E2E-001`である。

旧M14の資格記録に残る期限切れleaseや過去の外部credential名は履歴情報であり、現在の再開点ではない。merge、tag、releaseは引き続きhuman gateとする。

project statusの確認は `.venv/bin/python tools/project_status.py --check-readme`、validatorの最初の操作は `.venv/bin/python tools/validate.py --check` とする。

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

- self diversity 3 anchor未満は合成anchorを作らず、selectionへ`require_self_diversity=False`を明示し、summaryへ`INSUFFICIENT_SELF_DIVERSITY`を残した。
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

`PURPOSE-E2E-001`が次の最小eligible taskであり、queueではREADYへ進める。最初の操作は`.venv/bin/python tools/validate.py --check`である。

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
