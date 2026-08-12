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

## D-006 — v1.1の利用エージェントを会話型UIとする

- 日付: 2026-08-11
- 決定: 利用エージェントを単なる検索窓ではなく、人間が目的を達成するためのユーザーインターフェースとして扱う。
- 理由: repoやGit操作を利用者へ要求せず、会話から知識利用、成果物作成、feedback取得までを一つのinteractionとして成立させるため。
- 影響: interaction eventとexperience outcomeをv1.1の第一級contractにする。改善・監査の遅延は通常の会話応答をblockしない。

## D-007 — ユーザー成果物はGoogle Driveへ追記保存する

- 日付: 2026-08-11
- 決定: ユーザー体験から生まれた成果物はGoogle Driveを外部artifact正本とし、既存artifactを上書き・削除しない。
- 理由: 成果物履歴とfeedbackを失わず、Gitへ会話全文や機微本文を集約しないため。
- 実装: 親GitはDrive file ID、artifact ID、hash、provenance、access scope、derived_from/supersedesだけを保持する。Drive書込みは保存先と同意を確認したcreate-only adapter経由に限定する。

## D-008 — 暗黙feedbackは検証可能な仮説として扱う

- 日付: 2026-08-11
- 決定: 言語化されていない不満・欲求は、観測根拠とconfidenceを持つinferred feedbackとしてIssue候補化し、ユーザー事実へ自動昇格させない。
- 理由: UX改善の兆候を失わず、過剰推論や同意範囲外のself-model更新を防ぐため。

## D-009 — 改善と監査を非同期の独立laneにする

- 日付: 2026-08-11
- 決定: feedback由来の改善laneと、構造・品質を扱うaudit/refactoring laneをinteraction laneから分離する。
- 理由: ユーザー応答の待ち時間へ実装・監査を持ち込まず、Issue、lease、checkpoint、quality gateで独立再開できるようにするため。
- 影響: Issue選択、実装、test、draft PRまでは自律化できる。D-004のmerge/release人間gateは維持する。

## D-010 — 4repoをcore setとして追加型onboardingを許可する

- 日付: 2026-08-11
- 決定: manifestをexactly 4から4以上へ一般化する。既存4 IDはcore setとして必須とし、新規repoはentryをappendする。
- 理由: 将来のKB・consumer・control-plane extension追加に対応しつつ、既存の正本と依存関係を黙って置換しないため。
- 安全条件: unique ID/path/full_name/authority、role-contract整合、同一repoのIssue SSOT、immutable observed commit、instructions、quality gateを追加repoにも必須とする。
- 影響: fixtureの4repoは最小core scenarioとして維持する。実repoの追加、clone、branch、PRは別taskで明示された場合だけ行う。

## D-011 — リモートIssue #2はv1.2へ切り分ける

- 日付: 2026-08-12
- 決定: 親`agentic-art-orchestration#2`（半決定論的な制作研究パイプライン）と子`agentic-art-research#2`（自律実行v1.0 Epic）は、v1.1のrelease acceptanceには含めず、v1.2の設計・実装バックログへ切り分ける。
- 理由: v1.1はrepository-aware retrieval、append-only artifact、feedback routing、improvement、async auditのinteraction基盤を対象とし、rule engine、candidate space、seeded selection、specificity/genericness gateは別の大きな設計変更だからである。
- 安全条件: v1.1 qualification結果は変更せず、子repoのIssue・schema・canonical dataも変更しない。v1.2開始時に親Issueと子Issueをauthority、依存、quality gate、migration境界付きのtaskへ分解する。
- リモート操作: Issueのclose、label、comment、編集はこの決定では行わない。

## D-012 — v1.2は境界固定から始め、実装を依存DAGへ分解する

## D-013 — Production結線はマージ後に親mainで再確認する

- 日付: 2026-08-12
- 決定: 子repo Issue SSOTを親manifestへ追加する作業は、PR作成時点では未結線として扱い、human merge後に親mainのmanifest、merge commit、子repo pinを再確認して結線済みへ遷移させる。
- 理由: Draft PRの存在と親mainの実効設定を混同せず、レビュー・マージ境界を監査可能にするため。
- 安全条件: post-merge確認はread-onlyとし、子repoのIssue、schema、canonical data、branchは変更しない。マージ後の記録更新は別commit・別PRで行う。

- 日付: 2026-08-12
- 決定: v1.2は、境界契約、明示的変換rule、candidate space、specificity / genericness / counterfactual gate、seed付きselection、provenance、子repo品質gate、統合E2Eの順に親taskへ分解する。境界契約後に子repo品質gateを独立実行できる。
- 理由: 親Issue #2の「LLMを創作者ではなく実行系に限定する」要件と、agentic-art-research Issue #2の既存runtime/quality gateの正本性を同時に守るには、生成・選択・検証を一つの自由推論taskへまとめてはならないため。
- 安全条件: normalized research signalとsource repo@commitを入力の正本とし、子repoのcore schema・canonical data・Issueを親から変更しない。v1.1 interaction、append-only artifact、feedback、auditのrelease acceptanceは変更しない。
- 実装順: `V12-BOUNDARY-001` → `V12-TRANSFORM-001` → `V12-CANDIDATE-001` → `V12-GATES-001` → `V12-SELECTION-001` → `V12-PROVENANCE-001`。`V12-CHILD-GATES-001`はboundary後、`V12-E2E-001`はprovenanceとchild gates後に実行する。

## D-013 — Productionを双方向exchange runtimeとして追加する

- 日付: 2026-08-12
- 決定: `agentic-art-production`を既存4repo core setの置換ではなく5件目としてappendし、同一repoのIssue #10を`requirement_ssot`とする。境界は`production-handoff/v1` importと`production-result/v1` exportを一組の`exchange_contracts`として表す。
- 理由: Productionはnormalized research signalの入力KBでも単方向consumerでもない。既存roleへ偽装するとResearch→Production→Researchの責任分界が失われるため、control-plane-extensionの双方向runtimeとしてfail-closedに検証する。
- 影響: manifest schema、validator、snapshot、audit、improvement context、offline testsを同時更新する。子repoのIssue、schema、canonical data、branchは変更しない。
