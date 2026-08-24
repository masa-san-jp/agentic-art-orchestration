# Repository instructions

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
- 原則1タスク1commit。子repo変更が必要なら親と子を別commit・別PRにする。
- 完了判定はファイルの存在ではなく、acceptanceとchecksの観察可能な結果で行う。
- セッション記憶を前提にせず、repo内のstateとhandoffだけで再開可能にする。

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
8. leaseを解放する。

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

~~~bash
python3 tools/validate.py --check
python3 -m unittest discover -s tests -v
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
