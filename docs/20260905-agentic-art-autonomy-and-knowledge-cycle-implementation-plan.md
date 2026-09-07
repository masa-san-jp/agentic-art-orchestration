# Agentic Art：自律制作と累積知識の実装計画

作成日: 2026-09-05  
計画ID: AAK-PLAN / version: 1  
仕様SSOT: [20260905-agentic-art-autonomy-and-knowledge-cycle-specification.md](20260905-agentic-art-autonomy-and-knowledge-cycle-specification.md)  
この文書はAAK-01〜13の実装順・作業単位・検証・再開の正本。仕様の意味・受入条件は仕様SSOTに置き、ここで独自に変更しない。

## starting-point

1. 自分のIssueにpinされた仕様と本計画の同一commitを読み、共通節と対応AAK節を確認する。
2. ownerのAGENTS/README、領域schema、task queue/stateを読む。仕様のbaselineとの差分、既存Issue・PRの現状を観測する。
3. 本計画の依存表を実装依存として扱う。Issue番号の大小は実装順ではない。OPEN/CLOSEDだけで通過を判断せず、ownerが検証したcandidate commit・受入証拠・contract versionを照合する。
4. 依存が未完了でも読取・差分設計・fixture作成はできる。依存済みを偽装して結合受入を通したり、別repoの領域実装をコピーしたりしない。
5. 通常のタスク登録を行い、専用branch/worktreeで一つのIssueの範囲を実装する。ownerのschema/validator/export/documentationを同じ変更単位で整合させる。
6. 対応する受入IDと検証コマンドを実行し、結果・candidate commit・入力snapshot・成果物hashをdraft PRへ残す。未実施は未実施として記録する。

新しく追加するtests.* moduleは、各Issueの受入条件を検証する実装対象であり、baselineに存在するという主張ではない。実装前に存在しないmoduleの実行失敗を既存コードの故障としない。runtime/venv/uvの準備とcanonical fixture生成は各repoのREADME/AGENTSに従い、コマンドを見かけ上成功させるためにgateを省略しない。

## issue-index

<!-- AAK-ISSUE-INDEX-START -->
| ID | owner | Issue | 要点 | 起票時の実装状態 |
|---|---|---|---|---|
| AAK-01 | agentic-art-orchestration | [#194](https://github.com/masa-san-jp/agentic-art-orchestration/issues/194) | 設計原則・仕様SSOT・実装DAGをエージェントの正準入口へ接続する | 起票済み・未実装 |
| AAK-02 | agentic-art-orchestration | [#197](https://github.com/masa-san-jp/agentic-art-orchestration/issues/197) | 実エージェントで制作プラン出力・蓄積・次回再利用を自律完走させる | 起票済み・未実装 |
| AAK-03 | agentic-art-orchestration | [#195](https://github.com/masa-san-jp/agentic-art-orchestration/issues/195) | 全8repoの生成物蓄積・還流・検索の共通契約を実装する | 起票済み・未実装 |
| AAK-04 | agentic-art-orchestration | [#196](https://github.com/masa-san-jp/agentic-art-orchestration/issues/196) | 本人継続利用・clone・forkの利用者別初期化と蓄積保持を実装する | 起票済み・未実装 |
| AAK-05 | self-model-notes | [#93](https://github.com/masa-san-jp/self-model-notes/issues/93) | 本人別の感性・制作選択を蓄積し、出典と不確実性を保って自己モデルへ反映する | 起票済み・未実装 |
| AAK-06 | art-history-notes | [#386](https://github.com/masa-san-jp/art-history-notes/issues/386) | 制作研究の美術史知識を根拠付きで取り込み、次回探索へ還流する | 起票済み・未実装 |
| AAK-07 | marketing-trends-notes | [#86](https://github.com/masa-san-jp/marketing-trends-notes/issues/86) | 制作研究から社会・受容の変化を蓄積し、鮮度を再検証して再利用する | 起票済み・未実装 |
| AAK-08 | agentic-art-research | [#93](https://github.com/masa-san-jp/agentic-art-research/issues/93) | 調査・仮説・採否・未解決の問いを永続蓄積し次の研究へ再投入する | 起票済み・未実装 |
| AAK-09 | agentic-art-research | [#94](https://github.com/masa-san-jp/agentic-art-research/issues/94) | 蓄積を再利用しながら固有性・機構の接地・探索の幅を検証する | 起票済み・未実装 |
| AAK-10 | agentic-art-production | [#61](https://github.com/masa-san-jp/agentic-art-production/issues/61) | 研究要件から実制作可能な統合プランを生成し内容の完全性を検証する | 起票済み・未実装 |
| AAK-11 | agentic-art-production | [#62](https://github.com/masa-san-jp/agentic-art-production/issues/62) | 制作・試作・失敗の知識を条件付きで蓄積し次の計画に反映する | 起票済み・未実装 |
| AAK-12 | viewer-response-notes | [#6](https://github.com/masa-san-jp/viewer-response-notes/issues/6) | 鑑賞者反応を作品・意図・展示条件別に蓄積し次の研究へ還流する | 起票済み・未実装 |
| AAK-13 | agentic-art-project | [#10](https://github.com/masa-san-jp/agentic-art-project/issues/10) | 公開プランと作品の系譜を帰属付きで蓄積し、検証済み履歴を再参照可能にする | 起票済み・未実装 |
<!-- AAK-ISSUE-INDEX-END -->

この表の状態は起票時のsnapshot。進行状態はowner queueと検証証拠の正本を参照する。仕様文書を置いたdraft PRは全13Issueの実装完了ではなく、closeキーワードを使わない。

## dependency-dag

| task | owner | 本系列の前提 | 既存Issueの前提 |
|---|---|---|---|
| [AAK-01](#aak-01) | agentic-art-orchestration | なし | なし |
| [AAK-02](#aak-02) | agentic-art-orchestration | [AAK-05](#aak-05), [AAK-06](#aak-06), [AAK-07](#aak-07), [AAK-09](#aak-09), [AAK-11](#aak-11), [AAK-12](#aak-12), [AAK-13](#aak-13) | [agentic-art-orchestration#189](https://github.com/masa-san-jp/agentic-art-orchestration/issues/189), [agentic-art-orchestration#193](https://github.com/masa-san-jp/agentic-art-orchestration/issues/193), [agentic-art-orchestration#187](https://github.com/masa-san-jp/agentic-art-orchestration/issues/187) |
| [AAK-03](#aak-03) | agentic-art-orchestration | [AAK-01](#aak-01) | なし |
| [AAK-04](#aak-04) | agentic-art-orchestration | [AAK-03](#aak-03) | [agentic-art-orchestration#190](https://github.com/masa-san-jp/agentic-art-orchestration/issues/190) |
| [AAK-05](#aak-05) | self-model-notes | [AAK-04](#aak-04) | なし |
| [AAK-06](#aak-06) | art-history-notes | [AAK-04](#aak-04) | なし |
| [AAK-07](#aak-07) | marketing-trends-notes | [AAK-04](#aak-04) | なし |
| [AAK-08](#aak-08) | agentic-art-research | [AAK-04](#aak-04) | なし |
| [AAK-09](#aak-09) | agentic-art-research | [AAK-08](#aak-08), [AAK-05](#aak-05), [AAK-06](#aak-06), [AAK-07](#aak-07) | なし |
| [AAK-10](#aak-10) | agentic-art-production | [AAK-09](#aak-09) | [agentic-art-production#60](https://github.com/masa-san-jp/agentic-art-production/issues/60) |
| [AAK-11](#aak-11) | agentic-art-production | [AAK-10](#aak-10) | なし |
| [AAK-12](#aak-12) | viewer-response-notes | [AAK-04](#aak-04) | なし |
| [AAK-13](#aak-13) | agentic-art-project | [AAK-04](#aak-04) | [agentic-art-project#6](https://github.com/masa-san-jp/agentic-art-project/issues/6) |

同一ready集合ではID昇順を選ぶ。AAK-02は統合受入なので最後になる。

| 段階 | task | 段階の出口 |
|---|---|---|
| 1 | AAK-01 | 原則/仕様/計画を既存の開始手順とqueueへ接続 |
| 2 | AAK-03 | 共通交換・receipt・索引・dispatchをsynthetic ownerで検証 |
| 3 | AAK-04 | 利用者別profileとcode/knowledge refの分離を検証 |
| 4 | AAK-05/06/07/08/12/13 | ownerごとの蓄積・再読込・分離を検証 |
| 5 | AAK-09 | 累積知識を参照する研究の固有性/接地を検証 |
| 6 | AAK-10 → AAK-11 | 制作可能なplan、その経験の蓄積と再利用を検証 |
| 7 | AAK-02 | 3モード×2runの実エージェント統合受入 |

AAK-03/04が子owner実装を待つ循環を作らない。ここではversioned境界とsynthetic adapterを完了できる。子repoはその契約を実装し、AAK-02が実ownerを接続して最終確認する。AAK-10は既知knowledge fixtureで参照要件を確認し、AAK-11が実際のProduction保存/検索を実装する。

既存のplan正本証明・投影・受信（Production#60 → 親#193 / Project#6）とprofile/registry（親#190）は、そのownerの現行契約を完了させる。本系列は該当する依存点で受け取る。既存Issueへ新系列の依存を逆向きに追加して循環させない。将来追加のcatalog-reference能力は既存export-only projectionの実装を止める条件ではない。

## native-task-contracts

| owner | 登録・配送 |
|---|---|
| Orchestration | Issue intakeのtarget/acceptance/checks/human gateを満たす。AAK-01で既存queue/stateへ参照を登録 |
| Self Model | tools/task_harness.pyとexecution/tasks.yamlの正規手順で新task化。要件Issue#1への限定拡張参照を同期 |
| Art History | agent-task:v2 YAMLが機械実行契約。本文外側の説明にだけ要件を置かず、仕様pin・外部依存・全要件をYAMLへ投影 |
| Marketing | agent-task/v1、10必須節、agent-task label。依存完了前にagent-readyを手動付与しない |
| Research / Production | 既存AGENTS/PLANSとqueue/stateの最小taskへ登録。project runtimeの外部配置を維持したままknowledge規則を追加 |
| Viewer | 既存schemaとtool契約に従う。docs/configの追加を含むscopeはAAK-12で明示許可 |
| Project | 既存READMEとcatalogが入口。AAK-13でAGENTSを追加しreceiverとread-only exportを説明 |

Art Historyのdepends_onは同repo整数Issueのみを受けるため、cross-repo依存は要件内に正確なURLと着手条件を記す。親DAGが横断依存を解決する。YAML外に同じ文章を編集して契約を変えたことにしない。Marketingは実際のIssue本文もvalidatorで検証し、fixtureだけで本文の適合を主張しない。

## delivery-evidence

各Issueは最低限、次の証拠を残す。

- 仕様/計画の参照commit、task ID、ownerのcandidate code commit、入力fixture/knowledge revision。
- 受入IDごとのPASS/FAIL/NOT_RUNと該当test・CLI・出力参照。失敗した初回と修正後の最終結果は区別する。
- Git再読込・索引再構築・再実行など、当該taskのリスクを確認した結果。単に関数の実装をなぞるテストを増やさない。
- 必要なmigrationのdry-run、互換性、失効処理、rollback/retryの観測結果。
- 未解決blocker、次の正確な操作、人間の承認が必要ならその既存ルールと理由。

rawやcredentialをPR evidenceへ含めない。privacy-safe fixtureやhash/record ID/opaque locatorで示す。受入が通っていない状態はCODE_VERIFIED/INCOMPLETE等で示し、DONE/COMPLETEDとしない。

## resume-and-change-control

中断時はtask/run ID・base/candidate commit・receipt・次工程をowner stateへ保存し、既存lease/claimに従って再取得する。ユーザーの既存worktreeをresetして再開しない。planが完成済みでknowledge保存が一部失敗した場合は、そのplanと成功receiptを保持してpending ownerだけを再試行する。

仕様を改訂する場合は、同一SSOTファイルでversion/変更理由/影響AAK IDを更新し、仕様pin、Issue投影、machine contract、queueの参照/hashを同じ変更系列で同期する。Issueコメント、子README、PR説明だけに追加要求を残さない。owner schemaの実装上のフィールド名等はownerで決定するが、共通境界・identity・epistemic state・完了条件を独自に弱めない。

## human-gate

ローカル実装・テスト・作業branch・commit・draft PRを進める。既定branchへの直接push、merge/release、外部公開、実n=1移設はこのIssueの完了作業に含めず、既存のhuman gateを維持する。通常の設計選択・可逆修復・合成fixtureの検証で停止しない。

LLM/daemonの必須内蔵、作品の物理制作・購入・展示、実個人rawデータ移設、repoの可視性変更・公開、他人のprofile転用、既存thresholdの根拠なし緩和は対象外。

## task-plans

以下の各節は対応Issueの実装手順正本。新しいトップレベルpathはscopeに列挙されたものだけを許す。既存生成graph/indexはcanonical toolで再生成し、手編集しない。scopeの広いglobは列挙要件に必要な変更だけを許し、無関係な全体リファクタリングを許可しない。

## aak-01

対象: `masa-san-jp/agentic-art-orchestration`  
仕様: [AAK-01](20260905-agentic-art-autonomy-and-knowledge-cycle-specification.md#aak-01)  
前提: なし

### 最初に読むファイル

- `AGENTS.md`
- `README.md`
- `PLANS.md`
- `execution/task-queue.yaml`
- `execution/state.yaml`
- `docs/20260811-agentic-art-orchestration-system-design-specification.md`

### 変更対象

`README.md`, `AGENTS.md`, `PLANS.md`, `docs/**`, `config/**`, `schemas/**`, `tools/issue_intake.py`, `tools/validate.py`, `tools/project_status.py`, `tests/**`, `execution/**`

### 実装手順

1. 新SSOTと既存設計の差分・優先順位を読む。
2. 追加系列のtask IDと依存をqueueへ登録する正規手順を作る。
3. README/AGENTS/旧仕様からSSOTへリンクし、task投影の整合検査を追加する。
4. DAG・リンク・既存validatorを検証し、再開点を記録する。

### 検証コマンド

新規受入module: `tests.test_knowledge_cycle_contracts`。仕様のAAK-01-AC各項目へtest名/証拠を対応付ける。

```bash
.venv/bin/python -m unittest tests.test_knowledge_cycle_contracts -v
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

## aak-02

対象: `masa-san-jp/agentic-art-orchestration`  
仕様: [AAK-02](20260905-agentic-art-autonomy-and-knowledge-cycle-specification.md#aak-02)  
前提: [AAK-05](#aak-05), [AAK-06](#aak-06), [AAK-07](#aak-07), [AAK-09](#aak-09), [AAK-11](#aak-11), [AAK-12](#aak-12), [AAK-13](#aak-13), [agentic-art-orchestration#189](https://github.com/masa-san-jp/agentic-art-orchestration/issues/189), [agentic-art-orchestration#193](https://github.com/masa-san-jp/agentic-art-orchestration/issues/193), [agentic-art-orchestration#187](https://github.com/masa-san-jp/agentic-art-orchestration/issues/187)

### 最初に読むファイル

- `AGENTS.md`
- `README.md`
- `docs/agent-runtime-guide.md`
- `tools/run.py`
- `tools/autonomous_runner.py`
- `tools/batch_run.py`
- `tools/public_projection.py`
- `tests/test_autonomous_runner.py`

### 変更対象

`tools/**`, `config/**`, `schemas/**`, `tests/**`, `docs/**`, `README.md`, `AGENTS.md`, `PLANS.md`, `execution/**`

### 実装手順

1. 依存Issueの受入証拠とcandidate commitで隔離workspaceを構成する。
2. 外部エージェントの最小開始指示とnext_action連携を実装する。
3. plan/knowledge/projectionの独立完了検査と再開を接続する。
4. artifact欠落・中断・別利用者混入の統合回帰を実行する。
5. 3モード×2runの実エージェント試験を行い、全requirementsと証拠を照合する。

### 検証コマンド

新規受入module: `tests.test_knowledge_cycle_e2e`。仕様のAAK-02-AC各項目へtest名/証拠を対応付ける。

```bash
.venv/bin/python -m unittest tests.test_knowledge_cycle_e2e -v
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

fake回帰の成功後、仕様acceptance-matrixの各ケースを実エージェントで実施する。profile同意・予算・利用可能providerを初期条件として記録し、以後の工程はエージェントがnext_actionから進める。実Masa profileが使えない場合は合成継続利用と明示し、本人実データ検証の未実施を残す。外部エージェントが実行できない環境で最終受入を完了したと宣言しない。

## aak-03

対象: `masa-san-jp/agentic-art-orchestration`  
仕様: [AAK-03](20260905-agentic-art-autonomy-and-knowledge-cycle-specification.md#aak-03)  
前提: [AAK-01](#aak-01)

### 最初に読むファイル

- `AGENTS.md`
- `config/repositories.yaml`
- `tools/retrieval.py`
- `tools/ingest_signals.py`
- `tools/issue_intake.py`

### 変更対象

`config/**`, `schemas/**`, `tools/**`, `tests/**`, `docs/**`, `README.md`, `AGENTS.md`, `PLANS.md`, `execution/**`, `knowledge/**`

### 実装手順

1. 共通境界schema、registry、整合性のfixtureを実装する。
2. owner呼出しと冪等receipt、検索索引の共通契約を実装する。
3. Orchestrationの運用知識ownerを追加する。
4. synthetic ownerで全境界・復旧・失効を試験する。実owner統合はAAK-02で検証する。

### 検証コマンド

新規受入module: `tests.test_knowledge_cycle_contracts`。仕様のAAK-03-AC各項目へtest名/証拠を対応付ける。

```bash
.venv/bin/python -m unittest tests.test_knowledge_cycle_contracts -v
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

## aak-04

対象: `masa-san-jp/agentic-art-orchestration`  
仕様: [AAK-04](20260905-agentic-art-autonomy-and-knowledge-cycle-specification.md#aak-04)  
前提: [AAK-03](#aak-03), [agentic-art-orchestration#190](https://github.com/masa-san-jp/agentic-art-orchestration/issues/190)

### 最初に読むファイル

- `AGENTS.md`
- `tools/workspace.py`
- `tools/output_destinations.py`
- `config/output-destinations.example.yaml`
- `config/repositories.yaml`

### 変更対象

`config/**`, `schemas/**`, `tools/**`, `tests/**`, `docs/**`, `README.md`, `AGENTS.md`, `PLANS.md`, `execution/**`

### 実装手順

1. profileの互換adapterとidentity/owner mappingを実装する。
2. 3モードの初期化・再開を既存bootstrapへ接続する。
3. knowledge用の明示storeとcode用隔離worktreeを分離する。
4. mode混入・更新・migrationの回帰試験と最小操作手順を整える。

### 検証コマンド

新規受入module: `tests.test_instance_profiles`。仕様のAAK-04-AC各項目へtest名/証拠を対応付ける。

```bash
.venv/bin/python -m unittest tests.test_instance_profiles -v
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

## aak-05

対象: `masa-san-jp/self-model-notes`  
仕様: [AAK-05](20260905-agentic-art-autonomy-and-knowledge-cycle-specification.md#aak-05)  
前提: [AAK-04](#aak-04)

### 最初に読むファイル

- `AGENTS.md`
- `docs/schema.md`
- `tools/profile_root.py`
- `tools/export_signals.py`
- `tools/task_harness.py`
- `execution/tasks.yaml`

### 変更対象

`AGENTS.md`, `README.md`, `docs/**`, `tools/**`, `tests/**`, `config/**`, `schemas/**`, `execution/**`, `pyproject.toml`, `entities/**`

### 実装手順

1. 仕様authorityの限定更新と既存task_harnessへの新task登録を行う。
2. 派生knowledge storeとcreation-feedback intakeのschema/validatorを追加する。
3. 本人scope別の再計算・export・失効を実装する。
4. 合成A/BとGit再読込で境界・再利用・互換性を検証する。

### 検証コマンド

新規受入module: `tests.test_creative_feedback_memory`。仕様のAAK-05-AC各項目へtest名/証拠を対応付ける。

```bash
python3 tools/agent_runtime.py -m unittest tests.test_creative_feedback_memory -v
python3 tools/agent_runtime.py -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

## aak-06

対象: `masa-san-jp/art-history-notes`  
仕様: [AAK-06](20260905-agentic-art-autonomy-and-knowledge-cycle-specification.md#aak-06)  
前提: [AAK-04](#aak-04)

### 最初に読むファイル

- `AGENTS.md`
- `README.md`
- `docs/schema.md`
- `docs/agent/task-contract.md`
- `docs/agent/README.md`
- `tools/export_signals.py`

### 変更対象

`AGENTS.md`, `README.md`, `docs/**`, `tools/**`, `tests/**`, `config/**`, `entities/**`, `contexts/**`, `data/**`, `overviews/**`

### 実装手順

1. 既存schemaに対するintake写像とowner metadataを設計する。
2. 重複・競合・出典検証を実装する。
3. 既存graph/exportへ接続する。
4. 新しい知識の取込→Git再読込→次回検索をfixtureで検証する。

### 検証コマンド

新規受入module: `tests.test_research_knowledge_intake`。仕様のAAK-06-AC各項目へtest名/証拠を対応付ける。

```bash
uv run --locked python -m unittest tests.test_research_knowledge_intake -v
uv run --locked python tools/verify.py
uv run --locked python tools/test_agent_readiness.py
git diff --check
```

追加で実Issue本文をローカルfileへ取得し、tools/agent_task.pyのvalidate --fileで契約適合を確認する。canonical checkを省略せず、generated KB差分は既存toolで生成する。

## aak-07

対象: `masa-san-jp/marketing-trends-notes`  
仕様: [AAK-07](20260905-agentic-art-autonomy-and-knowledge-cycle-specification.md#aak-07)  
前提: [AAK-04](#aak-04)

### 最初に読むファイル

- `AGENTS.md`
- `README.md`
- `docs/schema.md`
- `docs/freshness.md`
- `docs/agent-task-contract.md`
- `tools/export_signals.py`

### 変更対象

`AGENTS.md`, `README.md`, `docs/**`, `tools/**`, `tests/**`, `config/**`, `entities/**`, `data/**`, `overviews/**`, `Makefile`

### 実装手順

1. agent-task/v1と既存schemaの差分を確認する。
2. 候補intake、重複照合、観測revisionを実装する。
3. freshness再検証taskとexportに接続する。
4. 固定時刻のfixtureで再利用と誤昇格防止を検証する。

### 検証コマンド

新規受入module: `tests.test_research_knowledge_intake`。仕様のAAK-07-AC各項目へtest名/証拠を対応付ける。

```bash
.venv/bin/python -m unittest tests.test_research_knowledge_intake -v
make test
make agent-verify ISSUE_BODY=tests/fixtures/issues/valid.md NOW=2026-09-05
git diff --check
```

追加で実Issue本文を一時fileへ取得し、tools/validate_agent_issue.py --body-fileの引数として指定して検証する。make agent-verifyのvalid.mdは既存fixtureの回帰であり、実Issue本文検証を代替しない。live時点のfreshnessは実行日時で評価し、上記NOWは再現用fixtureだけに用いる。

## aak-08

対象: `masa-san-jp/agentic-art-research`  
仕様: [AAK-08](20260905-agentic-art-autonomy-and-knowledge-cycle-specification.md#aak-08)  
前提: [AAK-04](#aak-04)

### 最初に読むファイル

- `AGENTS.md`
- `docs/project-output-boundary.md`
- `docs/20260811-agentic-art-research-system-design-specification.md`
- `tools/next_action.py`
- `tools/self_repetition.py`
- `tools/context_pack.py`

### 変更対象

`AGENTS.md`, `README.md`, `PLANS.md`, `docs/**`, `config/**`, `schemas/**`, `tools/**`, `tests/**`, `execution/**`, `knowledge/**`

### 実装手順

1. knowledge保存分類と既存output規則の限定改訂を実装する。
2. record生成・owner intake・Git commit receipt・索引を接続する。
3. next_action/context_pack/self_repetitionへ過去知識取得を接続する。
4. 棄却理由別の再利用とsource訂正時の再検証を試験する。

### 検証コマンド

新規受入module: `tests.test_research_memory`。仕様のAAK-08-AC各項目へtest名/証拠を対応付ける。

```bash
.venv/bin/python -m unittest tests.test_research_memory -v
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

## aak-09

対象: `masa-san-jp/agentic-art-research`  
仕様: [AAK-09](20260905-agentic-art-autonomy-and-knowledge-cycle-specification.md#aak-09)  
前提: [AAK-08](#aak-08), [AAK-05](#aak-05), [AAK-06](#aak-06), [AAK-07](#aak-07)

### 最初に読むファイル

- `AGENTS.md`
- `tools/self_repetition.py`
- `config/task-roles.yaml`
- `tools/complete.py`
- `tools/validate.py`
- `docs/20260811-agentic-art-research-system-design-specification.md`

### 変更対象

`AGENTS.md`, `README.md`, `PLANS.md`, `docs/**`, `config/**`, `schemas/**`, `tools/**`, `tests/**`, `execution/**`

### 実装手順

1. 既存検査とknowledge索引の共通参照を接続する。
2. origin/creator別比較とsource独立性を検証する。
3. 探索policyを版管理し、代表fixtureで根拠を記録する。
4. 機構重複・入力差替え・未読履歴の反例試験を実行する。

### 検証コマンド

新規受入module: `tests.test_cumulative_specificity`。仕様のAAK-09-AC各項目へtest名/証拠を対応付ける。

```bash
.venv/bin/python -m unittest tests.test_cumulative_specificity -v
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest discover -s tests -v
git diff --check
```

## aak-10

対象: `masa-san-jp/agentic-art-production`  
仕様: [AAK-10](20260905-agentic-art-autonomy-and-knowledge-cycle-specification.md#aak-10)  
前提: [AAK-09](#aak-09), [agentic-art-production#60](https://github.com/masa-san-jp/agentic-art-production/issues/60)

### 最初に読むファイル

- `AGENTS.md`
- `tools/build_plan.py`
- `docs/20260811-agentic-art-production-implementation-contract-specification.md`
- `docs/20260811-agentic-art-production-system-design-specification.md`
- `docs/schema-reference.md`

### 変更対象

`AGENTS.md`, `README.md`, `PLANS.md`, `docs/**`, `config/**`, `schemas/**`, `tools/**`, `tests/**`, `execution/**`

### 実装手順

1. 既存plan schemaとResearch requirementのcoverageを確認する。
2. 媒体別必須性とgap/blocker、作業依存を検証する。
3. visual packageとattestationへ接続する。
4. 異なる媒体のpositive/negative fixtureと正規rendererで受入確認する。

### 検証コマンド

新規受入module: `tests.test_plan_actionability`。仕様のAAK-10-AC各項目へtest名/証拠を対応付ける。

```bash
.venv/bin/python -m unittest tests.test_plan_actionability -v
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/run_evaluation.py --format json
git diff --check
```

## aak-11

対象: `masa-san-jp/agentic-art-production`  
仕様: [AAK-11](20260905-agentic-art-autonomy-and-knowledge-cycle-specification.md#aak-11)  
前提: [AAK-10](#aak-10)

### 最初に読むファイル

- `AGENTS.md`
- `tools/build_plan.py`
- `tools/build_result.py`
- `tools/export_result.py`
- `docs/20260811-agentic-art-production-implementation-contract-specification.md`

### 変更対象

`AGENTS.md`, `README.md`, `PLANS.md`, `docs/**`, `config/**`, `schemas/**`, `tools/**`, `tests/**`, `execution/**`, `knowledge/**`

### 実装手順

1. 観察/resultからknowledgeへの写像と検証を追加する。
2. owner store、索引、Git commit receiptを実装する。
3. plan生成へ条件照合と採否記録を接続する。
4. 予定/実績混同、revision、再利用の回帰を試験する。

### 検証コマンド

新規受入module: `tests.test_production_memory`。仕様のAAK-11-AC各項目へtest名/証拠を対応付ける。

```bash
.venv/bin/python -m unittest tests.test_production_memory -v
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/run_evaluation.py --format json
git diff --check
```

## aak-12

対象: `masa-san-jp/viewer-response-notes`  
仕様: [AAK-12](20260905-agentic-art-autonomy-and-knowledge-cycle-specification.md#aak-12)  
前提: [AAK-04](#aak-04)

### 最初に読むファイル

- `AGENTS.md`
- `README.md`
- `schemas/viewer-response-record.schema.json`
- `schemas/viewer-response-assessment.schema.json`
- `tools/validate.py`
- `tools/export_signals.py`

### 変更対象

`AGENTS.md`, `README.md`, `docs/**`, `config/**`, `schemas/**`, `tools/**`, `tests/**`, `records/**`, `assessments/**`, `exports/**`

### 実装手順

1. 条件/作品系譜のopaque参照と重複キーを既存schemaへ追加する。
2. 訂正・失効とassessment/exportの整合を実装する。
3. owner intakeと次回取得を境界fixtureで接続する。
4. aggregate-only、sample重複、未知状態の回帰を検証する。

### 検証コマンド

新規受入module: `tests.test_viewer_memory`。仕様のAAK-12-AC各項目へtest名/証拠を対応付ける。

```bash
python3 -m unittest tests.test_viewer_memory -v
python3 tools/validate.py --check
python3 -m unittest discover -s tests -v
git diff --check
```

## aak-13

対象: `masa-san-jp/agentic-art-project`  
仕様: [AAK-13](20260905-agentic-art-autonomy-and-knowledge-cycle-specification.md#aak-13)  
前提: [AAK-04](#aak-04), [agentic-art-project#6](https://github.com/masa-san-jp/agentic-art-project/issues/6)

### 最初に読むファイル

- `README.md`
- `docs/repositories.yaml`
- `public-project.yaml`
- `plans/index.yaml`
- `works/index.yaml`
- `tools/catalog_sync.py`

### 変更対象

`AGENTS.md`, `README.md`, `docs/**`, `config/**`, `schemas/**`, `tools/**`, `tests/**`, `public-project.yaml`, `plans/**`, `works/**`

### 実装手順

1. #6の受信契約へorigin/creator/lineageの補完metadataを追加する。
2. 既存record分類と移行dry-runを実装する。
3. read-only履歴exportを別能力として実装する。
4. fork/衝突/改訂と既存catalog互換を検証し、エージェント開始手順を整える。

### 検証コマンド

新規受入module: `tests.test_catalog_lineage`。仕様のAAK-13-AC各項目へtest名/証拠を対応付ける。

```bash
python3 -m unittest tests.test_catalog_lineage -v
python3 tools/validate.py --check
python3 tools/catalog_sync.py --check
python3 -m unittest discover -s tests -v
git diff --check
```

tools/validate.pyは前提Project#6のreceiver実装を確認して使う。未実装なら依存未解決として扱い、commandを削除して完了条件を緩めない。移行は既存IDと作者を保存するdry-runから始める。

## change-log

- v1 / 2026-09-05: 13件の実装DAG、個別scope、検証、再開、既存Issue境界を定義。実装は未実施。8repoに13件のIssueを起票し、indexと依存URLを照合した。
