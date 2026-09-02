# Operator runbook

この文書は、会話履歴なしの新しいagentが親repoだけを読み、4つのcore repoと追加Production repoを安全に展開・検査・実行・引き継ぐための手順である。子repoの要件、schema、Issue、データは各子repoが正本であり、親のrunbookはそれらを複製しない。

## 0. 最初の1操作

作業開始時は、親repoの作業状態を変更せずに確認する。

~~~bash
git status --short
~~~

次に必ず [AGENTS.md](../AGENTS.md)、設計仕様、実行計画、`PLANS.md`、`execution/task-queue.yaml`、`execution/state.yaml`、[handoff](../execution/handoff.md)を読む。`state.yaml`の`active_task`とleaseが自分の作業範囲と一致しない場合、同じpathを編集しない。

Fresh cloneで依存関係が未準備なら、先に[README.mdの正準bootstrap](../README.md#ブートストラップ検証)を上から実行する。GitHub認証がない環境では、実repoを操作せずREADME記載の`--offline-fixture`経路を使う。

## 1. 正本と安全境界

- `config/repositories.yaml`: 統合対象、workspace path、source commit、contract、子repo quality gateの正本。
- `schemas/`: manifest、normalized signal、work itemの親境界契約。
- `execution/task-queue.yaml`: 実装順の正本。依存が全て`DONE`の最小ID `READY`を1件選ぶ。
- `execution/state.yaml`: active task、lease、checkpoint、次の再開点の正本。
- `execution/handoff.md`: 人間可読の観測結果、判断、検証、次の1操作。
- `data/`: status、audit、snapshot、E2E等の生成物。手編集しない。
- `repos/`: 子repoのローカル生成物。親履歴へvendor copyしない。

次を自動で行わない。

- dirty、detached、unpushed、behind、diverged checkoutのreset、pull、rebase、merge。
- force push、branch削除、Issue/PR削除、既定branchへのmerge、release。
- `PRIVATE_RAW`、`RESTRICTED`、raw voice本文、個人識別情報、credentialの親への集約。
- stale marketing signal、同意範囲外のself signal、根拠不足のart-history signalの正常値化。

## 2. 初期化と検査

### 初期運用startup（M14実装後）

CodexまたはClaude Codeを利用agentとして起動したら、最初の回答または外部writeより前に次を実行する。

~~~bash
.venv/bin/python tools/startup.py --check
~~~

startupは全manifest repoのremote headをread-onlyで確認し、qualified pinと比較してからworkspace guard、snapshot、status、audit、securityを実行する。`READY`は通常利用可、`READY_WITH_FINDINGS`は表示されたqualified commitと制約の範囲でread-only利用可、`BLOCKED`は影響capabilityを停止する。差分検知時にcheckout、pull、manifest pin更新を行わない。

M14完了前はこのcommandが存在しないため、従来のnetworkless smokeと実repo workspace検査を用いる。存在しないstartup commandを実装済みとして扱わない。

### networkless smoke

ネットワークを使わない再現確認は次の順で行う。

~~~bash
FIXTURE_ROOT="$(mktemp -d /tmp/agentic-art-orchestration-offline.XXXXXX)"
.venv/bin/python tools/workspace.py init --offline-fixture --fixture-root "$FIXTURE_ROOT"
.venv/bin/python tools/workspace.py status --json
.venv/bin/python tools/workspace.py guard --offline-fixture --fixture-root "$FIXTURE_ROOT" --json
.venv/bin/python tools/workspace.py snapshot --fixture-root "$FIXTURE_ROOT"
.venv/bin/python tools/workspace.py snapshot --fixture-root "$FIXTURE_ROOT" --check
.venv/bin/python tools/status.py --check --offline-fixture
.venv/bin/python tools/audit.py --check --offline-fixture
.venv/bin/python tools/security.py --offline-fixture
.venv/bin/python tools/e2e.py --offline-fixture --check
~~~

fresh cloneからfull suiteまで行う場合は、READMEのbootstrap節にあるoffline fixture生成列を先に実行し、その後にREADME記載のvalidatorとfull suiteを実行する。`FIXTURE_ROOT`は毎回新しい一時ディレクトリにし、別のmanifestや古いbranchのremoteを再利用しない。

期待値は、manifest記載repo数（coreは4、現在はProductionとviewer-response-notesを含む6）、`main`、clean、ahead/behind 0、`blocked_count: 0`、status `CLEAN`、security `PASSED`、E2E clean `COMPLETE`である。auditは既知の非blocking findingを保持し、失敗を正常値へ変換しない。legacy failure fixtureが4repoであることはmanifestの6repo運用を意味しない。E2Eのfailure injectionは失敗を隠さず、各ケースに終端状態と復旧経路を持つ。

### 実repo workspace

認証済みで実repoを展開する場合は`--offline-fixture`を付けず、manifestのURLとdefault branchを使う。

~~~bash
.venv/bin/python tools/workspace.py init
.venv/bin/python tools/workspace.py fetch
.venv/bin/python tools/workspace.py status --json
.venv/bin/python tools/workspace.py guard --json
.venv/bin/python tools/workspace.py snapshot
.venv/bin/python tools/status.py
~~~

認証不足、remote不一致、checkout欠落はrepo単位で観測し、手動で解消する。`guard`のblockedを無視して先へ進めない。

v1.0.0の資格判定は、3回連続E2E、親validator/test、fixture、status、audit、security、Git history scanを行う。これはread-onlyの判定であり、tag、commit、merge、releaseは行わない。

~~~bash
.venv/bin/python tools/release_check.py --version 1.0.0 --runs 3
~~~

v1.1.0のqualificationは、上記v1.0ゲートに加えてretrieval、Drive create-only artifact、feedback routing、improvement、非同期audit、interaction E2E、privacy boundaryを3回の決定的offline実行で検査する。

~~~bash
.venv/bin/python tools/release_check.py --version 1.1.0 --runs 3
~~~

v1.2.0のqualificationは、v1.2の候補生成・gate・seeded selection・provenance E2Eに加え、当時manifestが固定した4子repoの品質ゲートを各observed commitのimmutable archiveから実行した。現在mainにはProductionが追加されているため、次の資格判定はv1.2.1として5repoを対象にする。子repoのstatusが`STALE`、`BLOCKED`、`FAILED`、`ENV_UNSATISFIED`、またはgateが`NOT_RUN`ならqualificationは失敗とし、親manifestや子repoを自動更新しない。

~~~bash
.venv/bin/python tools/release_check.py --version 1.2.0 --runs 3 --workspace-root <verified-child-workspace>
~~~

`V121-RECONCILE-001`完了後は次を使用する。

~~~bash
.venv/bin/python tools/release_check.py --version 1.2.1 --runs 3 --workspace-root <verified-child-workspace>
~~~

v1.2.1は、Productionを含む5件のmanifest entryを対象に、v1.2.0と同じv1.2 E2E・v1.1回帰・親validator/test・security・immutable child quality gateを実行する。`--runs 1`は実装taskの疎通確認、`--runs 3`だけがqualificationである。5件のchild statusが全て`PASSED`、execution modeが`immutable-archive`、remote/merge/tag/release operationが未実行であることを確認する。remote default branchに新commitがあっても、このtaskはpinを更新しない。

`PRODUCTION-QUALIFY-001`完了後は、manifest記録commitと一致するGit外のverified child workspaceを指定してv1.3.0をqualificationする。

~~~bash
.venv/bin/python tools/release_check.py --version 1.3.0 --runs 3 --workspace-root <verified-child-workspace>
~~~

v1.3.0は、Research→Production→Researchのexchange E2Eを3回バイト比較し、clean、tamper、stale、incompatible、dirty-source、replayの終端行列、Productionを含む5repo・14 child gate、親suite、Git外出力、物理/remote effectなしを確認する。qualificationは`--workspace-root`をpinの実体化元として読み、各manifest `observed_commit`をGit外の一時workspaceへcloneしてからquality gateとexchangeを実行する。実クローンが先行、dirty、detachedでも結果へ混入させず、source checkoutは変更しない。observed commitがsourceに存在しない場合は、対象repositoryとexact pinを含む失敗findingを記録して停止する。Production exchangeのCIは`tools/pinned_workspace.py`へ`--repository agentic-art-research --repository agentic-art-production`を渡し、viewer-response-notesなどexchange非依存のrepo権限を要求しない。qualificationはRelease操作ではなく、merge/tag/GitHub Releaseは`PRODUCTION-RELEASE-001`の人間承認後に実行する。

`data/release-check.json`で`status=PASSED`、`remote_operations=[]`、`merge_operation=NOT_PERFORMED`、`tag_operation=NOT_PERFORMED`、`release_operation=NOT_PERFORMED`を確認する。qualification成功だけではrelease済みとは扱わず、merge、tag、release、公開、共有範囲拡張、artifact削除は人間の明示承認後に別途実行する。

`data/release-check.json`の`pinned_workspace.repositories`には、repository ID、exact `observed_commit`、source checkoutの観測状態、materialized commit、source mutation=falseを保持する。sourceのHEADがpinより先行していても、新しいHEADへ自動追随しない。

### child quality-gate dependency preflight

immutable archiveに`requirements.txt`がある子repoは、quality gate実行前に選択した実行環境で依存名、単純な`>=`下限、または数値の`==`固定版を検査する。repoごとに異なる固定版を持つ場合は、`<child-environment-root>/<repository-id>/bin/python`へ事前準備した環境を`--python-root`で指定する。reportの`environment_mode`は、指定なしなら`shared-runner`、指定ありなら`per-child`となる。依存が未導入、下限未達、固定版不一致、または親runnerが扱えない形式の場合は、repository statusを`ENV_UNSATISFIED`、execution modeを`NOT_RUN`として記録し、gate commandは実行しない。資格判定は失敗のまま維持され、依存不足を`PASSED`や通常のgate failureへ変換しない。

不足時はrunnerが自動インストールせず、結果のremediationに記録された子repoのrequirements SSOTを人間または明示許可された環境で解消してから再実行する。

~~~bash
pip install --user -r <child-repository-path>/requirements.txt
.venv/bin/python tools/child_quality_gates.py --manifest config/repositories.yaml --workspace-root <verified-child-workspace> --python-root <child-environment-root> --output data/child-quality-gates.json
~~~

## 2.9 pin を採用する

検査が通っていても、採用する手段が無ければ pin は止まったままになる。`tools/startup.py` が出す `remote_update_candidate` を確認し、候補の child quality gate が通ったときだけ採用する。

### 確認する

```bash
python3 tools/pin_adopt.py --dry-run --workspace-root <実クローン>
```

リポジトリごとに現在の pin、候補コミット、候補での quality gate、採用可否と理由を出す。`config/repositories.yaml` は書き換えない。

### 採用する

```bash
python3 tools/pin_adopt.py --apply --workspace-root <実クローン>
```

全ての検査が PASS のときだけ書き換える。1つでも塞がっていれば何も書かずに非0で終わる。部分的な採用はしない。`--dry-run` と `--apply` は排他で、どちらも省略するとエラーになる。

同じコミットが manifest 以外にも fixture、retrieval index、test module、handoff record などへ繰り返し書かれている場合、`--apply` は全ての出現箇所を書き換え、`written_files` に残す。child checkout が dirty、候補が remote より古い、または候補の gate が FAILED の場合は `BLOCKED` として停止し、pin を書き換えない。

書き換えたあとの PR 作成と merge は人間が行う。manifest に関わる操作が人間の関門であることは変わらない。

## 3. taskを実行する

1. queueから依存が`DONE`の最小ID `READY` taskを選ぶ。
2. `execution/state.yaml`へtask、対象repo、開始HEAD、想定変更、lease scope、expires_atを記録する。
3. 同じrepo/pathのactive leaseがないことを確認する。
4. taskのacceptanceを満たす最小差分だけを編集する。
5. work itemがある場合は、要求されたファイルだけをcontext packにする。

~~~bash
.venv/bin/python tools/dispatcher.py \
  --work-item tests/fixtures/work-items/valid.yaml \
  --context-root .
~~~

6. 親validator、親test、変更した子repoのmanifest記載quality gateを実行する。変更repoだけを`--changed`で指定し、失敗を削除・skipしてはならない。

~~~bash
.venv/bin/python tools/quality_gates.py --changed <repository-id>
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest discover -s tests -v
git diff --check
~~~

7. `git status --short`と`git diff --stat`で、対象外の変更がないことを確認する。
8. acceptanceの観測結果、checks、repoごとのHEAD/commit、機微情報確認、未解決、次の1操作をqueue/state/handoffへ記録する。
9. leaseを解放する前に、実行SSOTを作業branchへfast-forward pushし、remoteとdraft PRのHEAD一致をread-onlyで確認する。force push、既定branchへの直接push、merge、ready化は行わない。

~~~bash
git status --short
git log --oneline origin/<working-branch>..HEAD
git push origin <working-branch>
git rev-parse HEAD
git rev-parse origin/<working-branch>
gh pr view <number> --json headRefOid,isDraft,baseRefName,headRefName
~~~

pushまたはremote／PRの確認ができない場合は、未pushまたは`UNKNOWN`をstateとhandoffへ残し、leaseを解放せず停止する。確認後、依存完了後の次taskをREADYへ進める。merge/releaseはhuman gateで停止する。

### PR triageと人間のマージ判断

open PRの確認が人間レビューのボトルネックになった場合は、全manifest repo（親control planeを含む）のメタデータだけをread-onlyで観測する。

~~~bash
.venv/bin/python tools/pr_triage.py --fixture tests/fixtures/pr-triage/open-prs.json --check
.venv/bin/python tools/pr_triage.py --live --observed-at <fixed-ISO-8601-time> --output /tmp/pr-triage-live.json --check
~~~

レポートの`MERGE_CANDIDATE`から人間が差分、根拠、品質ゲート、Issue SSOTを確認する。`NEEDS_REBASE`は競合解消後に再観測し、`NEEDS_CI_FIX`は失敗ゲートの修正後に再観測する。`SUPERSEDED_CANDIDATE`はbase到達または完了済みtaskへの包含候補を示すだけで、PRを自動closeしない。`HUMAN_JUDGMENT`はchecksまたは競合状態が不明なため、人間が追加確認する。

change classは`config/human-gates.yaml`の`merge_classes`に従い、record、docs、code、contractのいずれも`auto_merge: false`である。triageはmerge、close、rebase、force push、ready化を実行せず、PR本文・diff・コメント・credentialをレポートへ保存しない。実際のmerge判断と操作は既存のhuman gateで行う。

### 空queue時のIssue intake

READYも依存完了済みBACKLOGも無い場合は、open Issueを自動昇格・クローズせず、まずread-onlyのintake reportを作る。Issue本文全文は出力せず、番号・タイトル・URL・SSOT品質判定・推奨アクションだけを保持する。live入力には`gh auth login`済みのread権限が必要で、認証できない場合はfixtureを使う。

~~~bash
.venv/bin/python tools/issue_intake.py --fixture tests/fixtures/issue-intake/current-open-issues.json --check
.venv/bin/python tools/issue_intake.py --live --repository <manifest-repo-1> --repository <manifest-repo-2> --observed-at <fixed-ISO-8601-time> --check
~~~

`REGISTER_BACKLOG`だけがqueue登録候補であり、登録は依存関係、対象repo、Issue SSOT URLを確認してから1つのcommitで行う。`ALREADY_QUEUED`は重複登録せず、`UNQUEUED_NEEDS_SSOT`は実装せずにレポートへ残す。intake tool自体はGit、Issue、queueを書き換えない。
live intakeはIssue metadataと本文を別々に取得し、各`gh issue view`にも対象repositoryを明示する。GitHub CLI/APIのbody field差異や、親repoの作業ディレクトリによるIssue番号の誤解決で全体を誤停止させない。

## 4. signalから成果物まで

子repoのadapterは`normalized-research-signal/v1`の境界形式だけを出力する。consumerはmajor version不一致を拒否し、source repositoryとimmutable commitを保持する。

~~~bash
.venv/bin/python tools/trace.py --check --fixture tests/fixtures/portfolio
~~~

traceの各edgeは、requirement → signal ID → source entity → repository@commit → evidence locatorを持つ。欠落入力は推測せず`COMPLETE_WITH_GAPS`として制約と再検証経路を残す。

## 5. repository-aware conversational retrieval

利用agentは自由文を親Gitへ保存せず、interactionの一時処理で構造化したintentとcapability codeをretrieval requestへ渡す。routerは各repositoryのknowledge profileとadapter indexを照合し、要求capabilityを覆う最小のrepository集合だけを選ぶ。結果にはrepository、manifestのimmutable observed commit、evidence locator、freshness、unknowns、domain constraintsを残し、stale/unknownをcurrentへ変換しない。retrievalはfrontstage laneだが、artifactやauditを待たず、user artifactはread-onlyである。

~~~bash
.venv/bin/python tools/retrieval.py
.venv/bin/python tools/retrieval.py --check
.venv/bin/python -m unittest tests.test_retrieval -v
~~~

`data/retrieval-result.json`にはraw query、会話本文、child repoのcanonical本文を保存しない。保存するのはrequest ID、capability code、選択repo、source commit、opaque/local evidence locator、freshness、unknowns、制約だけである。証拠がない場合は`NO_MATCH`、一部欠落または再検証要の場合は`COMPLETE_WITH_GAPS`とし、推測で補完しない。

## 6. 外部artifactのcreate-only保存

利用agentがユーザー成果物を保存するときは、承認済み保存先・access scope・consentを確認してからDriveArtifactAdapterを呼ぶ。adapterはcontentを外部Driveへ渡し、親Gitへはartifact ID、opaque provider file ID、SHA-256、source snapshot、lineageだけを返す。既存artifactのUPDATE/DELETE、Drive URLの代用、本文のGit保存は拒否する。

同じinteraction-scoped idempotency keyと同じpayloadは既存CREATEのmetadata-only結果をreplayする。keyを同じままpayloadまたはmetadataを変えた場合は重複作成を止める。修正版は新しいartifact IDとderived_from/supersedesで表す。

~~~bash
.venv/bin/python -m unittest tests.test_external_artifact_contract tests.test_drive_adapter -v
~~~

networklessの回帰は`FakeDrive`と`FakeDriveLiveProvider`で行う。`DRIVE-LIVE-001`のlive portはGoogle Drive v3の検索、approved folderへのmultipart CREATE、metadataまたはcontent hashのread-backだけを公開する。既存fileのupdate/delete/move/share/permission変更は実装しない。

~~~bash
.venv/bin/python tools/drive_live_check.py --plan --check
.venv/bin/python -m unittest tests.test_drive_live_bridge -v
~~~

実Google Driveのsmokeは、専用sandbox folder IDとrepo外のcredential環境変数を人間が指定し、`--confirm-live`を明示したときだけ実行する。`AGENTIC_ART_APPROVED_DRIVE_FOLDER_ID`と`AGENTIC_ART_GOOGLE_DRIVE_TOKEN`の値、artifact本文、signed URLはGitへ保存しない。指定がない場合はliveを実行せずBLOCKEDとして再検証経路を残す。実DriveのCREATE/readを通るまで、接続済みとは報告しない。

## 6.1 GitHub sandboxのattempt-scoped CREATE/REUSE

GitHub Issueのlive qualificationは、実証専用の `masa-san-jp/agentic-art-sandbox-2` だけを対象とし、productionまたはmanifest登録repoを指定しない。live CLIには毎回、lowercaseの `--attempt-id`（`^[a-z0-9][a-z0-9._-]{0,63}$`）を明示する。dedup keyは `initial-operations-github-sandbox-v1:<attempt-id>` で、同じattemptの再実行はREUSE、別attemptは別のCREATEとして証跡を分離する。

fixtureだけは `fixture-attempt-1` を既定値として使える。liveの既定attemptは存在しない。証跡はmetadata-onlyで、credential、repository full name、Issue本文を保存せず、live outputはGit外の `/tmp/github-sandbox-live-<attempt-id>.json` に出す。

~~~bash
.venv/bin/python -m unittest tests.test_github_sandbox_live_check -v
AGENTIC_ART_APPROVED_GITHUB_SANDBOX_REPOSITORY=masa-san-jp/agentic-art-sandbox-2 .venv/bin/python tools/github_sandbox_live_check.py --live --confirm-live --attempt-id <unused-id> --output /tmp/github-sandbox-live-<unused-id>.json
AGENTIC_ART_APPROVED_GITHUB_SANDBOX_REPOSITORY=masa-san-jp/agentic-art-sandbox-2 .venv/bin/python tools/github_sandbox_live_check.py --live --confirm-live --attempt-id <same-id> --output /tmp/github-sandbox-live-<same-id>-replay.json
~~~

qualificationが記録する外部操作はREAD、CREATE一件、CREATE直後の有限READ、REUSEだけである。IssueのUPDATE、CLOSE、DELETE、COMMENT、LABEL、branch、commit、PR、merge、releaseは実行しない。

## 7. feedbackからIssue候補へのルーティング

feedback routerは、summary code、manifestのknowledge profile、target authority、confidence、consentを使って、domain feedbackを正本の子repoへ、UX・retrieval・adapter・artifact・orchestration feedbackを親repoへ決定的に割り当てる。authorityが未確定またはinferred confidenceが閾値未満なら`TRIAGE`に留め、同じIssue keyはcanonical候補へ集約して重複を抑止する。出力はprivacy-safeなIssue候補のmetadataだけで、GitHub Issueのcreate/update/deleteは行わず、人間gateを維持する。

~~~bash
.venv/bin/python tools/issue_router.py
.venv/bin/python tools/issue_router.py --check
.venv/bin/python -m unittest tests.test_issue_router -v
~~~

`data/feedback-routing.json`にはfeedback ID、interaction/artifactのopaque参照、source snapshot、confidence、候補のacceptanceだけを保存する。raw conversation、Drive本文、PRIVATE_RAW、RESTRICTED、direct identifierは保存しない。`issue_creation_permitted`がfalseのfeedbackは`BLOCKED`とし、推定feedbackをuser factへ昇格させない。`ISSUE-CREATE-001`完了後の初期運用では、eligible候補を実GitHub Issueとしてcreate/deduplicateできるが、そのIssueの編集、comment、close、実装、branch、commit、PRは行わない。

## 8. Issue-to-draft-PR improvement lane

improvement agentは`FEEDBACK_ROUTING`のmetadata-only候補から、`creation_permitted=true`、authority確定、human gate保持、重複なしのcanonical Issueだけを選ぶ。schedulerでpath conflictと依存を確認し、runtimeのlease/checkpointでselect → implement → test → quality gateを再開可能に記録する。implementation、test、対象repoのquality gateがすべて`PASSED`のときだけ、base commit、変更path、branch案を持つdraft PR planを作る。GitHub Issue/PRのcreate、branch、commit、merge、releaseはこのnetworkless実装では行わず、planは常にhuman gate付きである。

~~~bash
.venv/bin/python tools/improvement_loop.py
.venv/bin/python tools/improvement_loop.py --check
.venv/bin/python -m unittest tests.test_improvement_loop -v
~~~

`data/improvement-loop.json`にはIssue key、source feedback IDs、source commit、write scope、scheduler/runtime checkpoint、test/gate status、draft PR planだけを保存する。raw feedback、会話本文、Drive本文、credential、PRIVATE_RAW、RESTRICTEDは保存しない。gateが未実行・失敗・BLOCKEDなら`WAITING`または`BLOCKED`に留め、draft PRへ進めない。再実行はtask + repo + base commit + attemptのidempotency keyで同じcheckpointを再利用する。

## 9. interaction E2Eと中断再開

v1.1のnetworkless E2Eは、frontstageのretrievalが返したrepository@commit/evidenceを使って、Drive FakeへのCREATEと同一payloadのREPLAYを確認し、artifact本文をGitへ返さない。その後、interaction outcome、explicit/inferred feedback、authority routing、improvementのdraft PR plan、runtime lease expiry/process interruption recovery、独立した`ASYNC_AUDIT`を同じrunで検証する。失敗時は段階ごとのterminal stateとresume pathを残し、実Google Drive、GitHub Issue/PR、branch、commit、merge、releaseは実行しない。

~~~bash
.venv/bin/python tools/interaction_e2e.py
.venv/bin/python tools/interaction_e2e.py --check
.venv/bin/python -m unittest tests.test_interaction_e2e -v
~~~

`data/interaction-e2e.json`には各stageのmetadata、opaque artifact reference、source commit、feedback ID、checkpoint、statusだけを保存する。`raw_conversation_stored=false`、`direct_identifiers_stored=false`、`remote_operations=[]`、artifactは`CREATE`のみであることを確認する。

## 10. 非同期audit/refactoring lane

監査はinteraction request pathと別の`ASYNC_AUDIT` queue/leaseで実行する。interactionは監査完了を待たず、user artifactは常にread-onlyである。監査findingは重複抑止されたIssue候補になり、対象repositoryのquality gateが`PASSED`のときだけdraft-PR計画へ進む。実際のmerge、release、artifactのupdate/deleteは行わない。

~~~bash
.venv/bin/python tools/audit.py --offline-fixture
.venv/bin/python tools/async_auditor.py --run-id AUDITOR-002:attempt-1
.venv/bin/python tools/security.py --offline-fixture
~~~

`data/async-audit.json`にはsource snapshot、parent/child commit、audit hash、lease、gate status、proposalのtraceだけを保存する。Drive本文、会話全文、user artifact contentは保存しない。`NOT_RUN`、`FAILED`、`BLOCKED`のgateはIssue/triageへ留め、gateをskipしてdraft PR化しない。

## 11. handoffの必須項目

`execution/handoff.md`には、少なくとも次を日本語または明確な英語で残す。

- Task IDと対象repo。
- 観測可能な変更とacceptance達成数。
- 親validator、親test、子quality gateのcommandと結果。
- repoごとのbranch、HEAD、commit SHA、dirty状態。未commitならその事実。
- `PRIVATE_RAW`、`RESTRICTED`、credential、direct identifierを含めていないこと。
- 未解決と、BLOCKEDなら観測事実、選択肢、推奨、影響、解除条件。
- 次taskと最初の1操作。

最後にstateの`active_task`とleaseを解放し、generated dataを再生成してから、statusとdiffを再確認する。

## 13. バッチ進捗のread-only観測

100件規模の実行前後は、プロジェクトの研究state、Production handoff/plan、workspace repoの
`HEAD..origin/main`を横断表示する。`batch_status.py`はclaim、state、Git、Issue、Driveを変更しない。
source fileの相対locatorとhashを出力するため、同じ入力は同じJSONになる。欠損・不明なGit比較・
認識できない状態は`UNKNOWN`として残し、完了へ丸めない。

~~~bash
.venv/bin/python tools/batch_status.py --workspace-root <workspace-root> --format json
.venv/bin/python tools/batch_status.py --report <state-root>/<run-id>/batch-report.jsonl
~~~

batch reportはdriverだけが`<state-root>/<run-id>/batch-report.jsonl`へappendする。
`batch-report-event/v1`はevent ID、run ID、project/repository、source commit、RFC3339時刻、
attemptを必須とし、時間・tokenがない場合はnullを許す。DURATION/TOKENS eventがnullの場合は
拒否する。集計表示の`未計測`は未実行・未提供を示し、ゼロ値を意味しない。

## 12. 自律Research実行と再開

`tools/run.py`の`RESEARCH_PENDING`は、構造化された`agent-action/v1`を
`tools/autonomous_runner.py`へ渡す開始点である。workerは絶対実行ファイルをargvで起動し、
`--request <agent-action.json> --response <agent-result.json>`だけを受け取る。SDK、shell文字列、
会話本文、credentialはworker境界へ渡さない。

stateはGit外の外部rootへ置く。初回はrun-id単位でleaseを取得し、`supervisor.json`をatomic replace
する。同じrun-idの再実行は`PLAN_READY`またはblocked terminalを再利用し、accepted resultを二重に
受理しない。worker完了後にprocessが停止しても、responseが残っていれば次回起動時に同じrun-idで
checkpointから受理する。別processのlease競合、期限切れでないlease、stateの契約不整合は変更せず
拒否する。

~~~bash
.venv/bin/python tools/autonomous_runner.py --run-id <run-id> \
  --state-root <external-state-root> --worker-command <absolute-worker-path> \
  --source-commit <40-char-commit> --project-path <project-path> \
  --allowed-path project
.venv/bin/python -m unittest tests.test_run tests.test_autonomous_runner tests.test_runtime_recovery -v
~~~

human gate対象は`merge`、`release`、`public_share`、`consent_expansion`、`destructive_git`、
`external_cost_over_declared_budget`、`physical_action`である。workerが要求しても実行せず、観測事実・
影響・解除条件を保持した`BLOCKED_HUMAN`で停止する。worker契約失敗は同じstageとerror fingerprint
で3回まで再試行し、4回目は`FAILED_RETRY_EXHAUSTED`とする。
