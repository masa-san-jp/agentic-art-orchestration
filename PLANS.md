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
- [ ] M16: inspiration、self export/diversity、intent ranking、research/production/viewer evidence、autonomous runner、batch、新規テーマE2Eを依存順に閉じる。`PURPOSE-NAMING-001`、`PURPOSE-INSPIRATION-001`、`PURPOSE-SELF-EXPORT-SOURCE-001`は完了し、次は`SELF-EXPORT-E2E-001`である。

旧M14の資格記録に残る期限切れleaseや過去の外部credential名は履歴情報であり、現在の再開点ではない。merge、tag、releaseは引き続きhuman gateとする。

project statusの確認は `.venv/bin/python tools/project_status.py --check-readme`、validatorの最初の操作は `.venv/bin/python tools/validate.py --check` とする。

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
