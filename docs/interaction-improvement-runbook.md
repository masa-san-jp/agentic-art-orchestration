# v1.1 interaction / improvement runbook

この文書は、会話履歴を前提にせず、新しいagentが親repoの契約と生成物だけでv1.1のfrontstage/backstageを操作・検査・復旧するための実行ガイドである。子repoのschema、Issue、canonical dataは各子repoが正本であり、親repoはmanifestのprofile、source commit、adapter境界だけを保持する。

## 1. 最初の1操作と正本

最初に作業treeを変更せず確認する。

~~~bash
git status --short
~~~

次の順で読む。

1. `AGENTS.md`
2. `docs/20260811-agentic-art-orchestration-system-design-specification.md`
3. `docs/20260811-agentic-art-orchestration-repository-execution-plan.md`
4. `PLANS.md`
5. `execution/task-queue.yaml`
6. `execution/state.yaml` と `execution/handoff.md`
7. 変更対象のschema、fixture、test

`config/repositories.yaml`はrepository ID、authority、observed commit、knowledge profile、quality gateの正本である。子repoの追加はmanifestへのappendだけで行い、4つのcore IDを置換しない。`execution/task-queue.yaml`は実装順、`state.yaml`はactive leaseと再開点、`handoff.md`は人間可読の証跡である。

## 2. lane topology

利用agentはinteractionのfrontstageで人間のUIになる。retrievalは必要なrepoだけを選び、backstageのartifact保存・feedback routing・improvement・auditをユーザー応答の待ち時間へ持ち込まない。

~~~text
structured intent/capability codes
        |
        v
FRONTSTAGE_RETRIEVAL -> evidence(repo@commit, freshness, unknowns, constraints)
        |
        +-> DRIVE_ARTIFACT CREATE_ONLY -> opaque artifact reference
        +-> FEEDBACK_ROUTING -> child/parent Issue candidate or TRIAGE
                                      |
                                      v
                           AUTONOMOUS_IMPROVEMENT
                           select -> implement -> test -> gate -> draft PR plan

ASYNC_AUDIT (separate lease, non-blocking) -> Issue candidate / draft plan
~~~

共通の安全値は`interaction_blocking=false`、raw conversationをGitへ保存しないこと、user artifactを`READ_ONLY`または`CREATE_ONLY`として扱うこと、merge/releaseをhuman gateに残すことである。

## 3. repository-aware retrieval

利用agentは自由文を永続化せず、interaction中にintentとcapability codeへ変換した`retrieval-request/v1`を渡す。`tools/retrieval.py`はknowledge profileとadapter indexを照合し、要求capabilityを覆う最小repo集合だけを選ぶ。

~~~bash
.venv/bin/python tools/retrieval.py
.venv/bin/python tools/retrieval.py --check
.venv/bin/python -m unittest tests.test_retrieval -v
~~~

`data/retrieval-result.json`で確認する項目は次のとおり。

- `selected_repositories`: 過剰取得していない最小集合。
- `source_commit`: manifestのimmutable observed commitとの一致。
- `evidence[].locator`: child canonical dataを親へ複製しないlocal/opaque locator。
- `freshness_status`: `current`、`stale`、`unknown`をそのまま保持。
- `unknowns`、`domain_constraints`: 欠落や再検証条件。推測で補完しない。

`NO_MATCH`は証拠なし、`COMPLETE_WITH_GAPS`は部分的証拠または再検証が必要な状態である。どちらも正常値へ丸めない。

## 4. Google Drive artifact

ユーザー成果物の本文はGitに置かず、承認済みDrive保存先へadapter経由でCREATEする。親repoへ戻すのはartifact ID、opaque provider file ID、SHA-256、source snapshot、evidence、lineageだけである。修正版は新artifactとし、既存artifactのUPDATE/DELETEやDrive URLの代用をしない。

~~~bash
.venv/bin/python -m unittest tests.test_external_artifact_contract tests.test_drive_adapter -v
.venv/bin/python tools/interaction_e2e.py --check
~~~

同じinteraction-scoped idempotency keyと同じpayloadはmetadata-onlyのREPLAYになる。keyを使い回してpayload/metadataが変わる場合は重複作成を止める。現行fixtureは`FakeDrive`だけを使用し、実Google Driveへの書込みは行わない。実運用では保存先、access scope、consent、retentionを確認してからcreate権限だけを委譲する。

## 5. feedbackとIssue routing

feedbackは`explicit_request`等と`inferred_friction`/`inferred_need`を分離する。inferredのhypothesisは`unconfirmed`から始まり、routerがuser factへ昇格させない。

~~~bash
.venv/bin/python tools/issue_router.py
.venv/bin/python tools/issue_router.py --check
.venv/bin/python -m unittest tests.test_issue_router -v
~~~

domain content・evidence・freshness・child schemaは所有childへ、UX・retrieval・adapter・artifact・orchestrationは親へ送る。authority不明、target候補、低confidence、同意拒否はそれぞれ`TRIAGE`または`BLOCKED`に留める。`data/feedback-routing.json`の`issue_operations`は空で、候補はprivacy-safe metadataだけである。

## 6. autonomous improvement

`tools/improvement_loop.py`は`creation_permitted=true`、confirmed authority、human gate、duplicate-suppressedでないcanonical候補だけをschedulerへ渡す。worker証跡はIssue keyとbase commitで固定し、runtime lease/checkpointで再開する。

~~~bash
.venv/bin/python tools/improvement_loop.py
.venv/bin/python tools/improvement_loop.py --check
.venv/bin/python -m unittest tests.test_improvement_loop -v
~~~

状態遷移は次のように読む。

- `WAITING`: implementation/test/gateの観測が不足。次のcheckpointだけを実行する。
- `BLOCKED`: implementation、test、quality gateのいずれかが失敗または権限境界に抵触。失敗値を隠さずrepair経路を残す。
- `DRAFT_PR_READY`: implementation、test、対象repo gateがすべて`PASSED`。branchと変更pathは計画として記録されるが、remote操作は空。

draft PR planには`human_gate=true`、`merge_permitted=false`、`release_permitted=false`、`side_effect=NONE`が必要である。merge、release、公開範囲変更、同意拡張は人間の明示承認なしに進めない。

## 7. 非同期audit / refactoring

監査はinteraction laneと別の`ASYNC_AUDIT` leaseで起動する。ユーザー応答、Drive artifact、feedback routingを待たせず、findingはIssue候補またはquality gate通過後のdraft planへ変換する。

~~~bash
.venv/bin/python tools/audit.py --offline-fixture
.venv/bin/python tools/async_auditor.py --state tests/fixtures/async-audit/state.yaml --run-id AUDITOR-002:attempt-1
.venv/bin/python tools/security.py --offline-fixture
~~~

`NOT_RUN`、`FAILED`、`BLOCKED` gateをskipしてdraft PR化しない。audit結果にはsource snapshot、commit、audit hash、lease、gate statusだけを残し、Drive本文、会話全文、user artifact contentは残さない。

## 8. E2Eと復旧

全stageをnetworklessで連結するには次を実行する。

~~~bash
.venv/bin/python tools/interaction_e2e.py
.venv/bin/python tools/interaction_e2e.py --check
.venv/bin/python -m unittest tests.test_interaction_e2e -v
~~~

`data/interaction-e2e.json`で、retrievalのsource commit、artifact CREATE/REPLAY、feedback IDs、routing statuses、draft plan count、`ASYNC_AUDIT`、security PASSED、`remote_operations=[]`を確認する。

worker停止・lease expiry時は、まずstateの`execution_id`、base commit、checkpoint、evidence、lease expiryを照合する。既存treeをresetせず、次の手順で同じexecution IDを再利用する。

~~~text
observe state -> release/expire lease -> retain checkpoint -> reacquire -> resume missing step -> rerun gate
~~~

side effectの有無が不明な場合は新しいcommit、PR、artifactを作らずhuman gateへ渡す。child repoがdirty、detached、unpushed、divergedの場合は親から修復せず、対象childのownerへ返す。

## 9. 必須の最終検査とhandoff

~~~bash
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/status.py --check --offline-fixture
.venv/bin/python tools/audit.py --check --offline-fixture
.venv/bin/python tools/security.py --offline-fixture
.venv/bin/python tools/workspace.py status --json
git diff --check
~~~

handoffにはTask ID、対象repo、acceptanceの観測結果、実行commandと結果、子repoごとのbranch/HEAD/dirty状態、機微情報確認、未解決、次taskと最初の1操作を残す。親commitが未commitの場合はその事実を明記し、merge/releaseを完了と報告しない。
