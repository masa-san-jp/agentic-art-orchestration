# Agentic Art Orchestration システム設計仕様書

作成日: 2026-08-11  
対象: masa-san-jp/agentic-art-orchestration  
状態: v1.1計画 / 実装用正本

本書は、先行する repository-design-specification.md の構想・要求を、現在の4repoをcore setとして実測し、追加repoも安全にonboardできる実行契約へ具体化した文書である。意図・スコープは先行文書、実装ファイル名・検証・タスク順は本書を正とする。

## 1. 目的

本システムは、4つのcore独立GitHubリポジトリと、同じonboarding契約を満たす追加リポジトリを、人間とAIエージェントが単一ルートから安全かつ再現可能に扱うオーケストレーション基盤である。`agentic-art-production`は最初の追加runtimeである。

~~~text
Self Model × Art History × Marketing Trends
                    ↓
          Agentic Art Research
                    ↓
          Agentic Art Production
~~~

単なるリンク集や一括clone scriptではなく、次を実現する。

1. core 4repoと追加repoの正本・履歴・PR・Issueを保った単一workspace。
2. 取得commitを固定した再現可能な調査実行。
3. 子repo内部schemaを歪めない境界契約。
4. repoを跨ぐ依存DAG、task選択、lease、再試行、停止、再開。
5. repo固有の品質ゲートを必ず実行する完了判定。
6. Self Modelの同意、Marketingの鮮度、Art Historyの根拠を保持したprovenance。
7. LunaまたはSonnet級の実行系が、会話履歴なしでv1.0まで完成できる運用状態。
8. 利用エージェントとの会話だけで、体系化された子repoの知識を根拠付きで利用できるinteraction体験。
9. interactionから明示・推定feedbackを抽出し、正しいrepoのIssueへ変換して自律改善するloop。
10. ユーザー成果物をGoogle Driveへ追記保存し、改善・監査agentも権限内で参照できるexternal artifact plane。

## 2. スコープ

### 2.1 対象

- repository manifestとworkspace lifecycle
- repo状態のsnapshot、drift、divergence検知
- normalized research signal契約
- adapter / consumer compatibility test
- cross-repository work item、DAG、lease、checkpoint
- child quality gate runner
- portfolio status、audit、provenance trace
- GitHub Projects #4との冪等な優先順位・状態同期
- offline fixture、障害・回復・privacy E2E
- conversational interaction eventとexperience outcome契約
- repository-aware retrievalとknowledge profile
- Google Drive external artifact参照とcreate-only adapter
- explicit/inferred feedback、Issue routing、issue-to-draft-PR改善loop
- interaction latencyから分離した非同期audit/refactoring lane

### 2.2 スコープ外

- 子repoのcore schemaを親で再定義すること
- 各KBのデータそのものを親へ集約すること
- GitHub Projectsを子repoデータまたは実行再開状態の正本にすること
- LLM provider、model ID、API keyの固定
- 自動merge、自動release、強制push
- Self Modelの心理診断利用
- 作品生成モデルやGUI/mobile clientそのものの実装
- Google Driveをdomain knowledgeの正本にすること
- 推定feedbackをユーザー事実、同意、公開許可として扱うこと

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

### 3.7 Interaction is the product surface

利用エージェントは人間にとってのユーザーインターフェースである。repo、schema、Git操作をユーザーへ露出させず、意図達成、根拠付き回答、成果物、継続性を一つのinteractionとして提供する。

### 3.8 Append-only user artifacts

ユーザー体験から生まれた成果物はGoogle Driveへcreate-onlyで保存する。修正は既存artifactの更新ではなく、新artifactとderived_from/supersedes relationで表す。親Gitへ本文や会話全文を複製しない。

### 3.9 Inference is not user truth

言語化されていない不満・欲求はfeedback仮説である。観測根拠、confidence、consent scopeを保持し、明示要求、ユーザー属性、domain factへ自動昇格させない。

### 3.10 Frontstage and backstage isolation

interaction laneはユーザー応答を担い、improvement laneとaudit/refactoring laneは非同期に実行する。backstage failureは記録・再開するが、利用可能な最後のqualified snapshotによる通常応答を不必要に停止しない。

## 4. 利用者と責任

| Actor | 責任 | 禁止 |
|---|---|---|
| Human owner | 要件優先度、merge、release、公開・同意判断 | 暗黙要件の放置 |
| Orchestrator | task選択、context pack、状態管理、横断検証 | 子schemaの上書き |
| Interaction agent | 会話、意図理解、retrieval、成果物提示、feedback観測 | 推定を事実化、改善完了待ちで会話をblock |
| Improvement agent | feedback分類、Issue routing、実装、test、draft PR | authority不明のrepoへの直接変更 |
| Worker agent | 1taskの実装、test、記録、draft PR | 別taskへの無制限拡張 |
| Child repository | domain要件、データ、schema、quality gate | 親run stateの所有 |
| Auditor | 非同期のdrift、privacy、鮮度、孤立、構造品質の監査・refactoring提案 | 自動で事実を補完、user artifactの変更 |
| Google Drive artifact store | immutable user output、revision lineage、feedback reference | domain KBやtask queueの正本化 |

## 5. 全体アーキテクチャ

~~~text
User <-> Interaction Agent
              |
       parent control plane
  registry + contracts + queue + state
       /          |             \
 repository   artifact       feedback
 retrieval    adapter        router
     |            |             |
four child   Google Drive   Issue -> task
repositories  append-only   -> draft PR
     \            |             /
      provenance + audit/refactoring
~~~

親repoはcontrol plane、子repoはdomain knowledge/data/implementation plane、Google Driveはuser artifact planeである。interaction agentはfrontstage、improvement agentとauditorはbackstageである。workspaceはローカル生成物で、親Gitの管理対象外とする。

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

### 6.3 Google Drive artifacts

Google Driveはユーザー成果物と、その成果物に対するfeedbackの外部正本である。domain fact、子repo schema、task実行状態の正本ではない。親はartifact本文を保持せず、opaque file ID、content hash、provenance、access/consent scope、lineageだけを管理する。

## 7. Repository manifest

各entryは安定ID、full name、clone URL、workspace path、role、domain authority、default branch、観測commit、instructions、requirement SSOT、quality gates、export/import contractを持つ。v1.1ではknowledge profileとしてanswerable questions、canonical entities、retrieval entry points、evidence/freshness rules、feedback owner、write scope、forbidden dataも持つ。

manifestのcommitは運用開始点であり、永続pinではない。run開始時に生成するsnapshotが実際の入力commitを固定する。既存4repo IDはcore setとして必須とし、追加repoは既存entryの置換ではなくappendする。追加entryにもunique ownership、role-contract、同一repo Issue SSOT、instructions、quality gateを要求する。`agentic-art-production`は`production-handoff/v1`をimportし、`production-result/v1`をexportする双方向runtimeとして登録し、normalized research signalのproducer/consumerへ誤分類しない。

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

## 10A. Interaction event and experience outcome

interaction eventは会話全文ではなく、体験を再現・改善するための最小envelopeである。

- contract version、interaction ID、event ID、timestamp
- user intent categoryとgoal reference
- agent ID/version、session/run ID
- consulted repository snapshotsとsignal/evidence IDs
- outcome status、artifact references、未解決事項
- explicit feedback references
- privacy、consent、retention scope

生の会話本文、PRIVATE_RAW、RESTRICTED、直接識別情報は親Gitへ保存しない。必要な原文は承認された外部locatorとして扱い、context packには目的達成に必要な最小引用だけを入れる。

## 10B. External artifact contract

external artifactはユーザー体験から生まれたDrive成果物を参照するcreate-only envelopeである。

- artifact ID、Drive provider/file ID、MIME/category
- created_at、creator agent/version、interaction ID
- content hash、source repository snapshots、evidence references
- access scope、consent scope、retention policy
- derived_from、supersedes、feedback references

adapterはCREATEだけを通常操作として公開し、UPDATE、DELETE、既存file IDへの内容置換を拒否する。修正版は新artifactとして保存し、lineageで旧版と結ぶ。親Gitに本文を保存しない。

## 10C. Feedback and inferred need contract

feedbackは次のkindを区別する。

- explicit_request
- explicit_dissatisfaction
- output_correction
- knowledge_gap
- inferred_friction
- inferred_need

すべてのfeedbackは対象interaction/artifact、観測根拠、target owner候補、privacy/consent scopeを持つ。inferred kindはconfidenceと反証可能なhypothesisを必須とし、明示要求と同じ確度へ変換しない。routerの確信が閾値未満なら自動実装せずtriage可能なIssue候補へ送る。

## 10D. Issue routing and continuous improvement

domain content、evidence、freshness、子schemaのfeedbackは所有子repoへ、interaction UX、retrieval、adapter、artifact、orchestrationのfeedbackは親repoへrouteする。Issueにはfeedback kind、根拠参照、提案acceptance、target repo、重複判定key、privacy-safe summaryを含める。

eligible Issueは既存scheduler、lease、checkpoint、quality gateを通じて自律実装し、branch、commit、draft PRまで進められる。merge、release、公開範囲変更、同意拡張は人間gateを維持する。採用後は新snapshot/indexへ反映し、次のinteractionから利用する。

## 10E. Asynchronous audit/refactoring lane

auditorはinteraction request pathと別queue/leaseで動き、repository structure、duplicate knowledge、stale evidence、retrieval coverage、contract drift、privacy、artifact lineageを検査する。修復はIssueまたはdraft PRとして記録し、interaction中のuser artifactを変更しない。audit failureは最後のqualified snapshotによる利用を直ちに無効化せず、severityと影響範囲を明示する。

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
- interaction、artifact、feedback contractのversion互換性
- artifact operationがCREATEであり、opaque Drive referenceとhashを持つこと
- inferred feedbackがconfidence、evidence、hypothesisを持つこと
- Issue routing targetがmanifest authorityと一致すること
- forbidden data classとlikely secret
- generated dataが正本より古くないこと

## 16. Audit rules

auditはcommitを止めず、stale pin、SSOT変更後の未検証、orphan signal、requirementの根拠不足、marketing freshness、self-model consent、art relation根拠、重複Issue/PR、長期BLOCKED、孤児lease、未push commit、artifact lineage欠落、feedback routing drift、retrieval coverage、interaction/audit lane競合を次の修復候補として出す。

## 17. セキュリティとプライバシー

各子では低リスクでも、内面・行動・制作関心・トレンド・会話feedbackを結合すると再識別と過剰推論のリスクが上がる。親はraw dataを集約せず、最小signalとopaque locatorだけを扱う。

GitHub Projects #4は人間向け優先順位と可視化の正本とする。task-queue.yamlは機械実行と再開の正本とし、同期は冪等にする。Project APIが利用不能でもローカルqueueは継続し、復旧後に差分同期する。

禁止対象はsecret/token/private key、PRIVATE_RAW、RESTRICTED、個人メール本文、非公開音声、カレンダー詳細、直接識別情報を伴う心理・行動推論、同意範囲外signalである。

Drive書込みは保存先、access scope、consentが確定した場合だけ許可する。parent GitはDrive本文、会話全文、直接識別情報を保存しない。Drive artifactの公開、共有範囲拡張、削除は通常の自律改善権限に含めない。

## 18. 非機能要件

- Python 3.11以上、初期依存は標準library + PyYAML
- Linux/macOSで動作
- offline fixtureでnetworkなしに主要testが完走
- 同一snapshot/configから同一JSONを生成
- 100 work itemsでも実用時間内に終了
- 失敗にrepo、field、rule、remediationを含める
- 会話履歴なしで再開可能
- interaction応答はimprovement/audit処理の完了を待たない
- Drive adapterはnetworkless fakeでcreate-only/idempotencyを検証可能
- 同一interaction/snapshot/configから同一routingとmetadataを生成

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
- GitHub Projects #4同期が重複itemを作らず、接続不能でもローカル実行が継続する
- forbidden dataがworking tree、bundle、Git historyにない
- offline E2Eが3回連続成功
- 新規Luna/Sonnet級agentが文書だけで次taskを完了
- merge/releaseの人間gateが維持される

### 19.3 v1.1.0

- 利用エージェントがrepo名やGit操作を要求せず、最小の関連KBから根拠付き回答を返す
- すべての回答根拠がsource repository@commit、freshness、unknownsまで追跡可能
- interaction eventが会話全文をGitへ保存せず、intent、outcome、snapshot、artifact、feedbackを保持する
- Google Drive成果物がcreate-onlyで保存され、修正版は新artifact + lineageとなる
- explicit feedbackとinferred feedbackが機械的に区別され、推定がユーザー事実へ昇格しない
- feedbackがauthorityに従って親または子repoのIssue候補へ決定的にrouteされ、duplicateを抑止する
- eligible Issueがlease/checkpoint付きで実装・test・draft PRまで自律実行される
- auditorがinteraction latencyと独立してrefactoring Issue/draft PRを生成する
- privacy、consent、Drive権限、artifact lineage、child quality gateの失敗が期待する終端状態へ到達する
- networkless interaction E2Eが3回連続で決定的に成功する
- merge、release、公開、共有範囲拡張、artifact削除の人間gateが維持される

## 20. 変更管理

contract major、ownership、data boundary、human gateを変える場合は、Issueに観測事実、選択肢、推奨、migration、rollbackを記載し、人間決定後に設計・schema・fixture・testを同じ変更で更新する。実装都合で子repoのdomain schemaを変更しない。
