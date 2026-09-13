# 未解消Issueの自律実装完了計画

作成日: 2026-09-14  
対象: `masa-san-jp` 配下の Agentic Art 8 repository  
状態: OI-03 完了 / OI-04 READY / ExecPlan SSOT

この文書は、2026-09-14時点の未解消Issueを、会話履歴に依存しないエージェントが依存順に実装し、owner品質ゲート、親統合、PR、merge後確認、Issue closeまで完了するための実行計画である。domain要件は各Issue本文と各owner repositoryが正本であり、この文書は要件本文やschemaを複製せず、順序、境界、検証、再開方法を定める。

## Purpose / Big Picture

現在の親queueは179件すべてDONEで、READY/BACKLOGが0件である。一方、通常runで着想を制作可能な計画へ育て、判断可能なデジタル試作を生成し、canonical plan、attestation、Project-local deliveryまで完走する機能は未実装である。open Issueが存在するだけで実装queueへ接続されていないため、エージェントは次taskを選べない。

この計画の完了後、テーマ未指定の通常入口は、根拠付き入力から複数の着想候補を生成・比較・批評し、制作条件を解決した計画を作り、決定論的SVG試作を生成する。その試作はProduction本文とattestationに含まれ、Projectの同一revisionへ投影される。正常runは工程ごとの質問や追加承認なしに `delivery_completion.status=COMPLETED` へ到達する。物理制作、購入、展示、公開範囲変更、実n=1 profile移設はこの自動laneに含めない。

## Progress

- [x] 2026-09-14時点の親queue/stateとopen Issueを観測した。
- [x] 実装対象、意図的open、human-blockedを分離した。
- [x] Issue間の重複箇所を確認し、ResearchとProductionの実装順を決めた。
- [x] `OI-00`でIssue intakeとSSOT修復を完了し、実行queueへ登録する。
- [x] `OI-02`で#242/#243を既存AAK SSOT、実測call graph、owner境界へ統合する。
- [x] `OI-03`でResearch #109の試作契約をProduction境界まで検証する。
- [x] `OI-05`でProduction #76の決定論的SVG試作を実装・merge・closeする。
- [ ] `OI-04`、`OI-06`から`OI-12`を依存順に実装・検証・統合する。
- [ ] merge後のqualified mainで最終通常runを実施し、対象Issueをcloseする。

## Surprises & Discoveries

- 初回のintakeでは、親 #242 の見出し表記、Production #76 の番号付き受入条件、Project #31 のexport-only repository認識が機械判定に適合しなかった。Issue本文の意味を変えない最小修復と、`repository-relationships.yaml` を参照するintake変更を OI-00 で完了した。
- 修復後の固定時刻intakeは、#242、#243、Production #76、Production #77、Project #31、Self Model #82をSSOT要件充足として観測した。#109と#392はこのセッションで既にowner PRがmerge済みで、open Issue観測の対象外になっている。
- Project #31は公開catalogの正本であり、入力manifestへ追加しない。intakeとqueueのtarget repository検証だけがexport-only関係レジストリを参照する。
- #242のINSP-02/03と#243系列は、ResearchのhandoffとProductionのrenderer・`build_plan.py`を重複して変更する。試作契約を先に確立し、その上へ着想保持と制作可能性を実装する方が差分と競合が小さい。
- Production #10は要件SSOTとしてopen維持が明記されている。実装完了時もcloseしない。
- Self Model #82は実データを扱う前に `destination_root`、`consent_scope`、`retention_decision` が必要である。3項目がない限り、自律実装の完了件数に含めない。
- Art History #392は制作runtimeとは独立して実装できるが、入力ownerのqualified pinを変える。最終統合前に完了させ、新しいpinを使う。
- OI-03の横断fixtureは、Researchの正例をProductionへ受け渡すと `PLANNING` かつ `readiness.startable=true` になることを確認した。寸法・素材・数量がProduction planに無い状態でのrenderer停止は、`PROTOTYPE_RENDER_INPUTS` による入力不足の明示であり、placeholder出力を作らない。Production #76はこの境界を実装済みなので、OI-05をOI-03直後の独立taskとして完了記録した。

## Decision Log

- 2026-09-14: 実装対象を、制作runtimeの主系列7 Issue（親#242/#243、Research #109、Production #76/#77、Project #31、Art History #392）とする。
- 2026-09-14: Production #10は永続要件SSOT、Self Model #82はhuman-blockedとして別管理し、未実装Issueと同じclose判定を適用しない。
- 2026-09-14: Researchは #109 の試作plan契約を先に実装し、そのcandidate上で #242 INSP-02を実装する。
- 2026-09-14: Productionは #76をResearch #109の契約確認後に独立実装し、#77、#242 INSP-03をその上へ積む。rendererは一つだけ所有する。
- 2026-09-14: ownerごとにcommit/PRを分ける。複数Issueを一つの巨大commitで閉じない。
- 2026-09-14: 子PRのmerge前でも、exact candidate commitを隔離workspaceへ集めて親統合検証を進める。merge待ちを実装停止理由にしない。
- 2026-09-14: OI-00の修復後intakeは6件のqualified unqueued Issueを返し、#242、#243、#76、#77、#31を実装DAGへ、#82をBLOCKEDのhuman laneへ登録する。#10は既存の永続要件としてqueue外へ重複登録しない。

## Outcomes & Retrospective

OI-00はintake・SSOT修復・queue登録を完了し、OI-02は#242/#243のSSOT統合、call graph記録、AAK projection hash同期、親638-test gateを完了した。OI-03はResearch #109のowner candidateをProduction qualified candidateへ通し、OI-05はProduction #76をmergeしてIssueをcloseした。残りのmilestoneでは達成した受入条件、採用commit、失敗と回復、残存リスクを追記する。全完了時には、通常runのProject-local delivery ID、全owner merge commit、親merge commit、closeしたIssue、意図的にopen維持したIssueを記録する。

## Context and Orientation

親repositoryは制御面であり、正本は次のように分かれる。

| 領域 | 正本 | この計画での役割 |
|---|---|---|
| 着想生成・比較・handoff | `agentic-art-research` | #109、#242 INSP-02 |
| 制作可能性・試作・plan・attestation | `agentic-art-production` | #76、#77、#242 INSP-03 |
| 通常入口・再開・delivery completion | `agentic-art-orchestration` | #242 INSP-01/05/06、#243 PRT-04/06 |
| 公開record受理・lineage・catalog | `agentic-art-project` | #31、#242 INSP-04 |
| 美術史入力 | `art-history-notes` | #392 |
| 個人profile | `self-model-notes` | #82。human input後だけ実行 |
| 永続要件 | Production #10 | open維持。回帰確認だけ |

親の実行SSOTは `execution/task-queue.yaml`、`execution/state.yaml`、`execution/handoff.md` である。owner内部schema、fixture、tests、native taskはowner repoが保持する。親には子schemaやIssue本文をコピーせず、Issue URL、source/candidate/merge commit、contract version、acceptance evidence、hash、opaque locatorだけを記録する。

対象Issue:

- Orchestration #242: 着想生成、比較、批評、制作可能性、内容保持、統合受入。
- Orchestration #243: デジタル試作の必須生成、完了判定、Project投影。
- Research #109: `effect_type`必須化とデジタル試作plan。
- Production #76: `04_prototype`への実試作SVG生成。
- Production #77: 試作をplan、attestation、actionabilityへ接続。
- Project #31: 試作asset付きrecordの受理とmedia契約整合。
- Art History #392: Krueger / Videoplaceと機械生成系譜の欠落解消。

## Dependency DAG

```text
OI-00 intake・SSOT修復・queue登録
  ├─ OI-01 Art History #392
  └─ OI-02 親 #242/#243 のSSOT統合とcall graph
       ├─ OI-03 Research #109
       │    ├─ OI-04 Research INSP-02
       │    └─ OI-05 Production #76
       │         └─ OI-06 Production #77
       │              ├─ OI-07 Production INSP-03
       │              ├─ OI-08 Project #31
       │              │    └─ OI-09 Project INSP-04
       │              └─ OI-10 Parent PRT-04
       └───────────────────────────┐
OI-01 ─────────────────────────────┼─ OI-11 Parent INSP-05 / owner qualification
OI-07 + OI-09 + OI-10 + OI-11 ────┴─ OI-12 qualified integration、merge、close
```

同一owner内は直列に実装する。`OI-01`は別repoのため`OI-02`以降と並行可能だが、`OI-11`で採用commitを固定する前に完了させる。

## Plan of Work

### OI-00 — intake、#242 SSOT修復、queue登録

8repoを固定時刻でread-only intakeし、各Issueの4要件を再評価する。機械結果を優先し、以下は現在の本文観測から予想される修復対象として扱う。

- #242には `## 検証コマンド` 節を追加する。最低限、Research/Production/Projectのowner gates、親focused/full suite、通常入口、Project-local receipt、`git diff --check`を含める。
- Production #76の番号付き受入条件を、内容を変えずcheckboxへ変換する。
- Art History #392には対象repository、観測可能な受入条件、ownerの正準検証コマンド、human gateの有無を明記する。movement名を一次資料で確定できない場合の合格条件も定義する。

Issue本文の意味、scope、権限を広げず、SSOT最低要件だけを補完する。修復後にもう一度intakeし、#242/#243/#76/#77/#31/#82がqualifiedであることを確認する。#109と#392は既にmerge済みのため、open Issueとして再登録しない。親queueへこの文書の`OI-*` taskを依存関係付きで登録するcommitを一つ作る。登録commitでは実装しない。Production #10は `ALREADY_QUEUED`または永続SSOT、Self Model #82は`BLOCKED`のhuman laneとして扱う。Issue本文を変更する権限が実行taskに含まれない場合は、本文patchを提示して停止し、計画書やIssueコメントでSSOT欠落を代用しない。

### OI-01 — Art History #392

ownerのAGENTS、schema v2、source policyを読み、Issueの下書きをそのまま真実とせず一次・機関資料で再確認する。Myron KruegerとVideoplaceを追加し、movement化は一次資料で当事者名称を確認できた場合だけ行う。確認できなければ人物・作品entryを完了し、movement判断を根拠付きで `unresolved` として残す。coverage更新はownerの生成経路を特定し、生成物を手編集しない。

owner gatesを通してcommit、通常push、draft PRを作成し、candidate SHAを親へ記録する。#392のACが人物・作品追加だけで満たされずmovement判断まで要求する場合、判断記録もPRへ含める。

### OI-02 — 親 #242/#243 の既存AAK SSOT統合

#242 INSP-01と#243の親設計を、既存のAAK仕様・実装計画へ統合する。通常run、Research handoff、Production plan/prototype/attestation、Project receiver、delivery completionのcall graphを実測し、各変更点をIssueのS/ACへ対応付ける。既存AAK-02/08/09/10/11/13との互換性、legacy context、P0001–P0008の不変条件を明記する。

機械投影とqueueは2つのMarkdownから生成し、第三の仕様にしない。Issue参照は採用commit固定URLへ更新する。ここではruntime実装を行わない。

### OI-03 — Research #109 / PRT-01

`prototype-plan`の全taskで`effect_type`を必須にし、欠落を `PROTOTYPE_TASK_EFFECT_TYPE_REQUIRED` で拒否する。採択handoffには、`digital-prototype-renderer`、非物理effect、production planの寸法・素材・数量参照、SVG evidenceを備えたデジタル試作planを最低1件要求する。fixtureを一律`READ_ONLY`へ変換せず、実際のeffectへ分類する。

Research単体gateに加え、Productionのqualified candidateで正例handoffがBLOCKEDにならないことを境界テストする。既存immutable bundleは書き換えない。

### OI-04 — Research #242 / INSP-02

OI-03のcandidateを基線に、入力context、候補生成、意味による比較、制作方法の見通し、独立した批評、修正・再採択、creative-direction、handoffを実装する。外部事実と創作上の飛躍を区別し、タイトル・寸法だけの差を別案として水増ししない。候補の問い、体験、素材・形式、入力との関係、変更可能部分をProductionへ保持する。

固定fixtureはvalidatorと失敗注入に使い、実agent生成の代替証拠にはしない。有限retryとno-progress停止を維持する。

### OI-05 — Production #76 / PRT-02

`tools/lib/prototype_render.py`をowner唯一の決定論的rendererとして追加する。production planの寸法・単位・素材・数量・主要構成から、判断可能なSVGを `04_prototype/outputs/<plan-id>/`へ出力する。run ID、plan ID/revision、実使用寸法、縮尺または縮尺外を記録し、汎用文字箱だけの出力を拒否する。

出力はローカル作業領域に置き、作品asset本体、PRIVATE_RAW、credential、絶対local pathをGitへ入れない。既存projectの一つまたは隔離fixtureで実行し、`04_prototype`が非空になることを観測する。

### OI-06 — Production #77 / PRT-03

OI-05のrendererを再利用して公開previewを `03_plan/media/prototype/`へ同一bytesで生成する。`production-plan.md`にデジタル試作（simulated）として埋め込み、寸法・素材・run ID・revision・実物ではない旨を記載する。prototype run、public attestation、`plan_actionability`を同一hashへ接続する。

preview欠落、hash改変、本文リンク欠落、`prototype_status != READY`は `PROTOTYPE_OUTPUT_MISSING` とし、planとdeliveryを未完了にする。digital planを持たないlegacy handoffの本文/hashは変えない。

### OI-07 — Production #242 / INSP-03

OI-06のcandidateを基線に、Researchで採択した着想とProduction planの意味対応を検査する。完成物から工程を逆算し、材料・道具・データ・設備・技能・費用・時間・場所を工程へ対応付ける。必須依存が成立しない場合は同runで資料、材料、方法、規模を選び直し、着想が変わる場合だけResearchへ改訂を返す。

PR #74由来の準備開始判定と制作可能性を分離する。READ_ONLY確認taskを追加しただけ、coverageを100%にしただけ、未解決条件をユーザー承認へ送っただけではPASSしない負例を追加する。

### OI-08 — Project #31 / PRT-05

`media/prototype/*.svg`を含むrecordについて、receiver、local delivery、validator、catalog syncを一貫させる。`metadata.yaml.assets`の存在、media配下、許可拡張子、ignore非該当、attestation hashを検査する。`public-project.yaml`と`.gitignore`の拡張子矛盾を解消し、読者向け文書にsimulatedと非公開原本の境界を記す。

既存P0001–P0008のbytes、hash、lineageは変更しない。

### OI-09 — Project #242 / INSP-04

OI-08のreceiver上で、Project紹介がタイトルとリンクだけにならず、作品の具体像、素材・形式、発想の由来、制作への入口を示すようにする。紹介、plan本文、asset、metadata、lineageを同一revisionへ束ねる。Production正本の`plan.md`はbyte-for-byte投影を維持する。

### OI-10 — Parent #243 / PRT-04

親のnormal/cycle/batch/supervisor入口へprototype stageを追加し、Productionのqualified `prototype_status`とattestation assetをdelivery completionへ接続する。試作欠落/hash不一致は `missing: PROTOTYPE_OUTPUT` で `INCOMPLETE`、修復可能な失敗は同run ID、project root、validation command、resume commandを返す。

offline fixture、purpose E2E、production exchangeも同じstageと判定を使う。fixture SVGを実runの証拠へ昇格させない。

### OI-11 — Parent #242 / INSP-05とowner qualification

通常入口とbatch/recoveryを候補比較、批評、内容修復、知識保存へ接続する。Self Model、Art History、Marketing、Viewerの4入力ownerは現行契約で足りるか実測し、変更が必要なownerだけ別task/commit/PRに分割する。Art HistoryはOI-01のcandidateを採用する。

各owner candidateを隔離したGit外workspaceへ集め、source commit、contract version、acceptance evidence、native gatesを確認する。CLOSED状態やPR存在だけでdependency PASSにしない。

### OI-12 — qualified integration、merge、Issue close

Research、Production、Project、Art History、必要な入力ownerのcandidateをexact SHAで統合し、全child gateと親full suiteを実行する。通常入口をテーマ・slug・titleなしで開始し、外部エージェントが候補生成からProject-local deliveryまで進む実runを最低1件行う。

最終runでは、試作SVG、本文リンク、attestation hash、Project record、receiver receipt、知識保存、creator/origin、`delivery_completion.status=COMPLETED`を一つのprovenance chainとして検証する。providerやnetworkが使えない場合も試作生成は完了できる必要がある。実agentによる着想生成が必要な受入は、固定fixtureだけでPASSにしない。

全受入後、依存順に子PRをmergeし、各owner mainを再取得してcandidate一致またはmerge commit包含を確認する。次に親pinと証拠を更新した親PRをmergeし、remote mainで必須checkを再実行する。その後、#109、#76、#77、#31、#392、#242、#243を、各IssueのACとmerge evidenceが揃ったものだけcloseする。Production #10はopen維持する。Self Model #82は3入力がなくても本系列の失敗にはしない。

### OI-13 — Self Model #82 human lane

#82は実個人profileの移設を要求するため、主系列の自律実装から分離した `BLOCKED` taskとしてqueueに残す。`destination_root`、`consent_scope`、`retention_decision`がIssueに明示され、人間が移設範囲を承認するまでは、実データの読取、copy、move、delete、dry-runを開始しない。自動実装の受入数、Issue close数、qualified completionには含めない。

## Concrete Steps

最初のセッションでは次を実行する。固定時刻は実行開始時のISO-8601値に置換する。

```bash
.venv/bin/python tools/project_status.py --format json
.venv/bin/python tools/issue_intake.py --live \
  --repository masa-san-jp/agentic-art-orchestration \
  --repository masa-san-jp/self-model-notes \
  --repository masa-san-jp/art-history-notes \
  --repository masa-san-jp/marketing-trends-notes \
  --repository masa-san-jp/viewer-response-notes \
  --repository masa-san-jp/agentic-art-research \
  --repository masa-san-jp/agentic-art-production \
  --repository masa-san-jp/agentic-art-project \
  --observed-at <fixed-ISO-8601-time> --check
```

各taskは次の共通手順を守る。

1. 親SSOT、対象Issue、owner AGENTS、近接schema/testsを読む。
2. remote head、candidate、branch、dirty状態、active leaseをread-only確認する。
3. 親stateへtask、repo、開始点、変更予定を記録し、owner native taskをclaimする。
4. owner repoの隔離branch/worktreeで最小差分を実装する。
5. focused tests、owner full gates、diff、機微情報scanを実行する。
6. owner commitを一つ作り、通常pushし、remote SHAをread-backする。draft PRを作る。
7. 親にはpayloadではなくcandidate SHA、contract version、AC evidence、gate resultだけを記録する。
8. 親実行SSOTをcommit・通常pushしてからleaseを解放する。
9. queueから依存完了済み最小IDを次taskとして選ぶ。

## Validation and Acceptance

全task共通の親gate:

```bash
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/project_status.py --check-readme
git diff --check
```

Research gate:

```bash
python3 -m compileall -q tools tests
python3 tools/validate.py --check
python3 -m unittest discover -s tests -v
python3 tools/build_graph.py --check
git diff --check
```

Production gate:

```bash
.venv/bin/python tools/validate.py --check --format json
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tools/run_evaluation.py --format json
git diff --check
```

Project gate:

```bash
python3 tools/catalog_sync.py --check
python3 tools/validate.py --check
python3 -m unittest discover -s tests -v
git diff --check
```

Art History gate:

```bash
python3 tools/build_graph.py --check
python3 tools/build_context_vectors.py --check
python3 -m unittest discover -s tests -p "test*.py"
git diff --check
```

最終統合の観測可能な合格条件は次の通り。

- #242の着想候補、比較、批評、採択、制作方法、完成経路、本文、知識保存が同一runで追跡できる。
- #243のSVGがProduction原本と公開previewへ生成され、同一入力2回のsha256が一致する。
- Production本文、attestation、actionability、Project recordが同じasset hashとrevisionを参照する。
- SVG欠落、改変、prototype未完了、制作必須依存未解決の各負例がdelivery `COMPLETED`を拒否する。
- 正常runが追加の工程質問なしにProject-local `COMPLETED`へ到達する。
- 既存P0001–P0008のbytes/hash/lineageが変わらない。
- 全変更ownerのnative quality gatesと親full suiteがqualified commitでPASSする。
- PRIVATE_RAW、RESTRICTED、credential、direct identifier、絶対local path、会話全文をcommit/evidenceへ保存しない。

## Idempotence and Recovery

- intakeとqueue登録はIssue URLをkeyに冪等化し、既登録taskを複製しない。
- 各ownerは開始commitとremote headを記録し、dirty/divergedな既存checkoutをresetしない。必要なら新しいGit外workspaceを作る。
- rendererは同一canonical inputから同一bytesを生成し、partial outputは完成証拠にしない。一時出力を検証後にowner-defined final pathへ置く。
- child gate失敗時は成功済みowner candidateを保持し、失敗ownerだけを修復する。全系列を作り直さない。
- merge競合時は最新mainを通常merge/rebaseした新candidateで全owner gatesを再実行し、古いcandidate証拠を流用しない。
- 通常run停止時はrun ID、destination resolution、project root、last completed stage、failure code、validation command、exact resume commandをstateへ保存する。
- public reviewや権利reviewが不足する場合はprepared targetを保持してHUMAN待ちにし、承認を生成しない。正常なデジタル試作生成そのものには新しいreview gateを設けない。
- Issue closeはmerge後のmainと受入証拠をread-backしてから行う。close失敗はコード完成を巻き戻さず、外部操作未完了として再試行する。

## Interfaces and Dependencies

主要境界は、Research ownerのproduction handoff、Production ownerのcanonical plan/public attestation/prototype package、親のdelivery contract/completion、Project ownerのlocal receiver/lineageである。contract version変更はowner規則に従い、consumer snapshotと互換テストを同じdependency chainで更新する。

外部依存として必須なのはGitと、PR/Issue操作時のGitHub認証だけである。SVG生成とoffline統合検証はLLM、Cloudflare、外部provider、GitHub Actions、課金を要求しない。実agentによる着想生成受入は利用可能な外部agent laneを使うが、そのproviderをrepositoryへ内蔵しない。

merge、release、remote公開、既存8件の再投影、物理制作、購入、展示、Self Model #82の実移設は既存human gateに従う。承認済みscopeがある場合でも、対象PR、checks、merge順、release targetをread-onlyで再確認してから実行する。

## Completion Report

最終報告には次を必ず含める。

- 完了した`OI-*` Task IDと対象Issue。
- repoごとのcandidate commit、PR、merge commit、remote main確認結果。
- Issueごとの達成AC数と証拠locator。
- 親検証、子quality gate、通常runのdelivery completion結果。
- prototype assetのopaque locator、sha256、revision、simulated表示。
- 機微情報scan、create-only外部artifact、explicit/inferred feedbackの区別。
- closeしたIssue、意図的にopen維持したProduction #10、Self Model #82の状態。
- 未解決事項と、存在する場合は次taskの最初の一操作。

## Self Model #82 conditional lane

#82は本計画の自律実装主系列と並行して状態だけを監視する。`destination_root`、`consent_scope`、`retention_decision`の3項目がIssueへ明示されるまで、実データの読取、copy、move、delete、dry-runを行わない。3項目が揃った後は#82本文の手順と検証を独立したhigh-risk taskとして登録し、metadata-only plan、create-only copy、hash照合、通常Git差分、privacy scan、明示merge gateの順で実施する。履歴改変、force push、visibility変更、Drive uploadはこのlaneに含めない。
