# Decision log

## D-001 — 子repoをvendor copyしない

- 日付: 2026-08-11
- 決定: 親はmanifestからrepos/へ独立cloneを展開する。
- 理由: 正本、履歴、PR、権限、Issueを各repoに維持し、二重管理を避ける。
- 却下: subtreeによる複製。同期方向と正本が曖昧になる。

## D-002 — Git submoduleをv1の必須方式にしない

- 日付: 2026-08-11
- 決定: manifest駆動cloneを採用し、snapshotでcommitを固定する。
- 理由: 子repoの独立更新ごとに親pointer commitが必要となり、自律実行・個別PR・最新追従を妨げる。
- 影響: 再現性はsnapshotのrepo/commit組で保証する。

## D-003 — 共通化は境界形式だけ

- 日付: 2026-08-11
- 決定: 各KBのcore schemaは統一せず、normalized-research-signal/v1へadapterで翻訳する。
- 理由: Self Model、芸術史、マーケティングは証拠・鮮度・同意の意味が異なる。

## D-004 — mergeとreleaseは人間ゲート

- 日付: 2026-08-11
- 決定: エージェントはbranch、commit、draft PRまで。merge、release、破壊的Git操作は人間承認を要する。
- 理由: 複数repoへ波及する不可逆変更と公開操作を分離する。

## D-005 — Project #4とローカルqueueの責任分離

- 日付: 2026-08-11
- 決定: GitHub Projects #4は人間向け優先順位と可視化の正本、task-queue.yamlは自律実行順と再開の正本とする。
- 理由: Project API障害時もローカル実行を継続しつつ、人間の優先順位を失わないため。
- 実装: project syncは冪等とし、接続不能を全体停止へ変換しない。
