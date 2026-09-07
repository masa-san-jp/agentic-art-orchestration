# Repository instructions

## AAK：自律制作と累積知識の追加系列

今回の追加要件は[仕様SSOT](docs/20260905-agentic-art-autonomy-and-knowledge-cycle-specification.md)のprinciples/authority/compatibility、実装順・検証・再開は[実装計画SSOT](docs/20260905-agentic-art-autonomy-and-knowledge-cycle-implementation-plan.md)を読む。Issue参照版は `b0e7c7f8d0a1f756fa708deef4fb380a62e45e0d`。既存機能全体の仕様を置き換えない。

芸術の契機を「精霊や風が運び、人間が受け取って具象化する」と捉えるプロジェクトの精神を維持する。外部エージェントが既存の半決定論的ハーネスを動かす。LLM/daemonの内蔵を必須にしない。

次taskは[queue](execution/task-queue.yaml)と[state](execution/state.yaml)、`.venv/bin/python tools/project_status.py --format json`から確認する。AAK-01 → AAK-03 → AAK-04以降は計画DAGの依存を満たす最小ID、AAK-02は最後。既存Issueの前提はownerのcandidate commit・contract version・受入証拠を確認し、CLOSEDだけで通過させない。

機械契約 `config/aak-task-projection.json` とqueue参照は2つのMarkdownからの実行用投影であり、第三の仕様ではない。初回は `.venv/bin/python tools/issue_intake.py --register-aak` で冪等登録する。validatorは投影・参照hash・owner・DAGを照合する。子のschema/本文を親へ複製しない。merge/release/公開/実n=1移設のhuman gateを維持する。


## Mission

**エージェントが自律的に制作プランを出力するところまで動くエージェントハーネス。作品を作る仕組みそのもの。**

これが目的である（2026-08-25 マサさんの言葉のまま）。版番号は目的ではない。以下の control plane、境界契約、品質ゲート、qualification は、すべてこの目的のための手段である。

要件は README の「要件」節を正とする。読まずに着手しない。

## Read order

1. docs/20260811-agentic-art-orchestration-system-design-specification.md
2. docs/20260811-agentic-art-orchestration-repository-execution-plan.md
3. PLANS.md
4. execution/task-queue.yaml
5. execution/state.yaml と execution/handoff.md
6. 変更対象に最も近いschema、文書、テスト

## Task selection

- 依存がすべてDONEである最小IDのREADYタスクを1件選ぶ。
- READYがなく、依存完了済みBACKLOGがある場合は、最小IDをREADYにする。
- READYも依存完了済みBACKLOGもない場合は、`.venv/bin/python tools/issue_intake.py`で未登録のopen Issueをread-only観測し、SSOT最低要件を満たすIssueだけを依存関係付きで`task-queue.yaml`へBACKLOG/READY登録するcommitを1つ作る。登録だけを行い、実装は次のtaskで行う。

Issue SSOTの最低要件は、(1)観測可能な受入条件、(2)対象repository、(3)検証コマンド、(4)human gateの有無、の4点である。欠落Issueはqueueへ登録せず、intake reportで`UNQUEUED_NEEDS_SSOT`と不足項目を残す。Issueコメントによる要求はtaskで明示された場合だけ行い、Issue本文全文は親へコピーしない。
- 原則1タスク1commit。子repo変更が必要なら親と子を別commit・別PRにする。
- 完了判定はファイルの存在ではなく、acceptanceとchecksの観察可能な結果で行う。
- セッション記憶を前提にせず、repo内のstateとhandoffだけで再開可能にする。

## Production planning mode

このrepoを利用するエージェントとして起動された場合、ユーザーにテーマ・repo名・slug・titleを質問しない。READMEと`docs/agent-runtime-guide.md`のテーマ未指定入口を実行し、pin済みsignalからgate通過候補を選び、候補由来の`creative_question`をテーマ案としてResearchへ渡す。明示intentは任意の順位付け入力であり、必須ではない。startupがBLOCKEDの場合はテーマやPLAN_READYを捏造せず、観測された解除条件を返す。

## Work protocol

~~~text
inspect → claim → lock → edit → test → child-gates → diff → record → release
~~~

1. 親の仕様、task、対象子repoのAGENTS/Issue SSOT/testsを読む。
2. stateにtask、対象repo、開始点、想定変更を記録する。
3. 同じrepo/pathを扱うactive leaseがないことを確認する。
4. 最小差分で実装する。
5. 親checkと変更した各子repoの品質ゲートを実行する。
6. repoごとのGit状態と差分を個別確認する。
7. task、判断、発見、commit、テスト、次の開始点を更新する。
8. `state.yaml`、`handoff.md`、`task-queue.yaml`を含む実行SSOTのcommitを、lease解放前に作業branchからoriginへ通常のfast-forward pushで公開する。force pushと既定branchへの直接pushは禁止し、pushまたはremote確認ができない場合は`UNKNOWN`／未pushを記録してleaseを解放せず停止する。
9. leaseを解放する。

## Ownership and authority

- repositories.yamlは統合対象と取得方針の正本。
- 既存4repoはcore setとして保持し、追加repoはmanifest validation、knowledge profile、snapshot、個別quality gateを通してappendする。既存entryとの置換で追加しない。
- 子repoの要件・schema・データは常に子repoが正本。
- normalized research signalは境界形式だけを規定し、子の内部schemaを上書きしない。
- task-queue.yamlは親repo実装順の正本。
- state.yamlは現在の再開点、handoff.mdは人間可読の引継ぎ。
- data/とrepos/は生成物。手編集しない。
- Google Drive上の成果物は外部artifactの正本。親はopaque ID、hash、provenance、access scopeだけを保持する。
- 明示・推定feedbackの実行順はtask-queue.yaml、domain内容の採否は対象子repoのIssue/PRが正本。

## Safety invariants

- 子repoを親履歴へvendor copyしない。
- PRIVATE_RAW、RESTRICTED、個人識別情報、認証情報を親へ集約しない。
- dirtyな子repo、detached HEAD、未push commit、branch不一致を黙って変更しない。
- hard reset、強制push、branch削除、Issue/PR削除を自動実行しない。
- すべての入力にrepo IDとsource commitを付ける。
- marketingの鮮度切れ、self-modelの同意範囲外、art-historyの根拠不足を正常値へ変換しない。
- 失敗した品質ゲートをskip・削除して通したことにしない。
- branch作成・commit・draft PRまではtaskで明示された場合に限る。merge、release、削除は人間承認を要する。
- 利用エージェントはユーザー体験を優先し、改善・監査処理を同期実行して応答を不必要に待たせない。
- Drive artifactはcreate-onlyとし、修正は新artifact + derived_from/supersedesで表す。既存artifactを上書き・削除しない。
- 会話全文をGitへ保存しない。暗黙の不満・欲求は根拠とconfidenceを持つ仮説として扱い、ユーザー事実へ昇格させない。

## Stop conditions

次だけはBLOCKEDにして停止する。質問だけを残さず、観測事実、選択肢、推奨、影響、解除条件を記録する。

- 子repoのIssue SSOT同士が両立せず、adapterで解決できない。
- 機微情報の外部送信、同意拡張、公開範囲変更が必要。
- 破壊的Git操作、既定branchへのmerge、releaseが必要。
- データ損失または不可逆なschema migrationの可能性がある。
- 認証・権限がなく、read-onlyの代替でも受入条件を満たせない。
- acceptanceが相互矛盾し、保守的既定値でも解消できない。
- Driveへの外部送信に必要な同意・保存先・権限が確定していない。
- 推定feedbackだけを根拠に同意範囲、公開範囲、ユーザー属性を変更する必要がある。

## Required checks

Fresh cloneでは、まず[README.mdの正準bootstrap](README.md#ブートストラップ検証)を上から実行する。READMEにはrepo内`.venv`の作成と依存関係準備を含める。full suiteまで行う場合は、同じ節のoffline fixture生成を先に完了する。GitHub認証がない場合の子repo確認はREADME記載の`--offline-fixture`経路を使い、システムPythonへ依存関係をインストールしない。

~~~bash
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest discover -s tests -v
~~~

workspace実装後は workspace status、audit、変更子repoのmanifest記載commandも実行する。
interaction実装後はnetworkless fake Drive、append-only artifact、feedback routing、interaction E2Eも実行する。

## Completion report

- Task ID
- 対象repo
- 観察可能な変更
- acceptance達成数
- 親検証と子品質ゲート
- repoごとのcommit SHA
- 機微情報確認
- 外部artifactのcreate-only確認とopaque参照
- explicit/inferred feedbackの区別
- 未解決
- 次taskと最初の1操作
