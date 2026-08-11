# Agentic Art Orchestration システム設計仕様書

作成日: 2026-08-11  
対象: masa-san-jp/agentic-art-orchestration  
状態: v0.1 / 実装用正本

## 1. 目的

本システムは、以下4つの独立GitHubリポジトリを、人間とAIエージェントが単一ルートから安全かつ再現可能に扱うオーケストレーション基盤である。

~~~text
Self Model × Art History × Marketing Trends
                    ↓
          Agentic Art Research
~~~

単なるリンク集や一括clone scriptではなく、次を実現する。

1. 4repoの正本・履歴・PR・Issueを保った単一workspace。
2. 取得commitを固定した再現可能な調査実行。
3. 子repo内部schemaを歪めない境界契約。
4. repoを跨ぐ依存DAG、task選択、lease、再試行、停止、再開。
5. repo固有の品質ゲートを必ず実行する完了判定。
6. Self Modelの同意、Marketingの鮮度、Art Historyの根拠を保持したprovenance。
7. LunaまたはSonnet級の実行系が、会話履歴なしでv1.0まで完成できる運用状態。

## 2. スコープ

### 2.1 対象

- repository manifestとworkspace lifecycle
- repo状態のsnapshot、drift、divergence検知
- normalized research signal契約
- adapter / consumer compatibility test
- cross-repository work item、DAG、lease、checkpoint
- child quality gate runner
- portfolio status、audit、provenance trace
- offline fixture、障害・回復・privacy E2E

### 2.2 スコープ外

- 子repoのcore schemaを親で再定義すること
- 各KBのデータそのものを親へ集約すること
- GitHub Projectsをデータ正本にすること
- LLM provider、model ID、API keyの固定
- 自動merge、自動release、強制push
- Self Modelの心理診断利用
- 作品生成モデルやUIそのものの実装

## 3. 設計原則

### 3.1 Ownership first

要件、schema、entity、生成物は所有repoが正本である。親は「どこが正本か」と「どのcommitを使ったか」を管理する。

### 3.2 Translate once at boundaries

Self Model、芸術史、マーケティングは同じ型へ押し込めない。各repoの出口で一度だけ共通信号へ翻訳する。

### 3.3 Immutable input, explicit freshness

各runはcommit SHAを固定する。ただし固定commitだから内容が現在も有効とはみなさない。特にmarketingは再検証期限を別評価する。

### 3.4 No hidden recovery

dirty tree、未push commit、divergence、schema mismatchを自動修正しない。状態と解除条件を可視化する。

### 3.5 Repository-local quality

親のtestだけで子変更を完了にしない。変更した子repoの定義するquality gateが完了条件である。

### 3.6 Finite execution

retry、task数、lease、checkpoint、stopping criteriaを明示し、探索や修復が無限化しない。

## 4. 利用者と責任

| Actor | 責任 | 禁止 |
|---|---|---|
| Human owner | 要件優先度、merge、release、公開・同意判断 | 暗黙要件の放置 |
| Orchestrator | task選択、context pack、状態管理、横断検証 | 子schemaの上書き |
| Worker agent | 1taskの実装、test、記録、draft PR | 別taskへの無制限拡張 |
| Child repository | domain要件、データ、schema、quality gate | 親run stateの所有 |
| Auditor | drift、privacy、鮮度、孤立を報告 | 自動で事実を補完 |

## 5. 全体アーキテクチャ

~~~text
agentic-art-orchestration/
  manifest + contracts + queue + state + audit
                     |
              workspace manager
                     |
  workspace/repos/{four independent git repositories}
                     |
             adapters / contracts
                     |
             agentic-art-research
~~~

親repoはcontrol plane、子repoはdata/implementation planeである。workspaceはローカル生成物で、親Gitの管理対象外とする。

## 6. 正本と優先順位

### 6.1 親repo

1. 本設計仕様書
2. repositories.yamlとschemas
3. 実行計画
4. task-queue.yaml
5. AGENTSとrunbook
6. README

### 6.2 子repo

子repo内では、そのrepoのIssue SSOT、AGENTS、schema、testの優先順位に従う。親と子のdomain要件が競合する場合、adapterで解決する。解決不能なら停止条件とする。

## 7. Repository manifest

各entryは安定ID、full name、clone URL、workspace path、role、domain authority、default branch、観測commit、instructions、requirement SSOT、quality gates、export/import contractを持つ。

manifestのcommitは運用開始点であり、永続pinではない。run開始時に生成するsnapshotが実際の入力commitを固定する。

## 8. Workspace lifecycle

### 8.1 init

1. manifestを検証する。
2. pathがなければcloneする。
3. pathがあればremote URLとrepo IDを照合する。
4. credentials不足はrepo単位のBLOCKEDにする。
5. 既存作業を変更しない。

### 8.2 fetch

fetchはremote refsを更新するが、checkout、pull、rebase、resetを暗黙実行しない。

### 8.3 snapshot

repo ID、branch、HEAD、upstream、dirty/untracked/detached/ahead/behind、SSOT、contract、quality gate hash、captured_atを決定的順序で記録する。再現runは既存treeを移動せず、専用worktreeまたは専用branchを使う。

## 9. Git操作モデル

- repoごとにbranch、commit、PRを分離する。
- 親commitはmanifest、contract、queue、status等だけを含む。
- 子変更の親側記録はrepo、branch、commit、PR URL、test resultで行う。
- partial successを許容し、成功repoを巻き戻さず残りをcheckpointする。
- force push、history rewrite、hard reset、branch deletionは自動化しない。

## 10. Normalized research signal

共通schemaは内部entityの最小公倍数ではなく、制作リサーチが安全に引用・判断するためのenvelopeである。

### 10.1 共通必須情報

- contract version、signal ID、kind
- source repo、immutable commit、entity IDs、locator
- statement、evidence refs、certainty、unknowns
- constraints、validity/freshness
- adapter name/version、generated timestamp

### 10.2 Domain拡張

- self-model: consent scope、trait/state/context、tension、raw voice locator policy
- art-history: kind、time、geo、relation、interpretive certainty
- marketing: stage、freshness、revalidate date、certainty/retrieved、vendor interest、counterevidence

### 10.3 Provenance

~~~text
output requirement
  -> decision
    -> normalized signal
      -> source entity
        -> source repository@commit
          -> evidence locator
~~~

## 11. Cross-repository work item

work itemはID、owner repo、dependency、allowed paths、context、acceptance、checks、risk、attempts、lease、checkpoint、terminal state、commit/PR/test evidenceを持つ。schedulerは選択結果だけでなく、他taskが選ばれない理由も出力する。

## 12. 実行状態機械

~~~text
BACKLOG -> READY -> IN_PROGRESS -> DONE
                   |            |
                   v            v
                retry        BLOCKED
                   |
                   +-> READY
~~~

retryはattempt情報付きREADYとして表す。task ID + repo ID + base commit + attemptをidempotency keyとし、branch/PR等の重複を防ぐ。transient failureだけを最大3回retryする。

## 13. Context pack

workerへ全repoを渡さず、親AGENTS/task、owner repo instructions/SSOT、変更対象、直接依存contract、source/target commit、acceptance、quality gates、前回failureの最小ログだけを渡す。PRIVATE_RAW/RESTRICTEDは含めない。

## 14. Quality gates

完了には次の積が必要である。

~~~text
parent validation
× parent tests
× changed child repository gates
× contract compatibility
× security boundary
× clean intended diff
~~~

command不存在、dependency不足、timeout、test failureを区別して記録する。timeoutはpassではない。

## 15. Validation rules

blocking validatorは最低限次を検査する。

- manifest/schema一致、unique ID/path/full_name
- 40桁SHA、HTTPS GitHub URL、known role/contract
- task ID一意、known status、known dependency、DAG cycleなし
- READY taskのdependencyがDONE
- active leaseのowner、expiry、scope
- signal source repo/commit/entity/evidence
- consent/freshness/certaintyのdomain rules
- consumer contract majorの互換性
- forbidden data classとlikely secret
- generated dataが正本より古くないこと

## 16. Audit rules

auditはcommitを止めず、stale pin、SSOT変更後の未検証、orphan signal、requirementの根拠不足、marketing freshness、self-model consent、art relation根拠、重複Issue/PR、長期BLOCKED、孤児lease、未push commitを次の修復候補として出す。

## 17. セキュリティとプライバシー

各子では低リスクでも、内面・行動・制作関心・トレンドを結合すると再識別と過剰推論のリスクが上がる。親はraw dataを集約せず、最小signalとopaque locatorだけを扱う。

禁止対象はsecret/token/private key、PRIVATE_RAW、RESTRICTED、個人メール本文、非公開音声、カレンダー詳細、直接識別情報を伴う心理・行動推論、同意範囲外signalである。

## 18. 非機能要件

- Python 3.11以上、初期依存は標準library + PyYAML
- Linux/macOSで動作
- offline fixtureでnetworkなしに主要testが完走
- 同一snapshot/configから同一JSONを生成
- 100 work itemsでも実用時間内に終了
- 失敗にrepo、field、rule、remediationを含める
- 会話履歴なしで再開可能

## 19. 完了条件

### 19.1 Bootstrap

- 設計、計画、規則、manifest、queue、state、handoffが存在
- 初期validatorとunit testが通る
- 次のREADY taskと最初の操作が一意

### 19.2 v1.0.0

- clean machineから4repoを再現可能に展開でき、2回目initがno-op
- dirty/detached/diverged/unpushedを非破壊検知
- signal v1と3adapter/1consumerのcontract testが通る
- outputからsource repo@commitまで完全trace
- scheduler、lease、retry、resumeが障害testを通る
- 変更repoのquality gateが必ず実行される
- status/auditがJSONとMarkdownで再現生成される
- forbidden dataがworking tree、bundle、Git historyにない
- offline E2Eが3回連続成功
- 新規Luna/Sonnet級agentが文書だけで次taskを完了
- merge/releaseの人間gateが維持される

## 20. 変更管理

contract major、ownership、data boundary、human gateを変える場合は、Issueに観測事実、選択肢、推奨、migration、rollbackを記載し、人間決定後に設計・schema・fixture・testを同じ変更で更新する。実装都合で子repoのdomain schemaを変更しない。
