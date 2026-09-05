# Agentic Art：自律制作と累積知識の統合仕様

作成日: 2026-09-05  
仕様ID: AAK-SPEC / version: 1  
実装計画SSOT: [20260905-agentic-art-autonomy-and-knowledge-cycle-implementation-plan.md](20260905-agentic-art-autonomy-and-knowledge-cycle-implementation-plan.md)  
適用範囲: 本文AAK-01〜AAK-13で明示した追加・変更。これは目標仕様であり、実装済みの宣言ではない。

## principles

このプロジェクトの精神は、芸術の契機を「精霊や風が運び、人間が受け取って具象化する」と捉える営みを、AIエージェントを用いて再現することにある。これは利用者が示した制作思想であり、歴史学上の普遍的事実の主張ではない。

求める状態は「エージェントハーネスとしてエージェントが自律的に制作プランを出力できる」ことである。エージェントは参照可能な知識と世界との接触から表現の契機を運び、人間が具体的な制作に着手できるプランを届ける。通常工程の選択・呼び出し・再開・可逆な修復を人間に丸投げしない。

1. ハーネスを使う外部エージェントを実行主体とする。リポジトリにLLMやdaemonを内蔵していないこと自体は欠陥ではない。
2. 既存の半決定論的設計を保持する。固有入力、変換規則、候補、seed、選択、機構と参照資料の関係を追えることを要求する。出典にない意味の自由生成を標準経路へ持ち込まない。
3. 一つの成功例に限定せず、異なる制作プランを継続的に生成する。
4. 全8リポジトリが、その性質に応じた知識・判断・制作記録・運用経験を蓄積し、次回の制作で再利用する。
5. 利用者ごとの感性・選択・制作履歴を区別し、共有知識と制作の系譜は帰属と条件を保持して継承する。
6. 成功状態やファイル数を目的にしない。制作プランの内容と実体、永続化、次回利用の証拠で完了を判定する。
7. 採否・比較・根拠を記録するが、モデルの非公開な内部推論全文の保存は要求しない。

## authority

この仕様と実装計画は、利用者が本会話で要求した改修系列のSSOTである。既存機能の全要件を置き換える文書ではない。

| 対象 | 正本 | 他の文書の役割 |
|---|---|---|
| 今回の目的、追加要件、境界、受入条件 | 本仕様の共通節とAAK別節 | Issueの説明は実行用の投影。意味を変える場合は先に本仕様を改訂する |
| 実装順、依存、検証方法、再開手順 | 実装計画のAAK別節 | queueはownerごとの現在状態を持ち、計画と契約hashを照合する |
| 領域のデータ形式・renderer・validator | 各ownerの既存schemaと、本仕様に従ってownerが改訂するschema | 親は境界形式だけ所有し、子のschema・本文をvendor copyしない |
| 実装の現在状態 | ownerのtask queue/stateと観測済み検証証拠 | Issueはtask識別と配送状態、PRは差分と証拠を持つ |
| 原始資料・測定・作品 | ownerが指定する原本 | hash・revision・権利と参照を保持する |

Issueには仕様と計画のcommit固定URLを付ける。仕様改訂時はversion/変更理由/影響taskを更新し、影響Issueのpinも更新する。コメントだけを新しい要件の正本にしない。未mergeのSSOT文書も指定commitから読める。AAK-01が通常のPR経路でREADME/既存仕様/queueへ参照を定着させる。

今回のIssue起票はコード変更の完了や、実個人データ移行、外部公開、merge、releaseの承認を意味しない。コーディングエージェントはIssueで指定した範囲の実装・テスト・作業branch・commit・draft PRまで進め、既存の人間承認が必要な操作はその境界でのみ判断を求める。単に旧文書が「この型はまだ無い」とすることを、本仕様で明示した型の追加を止める理由にしない。

## baseline

以下は2026-09-05にGitHubの既定branchから読み取った基準commit。過去の検証成功は履歴として扱い、この仕様の受入通過と混同しない。実装開始時に最新差分と既存PRを再確認する。

| リポジトリ | 既定branch | 観測commit |
|---|---|---|
| agentic-art-orchestration | `main` | [02153dde6304](https://github.com/masa-san-jp/agentic-art-orchestration/commit/02153dde6304ec4457cf41113a73a83c7f67d361) |
| self-model-notes | `main` | [a61460d4f9ad](https://github.com/masa-san-jp/self-model-notes/commit/a61460d4f9add36b256b2db9a860c53a98bd5fcd) |
| art-history-notes | `main` | [de5a3c3ef2d1](https://github.com/masa-san-jp/art-history-notes/commit/de5a3c3ef2d1cb13f84e522ee73211d70e214f65) |
| marketing-trends-notes | `main` | [de1f77730d38](https://github.com/masa-san-jp/marketing-trends-notes/commit/de1f77730d3856e7e81d591de48da5aed79a983a) |
| agentic-art-research | `main` | [71bfec77ea0d](https://github.com/masa-san-jp/agentic-art-research/commit/71bfec77ea0d189186b8248565d340c124b81eab) |
| agentic-art-production | `main` | [9d125fb87be1](https://github.com/masa-san-jp/agentic-art-production/commit/9d125fb87be133f5e73e61e04e23c0a3bfafb462) |
| viewer-response-notes | `feat/viewer-response-contracts` | [78b6e9a87831](https://github.com/masa-san-jp/viewer-response-notes/commit/78b6e9a87831eca5a5c20993374b61b8cc61bd0d) |
| agentic-art-project | `main` | [aa32bfe29e25](https://github.com/masa-san-jp/agentic-art-project/commit/aa32bfe29e25acdefab6a62f8893fc369c569df5) |

確認済みの既存実装と関連Issue:

- 半決定論的候補生成: [agentic-art-orchestration#2](https://github.com/masa-san-jp/agentic-art-orchestration/issues/2)。自律ループの要求: [agentic-art-orchestration#88](https://github.com/masa-san-jp/agentic-art-orchestration/issues/88)。新しいdaemonを作ることを本系列のゴールにしない。
- Researchの機構接地・過去作比較: [agentic-art-research#83](https://github.com/masa-san-jp/agentic-art-research/issues/83)、[agentic-art-research#85](https://github.com/masa-san-jp/agentic-art-research/issues/85)。未実装扱いで再作成せず、新しい累積知識へ接続する。
- 個人profile分離: [self-model-notes#81](https://github.com/masa-san-jp/self-model-notes/issues/81)。実n=1移設: [self-model-notes#82](https://github.com/masa-san-jp/self-model-notes/issues/82)。後者の実データ移設は本系列で自動実行しない。
- plan attestation: [agentic-art-production#60](https://github.com/masa-san-jp/agentic-art-production/issues/60)、無変換投影: [agentic-art-orchestration#193](https://github.com/masa-san-jp/agentic-art-orchestration/issues/193)、受信・旧要約の移行: [agentic-art-project#6](https://github.com/masa-san-jp/agentic-art-project/issues/6)。これらを完全性検証の正本として再利用する。
- 出力先/clone基盤: 親#148/#149/#150。最新pin問題: [agentic-art-orchestration#189](https://github.com/masa-san-jp/agentic-art-orchestration/issues/189)。公式catalog関係: [agentic-art-orchestration#190](https://github.com/masa-san-jp/agentic-art-orchestration/issues/190)、自動plan出力: [agentic-art-orchestration#187](https://github.com/masa-san-jp/agentic-art-orchestration/issues/187)。
- Orchestrationの既存PR #191とProject #9は正本検証関連の作業候補。Issueの現行契約、特にattestation/v2と一致するか検証してから採用し、PRがあるだけで解決済みとしない。

## ownership

| owner | 永続蓄積するもの | 読み出して利用する場面 |
|---|---|---|
| self-model-notes | 本人選択と根拠付き派生自己モデル | 同意済み本人signalを作る |
| art-history-notes | 美術史の作品・技法・時空間・関係・反証 | 制作の歴史的接地と新しい参照探索 |
| marketing-trends-notes | 時点・地域・媒体を持つ社会観測と再検証 | 制作の現代的文脈と適用条件の確認 |
| agentic-art-research | 仮説・証拠・採否・矛盾・未解決の問い | 前回の到達点から研究を再開・発展させる |
| agentic-art-production | 条件付き技法・試作・実績・失敗・修正 | 実現可能な材料・工程・資源を計画する |
| viewer-response-notes | 条件を持つ集計反応と保守的assessment | 表現の受容を支持・反証・新しい問いとして扱う |
| agentic-art-project | 正規plan・作品・作者・改訂・派生の系譜 | 自作/他者/未制作構想の比較 |
| agentic-art-orchestration | 実行の失敗・復旧・検証済み運用知識 | 自律実行と改善の判断。権限規則の自動変更には使わない |

一つの資料が複数ownerに関係しても、同じ原本を複数の正本として保管しない。owner別の派生recordから元artifactを参照する。Researchは知識候補を生成できるが、美術史のverified化や本人のtrait確定は各owner validatorの責任とする。

## storage

知識は明示したownerのGit管理対象にする。通常のスキーマに適合する共有知識は既存entities/contexts等へ、Research/Production/Orchestrationの再利用記録はknowledge/へ追加する。配置名と領域schemaはowner側で固定する。

利用者データを公開protocolへ混ぜず、必要に応じて利用者所有の非公開 counterpart repositoryまたはローカルGit repositoryをそのownerのknowledge storeとして指定する。これは一時output directoryに放置する代替ではなく、同じowner契約でcommit・索引・再読込可能な正本である。clone-only利用でもremoteなしで永続化・再利用を完了できる。

| 保存区分 | 例 | 保存と寿命 |
|---|---|---|
| canonical knowledge | 検証済みentity、採否、条件付き技法 | owner Gitへcommit。自動期限削除しない。訂正はrevision/撤回参照で追跡 |
| canonical plan/work | 統合plan、作品の記録 | ownerの原本とカタログ系譜。plan本文を短い要約で置換しない |
| restricted/raw/large asset | 個人原文、録音、RAW、大容量映像 | 明示external store。必要なopaque locator/hash/権利だけownerへ |
| execution state | claim、lease、checkpoint、attempt log | run用外部state。復旧に必要な間保持し、cleanupは明示policyと到達済みreceiptに基づく |
| reproducible cache | graph、bundle、index | 原本から再生成。手編集しない。削除しても正本は失わない |
| rejected/unresolved | 不成立の仮説、未採用案、未解決問い | 知識として価値があれば理由/条件付きで保持。事実や成功例にはしない |

同じrunで生成された全ファイルを無差別にGitへcommitしない。登録対象のallowlistをowner validatorで確認し、raw/credential/権利不明物を除外する。

code_refとknowledge_refを分離する。実行コードは資格済みcommitの隔離checkoutから読み、入力知識はowner/collectionごとの別commitで固定する。同一物理repoでもrefの役割を区別する。知識の正常な追加がcode pin guardを毎回失敗させてはいけない。既存ユーザーworktreeをreset/checkoutして整合させず、専用の検証済みworktreeを作る。

## instance-profile

新しいversioned instance profileは以下を持つ。schema名はinstance-profile/v1、既存output-destinations/v1は互換adapterで利用する。共有設定にmachine固有絶対pathやcredentialをcommitしない。

```yaml
contract_version: instance-profile/v1
instance_id: example-instance-b
creator_id: creator-b
mode: new-clone
delivery_mode: internal
personalization_mode: explicit-profile
repositories:
  agentic-art-research:
    code_repository: example/research-code
    code_commit: <40-character-commit>
    knowledge_store_id: research-memory-b
    knowledge_ref: knowledge/creator-b
    source_collections: [shared-art-history, research-memory-b]
permissions:
  local_knowledge_write: true
  local_git_commit: true
  remote_write: false
  public_projection: false
```

例は省略形。実schemaではrepositoriesへ全8ownerを宣言し、creator/collection/store権限・local mappingを検証する。絶対pathはinstance外部local configでstore_idから解決する。null/欠落で他人のprofileや元ownerへfallbackしない。

- resume: instance/creator/collection identityを保存済みprofileと照合し、蓄積を継続する。
- new-clone: 新instanceと本人identity、空の本人履歴を作る。ライセンス・権利の許す共有知識/作品はoriginを保持して参照する。
- fork: 新instanceの制作を新originで記録する。継承したレコードの作者・originは保持する。upstreamからのcode更新とknowledgeの差分取込は独立させる。
- personalization_mode=public-seed-only: 本人資料未準備で公開知識から探索する明示モード。本人固有性は未充足と表示し、個人モードの合格証拠にしない。
- 初回本人選択・同意・出力先決定はsetupとして一度記録する。通常の制作でテーマ・slug・次工程を繰り返し質問しない。
- 他者のprofileを参照作品・資料として許可された範囲で読む場合も、active creator本人モデルとは別扱いにする。

新profileのdelivery_mode=internalではplanの内部保存とknowledgeの永続化が必須で、public projectionは未選択ならSKIPPED。public-catalogを選んだ場合だけ設定済みcatalogへの正規投影を必須にする。既存legacy profileの未設定時挙動は互換経路として残し、変更時は明示version移行する。remote公開は両モードの必須条件ではない。

## artifact-record

共通の交換envelopeはartifact-record/v1とし、内容はowner schemaで検証する。必須フィールドと意味:

| フィールド | 契約 |
|---|---|
| record_id / revision | origin-instance内の安定ID、1以上のrevision。同revision同hashは同一物 |
| origin_instance_id / creator_id / owner_repository / collection_id | 発生元・本人/作者・正本の責任・アクセス単位。unknownは本人へ推定変換しない |
| kind / payload_schema | ownerが宣言した型とschema version。親に子のcore型定義を複製しない |
| payload_ref / content_sha256 | repo-relative locatorと正確なUTF-8 bytesまたはasset bytesのSHA-256 |
| sources / derived_from | origin、record ID、revision、source repository、code/knowledge commit、locator/hash |
| epistemic_status | observed / externally-supported / inferred / proposed / simulated / unknown。domain語彙との変換をownerが定義 |
| lifecycle | candidate / accepted / rejected / superseded / revoked。候補のまま独立した事実には数えない |
| applicability | 時間・地域・材料・媒体・設備・対象等の条件。欠落はunknown |
| rights / access_scope / consent_ref | 利用可能範囲。private storeの許諾とpublic再配布を別判定 |
| created_at / reviewed_at / valid_until | timestampと再検証条件。時間のない記録は時点推定しない |
| producer | agent/human/toolの帰属、generator version、code commit、run ID。モデル情報は実際の観測値だけ |
| supersedes / invalidates | 訂正・撤回の対象。履歴を消さずactive検索への適用を制御 |

参照の識別キーはorigin_instance_id＋owner_repository＋record_id＋revision。コンテンツhashを人格/作品のidentityにしない。履歴に同じID/同revision/異hashを追加しようとした場合はREVISION_CONFLICT。同内容replayはALREADY_APPLIED。未知schema major、owner不一致、path traversal、symlink escape、権限外collectionは拒否する。

生成AIが同じ情報を別表現で再出力しても、新しい独立出典にはならない。sourcesの祖先をたどり、同一測定/同一一次資料/同一生成recordへの循環を検出する。親や他者のGitへ機微本文を複製しない。

## knowledge-cycle

一つのrunの標準経路は、入力snapshot固定→過去知識検索→候補/仮説/比較→調査と検証→制作プラン生成→owner別knowledge保存→索引更新→次回参照である。物理制作や鑑賞者計測が未実施なら、そのownerの実測知識はNO_NEW_EVIDENCEとし、値を作らない。

ownerの正規CLIへ次の機能を追加する。既存CLIが同機能を持つ場合は互換adapterを使い、同じ実装を別名で複製しない。

| 操作 | 入力 | 出力・不変条件 |
|---|---|---|
| prepare | 検証候補bundle、origin/run、target collection | candidate manifest。正本は未変更 |
| validate | candidate＋固定owner schema/policy | structured findings。失敗を補完してPASSにしない |
| commit | 検証済みcandidate、期待するknowledge parent SHA、operation ID | ownerだけのatomicローカルGit commitとknowledge-write-receipt/v1。remote副作用なし |
| index | 採用済みknowledge commit | 再生成可能な索引。失敗ならcommitを消さずINDEX_PENDING |
| retrieve | query、creator、scope、時点、snapshot、探索policy | record refs＋理由＋状態。rawや権限外recordは返さない |
| invalidate | source revision/撤回 | active索引の失効・派生再検証対象。過去runの原本は削除しない |

knowledge-write-receipt/v1にはoperation_id、run_id、owner、collection、target parent/commit、採用/棄却ID、schema/policy version、index commit/hash、status、理由を持つ。少なくともNO_CHANGE/COMMITTED/INDEX_PENDING/REJECTED/CONFLICTを区別する。実体とtree/commitを検証してからCOMMITTEDとする。

複数repoへの保存は分散transactionとみなす。一括atomicを主張せず、owner別receiptとoutboxで再開する。成功済みownerを巻き戻して履歴を消さない。同runのpending ownerだけを再実行する。同一owner branchはsingle writer/CASで競合を検知する。

reuse-trace/v1には、query/selection policy version、input snapshot、取得したrecord/revision、見た範囲、採用/棄却/要再検証、判断理由、影響した仮説/要件/機構を保持する。検索結果に載っただけを「再利用」と数えない。EMPTY_HISTORY、NOT_APPLICABLE、UNAVAILABLEを区別する。

棄却理由は少なくともevidence-contradicted / insufficient-evidence / budget / environment / timing / artistic-choiceを区別する。理由だけで自動採択し直さず、現在条件と元の証拠を再検証する。

## completion

次の状態軸を分けてreportする。既存状態を互換adapterで接続する。

- plan_status: RESEARCH_PENDING / PLAN_BUILDING / PLAN_READY / BLOCKED / FAILED。
- knowledge_status: PENDING / COMMITTED / NO_NEW_EVIDENCE / PARTIAL / FAILED。
- projection_status: SKIPPED / PROJECTED / BLOCKED / FAILED。
- run_status: RUNNING / COMPLETED / BLOCKED / FAILED / INCOMPLETE。

PLAN_READYは、正規Production aggregate、要件の意味的coverage、renderer、plan本体と必要asset/hash/参照が検証できた場合だけ許す。workerのCOMPLETED JSONだけでは到達しない。AAK-10は計画内容、既存Production#60は正本証明、親#193/Project#6は投影・受信境界を所有する。

runのCOMPLETEDは、そのdelivery modeで必須のplan保存・knowledge永続化/索引・投影が完了した場合だけ許す。知識保存に失敗してもplan原本を失わずPARTIAL/INCOMPLETEと次の正確な操作を返す。実測反応が無いことはNO_NEW_EVIDENCEで正常であり、plan生成を妨げない。

再開時は同じprofile/snapshot/run IDを照合し、完了stageのartifact hashとreceiptを確認して再利用する。retry/timeout/探索/コスト上限はconfigに有限値を置き、現在の上限を未検証で増やして通さない。再試行ごとに進捗を確認し、無進捗反復を検出する。人間の権限が必要な場合のみ、観測・停止位置・解除条件を一件のreportへ集約する。

## compatibility

| 現行の規則・Issue | 今回の変更 | 維持する境界 |
|---|---|---|
| Self Model #1/#81: 実データexternal-localのみ | 派生自己モデル等を本人所有のprivate/ローカルGit knowledge storeへ保存できる版付き拡張をAAK-05で追加 | 公開protocolから個人記録を分離。rawは外部。実n=1移設#82は別承認 |
| Research/Production: 実projectをGitへ常設しない | 再利用可能な検証済みknowledgeをGit管理する明示owner経路を追加 | attempt/runtime/rawをproject丸ごとcopyしない |
| Orchestration #190/#193: Projectをexport-onlyとする | 公開projectionは出力専用を維持し、canonical公開履歴を読む独立catalog-reference能力をAAK-13で追加 | Projectを本人KBとして扱わず、内部ログ/handoffを公開しない |
| #187: 出力先profileと自動plan投影 | 新instance profileでinternal/public-catalogを明示。legacyはversion互換を保持 | canonical planの無変換、権利・同意・remote公開の境界 |
| 親の全child pin guard | code refsとknowledge refsを分離し、資格済み隔離workspaceで参照 | 既存dirty treeの破壊修復、無検証pin採用は禁止 |
| viewerのappend-only/集計only | 系譜/展示条件/失効参照を追加 | 自由回答・個人識別・統計閾値の無断変更は禁止 |

既存Issue本文とAGENTSへの参照更新は、各ownerタスクの仕様同期に含める。実装を止めるための曖昧な「別途設計」は残さない。ここに明示した限定変更は本系列で実装できるが、機微原文公開、権利・同意の拡張、実データの不可逆移行は含まない。

## acceptance-matrix

最終検証は3利用モードそれぞれで連続2runを実行する。2runは「蓄積して次へ使う」を観測する最小の回数であり、芸術的品質の統計的保証ではない。

| ケース | 観測すること |
|---|---|
| 本人の継続利用 | 明示profileと過去履歴を保ち、2回目で1回目の新しい知識を判断へ利用する |
| 新規clone | 新identity・本人資料・ローカルGitだけで開始。元作者の本人データを借りない |
| fork | 継承作品の作者/出典を保持し、新作が新originに属する。upstreamへ自動writeしない |
| 改竄/偽成功 | 空plan・要約・成功JSONのみ・異revision・hash不一致は完了しない |
| 再開 | Research後、plan後、一部owner保存後の中断から重複なく再開 |
| 失効 | 訂正/同意変更/鮮度切れを次回active検索へ反映 |
| 実行能力 | 外部エージェントがnext_actionを消化。人間の逐次コマンドが不要 |
| 固有性と探索 | 入力差替え・同機構言換え・根拠なし比喩・自己引用を検出 |

実Masa profileを使う場合は既存同意とアクセス範囲内だけに限定する。使えなければ合成の継続利用ケースと明示し、実本人データ検証済みとしない。LLM providerが利用できない環境はfake回帰のみ実行し、最終live受入は未完了とする。

## issue-contracts

以下の各節がtaskごとの仕様正本。Issue本文・機械taskはこの投影であり、差が出た場合はこの節を確認する。タスクの実装順・検証は実装計画の同じID節を参照する。

## aak-01

対象: `masa-san-jp/agentic-art-orchestration`  
Issue件名: 設計原則・仕様SSOT・実装DAGをエージェントの正準入口へ接続する

理由: 制作プランの実体を届ける目的より、基盤の完成や成功状態の表示が優先される読み違いを防ぐ。今回の設計を会話履歴なしで実行できるようにする。

確認した現状: README/AGENTSに目的はあるが、全8repoの累積知識・利用者別継承を含む今回の統合仕様は未接続。既存の半決定論的方針は親Issue #2で定義済み。

### 実装要件

1. 本仕様のprinciples/authorityをREADME・AGENTS・既存設計の読順へ接続し、この変更範囲の上位要件として参照する。歴史の断定ではなくプロジェクトの精神として記述する。
2. AAK-01〜13のID、owner、仕様anchor、依存、checksを実行計画から既存queueへ登録する。子Issue本文は親へ複製せず、URLとcommit付き仕様参照を持つ。
3. 実行順は依存解決済みの最小IDとする。完了済みの旧タスクを再開せず、今回の差分を新系列で追加する。
4. 仕様/計画のMarkdownを唯一の規範本文とし、task contractはその内容から生成・検証する実行用投影にする。SSOTのリンク切れ・契約hash不一致を検出する。
5. 各子repoの領域schema所有権を保持し、変更対象・旧規則との差分をauthority表で明示する。

### 受入条件

- [ ] AAK-01-AC1: 13件が重複なく8repoに対応し、依存グラフに循環がないことを機械検証する。
- [ ] AAK-01-AC2: 新しいエージェントがREADMEから仕様・計画・次taskへ到達できる。
- [ ] AAK-01-AC3: 仕様参照の欠落・誤ったowner・循環依存・契約hash不一致の負例が失敗する。
- [ ] AAK-01-AC4: 今回の機能を未実装のままDONEにせず、旧タスクの証跡・既存進捗を保持する。

## aak-02

対象: `masa-san-jp/agentic-art-orchestration`  
Issue件名: 実エージェントで制作プラン出力・蓄積・次回再利用を自律完走させる

理由: ハーネスを使うエージェントが、工程ごとの人間の段取りなしに実制作可能なプランを届け、次回へ経験を返すことを実証する。

確認した現状: run.pyはResearch未完了時にnext_actionを返す。autonomous_runner.pyはworkerのCOMPLETEDからPLAN_READYへ遷移し、同箇所ではplan実体の検証をしない。旧Issue #88と実行証跡を尊重し、差分と統合を検証する。

### 実装要件

1. 外部Codex/Claude Code等がnext_actionを消化する標準経路を完成させる。組込daemonやproviderの必須化はしない。worker方式を提供する場合も同じ完了検査に合流させる。
2. Research完了→正規handoff→Production build/validate→plan実体検証→owner別knowledge commit/index→完了reportまでを継続する。worker自己申告だけでPLAN_READYにしない。
3. code revisionとknowledge revisionを分離して固定する。#189のpin/upstream不整合を再発させず、既存作業treeは変更せず隔離workspaceで検証する。
4. run-id・checkpoint・段階receiptで冪等再開し、有限retry、実行時間上限、lease/heartbeatを持つ。進捗を繰り返すだけのループも上限でnamed failureにする。
5. 実LLM接続済みエージェントで3利用モード×連続2runを実行し、plan実体・人間の介入箇所・出典・蓄積採用traceを記録する。fakeは回帰試験に限定しliveの代用にしない。

### 受入条件

- [ ] AAK-02-AC1: Masa継続利用・新規clone・forkの各モードで2つの異なるrunを実行し、各runから検証済みproduction-plan.mdと永続化receiptを得る。
- [ ] AAK-02-AC2: 2回目で1回目の許可済み知識がcontext/比較/採否判断に実際に使われたsource参照と判断を検証する。
- [ ] AAK-02-AC3: 成功JSONのみ、空plan、要約への差替え、改ざんhash、未採用知識の正本偽装を拒否する。
- [ ] AAK-02-AC4: Research後/plan後/一部knowledge保存後の中断から二重生成・二重commitなく再開する。
- [ ] AAK-02-AC5: 実行終了時にplan_status・knowledge_status・projection_status・停止理由を区別し、欠落を成功表示しない。
- [ ] AAK-02-AC6: 外部エージェントでの実行証拠が取れなければCODE_VERIFIED/INCOMPLETEに留め、統合Issueを完了扱いにしない。

## aak-03

対象: `masa-san-jp/agentic-art-orchestration`  
Issue件名: 全8repoの生成物蓄積・還流・検索の共通契約を実装する

理由: 生成物の保存を、次回に発見・検証・採用できる累積知識へ変える。全8repoを対象にし、子の知識本文を親へ集約しない。

確認した現状: manifest、export/import、retrieval、出典pinの基盤は既存。今回要求する全8ownerの知識保存receipt、更新失効、次回利用証拠の横断契約は追加設計対象。

### 実装要件

1. specのartifact-record/knowledge-write-receipt/reuse-traceおよびinstance-profile境界をversionedなclosed schemaとして定義する。domain payloadは各ownerが検証する。
2. publishではなくローカルowner書込を仲介するprepare/validate/commit/index/retrieveのdispatchを実装する。各段階はoperation IDで再実行可能とし、複数repo同時成功を偽らない。
3. registryへ全8ownerのread/write能力と帰属を登録し、Projectの公開projectionは出力専用のまま、履歴参照を別のread-only能力として追加できる形にする。
4. 知識増分によるcode pin失効を防ぎ、コード参照と利用知識snapshotを別々に固定する。read/commitが別repoでも親履歴へ本文を複製しない。
5. Orchestration自身にも実行失敗・復旧・検証済み運用知識をknowledgeとして保存する。これは命令ではなく改善候補であり、権限や実行規則を自動変更しない。

### 受入条件

- [ ] AAK-03-AC1: 8ownerを持つsynthetic providerでprepare→commit→index→retrieveを通し、receiptと参照が一致する。
- [ ] AAK-03-AC2: 同ID同revisionの異なる内容、owner不一致、未検証payload、権限外pathを拒否する。同一操作・同一内容の再送はALREADY_APPLIED/NO_CHANGEとして二重commitを作らない。
- [ ] AAK-03-AC3: 1ownerの失敗でも成功済みownerの記録を失わず、失敗ownerだけ再開して一貫したreportを生成する。
- [ ] AAK-03-AC4: 撤回/旧版/権利変更された記録を次回active検索から除外し、派生物の再検証候補を列挙する。
- [ ] AAK-03-AC5: code commitを変えずknowledge commitだけ進めても、過去run再現と新runのsnapshot採用を両立する。

## aak-04

対象: `masa-san-jp/agentic-art-orchestration`  
Issue件名: 本人継続利用・clone・forkの利用者別初期化と蓄積保持を実装する

理由: 共通知識を継承しても本人の自己モデルや自作履歴を誤継承せず、利用者ごとに育つ環境を確実に構築する。

確認した現状: 既存#148/#149/#150で出力profileとworkspace bootstrapを実装済み。#190の公式repo関係を保持し、利用者identity・knowledge branch・継承sourceの解決を拡張する。

### 実装要件

1. 既存output-destinationsを破壊せずinstance-profileへ接続する。instance-id、creator-id、mode、8ownerのcode/source/store、権限を解決しprofile fingerprintを保存する。
2. resumeは既存identityと全knowledge refsを維持。new-clone/forkは新identity・空の本人履歴で開始し、継承レコードはoriginを保持する。クローンしただけで誰のデータか推測しない。
3. クローン利用はローカルの知識用Git履歴だけでも完結できる。フォークは利用者のremoteを明示し、元remoteへの自動push・Issue・PR送信をしない。
4. 個人領域の初期設定は本人選択を一度記録し、以後自動解決する。未設定時にMasaやcwdから個人profileを借りず、public-seed-onlyかSETUP_REQUIREDを宣言する。
5. isolated worktreeと資格済みcommitを使い、既存dirty/diverged workspaceを修復せず回避する。共有codeの更新とデータmigrationを分け、履歴を失わないdry-runを提供する。

### 受入条件

- [ ] AAK-04-AC1: 3モードのfresh bootstrapと再実行でidentity・帰属・保存先の期待値が一致する。
- [ ] AAK-04-AC2: 利用者BがAの本人領域を自分として使う、forkで作者を書き換える、upstreamへ無指定writeする負例を拒否する。
- [ ] AAK-04-AC3: upstream code更新、knowledgeのみ更新、同じrun再開で本人履歴と既存IDが保持される。
- [ ] AAK-04-AC4: GitHub認証不要のローカルclone運用をfixtureで完了できる。
- [ ] AAK-04-AC5: public-seed-onlyは個人固有性を未充足と記録し、個人モードの完了試験と混同しない。

## aak-05

対象: `masa-san-jp/self-model-notes`  
Issue件名: 本人別の感性・制作選択を蓄積し、出典と不確実性を保って自己モデルへ反映する

理由: 制作を重ねるほど利用者本人の感性との接点を深める。AIが生成した案や無反応を本人の好みの証拠にして循環強化しない。

確認した現状: Source→Event→Claim→Pattern→Derivedと会話intake、外部profile rootは実装済み（#79/#81）。#82は実n=1移設の別human gate。本Issueは合成profileで新しいGit管理の派生知識storeを実装し、実n=1移設を実行しない。

### 実装要件

1. 既存の外部raw profileを保ち、本人用private knowledge repo/ローカルGit storeに検証済み派生recordを蓄積できる新契約を追加する。公開protocol treeに実person recordを混ぜない。
2. 制作時の本人の採択・棄却・修正・評価をsource/時点/context付きで受理し、agent inference、本人観測、未観測を区別する。
3. 単一の選択から恒常的traitを決めず、既存の代替説明・反証・confidence・同意を維持する。agentだけの選択は本人Eventに変換しない。
4. 修正・撤回・同意変更は既存IDと来歴を保持し派生model/exportを再計算する。選択profile以外を検索・exportしない。
5. 旧external-local限定規則と今回の派生知識Git storeの区別をIssue #1/AGENTS/schema/validatorへ限定的に反映する。raw規則、実データ移行#82は弱めない。

### 受入条件

- [ ] AAK-05-AC1: 合成利用者A/Bで選択記録→派生知識のGit commit→再起動→本人signal exportまで再現できる。
- [ ] AAK-05-AC2: 本人選択・AI推定・未観測が異なる状態のまま保存され、無反応とAI案から本人の嗜好を捏造しない。
- [ ] AAK-05-AC3: source修正・同意取消でactive exportと索引が更新され、履歴を追跡できる。
- [ ] AAK-05-AC4: fork継承したAの記録をBの本人自己モデルへ自動投入しない。
- [ ] AAK-05-AC5: raw原文・認証情報・実n=1の移設/公開を行わず、既存profile互換検証が通る。

## aak-06

対象: `masa-san-jp/art-history-notes`  
Issue件名: 制作研究の美術史知識を根拠付きで取り込み、次回探索へ還流する

理由: 制作ごとの調査から作品・技法・時代背景の知識が増え、次の制作の参照範囲を広げられるようにする。

確認した現状: entities/contexts、source付き関係、read-only外部agent harnessとexportは既存。Research成果からのcontrolled intakeと次回context利用の証拠を接続する。

### 実装要件

1. 研究由来の候補を既存entity/contextへ写像するowner intakeを追加し、出典、該当箇所、検証区分、時空間・関係を保持する。
2. 既存canonical IDと照合して重複を統合し、競合する根拠・解釈は併記する。新たな歴史的事実をLLM出力だけでverifiedにしない。
3. 制作固有の解釈はcreator/project/sourceを持つ派生層へ置き、共通美術史の事実・学説・本人の解釈を区別する。
4. 正規生成commandでgraph/context vectors/exportを更新し、次のResearchが新規recordを参照できる。fork/upstream差分でもorigin IDを維持する。
5. 既存task contract v2を使い、内蔵agent起動・daemon・自動PR配送を復活させない。

### 受入条件

- [ ] AAK-06-AC1: 同一候補の再取込が重複entityを作らず、異なる根拠の競合を保持する。
- [ ] AAK-06-AC2: 出典不在・未読原典の既読偽装・本人解釈の歴史的事実化を拒否または未確認で隔離する。
- [ ] AAK-06-AC3: 永続化と索引再生成後、次回export/retrievalが新recordをID付きで返す。
- [ ] AAK-06-AC4: 新知識の追加で既存context/関係・fork由来の作者帰属を破壊しない。
- [ ] AAK-06-AC5: canonical verifierと外部agent readinessが成功する。

## aak-07

対象: `masa-san-jp/marketing-trends-notes`  
Issue件名: 制作研究から社会・受容の変化を蓄積し、鮮度を再検証して再利用する

理由: 制作と時代の接点を更新し続け、過去の観測を現在の事実として誤用しないため。

確認した現状: entities、freshness、vendor/primary区分とexport、agent-task/v1が実装済み。Researchからの追加候補、改訂と次回利用を一貫した経路に接続する。

### 実装要件

1. 研究成果からtrend/practice/context候補を受理し、出典、retrieved、certainty、as_of、地域、チャネル、反証を既存schemaに写像する。
2. 重複はsource identityで検出し、継続観測と修正を履歴として蓄積する。vendor単独や未読原典をverifiedへ上げない。
3. 鮮度は既存stage/freshness正本から計算し、再検証候補を自律taskとして返す。予算内で原典を確認できなければstale/unknownのまま検索結果へ理由を返す。
4. 更新後のsignalを次回Researchへ接続し、利用時の対象地域・観測条件・有効時点を保持する。人気を唯一の芸術評価に変換しない。
5. 既存のschema/語彙は可能な限り再利用し、本Issueに必要なowner/revision境界の追加だけを明示移行として実装する。Actionsの再有効化を必須にしない。

### 受入条件

- [ ] AAK-07-AC1: 同一観測の二重取込を防ぎ、異時点の観測は元のas_ofを保って履歴化する。
- [ ] AAK-07-AC2: 固定時計でfresh→stale→再検証済みを再現し、未確認のままfreshにしない。
- [ ] AAK-07-AC3: 誤地域・誤チャネル適用とvendor-onlyのverified化を拒否する。
- [ ] AAK-07-AC4: 2回目のResearch用exportが新しい観測とその日付を返し、旧版を現在値扱いしない。
- [ ] AAK-07-AC5: issue contract検証とmake agent-verifyが成功する。

## aak-08

対象: `masa-san-jp/agentic-art-research`  
Issue件名: 調査・仮説・採否・未解決の問いを永続蓄積し次の研究へ再投入する

理由: 棄却案や未解決の問いも、別の条件で再び表現の契機となる。調査成果が実行領域に残るだけの状態を解消する。

確認した現状: Researchは実projectをGit外rootへ置く設計。#83/#85で過去機構照合は実装済み。本Issueはその検査を新設せず、蓄積owner・索引・再投入を補完する。

### 実装要件

1. 一時attempt/runtimeは外部に維持し、採用可能な調査knowledgeをownerのknowledge/または利用者のprivate counterpartへGit管理で保存する。実project全体の無差別copyはしない。
2. 証拠・観察・主張・仮説・採択/棄却・矛盾・問い・要件への対応を安定IDで保持する。棄却は理由code、当時の条件、再検討可能条件を記録する。
3. next_action/context_packが関連する既存知識を先に検索し、採用/棄却/要再検証と不足調査を返す。未採用案が再浮上した理由をreuse-traceに残す。
4. 自己モデル/美術史/社会動向への知識候補をowner契約へexportするが、Researchが他ownerの事実認定を代行しない。
5. project-output-boundaryとruntime guardを更新し、検証済みknowledge保存と一時project隔離を両立する。撤回・改訂時の依存再検証と履歴を残す。

### 受入条件

- [ ] AAK-08-AC1: 完了projectからknowledgeを生成し、Git再読込後もsource→判断→要件が逆引きできる。
- [ ] AAK-08-AC2: 別projectで過去knowledgeがcontextへ入り、追加調査の必要範囲と採否理由が記録される。
- [ ] AAK-08-AC3: 予算不一致で棄却した仮説が条件変更時に候補として再取得され、虚偽として棄却した仮説は事実に昇格しない。
- [ ] AAK-08-AC4: 再実行・source revision・部分保存失敗でも重複や履歴喪失がない。
- [ ] AAK-08-AC5: raw/会話/秘密/権限外profileの混入を拒否し、既存#83/#85の回帰が通る。

## aak-09

対象: `masa-san-jp/agentic-art-research`  
Issue件名: 蓄積を再利用しながら固有性・機構の接地・探索の幅を検証する

理由: 蓄積が同じ仕掛けの反復やAIによる一般論への収束を強めず、固有の表現を育てるようにする。

確認した現状: 機構の命題/referenceへの接地とself repetition検査は#83/#85に存在。今回の知識索引・利用者分離・探索政策へ接続して統合検証する。

### 実装要件

1. 既存の半決定論的candidate/selectionと機構接地を保持し、参照した入力・rule・seed・knowledge revision・機構・比較対象を追跡する。
2. 本人の過去作、継承した他者作品、外部先行作品を区別して比較する。タイトルの言換えだけで機構の重複判定を回避できないようにする。
3. 既存候補の再利用、未解決の問いの再探索、新しい参照の探索を候補の性質として明示する。探索枠や閾値はconfigで固定し、既存基準を恣意的に弱めない。
4. 既存知識がない場合はEMPTY_HISTORY、権限/索引不良で読めない場合はUNAVAILABLEを区別し、未実施照合をLOW/PASSとしない。
5. 一次出典とAI派生物の出典系列をたどり、同じ生成文の再引用を独立した裏付けとして数えない。

### 受入条件

- [ ] AAK-09-AC1: 同一snapshot/rule/seedでは構造化候補と採否が再現し、別seedの差は許された範囲だけに限られる。
- [ ] AAK-09-AC2: 本人signal差替え、タイトル言換えの同機構、根拠なし比喩、AI文の自己引用という負例を検出する。
- [ ] AAK-09-AC3: 明示的な継続制作は差分と理由付きで受理でき、機械的な全類似作禁止にしない。
- [ ] AAK-09-AC4: EMPTY_HISTORYとUNAVAILABLEを別状態として返す。
- [ ] AAK-09-AC5: reuse有無の比較で根拠充足・未解決・構造重複の指標を報告し、芸術的優劣の自動保証を主張しない。

## aak-10

対象: `masa-san-jp/agentic-art-production`  
Issue件名: 研究要件から実制作可能な統合プランを生成し内容の完全性を検証する

理由: 人間が受け取って具象化できる制作プランを最終成果とし、体裁だけの成功・要約・テンプレートで完了させない。

確認した現状: build_plan、production-plan.md、visual board/mockupは既存。#60がcanonical attestationを担当。本Issueはその再実装ではなく、研究由来の内容・実現方法・蓄積利用の意味的充足を担当する。

### 実装要件

1. Production-owned schemaから統合planを生成し、コンセプト/メッセージ/調査要約/完成像/材料/寸法等の必要仕様/作業順/資源/日程/費用前提/試験/参考資料を要件へ接続する。
2. 媒体に応じて必要項目を選び、適用しない項目は理由を記録する。未確定値は確認方法・担当actor・成立条件を持つgapにし、必須の制作手順不足はPLAN_READYを阻害する。
3. 既存ビジュアルボードとCONCEPTUAL mockupの実ファイル・リンク・由来を検証する。fixtureと実素材、概念図と実証を区別する。
4. #60のattestationと正規renderer検証を再利用し、外部ownerに章名・schemaを複製しない。PLAN_READYは制作・購入・展示の実施や承認を意味しない。
5. knowledge参照由来の材料・工程・見積にはsource条件を付け、当該制作環境との不適合を検出する。

### 受入条件

- [ ] AAK-10-AC1: 構造の異なる2種類以上のhandoffから、媒体に適合した手順と要件coverageを持つplanが生成される。
- [ ] AAK-10-AC2: 空の必須仕様、要件と工程の矛盾、根拠なし実績、壊れたvisual/referenceリンクを検出する。
- [ ] AAK-10-AC3: #60のattestationでMarkdown実体とcanonical aggregateの一致を検証する。
- [ ] AAK-10-AC4: 実証前の事項は未実証のまま表示し、試験・購入・設営を完了済みにしない。
- [ ] AAK-10-AC5: 人間が最初に行う制作作業と必要な物・条件をplanだけから特定できる受入rubricを満たす。

## aak-11

対象: `masa-san-jp/agentic-art-production`  
Issue件名: 制作・試作・失敗の知識を条件付きで蓄積し次の計画に反映する

理由: 実現条件の知識を累積し、想定と実績の差や失敗を次の制作に生かす。

確認した現状: append-only observation/result、revision/replayは既存（#34/#36/#38/#39）。今回はproject間で再利用できるknowledgeと設備・資源条件の照合を追加する。

### 実装要件

1. 素材・技法・手順・設備・作業条件・予定/実績・失敗原因・修正のknowledgeを安定ID/source付きで保存する。runtime/eventのownerを移さず参照する。
2. planned/simulated/prototyped/observedを区別し、実証なしに成功技法へ昇格しない。失敗原因のAI推定も観測事実と区別する。
3. build_planが候補knowledgeの設備・技能・サイズ・安全条件・通貨/時点を照合し、採用/不適合/要再検証を記録する。
4. 同じproduction projectの改訂と別projectへの知識再利用を区別し、result還流で重複を防ぐ。
5. protocol-only規則を検証済みknowledge蓄積に限って更新し、大容量作品やraw/契約書/機微情報は外部参照のまま保持する。

### 受入条件

- [ ] AAK-11-AC1: 試作結果の取込→Git再読込→別planの工程候補への反映をsource付きで再現する。
- [ ] AAK-11-AC2: 計画上の見積を実績扱いせず、異なる設備/サイズ条件の成功例を無条件転用しない。
- [ ] AAK-11-AC3: 同一resultの再取込は無変更、訂正版は履歴と影響先を保持する。
- [ ] AAK-11-AC4: 観察0件では実績を生成せず、知識還流待ちがplan完了を虚偽に阻害しない。
- [ ] AAK-11-AC5: 撤回sourceに依存する再利用候補を再検証へ戻せる。

## aak-12

対象: `masa-san-jp/viewer-response-notes`  
Issue件名: 鑑賞者反応を作品・意図・展示条件別に蓄積し次の研究へ還流する

理由: 作品がどう届いたかを知識にし、意図しなかった受容も次の問いへ返す。人気だけに生成を最適化しない。

確認した現状: aggregate-only record/assessment/export、追記・Wilson区間の境界が既存。作品系譜と収集条件の参照、および次回Researchへの接続を拡張する。

### 実装要件

1. recordをcreator/project/work/revision、意図した体験、収集法/期間/展示条件に関連付ける。個人識別・raw自由回答を保持しない。
2. measured集計、external根拠、未測定を既存契約のまま区別する。意図外の受容は定義済みカテゴリの集計または非個人の外部根拠として扱う。
3. 同じ計測の重複、重なったsample集合の二重合算を検知する。異なる観客・展示条件は自動合算せず適用範囲を保持する。
4. 追記型訂正で旧recordを失効させ、元記録を消さずassessment/exportを再生成する。統計手法・閾値は本Issueで変更しない。
5. 次回Researchが承認範囲内の派生signalを読み、支持/反証/不明として判断に利用できる。反応ゼロは失敗/低評価へ変換しない。

### 受入条件

- [ ] AAK-12-AC1: 同作品の異なる展示条件を分離し、集計→assessment→export→再読込が一致する。
- [ ] AAK-12-AC2: 同一sourceの二重計上、重複sample、未測定のサンプル捏造、本人取り違えを拒否する。
- [ ] AAK-12-AC3: 訂正後のactive assessmentが再計算され旧recordと来歴を追える。
- [ ] AAK-12-AC4: 個人名・自由回答・raw・秘密をschema/validatorが拒否する。
- [ ] AAK-12-AC5: 反応が存在しない新規利用者でもUNKNOWNを返し、制作計画の開始自体を妨げない。

## aak-13

対象: `masa-san-jp/agentic-art-project`  
Issue件名: 公開プランと作品の系譜を帰属付きで蓄積し、検証済み履歴を再参照可能にする

理由: カタログを制作の系譜として引き継ぎ、過去の表現・未制作の構想・改訂を比較しながら各利用者の制作を育てる。

確認した現状: plans/works/indexとexport-only公開カタログが既存。#6がcanonical plan受信・旧要約移行を担当。本Issueは作者・instance・系譜とread-only再参照を追加する。

### 実装要件

1. 既存P/W IDを保持し、origin-instance、creator、stable source identity、revision、derived_from/source_plansをメタデータと索引で追跡する。fork後の新作には新originを割り当てる。
2. clone/forkで継承された作品を新利用者の自作にしない。ID衝突はorigin＋local IDで解決し、既存IDを再利用しない。
3. #6の正規plan/attestation検査に合格した公開recordのみ、別能力catalog-reference/v1からread-only exportできるようにする。公開projection自体は出力専用のまま保つ。
4. Researchの比較用にテーマ/機構等の参照可能情報をsource locator付きで提供し、計画/実制作/展示済みを区別する。Projectへ内部研究台帳やrawを集約しない。
5. root README・catalog・関係定義と新AGENTSを同期し、利用者設定から任意の出力repoを解決する。公式owner名のruntimeハードコードを避ける。

### 受入条件

- [ ] AAK-13-AC1: 既存recordのP/W IDと作者を保持して新schemaへ移行でき、不明な作者/正本はunknown/blockerのままにする。
- [ ] AAK-13-AC2: fork利用者の新作と継承作品が異なるoriginとして索引化される。
- [ ] AAK-13-AC3: read-only exportが正規recordだけを返し、hash不一致/旧要約/内部asset/未確認権利を拒否する。
- [ ] AAK-13-AC4: 再exportで元catalogを変更せず、Research用参照から元planとrevisionへ到達できる。
- [ ] AAK-13-AC5: 計画済みを制作/展示済みとしない。catalog syncとreceiver validatorが通る。

## change-log

- 2026-09-05 / v1: 利用者の議論を統合し、自律制作・全8ownerの蓄積と再利用・本人/clone/fork・完了証拠を定義。既存Issueの完全性検証と領域schemaの所有権を再利用する。実装状態は未着手。
