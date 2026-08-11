# Operator runbook

この文書は、会話履歴なしの新しいagentが親repoだけを読み、4つの独立repoを安全に展開・検査・実行・引き継ぐための手順である。子repoの要件、schema、Issue、データは各子repoが正本であり、親のrunbookはそれらを複製しない。

## 0. 最初の1操作

作業開始時は、親repoの作業状態を変更せずに確認する。

~~~bash
git status --short
~~~

次に必ず [AGENTS.md](../AGENTS.md)、設計仕様、実行計画、`PLANS.md`、`execution/task-queue.yaml`、`execution/state.yaml`、[handoff](../execution/handoff.md)を読む。`state.yaml`の`active_task`とleaseが自分の作業範囲と一致しない場合、同じpathを編集しない。

## 1. 正本と安全境界

- `config/repositories.yaml`: 統合対象、workspace path、source commit、contract、子repo quality gateの正本。
- `schemas/`: manifest、normalized signal、work itemの親境界契約。
- `execution/task-queue.yaml`: 実装順の正本。依存が全て`DONE`の最小ID `READY`を1件選ぶ。
- `execution/state.yaml`: active task、lease、checkpoint、次の再開点の正本。
- `execution/handoff.md`: 人間可読の観測結果、判断、検証、次の1操作。
- `data/`: status、audit、snapshot、E2E等の生成物。手編集しない。
- `repos/`: 子repoのローカル生成物。親履歴へvendor copyしない。

次を自動で行わない。

- dirty、detached、unpushed、behind、diverged checkoutのreset、pull、rebase、merge。
- force push、branch削除、Issue/PR削除、既定branchへのmerge、release。
- `PRIVATE_RAW`、`RESTRICTED`、raw voice本文、個人識別情報、credentialの親への集約。
- stale marketing signal、同意範囲外のself signal、根拠不足のart-history signalの正常値化。

## 2. 初期化と検査

### networkless smoke

ネットワークを使わない再現確認は次の順で行う。

~~~bash
.venv/bin/python tools/validate.py --check
.venv/bin/python tools/workspace.py init --offline-fixture
.venv/bin/python tools/workspace.py status --json
.venv/bin/python tools/workspace.py guard --offline-fixture --json
.venv/bin/python tools/workspace.py snapshot --check
.venv/bin/python tools/status.py --check --offline-fixture
.venv/bin/python tools/audit.py --check --offline-fixture
.venv/bin/python tools/security.py --offline-fixture
.venv/bin/python tools/e2e.py --offline-fixture --check
~~~

期待値は、manifest記載repo数（coreは4）、`main`、clean、ahead/behind 0、`blocked_count: 0`、status `CLEAN`、audit finding 0、security `PASSED`、E2E clean `COMPLETE`である。E2Eのfailure injectionは失敗を隠さず、各ケースに終端状態と復旧経路を持つ。

### 実repo workspace

認証済みで実repoを展開する場合は`--offline-fixture`を付けず、manifestのURLとdefault branchを使う。

~~~bash
.venv/bin/python tools/workspace.py init
.venv/bin/python tools/workspace.py fetch
.venv/bin/python tools/workspace.py status --json
.venv/bin/python tools/workspace.py guard --json
.venv/bin/python tools/workspace.py snapshot
.venv/bin/python tools/status.py
~~~

認証不足、remote不一致、checkout欠落はrepo単位で観測し、手動で解消する。`guard`のblockedを無視して先へ進めない。

v1.0.0の資格判定は、3回連続E2E、親validator/test、fixture、status、audit、security、Git history scanを行う。これはread-onlyの判定であり、tag、commit、merge、releaseは行わない。

~~~bash
.venv/bin/python tools/release_check.py --version 1.0.0 --runs 3
~~~

v1.1.0のqualificationは、上記v1.0ゲートに加えてretrieval、Drive create-only artifact、feedback routing、improvement、非同期audit、interaction E2E、privacy boundaryを3回の決定的offline実行で検査する。

~~~bash
.venv/bin/python tools/release_check.py --version 1.1.0 --runs 3
~~~

`data/release-check.json`で`status=PASSED`、`remote_operations=[]`、`merge_operation=NOT_PERFORMED`、`tag_operation=NOT_PERFORMED`、`release_operation=NOT_PERFORMED`を確認する。qualification成功だけではrelease済みとは扱わず、merge、tag、release、公開、共有範囲拡張、artifact削除は人間の明示承認後に別途実行する。

## 3. taskを実行する

1. queueから依存が`DONE`の最小ID `READY` taskを選ぶ。
2. `execution/state.yaml`へtask、対象repo、開始HEAD、想定変更、lease scope、expires_atを記録する。
3. 同じrepo/pathのactive leaseがないことを確認する。
4. taskのacceptanceを満たす最小差分だけを編集する。
5. work itemがある場合は、要求されたファイルだけをcontext packにする。

~~~bash
.venv/bin/python tools/dispatcher.py \
  --work-item tests/fixtures/work-items/valid.yaml \
  --context-root .
~~~

6. 親validator、親test、変更した子repoのmanifest記載quality gateを実行する。変更repoだけを`--changed`で指定し、失敗を削除・skipしてはならない。

~~~bash
.venv/bin/python tools/quality_gates.py --changed <repository-id>
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest discover -s tests -v
git diff --check
~~~

7. `git status --short`と`git diff --stat`で、対象外の変更がないことを確認する。
8. acceptanceの観測結果、checks、repoごとのHEAD/commit、機微情報確認、未解決、次の1操作をqueue/state/handoffへ記録する。
9. leaseを解放し、依存完了後の次taskをREADYへ進める。merge/releaseはhuman gateで停止する。

## 4. signalから成果物まで

子repoのadapterは`normalized-research-signal/v1`の境界形式だけを出力する。consumerはmajor version不一致を拒否し、source repositoryとimmutable commitを保持する。

~~~bash
.venv/bin/python tools/trace.py --check --fixture tests/fixtures/portfolio
~~~

traceの各edgeは、requirement → signal ID → source entity → repository@commit → evidence locatorを持つ。欠落入力は推測せず`COMPLETE_WITH_GAPS`として制約と再検証経路を残す。

## 5. repository-aware conversational retrieval

利用agentは自由文を親Gitへ保存せず、interactionの一時処理で構造化したintentとcapability codeをretrieval requestへ渡す。routerは各repositoryのknowledge profileとadapter indexを照合し、要求capabilityを覆う最小のrepository集合だけを選ぶ。結果にはrepository、manifestのimmutable observed commit、evidence locator、freshness、unknowns、domain constraintsを残し、stale/unknownをcurrentへ変換しない。retrievalはfrontstage laneだが、artifactやauditを待たず、user artifactはread-onlyである。

~~~bash
.venv/bin/python tools/retrieval.py
.venv/bin/python tools/retrieval.py --check
.venv/bin/python -m unittest tests.test_retrieval -v
~~~

`data/retrieval-result.json`にはraw query、会話本文、child repoのcanonical本文を保存しない。保存するのはrequest ID、capability code、選択repo、source commit、opaque/local evidence locator、freshness、unknowns、制約だけである。証拠がない場合は`NO_MATCH`、一部欠落または再検証要の場合は`COMPLETE_WITH_GAPS`とし、推測で補完しない。

## 6. 外部artifactのcreate-only保存

利用agentがユーザー成果物を保存するときは、承認済み保存先・access scope・consentを確認してからDriveArtifactAdapterを呼ぶ。adapterはcontentを外部Driveへ渡し、親Gitへはartifact ID、opaque provider file ID、SHA-256、source snapshot、lineageだけを返す。既存artifactのUPDATE/DELETE、Drive URLの代用、本文のGit保存は拒否する。

同じinteraction-scoped idempotency keyと同じpayloadは既存CREATEのmetadata-only結果をreplayする。keyを同じままpayloadまたはmetadataを変えた場合は重複作成を止める。修正版は新しいartifact IDとderived_from/supersedesで表す。

~~~bash
.venv/bin/python -m unittest tests.test_external_artifact_contract tests.test_drive_adapter -v
~~~

現段階の検証はnetworkless FakeDriveだけで行い、実Google Driveへの書込みは実行しない。

## 7. feedbackからIssue候補へのルーティング

feedback routerは、summary code、manifestのknowledge profile、target authority、confidence、consentを使って、domain feedbackを正本の子repoへ、UX・retrieval・adapter・artifact・orchestration feedbackを親repoへ決定的に割り当てる。authorityが未確定またはinferred confidenceが閾値未満なら`TRIAGE`に留め、同じIssue keyはcanonical候補へ集約して重複を抑止する。出力はprivacy-safeなIssue候補のmetadataだけで、GitHub Issueのcreate/update/deleteは行わず、人間gateを維持する。

~~~bash
.venv/bin/python tools/issue_router.py
.venv/bin/python tools/issue_router.py --check
.venv/bin/python -m unittest tests.test_issue_router -v
~~~

`data/feedback-routing.json`にはfeedback ID、interaction/artifactのopaque参照、source snapshot、confidence、候補のacceptanceだけを保存する。raw conversation、Drive本文、PRIVATE_RAW、RESTRICTED、direct identifierは保存しない。`issue_creation_permitted`がfalseのfeedbackは`BLOCKED`とし、推定feedbackをuser factへ昇格させない。

## 8. Issue-to-draft-PR improvement lane

improvement agentは`FEEDBACK_ROUTING`のmetadata-only候補から、`creation_permitted=true`、authority確定、human gate保持、重複なしのcanonical Issueだけを選ぶ。schedulerでpath conflictと依存を確認し、runtimeのlease/checkpointでselect → implement → test → quality gateを再開可能に記録する。implementation、test、対象repoのquality gateがすべて`PASSED`のときだけ、base commit、変更path、branch案を持つdraft PR planを作る。GitHub Issue/PRのcreate、branch、commit、merge、releaseはこのnetworkless実装では行わず、planは常にhuman gate付きである。

~~~bash
.venv/bin/python tools/improvement_loop.py
.venv/bin/python tools/improvement_loop.py --check
.venv/bin/python -m unittest tests.test_improvement_loop -v
~~~

`data/improvement-loop.json`にはIssue key、source feedback IDs、source commit、write scope、scheduler/runtime checkpoint、test/gate status、draft PR planだけを保存する。raw feedback、会話本文、Drive本文、credential、PRIVATE_RAW、RESTRICTEDは保存しない。gateが未実行・失敗・BLOCKEDなら`WAITING`または`BLOCKED`に留め、draft PRへ進めない。再実行はtask + repo + base commit + attemptのidempotency keyで同じcheckpointを再利用する。

## 9. interaction E2Eと中断再開

v1.1のnetworkless E2Eは、frontstageのretrievalが返したrepository@commit/evidenceを使って、Drive FakeへのCREATEと同一payloadのREPLAYを確認し、artifact本文をGitへ返さない。その後、interaction outcome、explicit/inferred feedback、authority routing、improvementのdraft PR plan、runtime lease expiry/process interruption recovery、独立した`ASYNC_AUDIT`を同じrunで検証する。失敗時は段階ごとのterminal stateとresume pathを残し、実Google Drive、GitHub Issue/PR、branch、commit、merge、releaseは実行しない。

~~~bash
.venv/bin/python tools/interaction_e2e.py
.venv/bin/python tools/interaction_e2e.py --check
.venv/bin/python -m unittest tests.test_interaction_e2e -v
~~~

`data/interaction-e2e.json`には各stageのmetadata、opaque artifact reference、source commit、feedback ID、checkpoint、statusだけを保存する。`raw_conversation_stored=false`、`direct_identifiers_stored=false`、`remote_operations=[]`、artifactは`CREATE`のみであることを確認する。

## 10. 非同期audit/refactoring lane

監査はinteraction request pathと別の`ASYNC_AUDIT` queue/leaseで実行する。interactionは監査完了を待たず、user artifactは常にread-onlyである。監査findingは重複抑止されたIssue候補になり、対象repositoryのquality gateが`PASSED`のときだけdraft-PR計画へ進む。実際のmerge、release、artifactのupdate/deleteは行わない。

~~~bash
.venv/bin/python tools/audit.py --offline-fixture
.venv/bin/python tools/async_auditor.py --run-id AUDITOR-002:attempt-1
.venv/bin/python tools/security.py --offline-fixture
~~~

`data/async-audit.json`にはsource snapshot、parent/child commit、audit hash、lease、gate status、proposalのtraceだけを保存する。Drive本文、会話全文、user artifact contentは保存しない。`NOT_RUN`、`FAILED`、`BLOCKED`のgateはIssue/triageへ留め、gateをskipしてdraft PR化しない。

## 11. handoffの必須項目

`execution/handoff.md`には、少なくとも次を日本語または明確な英語で残す。

- Task IDと対象repo。
- 観測可能な変更とacceptance達成数。
- 親validator、親test、子quality gateのcommandと結果。
- repoごとのbranch、HEAD、commit SHA、dirty状態。未commitならその事実。
- `PRIVATE_RAW`、`RESTRICTED`、credential、direct identifierを含めていないこと。
- 未解決と、BLOCKEDなら観測事実、選択肢、推奨、影響、解除条件。
- 次taskと最初の1操作。

最後にstateの`active_task`とleaseを解放し、generated dataを再生成してから、statusとdiffを再確認する。
