# Agentic Art Orchestration Repository 設計仕様書

- 作成日: 2026-08-11
- 推奨リポジトリ名: `agentic-art-orchestration`
- GitHub上の想定配置: `masa-san-jp/agentic-art-orchestration`
- 想定可視性: Private
- 対象GitHub Project: [masa-san-jp Project #4](https://github.com/users/masa-san-jp/projects/4)
- 文書状態: Initial Design / Implementation Ready

## 1. 結論

`agentic-art-orchestration` は、次の4リポジトリを単一リポジトリへ統合するものではない。

- [`self-model-notes`](https://github.com/masa-san-jp/self-model-notes)
- [`art-history-notes`](https://github.com/masa-san-jp/art-history-notes)
- [`marketing-trends-notes`](https://github.com/masa-san-jp/marketing-trends-notes)
- [`agentic-art-research`](https://github.com/masa-san-jp/agentic-art-research)

各リポジトリの独立性と正本を維持したまま、以下を横断的に管理するオーケストレーション層とする。

1. リポジトリの取得と実行環境構築
2. リポジトリ間の依存関係と接続契約
3. 横断タスクの分解、順序制御、リース、再開
4. エージェントへの作業コンテキスト配布
5. 各リポジトリの検証と横断整合性検査
6. 複数リポジトリにまたがる変更の追跡
7. 失敗の局所化、修復タスク化、引継ぎ
8. GitHub Projects #4との進捗同期

Git Submoduleは採用しない。`repos.yaml`による宣言とbootstrapスクリプトで通常のGitリポジトリとして取得し、再現が必要な時点は`workspace.lock.yaml`でcommit SHAを固定する。

---

## 2. 命名

### 2.1 採用名

```text
agentic-art-orchestration
```

### 2.2 GitHub Description案

```text
Cross-repository orchestration layer for Self Model, Art History, Marketing Trends, and Agentic Art Research.
```

### 2.3 命名理由

- `workspace`よりも、依存関係、実行順序、復旧、引継ぎまで扱うことを明示できる。
- `orchestrator`は単一の実行プログラムを想起させるが、実体は規則、manifest、タスク、スクリプト、証跡を含む層である。
- 芸術的概念名と技術基盤名を分離できる。
- 将来、Codex、Claude Code、ローカルモデルなど実行系が変わっても名称が陳腐化しない。

---

## 3. 全体目的

Agentic Artの基本構造は以下とする。

```text
Self Model ───────────┐
Art History ──────────┼─→ Agentic Art Research ─→ Research Package / Prototype
Marketing Trends ─────┘
```

本リポジトリは、この知識と制作研究の流れそのものを実行可能にする。

目標は、人間が毎回対象リポジトリ、読むべき文書、実行順序、検証方法、次の担当を指示しなくても、GPT-5.6 LunaまたはClaude Sonnet級の実行エージェントが、許可された範囲内でタスクを選択し、完了または有限の停止状態まで進められることである。

---

## 4. スコープ

### 4.1 実施すること

- 4リポジトリのローカル取得と状態確認
- 各リポジトリの役割、正本、検証コマンドの登録
- 横断タスクの機械可読な管理
- タスクごとの対象、入力、出力、依存関係、完了条件の固定
- エージェントが読むContext Bundleの生成
- リポジトリ単位および横断単位の検証
- 複数リポジトリにまたがるbranch、commit、PRの関連付け
- 実行結果、判断、失敗、引継ぎの記録
- GitHub Projects #4との状態対応

### 4.2 実施しないこと

- 4リポジトリのMonorepo化
- 各リポジトリの要件やスキーマの上書き
- 各KBの正本データの複製
- Self Modelの機微な原文や`PRIVATE_RAW`データの保存
- LLMプロバイダー固有の人格定義の正本化
- 人間確認が必要な判断の無断代行
- `main`への直接push、force push、履歴改変
- 失敗を隠して成功として扱うこと

---

## 5. 正本の階層

| 対象 | 正本 |
|---|---|
| 各領域の目的・要件 | 各リポジトリのIssue #1 |
| 各領域のスキーマ | 各リポジトリの設計文書・schema |
| 各領域の実データ・実装 | 各リポジトリ |
| 横断インターフェース | 本リポジトリの`contracts/` |
| 対象リポジトリと取得規則 | `repos.yaml` |
| 再現対象commit | `workspace.lock.yaml` |
| 横断実行順序 | `execution/tasks.yaml` |
| 実行時判断 | `execution/decisions/` |
| プロジェクト全体の優先順位・可視化 | GitHub Projects #4 |
| エージェント人格 | 人格管理元のGitリポジトリ |

矛盾時は、法令・絶対制約、安全・データ保護、委任権限、領域要件、横断設計、効率の順で優先する。

本リポジトリは、各領域の要件を変更できない。変更が必要な場合は、対象リポジトリにIssueまたは変更提案を作成し、その採否が確定してから横断契約を更新する。

---

## 6. リポジトリの役割

| Repository | 役割 | オーケストレーションからの主な利用 |
|---|---|---|
| `self-model-notes` | 感情・内的動機・行動原理・葛藤を根拠付きで管理する汎用Self Model KB | `research_signals`の取得 |
| `art-history-notes` | 美術史を時間・空間・関係で管理するKB | 芸術史的文脈、作品、運動、技法、関係の取得 |
| `marketing-trends-notes` | 外部マーケティング変化を時間・チャネル・関係・鮮度で管理するKB | 時代の欲望、需要変化、チャネル変化の取得 |
| `agentic-art-research` | 証拠収集から制作判断、制作要件、試作検証までを実行する基盤 | 3つの入力を統合し、研究パッケージと試作要件を生成 |

各KBのコアスキーマは統一しない。翻訳は`contracts/`で定義する境界に限定する。

---

## 7. 推奨ディレクトリ構成

```text
agentic-art-orchestration/
├── README.md
├── AGENTS.md
├── ARCHITECTURE.md
├── PLANS.md
├── repos.yaml
├── workspace.lock.yaml
├── pyproject.toml
├── .gitignore
├── .github/
│   ├── workflows/
│   │   └── validate.yaml
│   └── ISSUE_TEMPLATE/
│       └── cross-repository-task.yml
├── config/
│   ├── policies.yaml
│   ├── states.yaml
│   ├── agents.yaml
│   └── project-fields.yaml
├── contracts/
│   ├── research-signals.schema.yaml
│   ├── art-history-context.schema.yaml
│   ├── marketing-context.schema.yaml
│   ├── research-package.schema.yaml
│   └── interop-mapping.md
├── execution/
│   ├── tasks.yaml
│   ├── leases/
│   ├── decisions/
│   ├── handoffs/
│   └── runs/
├── templates/
│   ├── task.yaml
│   ├── context-bundle.md
│   ├── completion-record.yaml
│   ├── failure-record.yaml
│   └── escalation-package.md
├── tools/
│   ├── bootstrap.py
│   ├── lock.py
│   ├── status.py
│   ├── select_task.py
│   ├── build_context.py
│   ├── validate.py
│   ├── validate_all.py
│   ├── project_sync.py
│   ├── record_run.py
│   └── recover.py
├── tests/
│   ├── fixtures/
│   ├── test_manifest.py
│   ├── test_task_state.py
│   ├── test_dependency_graph.py
│   ├── test_write_scope.py
│   └── test_context_bundle.py
└── repos/                       # .gitignore。通常の独立Git checkout
    ├── self-model-notes/
    ├── art-history-notes/
    ├── marketing-trends-notes/
    └── agentic-art-research/
```

`execution/runs/`には実行要約と成果物参照のみを保存する。巨大な生ログ、秘密情報、会話全文、機微データはGitへ保存しない。

---

## 8. Repository Manifest

`repos.yaml`は、対象リポジトリを人間と機械の双方が解釈できる唯一の一覧とする。

```yaml
version: 1

repositories:
  - id: self-model
    full_name: masa-san-jp/self-model-notes
    clone_url: https://github.com/masa-san-jp/self-model-notes.git
    path: repos/self-model-notes
    default_branch: main
    role: knowledge-base
    requirements_ssot: https://github.com/masa-san-jp/self-model-notes/issues/1
    agent_entrypoint: AGENTS.md
    write_policy: task-explicit
    required_checks:
      - python3 tools/build_graph.py --check
      - python3 -m unittest discover -s tests -p "test_*.py"

  - id: art-history
    full_name: masa-san-jp/art-history-notes
    clone_url: https://github.com/masa-san-jp/art-history-notes.git
    path: repos/art-history-notes
    default_branch: main
    role: knowledge-base
    requirements_ssot: https://github.com/masa-san-jp/art-history-notes/issues/1
    agent_entrypoint: AGENTS.md
    write_policy: task-explicit

  - id: marketing-trends
    full_name: masa-san-jp/marketing-trends-notes
    clone_url: https://github.com/masa-san-jp/marketing-trends-notes.git
    path: repos/marketing-trends-notes
    default_branch: main
    role: knowledge-base
    requirements_ssot: https://github.com/masa-san-jp/marketing-trends-notes/issues/1
    agent_entrypoint: AGENTS.md
    write_policy: task-explicit

  - id: agentic-art-research
    full_name: masa-san-jp/agentic-art-research
    clone_url: https://github.com/masa-san-jp/agentic-art-research.git
    path: repos/agentic-art-research
    default_branch: main
    role: integration-runtime
    requirements_ssot: https://github.com/masa-san-jp/agentic-art-research/issues/1
    agent_entrypoint: AGENTS.md
    write_policy: task-explicit
```

実装時は、各リポジトリの実際の検証コマンドを読み取り、`required_checks`を補完する。存在しないコマンドを推測で登録してはならない。

---

## 9. Lock Manifest

`workspace.lock.yaml`は、ある実行がどのcommitの組合せで行われたかを再現する。

```yaml
version: 1
generated_at: 2026-08-11T00:00:00+09:00
repositories:
  self-model:
    commit: "<40-character-sha>"
    branch: main
    dirty: false
  art-history:
    commit: "<40-character-sha>"
    branch: main
    dirty: false
  marketing-trends:
    commit: "<40-character-sha>"
    branch: main
    dirty: false
  agentic-art-research:
    commit: "<40-character-sha>"
    branch: main
    dirty: false
```

次の場合はlockを作成してはならない。

- 未追跡または未commitの変更がある
- commit SHAが取得できない
- 対象リポジトリの取得に失敗している
- 必須検証が失敗している

---

## 10. 横断タスクモデル

### 10.1 タスク状態

```text
DRAFT
  ↓
READY
  ↓
LEASED
  ↓
RUNNING
  ├─→ VERIFYING ─→ COMPLETE
  ├─→ COMPLETE_WITH_GAPS
  ├─→ BLOCKED_EXTERNAL
  ├─→ BLOCKED_HUMAN
  ├─→ NEEDS_REPAIR
  └─→ FAILED_TERMINAL
```

単一workerの失敗は、他の独立タスクを停止させない。依存関係のないREADYタスクは継続できる。

### 10.2 タスク定義

```yaml
id: AOR-001
title: Normalize Self Model research signals for Agentic Art Research
state: READY
priority: 10

target_repositories:
  read:
    - self-model
    - agentic-art-research
  write:
    - self-model
    - agentic-art-research

depends_on: []
blocks: []

requirements:
  - repository: self-model
    ref: https://github.com/masa-san-jp/self-model-notes/issues/1

inputs:
  - contracts/research-signals.schema.yaml

deliverables:
  - repository: self-model
    paths:
      - docs/interop-mapping.md
      - tools/export_signals.py
  - repository: agentic-art-research
    paths:
      - schemas/research-signals.schema.yaml

acceptance:
  commands: []
  assertions:
    - Exported signals validate against the cross-repository contract.
    - Every derived signal retains evidence references and certainty.

write_scope:
  allow: []
  deny:
    - "**/data/private/**"
    - "**/.env*"
    - "**/secrets/**"

human_gate:
  required: false
  reasons: []

retry:
  max_attempts: 3
  strategy: diagnose-then-repair
```

### 10.3 完了契約

`COMPLETE`には最低限、以下が必要である。

- 指定成果物が存在する
- 受入条件を満たす
- 対象リポジトリの必須検証が成功する
- セキュリティ・データ保護規則に違反しない
- 実行したcommit、変更ファイル、検証結果が記録される
- 横断契約に破壊的変更がない、または承認済みである
- ロールバック方法が明らかである
- 次タスクまたは終了理由が記録される

未解決事項が成果利用を妨げず、未解決範囲と影響が明示されている場合のみ`COMPLETE_WITH_GAPS`を認める。

---

## 11. エージェント実行プロトコル

実行エージェントは、1タスクにつき以下を順守する。

1. ルートの`AGENTS.md`を読む。
2. `repos.yaml`と`workspace.lock.yaml`を読む。
3. 対象タスクのread/write scopeを確定する。
4. 対象リポジトリごとに`AGENTS.md`、要件SSOT、設計SSOTを読む。
5. `tools/status.py`でdirty、branch、commit、取得状態を検査する。
6. `tools/build_context.py`で必要部分だけをContext Bundleにする。
7. 対象リポジトリごとに作業branchを作る。
8. 依存順に実装する。
9. リポジトリ単位の検証を実行する。
10. `tools/validate_all.py`で横断契約を検証する。
11. completion recordまたはfailure recordを作る。
12. commit、PR、GitHub Project itemを共通タスクIDで関連付ける。
13. 次のREADYタスクを選択するか、有限の停止状態へ移る。

エージェントは、対象外リポジトリを既定でread-onlyとして扱う。書込み対象を自分の判断で拡張してはならない。

---

## 12. Context Bundle

コンテキスト全量をモデルへ投入しない。タスクごとに以下だけを生成する。

```text
Task Definition
Design Invariants
Target Repository Map
Relevant Requirements
Relevant Schemas and Contracts
Allowed Write Scope
Current Commit Set
Validation Commands
Known Decisions
Known Failures
Expected Deliverables
Completion Contract
```

Context Bundleには、出典となるファイルパス、Issue URL、commit SHAを付ける。要約だけを根拠に実装してはならない。

---

## 13. Branch、Commit、PR規則

### 13.1 branch名

```text
orchestration/<task-id>/<repository-id>
```

例:

```text
orchestration/aor-001/self-model
orchestration/aor-001/agentic-art-research
```

### 13.2 commit

- リポジトリごとに独立してcommitする。
- 1つのcommitへ複数リポジトリの変更を混在させない。
- commit messageに共通タスクIDを含める。
- 生成物更新が必要な場合は正本変更と同じcommitに含める。

### 13.3 PR

- リポジトリごとにPRを作る。
- PR本文に、共通タスクID、依存PR、検証結果、適用順序を記載する。
- 依存PRがmergeされるまで、後続PRをmerge可能と扱わない。
- 破壊的なcontract変更は人間確認を必須とする。

---

## 14. GitHub Projects #4連携

GitHub Projects #4は、全体の優先順位と人間向け可視化の正本とする。

最低限の対応項目:

| Orchestration | GitHub Project |
|---|---|
| `task.id` | Issueまたはitemの参照ID |
| `state` | Status |
| `priority` | Priority |
| `target_repositories` | Repository / Labels |
| `human_gate` | Human Review |
| `run_id` | 実行記録URLまたはコメント |

`project_sync.py`は冪等にする。同じ状態で複数回実行しても重複itemや重複コメントを作らない。

Project APIへ接続できない場合でも、ローカルの`execution/tasks.yaml`だけで実行を継続できること。接続障害を全体停止条件にしない。

---

## 15. 停止・回復・再実行

### 15.1 停止条件

- 権限または認証が不足している
- write scopeが曖昧または競合している
- 対象リポジトリに未確認の既存変更がある
- 要件SSOT同士が矛盾している
- 機微情報をGitへ保存する可能性がある
- 破壊的なスキーマ変更が必要である
- 外部への公開、送信、課金、法的判断が必要である
- 受入条件を満たす方法が複数あり、選択で成果が大きく変わる

### 15.2 回復手順

```text
Failure Pattern検索
  ↓
既知修復の適用、または診断タスク生成
  ↓
回復計画と子タスク作成
  ↓
子タスクを検証
  ↓
元タスクをREADYへ再投入
```

同じ失敗を根拠なく繰り返してはならない。3回失敗した場合は、原因、実行済み対応、必要な判断を`escalation-package.md`へまとめる。

外部待ちは永久停止にせず`BLOCKED_EXTERNAL`として条件と期限を記録する。期限超過時は人間向けescalation packageを生成する。

---

## 16. セキュリティとデータ保護

- `.env`、token、秘密鍵、認証情報をcommitしない。
- privateリポジトリへのアクセス権がない場合、迂回取得しない。
- Self Modelの直接識別情報、会話全文、機微な原文を本リポジトリへ複製しない。
- `PRIVATE_RAW`、`RESTRICTED`のデータはGitへ保存しない。
- Context Bundleには必要最小限の引用または参照だけを含める。
- エージェントの出力を外部公開する操作は、明示された委任がない限り行わない。
- cleanup目的でも、他リポジトリの未確認変更を削除、reset、checkoutしてはならない。

---

## 17. 検証

### 17.1 構造検証

```bash
python3 tools/validate.py --check
```

検査対象:

- `repos.yaml`の必須項目
- IDとpathの一意性
- タスク状態語彙
- 依存関係の循環
- 存在しないrepository ID参照
- read/write scopeの矛盾
- 完了タスクのcompletion record欠落
- lock manifestのSHA形式
- contract version不整合
- human gateを必要とする変更の無承認

### 17.2 横断検証

```bash
python3 tools/validate_all.py --check
```

検査対象:

- 全リポジトリの取得状態
- dirty worktree
- 各リポジトリ固有のrequired checks
- exportとimportのcontract適合
- 参照commitの存在
- 生成物の鮮度
- 横断タスクの成果物存在

実行環境に外部ネットワークがない場合、ネットワーク必須検証は`NOT_RUN`として理由を記録し、成功へ読み替えない。

---

## 18. 実行記録

1回の実行につき、以下を保存する。

```yaml
run_id: 20260811T143000+0900-aor-001
task_id: AOR-001
agent:
  id: aiko-dev
  runtime: claude-code
  model: sonnet
started_at: null
finished_at: null
input_commits: {}
output_commits: {}
changed_files: []
checks: []
decisions: []
failures: []
result: COMPLETE
next_start: null
```

保存するのは再現と監査に必要な証跡であり、モデルの内部思考全文ではない。

HANDOFFは以下で生成する。

- 明示的な引継ぎ
- fallback発生
- セッション終了
- コンテキスト上限への接近
- restartまたはshutdown前
- 別エージェントへの担当変更

---

## 19. 非機能要件

- Python 3標準ライブラリを優先し、依存を最小化する。
- macOSとUbuntuで動作する。
- 全ツールは非対話モードを持つ。
- 同じ入力に対するmanifest、context bundle、検証結果は決定的に生成する。
- 失敗時は非0終了コードと機械可読なエラーを返す。
- エージェントが単独で1タスクを開始・完了・引継ぎできる。
- 特定のLLM、IDE、MCPクライアントに依存しない。
- 4リポジトリから将来Nリポジトリへ拡張できる。
- 1つのworker失敗を全体失敗へ拡大しない。
- 10年後も、どの要件とcommitの組合せで実行されたか追跡できる。

---

## 20. 初期実装計画

### Phase 0: Bootstrap

- [ ] リポジトリを作成する
- [ ] `README.md`、`AGENTS.md`、`ARCHITECTURE.md`を配置する
- [ ] `repos.yaml`を作成する
- [ ] `tools/bootstrap.py`を実装する
- [ ] `tools/status.py`を実装する
- [ ] `tools/lock.py`を実装する
- [ ] manifest検証を実装する
- [ ] CIで構造検証を実行する

### Phase 1: Task Orchestration

- [ ] `execution/tasks.yaml`のschemaを実装する
- [ ] 依存関係と状態遷移を検証する
- [ ] leaseとtimeoutを実装する
- [ ] `select_task.py`を実装する
- [ ] completion / failure / handoffテンプレートを実装する
- [ ] Failure Patternからrepair taskを作る

### Phase 2: Cross-Repository Contracts

- [ ] Self Model export contractを登録する
- [ ] Art History context contractを登録する
- [ ] Marketing context contractを登録する
- [ ] Agentic Art Research import contractを登録する
- [ ] 横断fixtureとGolden Scenarioを作る
- [ ] `validate_all.py`を実装する

### Phase 3: GitHub Integration

- [ ] GitHub Projects #4のfield mappingを確定する
- [ ] `project_sync.py`を実装する
- [ ] branch / commit / PRの共通タスクID規則を検証する
- [ ] partial failure時の再同期を実装する

### Phase 4: Autonomous Operation

- [ ] GPT-5.6 Luna級エージェントでGolden Scenarioを完走する
- [ ] Claude Sonnet級エージェントで同一Scenarioを完走する
- [ ] 中断からのHANDOFF再開を検証する
- [ ] 1リポジトリ失敗時に独立タスクが継続することを確認する
- [ ] 人間確認が必要な変更で確実に停止することを確認する

---

## 21. Golden Scenario

初期のE2E受入試験は、以下の1本に固定する。

```text
1. self-model-notesから根拠付きresearch_signalsをexport
2. art-history-notesから関連する歴史的文脈を取得
3. marketing-trends-notesから鮮度付きの外部トレンドを取得
4. agentic-art-researchで3入力をResearch Packageへ統合
5. 制作判断、制作要件、試作検証項目を生成
6. 全出力から元の証拠、KB commit、contract versionへ逆引き
```

入力不足は推測で補わず、`COMPLETE_WITH_GAPS`として不足、影響、次の調査タスクを出す。

---

## 22. 初期受入条件

以下をすべて満たした時点で、オーケストレーション・リポジトリの基盤完成とする。

- [ ] 1コマンドで4リポジトリを所定位置へ取得できる
- [ ] 各リポジトリのbranch、commit、dirty状態を一覧化できる
- [ ] cleanな4リポジトリのcommit組合せをlockできる
- [ ] 各リポジトリの要件SSOTとagent entrypointへ到達できる
- [ ] 横断タスクを依存順に1件選択できる
- [ ] write scope外の変更を検出して失敗できる
- [ ] リポジトリ固有の検証を一括実行できる
- [ ] export/import contractの不一致を検出できる
- [ ] completion、failure、handoffの3記録を生成できる
- [ ] 中断後、別エージェントがHANDOFFから再開できる
- [ ] 1つのworker失敗が独立タスクを停止させない
- [ ] Golden Scenarioが`COMPLETE`または`COMPLETE_WITH_GAPS`へ有限時間で到達する
- [ ] 実行結果から入力commit、変更commit、検証結果、判断を追跡できる
- [ ] GitHub Projects #4が利用不能でもローカルキューで継続できる
- [ ] private data、秘密情報、モデル内部思考全文がGitへ保存されない

---

## 23. 実装エージェントへの開始指示

```text
この設計仕様書を要件として、Phase 0から順に実装する。

1. 不明な点を推測で補わない。
2. 各対象リポジトリの現在のREADME、AGENTS.md、Issue #1、検証コマンドを確認する。
3. 本文に例示されたコマンドと実際のリポジトリが異なる場合、実測を正としてmanifestへ反映する。
4. 依存関係が完了した最小IDのREADYタスクを1件ずつ処理する。
5. 各タスクはテスト、実行証拠、変更ファイル、次の開始点を残す。
6. write scope拡張、破壊的変更、機微情報、外部公開が必要なら停止してescalation packageを作る。
7. 人間へ一般的な「次に何をしますか」と聞かず、定義済みキューを進める。
8. Phase 0の受入条件を満たすまで、機能追加より基盤の再現性と検証を優先する。
```

