# Agentic Art Orchestration リポジトリ完成実行計画

作成日: 2026-08-11  
対象: masa-san-jp/agentic-art-orchestration  
実行者: GPT-5.6 Luna / Claude Sonnet相当以上  
目標: v1.0 control planeを維持し、会話型knowledge UXと継続改善loopを備えたv1.1.0まで自律実装・検証・再開できること

## Purpose / Big Picture

4つの独立repoを単一workspaceへ安全に展開するv1.0 control planeの上に、利用エージェントを会話型UIとして動かすinteraction plane、Google Driveへのappend-only artifact plane、feedbackからIssue・draft PRまでを進めるimprovement plane、非同期audit/refactoring planeを完成させる。

完成時の主要確認コマンド:

~~~bash
python3 tools/workspace.py init
python3 tools/status.py --format markdown
python3 tools/validate.py --check
python3 tools/audit.py --check
python3 -m unittest discover -s tests -v
~~~

## Progress

- [x] 2026-08-11 M0: 設計、計画、規則、manifest、queue、初期validator/test/CIを作成
- [x] 2026-08-11 M1: manifestとworkspace lifecycleを完成（MANIFEST-001、WORKSPACE-001、WORKSPACE-002、SNAPSHOT-001）
- [x] 2026-08-11 M2: signal契約、adapter、consumer、traceを完成（CONTRACT-001、3 adapter、CONSUMER-001、TRACE-001）
- [x] M3: work item、scheduler、runtime、quality gate、dispatcherを完成（WORKITEM-001、SCHEDULER-001、RUNTIME-001、GATES-001、DISPATCH-001）
- [x] M4: status、Project #4同期、audit、security boundaryを完成（STATUS-001、PROJECT-001、AUDIT-001、SECURITY-001）
- [x] M5: offline fixtureとE2E障害試験を完成（FIXTURE-001、E2E-001）
- [x] M6: runbookとv1.0判定を完成（DOCS-001、RELEASE-001。merge/releaseはhuman gate）
- [x] M7: v1.1 interaction、artifact、feedback、knowledge profile契約を完成
- [x] M8: retrieval、Drive adapter、Issue routing、自律改善、非同期auditorを完成
- [x] M9: interaction E2E、runbook、v1.1 qualificationを完成（RELEASE-002。merge/releaseはhuman gate）
- [x] M10: v1.2 Issue #2の半決定論的制作研究実行を設計・分解・実装（V12-ISSUE2-001、V12-BOUNDARY-001、V12-TRANSFORM-001、V12-CANDIDATE-001、V12-GATES-001、V12-SELECTION-001、V12-CHILD-GATES-001、V12-PROVENANCE-001、V12-E2E-001、V12-RELEASE-001完了。v1.2 qualificationは4子repo固定commit gateを含めPASS。merge・tag・releaseは別途human gate）
- [x] M11: `agentic-art-production`を同一repo Issue SSOTとhandoff/result exchange契約付きで親manifestへ追加し、5repo snapshot・quality gate・auditへ接続する（MANIFEST-PRODUCTION-001/002）。PR #15をhuman gate経由でmergeし、親mainへの結線を確認済み。

## Surprises & Discoveries

- 2026-08-11: 親repoは完全な空repoだったため、既存実装との互換維持は不要。
- 2026-08-11: art-historyとmarketingは既に独自graph/check運用を持つ一方、self-modelとagentic-art-researchは同日に自律実行ブートストラップされた。全repoへ同一内部構造を要求できない。
- 2026-08-11: marketingの鮮度とself-modelの同意は一般的graph relationへ平坦化できない。共通envelope + domain拡張が必要。
- 2026-08-11: offline fixtureは実子repoを親へvendorせず、stableな一時bare remoteとstaging cloneでinitの冪等性を検証できる。
- 2026-08-11: upstreamなし・behindのみも安全に証明できない状態としてguardし、観測とremediationを返す。guardはfixture生成を行わずread-onlyで検査する。
- 2026-08-11: snapshotのcaptured_atはHEAD committer timestampから導出し、同一入力でJSON/Markdownがbyte一致するようにした。
- 2026-08-11: normalized signalは共通envelopeの必須provenance/freshnessと、self/art-history/marketingのdomain拡張を分離した。stale、unknown、consent、raw voice locatorを暗黙変換せず検証する。
- 2026-08-11: ユーザーが求めるproduct surfaceはrepo操作ではなく利用エージェントとのinteractionである。検索精度だけでなく、意図達成、成果物、継続性、feedback取得をexperience outcomeとして扱う必要がある。
- 2026-08-11: ユーザー成果物とfeedbackはGitの正本ではなくGoogle Driveへ蓄積する必要がある。既存成果物を上書きせず、親Gitはopaque参照とlineageだけを保持する。
- 2026-08-11: 言語化されていない不満・欲求を改善へ利用する一方、推定をユーザー事実や同意へ昇格させないfeedback contractが必要である。
- 2026-08-12: MANIFEST-PRODUCTION-001/002のDraft PR #15がhuman gateでmergeされ、production Issue SSOTと親main manifestの結線が実運用状態になった。子repoの正本は変更せず、親mainのmerge commitだけをpost-merge stateへ記録する。

## Decision Log

- D-001: vendor copyではなくmanifest駆動の独立clone。
- D-002: submoduleを必須方式にせずsnapshotで再現性を保証。
- D-003: 共通化はnormalized signalの境界だけ。
- D-004: branch/commit/draft PRまで自動、merge/releaseは人間gate。
- D-006: 利用エージェントを会話型UIとする。
- D-007: ユーザー成果物はGoogle Driveへappend-onlyで保存する。
- D-008: 暗黙feedbackは根拠とconfidenceを持つ仮説として扱う。
- D-009: improvementとaudit/refactoringをinteractionから分離した非同期laneにする。
- D-013: Productionの親manifest結線は、PR作成ではなくhuman merge後の親main再確認を完了条件とする。

詳細は execution/decisions.md を正本とする。

## Outcomes & Retrospective

M0時点では構造と実行可能なqueueを確定した。M1でmanifest schema、workspace lifecycle、非破壊Git guard、決定的snapshotを実装し、M2でnormalized research signal v1、3 adapter、consumer compatibility、requirement-to-source traceを完成した。M3ではWORKITEM-001でowner、target、allowed paths、dependency、checks、risk、attempts、lease、checkpoint、terminal evidenceを機械検証するschemaを追加し、SCHEDULER-001で依存DONE・path conflictなしの候補だけをID順に選び、除外理由を返す処理を追加した。RUNTIME-001では期限切れleaseからcheckpointとdecisionを保持して再開し、evidenceをidempotentに記録するstate transitionを追加した。GATES-001では変更repoだけのmanifest quality gate実行、shell制御構文拒否、出力redact/hash、失敗時blockingを実装した。DISPATCH-001ではrequired files以外を除外し、rules/contracts/acceptance/allowed pathsとrecoveryをdeterministicにpackし、unsafe pathとsensitive assignmentを拒否するCLIを実装した。M3の運用基盤は完了した。STATUS-001ではsnapshot、live Git状態、queue、stateを統合し、commit、drift、child progress、compatibility、blocker、next workをJSON/Markdownへ決定的に出力した。PROJECT-001ではProject #4のstatus/priority/target/human gate/run IDをstable task IDでmappingし、重複remote itemを拒否、CREATE/UPDATE/UNCHANGEDを冪等に計画し、API unavailable時はlocal-onlyでqueue実行を継続可能にした。AUDIT-001ではmanifest/snapshot pin、contract schema、signal freshness/consent/orphan、queue duplicate、boundary test coverageをread-onlyで非blocking監査し、clean fixtureでfinding 0、注入fixtureで各findingを観測可能にした。SECURITY-001ではparent payloadとnormalized signalを再帰的にscanし、forbidden class、likely secret、unapproved exportをsanitized findingとしてcommit前にblockingできる境界を実装した。FIXTURE-001では一時rootに4 synthetic repoをcloneし、network disabledでclean/stale/dirty/diverged/incompatible/privacyの6シナリオを再現できるfixture builderを実装した。E2E-001ではconsumer、trace、security、quality gate、runtimeを4-repository offline fixtureへ接続し、cleanのCOMPLETEと9 failure injectionの終端・復旧経路をdeterministicに確認した。DOCS-001とRELEASE-001でv1.0 control planeをqualifiedにした。v1.1ではこの基盤を変更せず、interaction、external artifact、feedback、retrieval、improvement、asynchronous auditを後続milestoneとして追加する。

M11では、追加runtimeのDraft PR #15をhuman gate経由でmergeした後、親mainのmanifest、Issue SSOT、子commit pin、quality gate結線を再確認し、post-merge状態を親state/handoffへ記録した。親mainの実効結線とDraft PRの存在を別状態として扱えるようになった。

## Context and Orientation

| ID | Role | Authority | Bootstrap head |
|---|---|---|---|
| self-model | input-kb | 内面の観測・claim・pattern・同意 | 2ac3180 |
| art-history | input-kb | 芸術史entity・relation・evidence | 8370305 |
| marketing-trends | input-kb | trend・practice・鮮度・反証 | edcb49c |
| agentic-art-research | consumer-runtime | 調査DAG・判断・制作要件・成果物 | 9bfa07d |

親repoはこれらの内容を所有しない。repositories.yamlが入口、workspaceがローカル展開先、dataが生成status/audit/traceである。

## Plan of Work

### M1 — Manifest and workspace

MANIFEST-001でmanifest schema、semantic checks、invalid fixturesを作る。WORKSPACE-001でclone/init/fetch/statusを実装し、offline fake remotesでidempotenceを証明する。WORKSPACE-002はdirty、detached、ahead/behind/divergedを作り、既存treeを変更せずblocking stateへ変換する。SNAPSHOT-001は4repoのimmutable input setをJSON/Markdownへ決定的に出す。

M1完了の観察可能な動作は、clean fixtureで2回initし、2回目の変更件数が0、異常fixtureでGit HEADとworking tree hashが変わらないことである。

### M2 — Contracts and provenance

CONTRACT-001でsignal v1 schemaとvalid/invalid matrixを作る。3adapter taskは各子repoの実データschemaを読んでmappingを文書化し、offline fixtureで契約を検証する。子repo変更が必要なら各子に独立PRを作る。CONSUMER-001はimport version、source commit、unknown、domain constraintを保持する。TRACE-001はoutput requirementからsource entity@commitまで逆引きする。

Self Modelのraw voiceはlocatorのみとし、本文がexportされたfixtureは必ず失敗させる。

### M3 — Runtime

WORKITEM-001でowner repo、dependency、allowed paths、checks、risk、terminal criteriaをschema化する。SCHEDULER-001は選択結果と非選択理由を出す。RUNTIME-001はlease expiry前後、process kill、commit済み/PR未作成、PR作成済み/state未更新の各地点から再開する。GATES-001は変更repoだけを実行し、outputをredact・hash化してstateへ保存する。DISPATCH-001はtask-minimal context packを作る。

M3の中核受入は、kill-and-resumeでcommit/PRを重複させず、同じallowed pathへ2workerを割り当てないこと。

### M4 — Visibility and safety

STATUS-001は人間向けMarkdownと機械向けJSONを同一モデルから出す。PROJECT-001はGitHub Projects #4の優先順位・状態とローカルqueueを重複なく同期し、API障害時もローカル実行を継続する。AUDIT-001はstale pin、contract drift、orphan、freshness、consent、重複task、長期blockerを非blockingで報告する。SECURITY-001はsecretだけでなく、aggregate repo固有のPRIVATE_RAW/RESTRICTED/direct identifierを検知し、context packとbundleから排除する。

### M5 — Offline E2E

4つのsynthetic Git repoを一時directoryへ作り、networkなしでclone、snapshot、adapter、consumer、trace、scheduler、quality gate、status、auditを通す。failure injectionはstale、dirty、diverged、major mismatch、child test failure、secret、consent violation、lease expiry、process killを含む。

### M6 — Operations and release qualification

新規agentがrunbookだけで初期化・task実行・障害回復・handoffできるmanual testを行う。release_check.pyは設計仕様19.2を機械判定可能項目へ対応付け、offline E2Eを3回連続実行する。release tagとmergeは人間gateのまま残す。

### M7 — Interaction, artifact, feedback, and knowledge contracts

V11-DESIGN-001でfrontstage interaction、backstage improvement/audit、Google Drive artifact plane、authorityとhuman gateを固定する。INTERACTION-001は会話全文をGitへ保存せずintent、outcome、source snapshot、artifact、feedbackを保持する。ARTIFACT-001はDrive create-only、hash、access scope、lineageを契約化する。FEEDBACK-001はexplicitとinferredを分離し、inferredにevidence/confidence/hypothesisを要求する。REPOSITORY-ONBOARDING-001は4repoをcore setとして保持しながら追加entryを安全に許可する。KNOWLEDGE-PROFILE-001はcoreと追加repoが答えられる問い、retrieval入口、evidence/freshness、feedback owner、write scopeをmanifestへ追加する。

### M8 — Conversational retrieval and autonomous improvement

RETRIEVAL-001は質問を最小の関連repoへrouteし、repository@commit、freshness、unknowns付きで回答材料を返す。DRIVE-001はnetworkless fakeでcreate-only/idempotencyを検証する。ISSUE-ROUTER-001はdomain feedbackを子repo、UX/adapter/orchestration feedbackを親へ送り、低confidenceとduplicateを安全に扱う。IMPROVEMENT-001はIssueから実装・test・draft PRまでを既存scheduler/runtime/gatesへ接続する。AUDITOR-002はinteraction latencyと独立したqueue/leaseでrefactoring Issue/draft PRを生成する。

### M9 — Interaction E2E and v1.1 qualification

INTERACTION-E2E-001は、versioned child knowledgeからの回答、append-only artifact、explicit/inferred feedback、Issue routing、中断再開、自律改善、非同期auditをnetworkless fixtureで連結する。DOCS-002はinteraction、Drive参照、改善、監査、障害回復をrunbook化する。RELEASE-002はE2Eを3回連続実行し、merge、release、公開、共有範囲拡張、artifact削除を行わずv1.1を判定する。

### M10 — v1.2 semi-deterministic research execution

親のリモートIssue #2と`agentic-art-research#2`はv1.1のrelease blockerではなく、v1.2の設計・実装対象とする。V12-ISSUE2-001で、normalized signalを正本とするexplicit transformation rules、candidate space、seeded selection、specificity/genericness gates、counterfactual test、provenance拡張、LLMのretrieve/normalize/classify/match/execute/verify境界、子repo個別quality gateを分解する。v1.2開始前にIssue SSOT、対象repo、migration、rollback、human gateを明記し、子repoの内部schemaを親から変更しない。

分解後の実装順は、`V12-BOUNDARY-001`（境界契約）→ `V12-TRANSFORM-001`（明示rule）→ `V12-CANDIDATE-001`（候補空間）→ `V12-GATES-001`（specificity / genericness / counterfactual）→ `V12-SELECTION-001`（seed付き選択）→ `V12-PROVENANCE-001`（逆引きtrace）とする。`V12-CHILD-GATES-001`は境界契約後に独立実行でき、immutable observed commitからの品質ゲート実行とstale/unknown/failed状態の保存まで完了した。`V12-PROVENANCE-001`でselection decision、candidate、active rule、normalized signal、source commit、evidence locatorのtraceも完了し、`V12-E2E-001`でnetworkless統合、反復決定性、v1.1 interaction/artifact回帰を検証した。`V12-RELEASE-001`は、親のv1.2 qualificationと4子repoの固定commit gateをread-onlyで総合判定し、子gateが1件でもstale/blocked/failedならreleaseを不合格とする。M10の実装は完了、release操作は別途human gateとする。各taskは親control planeだけを変更対象とし、子repoのIssue・schema・canonical data変更は別task・別PR・子repo側の正本に従う。

## Concrete Steps

### Every session

~~~bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
python3 tools/validate.py --check
python3 -m unittest discover -s tests -v
~~~

期待: exit 0。失敗時は最初のruleを修復し、test/checkを削除しない。

### Task start

~~~bash
git status --short
python3 tools/validate.py --check
~~~

queueからtaskを選び、stateにtask/repo/lease/resume pointを書く。workspace実装後はworkspace statusとsnapshotも実行する。

### Task completion

~~~bash
python3 tools/validate.py --check
python3 -m unittest discover -s tests -v
git diff --check
git status --short
~~~

変更子repoではmanifest記載quality gateをそのrepo rootで実行する。結果をrepo、command、exit code、duration、commitとともにstate/handoffへ記録する。

## Validation and Acceptance

各taskは次をすべて満たすまでDONEにしない。

1. acceptanceを実際のcommand/outputで確認。
2. 正常系と禁止/失敗系testを追加。
3. 親validatorと全testがpass。
4. 変更した子repoのquality gateがpass。
5. generated dataを再生成し、意図しないdiffなし。
6. secret、PRIVATE_RAW、RESTRICTED、direct identifierなし。
7. queue/state/handoff/Progressが実際のGit状態と一致。
8. 次taskと最初の1操作が一意。

v1.1 taskはさらに、interaction応答をbackstage処理でblockしないこと、Drive artifactを上書き・削除しないこと、inferred feedbackを明示要求へ変換しないこと、外部artifact本文をGitへ保存しないことを満たす。

## Idempotence and Recovery

- init、fetch、snapshot、status、audit、context pack生成は再実行可能にする。
- partial clone/生成物はtemp pathへ作り、検証後atomic renameする。
- 既存repo pathのremote不一致を自動置換しない。
- lease切れ後はbranch、commit、PR、stateを照合してside effect済み地点から再開する。
- 子repo A成功、B失敗の場合、AをresetせずAのevidenceをcheckpointしBだけ再開する。
- schema migrationは旧version fixtureと移行testを持つまで実行しない。
- GitHub書込失敗時はcommit SHAと再実行対象だけを残し、PRを二重作成しない。
- Drive create失敗時は既存artifactを置換せずidempotency keyと再実行対象だけを残す。
- feedback routing失敗時は元interaction/artifact参照を保持してtriageへ戻し、Issueを重複作成しない。
- interaction応答後にimprovement/audit processが停止しても、checkpointからbackstage laneだけを再開する。

## Interfaces and Dependencies

### Initial commands

- tools/validate.py --check
- tools/workspace.py init|fetch|status|guard|snapshot
- tools/status.py --format json|markdown
- tools/audit.py --check
- tools/trace.py --check
- tools/release_check.py --version VERSION --runs N

### Data interfaces

- config/repositories.yaml
- config/orchestration.yaml
- schemas/repository-manifest.schema.json
- schemas/normalized-research-signal.schema.json
- schemas/work-item.schema.json
- schemas/run-state.schema.json
- schemas/interaction-event.schema.json
- schemas/external-artifact.schema.json
- schemas/feedback-signal.schema.json
- schemas/async-audit.schema.json
- schemas/issue-routing.schema.json
- schemas/retrieval-request.schema.json
- schemas/retrieval-index.schema.json
- schemas/retrieval-result.schema.json
- schemas/improvement-loop.schema.json
- schemas/interaction-e2e.schema.json
- execution/task-queue.yaml
- generated data/snapshot.json、status.json、audit.json、retrieval-result.json、feedback-routing.json、improvement-loop.json、interaction-e2e.json、async-audit.json、trace.json、artifact-registry.json

### Dependencies

- Python 3.11+
- Git 2.39+
- PyYAML 6.x
- private repo read権限、実装時はbranch/commit/draft PR権限
- Google Driveの承認済み保存先とcreate/read権限。update/delete/share権限はv1.1 coreに不要
- GitHub Projects連携はv1 coreの必須依存にしない

## Agent continuation rule

task完了後に「次に何をしますか」と質問しない。queue上の次taskをREADYにし、state/handoffを更新して継続する。Stop conditionsに該当した場合のみBLOCKEDとし、必要な決定、選択肢、推奨、影響、解除条件を残す。
