# Agentic Art Orchestration システム設計仕様書

作成日: 2026-08-11  
最終更新: 2026-08-12
対象: masa-san-jp/agentic-art-orchestration  
状態: v1.2.1基線化・v1.3 Production実連携・v1.4初期運用 / 実装用正本

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
11. 初期段階ではCodexまたはClaude Codeを会話UIとし、専用Web/GUIを待たずに利用可能にする。
12. 初期改善はprivacy-safeなGitHub Issueの作成まで、初期監査と子repo更新確認はオーケストレーション起動時に毎回行う。

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
- immutable bundleによるResearch→Production→Researchのhandoff/result往復
- Codex/Claude Code用の起動契約、全登録repoのremote head確認、起動時audit
- 実Google Driveへのcreate/read確認と、GitHub Issueのcreate-only delivery

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
- 初期運用で専用Web UI、mobile client、常駐daemonを必須にすること
- 初期運用でIssue作成後の自動実装、branch、commit、PR、merge、releaseを実行すること
- 起動時の更新検知だけでmanifest pinや子repo checkoutを自動更新すること

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
| Interaction agent | CodexまたはClaude Codeとして会話、意図理解、retrieval、成果物提示、feedback観測 | 推定を事実化、改善完了待ちで会話をblock |
| Improvement agent | feedback分類、Issue routing、初期運用ではcreate-only Issue delivery | authority不明のrepoへの直接変更、初期運用での実装・PR作成 |
| Worker agent | 1taskの実装、test、記録、draft PR | 別taskへの無制限拡張 |
| Child repository | domain要件、データ、schema、quality gate | 親run stateの所有 |
| Auditor | 初期運用では起動時にdrift、privacy、鮮度、孤立、構造品質を監査しIssue候補を作る | 自動で事実を補完、user artifact変更、初期運用でのrefactoring実装 |
| Google Drive artifact store | immutable user output、revision lineage、feedback reference | domain KBやtask queueの正本化 |

## 5. 全体アーキテクチャ

~~~text
User <-> Codex / Claude Code
              |
       startup + parent control plane
  registry + contracts + queue + state
       /          |             \
 repository   artifact       feedback
 retrieval    adapter        router
     |            |             |
five child   Google Drive   create-only
repositories  append-only   GitHub Issue
     \            |             /
      provenance + startup audit
~~~

親repoはcontrol plane、子repoはdomain knowledge/data/implementation plane、Google Driveはuser artifact planeである。CodexまたはClaude Codeが初期frontstage、Issue deliveryとauditorがbackstageである。workspaceはローカル生成物で、親Gitの管理対象外とする。専用UIへの置換はこの境界を保つ限り後方互換なadapter追加として扱う。

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

manifestのcommitは最後にqualifiedとなった利用可能pinであり、run開始時に生成するsnapshotがそのrunの実入力commitを固定する。既存4repo IDはcore setとして必須とし、追加repoは既存entryの置換ではなくappendする。追加entryにもunique ownership、role-contract、同一repo Issue SSOT、instructions、quality gateを要求する。`agentic-art-production`は`production-handoff/v1`をimportし、`production-result/v1`をexportする双方向runtimeとして登録し、normalized research signalのproducer/consumerへ誤分類しない。

remote default branchの先端は起動時に毎回read-onlyで観測するが、manifest pinと同一ではない。差分はupdate candidateとして記録し、資格確認、child quality gate、親PRを経るまでrunの入力へ昇格させない。この分離により、子repoが随時更新されても会話は最後のqualified snapshotを再現可能に利用できる。

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

## 10F. 初期運用profile

初期運用profileは、将来像を削除せず、実際にremote side effectを伴う範囲を次へ限定する。

| Concern | 初期運用 | 後続拡張 |
|---|---|---|
| Human interface | CodexまたはClaude Code | 専用Web/GUI、他agent client |
| Improvement | GitHub Issueのcreateまたはduplicate reuseまで | 実装、test、draft PR |
| Audit | orchestration起動時に同期実行し、findingをIssue候補化 | 非同期常駐監査、refactoring PR |
| Child updates | 起動時に全repoのremote headをread-only確認 | webhook/polling、再qualification自動起票 |
| User artifacts | 承認済みDrive folderへのcreate/read verification | 外部artifact検索・高度なfeedback連携 |

初期profileで許可する外部mutationは、ユーザーが成果物保存を求めた場合のDrive CREATEと、feedback/audit findingがpolicyを満たす場合のGitHub Issue CREATEだけである。既存Drive fileのupdate/delete/move/share/permission変更、既存Issueのedit/comment/close/delete/label変更、子repoのbranch/commit/PR、merge、releaseは許可しない。

## 10G. Orchestration startup contract

CodexまたはClaude Codeは、最初のknowledge利用または外部writeより前に、単一のstartup commandを一度実行する。同じagent process内ではstartup reportの有効期限内だけ再利用でき、新しい起動では必ず再実行する。

~~~text
validate parent configuration
  -> observe every manifest repository remote HEAD (read-only)
  -> guard local workspaces and select qualified pins
  -> snapshot
  -> status + audit + security
  -> capability decision
     READY | READY_WITH_FINDINGS | BLOCKED
~~~

startup reportは、run ID、親commit、各repoのqualified pin、remote observed commit、observation timestamp、drift、workspace guard、audit/security finding code、capability、remediationだけを持つ。token、raw remote response、会話全文、Drive本文、直接識別情報を持たない。

状態判定は次の通りとする。

- `READY`: 全repoを観測でき、qualified pinが利用可能で、blocking findingがない。
- `READY_WITH_FINDINGS`: remote head差分、非critical audit finding、または一時的なread-only remote観測不能があるが、最後のqualified snapshotで安全に回答できる。回答には使用commitと制約を表示し、release、pin更新、子repo変更、影響repoへのpin-bound improvementを止める。findingがすべてnoncritical warningの場合は、親のbranch、commit、draft PRによるcontrol-plane修復を許可し、merge、release、tagは人間承認に残す。
- `BLOCKED`: parent validation失敗、dirty/detached/divergedな利用対象、schema major不一致、credential/PRIVATE_RAW/RESTRICTED、consent違反、またはcritical security findingがある。影響capabilityを実行しない。

remote head差分は更新の存在であり、直ちに異常でも採用指示でもない。startupはcheckout、pull、merge、reset、manifest編集を行わず、repo ID、qualified pin、remote observed commitを持つupdate candidateを生成する。採用は別taskでimmutable archiveを取得し、manifest記載child gateと親compatibilityを通して親PRにする。

auditは初期profileではstartupの一部として完了を待つ。ただしaudit findingのIssue作成と将来の修復はユーザー応答後のbackstage side effectとしてよく、Issue API障害だけを理由にqualified knowledgeのread-only利用を止めない。

## 10H. Create-only GitHub Issue delivery

Issue deliveryは既存Issue routerのprivacy-safe候補だけを入力とし、target repositoryをmanifest authorityとallowlistの積で決定する。実行前に同じstable deduplication keyを検索し、既存Issueがあれば新規作成せずそのURLを返す。

Issue bodyは次だけを含む。

- stable issue key、source kind (`explicit` / `inferred` / `audit` / `repository-update`)
- privacy-safe summary、観測されたfrictionまたはfinding、期待outcome
- target authority、proposed acceptance、source repository@commitまたはopaque interaction/artifact reference
- inferredの場合は`unconfirmed hypothesis`、confidence、反証条件
- prohibited data scanと生成agent/run ID

raw conversation、Drive本文、PRIVATE_RAW、RESTRICTED、credential、direct identifierをIssueへ送らない。consentまたはauthorityが不十分なら`TRIAGE`に留める。初期profileではIssueの作成または既存Issueの再利用がterminal stateであり、実装task、branch、commit、PRを自動開始しない。

## 10I. Real Google Drive boundary

実Drive adapterはprovider-neutralなportとし、Codex/Claude Codeのconnector、承認済みCLI、またはservice adapterのいずれでも同じrequest/result envelopeを使う。OAuth tokenやprovider sessionはrepo外の実行環境が所有する。

CREATE requestはapproved folder ID、artifact metadata、content hash、idempotency key、access/consent scope、lineageを持つ。adapterは新規fileを作成後、file IDとcontent hashまたはread-back hashを確認してopaque resultを返す。同じkey・同じhashは既存結果をreplayし、同じkey・異なるhashは拒否する。修正版は新key・新file・`supersedes` relationで保存する。

実装・qualificationは、networkless fakeによる決定性検証と、明示的に指定したsandbox folderでのopt-in live smokeを分離する。live smokeは既存fileを更新せず、作成したtest file IDを証跡化する。削除を自動cleanupに使わないため、保存先にはtest artifactのretention policyを事前に設定する。

## 10J. Research / Production exchange

親が所有するのは双方向交換の順序とevidence envelopeだけであり、`production-handoff/v1`はResearch、`production-result/v1`はProductionが所有する。

~~~text
Research@commit
  export_handoff -> immutable handoff bundle
    Production@commit
      receive -> plan/prototype/simulated execution in Git-external project
      export_result -> immutable result bundle
        Research@commit
          import_result --dry-run -> optional apply only in an explicit child task
~~~

親は隣接working treeを直接参照せず、manifest pinから作ったclean immutable archive上で子repo自身のgenerator/validatorを呼ぶ。bundleとProduction project/resultはGit外のrun-scoped output rootへ置く。親のevidenceはproducer/consumer repository@commit、contract version、schema/bundle semantic hash、child command、exit status、terminal status、opaque output locatorだけを保持し、子schemaやbundle本文を複製しない。

Productionの物理作業、購入、契約、公開、外部送信はE2Eで実行せず、`NOT_RUN`または`EXTERNAL_VALIDATION_REQUIRED`を保持する。Researchへのresult applyは子repoを変更するため、初期の親E2Eでは`--dry-run`までを必須とし、applyは別child task、別commit、別PRとする。

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
- startup reportが全manifest repoのqualified pinとremote observationを区別すること
- remote driftがmanifest pinまたはcheckoutを暗黙更新していないこと
- GitHub write operationがIssue CREATEまたはduplicate reuseだけであること
- live Drive operationがCREATE/read verificationだけであること
- Production exchangeのcontract owner、producer/consumer commit、bundle hashが完全であること
- forbidden data classとlikely secret
- generated dataが正本より古くないこと

## 16. Audit rules

auditは通常のcommitを一律に止めず、stale pin、remote update、SSOT変更後の未検証、orphan signal、requirementの根拠不足、marketing freshness、self-model consent、art relation根拠、重複Issue/PR、長期BLOCKED、孤児lease、未push commit、artifact lineage欠落、feedback routing drift、retrieval coverage、interaction/audit lane競合を次の修復候補として出す。初期startupではcritical privacy/security/schema findingだけを`BLOCKED`、それ以外を`READY_WITH_FINDINGS`に写像する。

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
- startupはmanifest repo数に依存せず全entryを検査し、同一観測入力から同一判定を生成
- remote API、GitHub Issue、Google Drive障害はrepo/operation単位に分離し、成功済みside effectを重複しない
- Production exchangeはGit外output rootで反復可能で、子schemaやasset bodyを親Gitへ保存しない

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

### 19.4 v1.2.1 baseline

- `agentic-art-production`を含む5repoのmanifest pin、snapshot、status、audit、child gateが一致する
- v1.2.0公開後の親main変更をv1.2.1として3回連続qualificationする
- 5repoすべてのimmutable child gateがpassし、remote mutationは0件である
- review、main merge、tag、GitHub Releaseは明示的な人間承認で実行する

### 19.5 v1.3.0 Production exchange

- Research pinがhandoff exportとproduction-result dry-run importを、Production pinがhandoff receiptとresult exportを提供する
- 親orchestratorがResearch→Production→Researchをclean immutable commitとGit外output rootだけで往復させる
- tamper、schema/hash mismatch、dirty source、replay、未実施外部検証をfail-closedで観測する
- 子repo schema、canonical data、working treeを親が変更・複製しない
- parent + 5 child gatesとexchange E2Eが3回連続成功する

### 19.6 v1.4.0 initial interactive operations

- CodexまたはClaude Codeだけでstartup、根拠付き回答、成果物保存、feedback収集を会話として完結できる
- orchestration起動ごとに全manifest repoのremote head確認とaudit/securityを行う
- updateがある場合も最後のqualified pinを使い、差分と制約を明示して自動pin更新しない
- 実Google Driveの承認済みfolderに新規artifactをcreateし、read-back/hashを確認し、既存artifactを上書きしない
- eligible feedback/audit findingをauthority repoのGitHub Issueとしてcreateまたはdeduplicateし、Issue後の実装を自動開始しない
- raw conversation、Drive本文、機微情報、credentialをGitHubまたは親Gitへ保存しない
- networkless E2Eを3回、opt-in sandbox live smokeでDrive CREATE/readとIssue CREATE/deduplicateを確認する
- PR、merge、release、子repo mutation、Drive update/delete/shareは人間または別明示taskのgateを維持する

## 20. 変更管理

contract major、ownership、data boundary、human gateを変える場合は、Issueに観測事実、選択肢、推奨、migration、rollbackを記載し、人間決定後に設計・schema・fixture・testを同じ変更で更新する。実装都合で子repoのdomain schemaを変更しない。
