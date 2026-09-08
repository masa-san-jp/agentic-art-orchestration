# Agent runtime guide

## 共通起動プロンプト

~~~text
このメタ・リポジトリを自律的に完成させてください。

AGENTS.mdを読み、20260811-agentic-art-orchestration-repository-execution-plan.mdを
ExecPlanとして実行してください。task-queue.yamlで依存がDONEの最小IDのREADYタスクを
選び、親の受入条件と変更した全子repoの品質ゲートを満たしてください。

子repoの要件とschemaは子repoを正本とし、親へ複製しないでください。完了後はqueue、
state、handoff、ExecPlanを更新し、次のREADYタスクへ進んでください。Stop conditionsに
該当する場合だけBLOCKEDにし、観測事実、選択肢、推奨、影響、解除条件を残してください。
~~~

## Fresh cloneから全repository workspaceを準備する

会話履歴がなく、child workspaceがまだ無い場合は、repo名を質問したり個別cloneしたりせず、
manifest駆動の`bootstrap`を一回実行する。実repoではcredential本文を扱わず、GitHubの既存
credential helperだけを使う。認証確認の出力をstate、Issue、Gitへ貼り付けない。

~~~bash
gh auth status --hostname github.com
gh auth setup-git
WORKSPACE_ROOT="/absolute/path/outside/agentic-art-orchestration"
.venv/bin/python tools/workspace.py bootstrap \
  --workspace-root "$WORKSPACE_ROOT" --json
~~~

`bootstrap`が対象にするのは`config/repositories.yaml.repositories`の全entryである。
`--workspace-root`は親repo・child checkout・filesystem rootと重ならない専用の絶対pathを指定する。
未指定時はmanifestの`repos`が親repo基準で使われるが、fresh cloneのagentは外部専用rootを明示する。
missing remoteのread accessはclone前に`GIT_TERMINAL_PROMPT=0`で検査されるため、prompt待ちにならない。

agentはresultの`status`とexit codeだけで次を決める。

| status / exit | 自律agentの動作 |
| --- | --- |
| `READY` / 0 | 全entryが`cloned`または`reused`、guard PASS、pin MATCHED。`status`/startupを再確認してtaskへ進む |
| `BLOCKED_PIN_DRIFT` / 2 | clean checkoutを変更せず、`tools/pin_adopt.py --dry-run`の候補確認か`tools/pinned_workspace.py`のqualificationへ進む。pin採用はhuman gate後 |
| `BLOCKED_EXISTING_WORKSPACE` / 2 | dirty/untracked/detached/remote/upstream/ahead/behind/diverged等を記録し、既存checkoutを修復せず停止する |
| `BLOCKED_REMOTE_ACCESS` / 2 | sanitized findingだけを記録し、credential/networkを人間が解消するまでcloneもpartial配置もしない |
| `BLOCKED_RACE` / 2 | lock ownerまたはmarker付きtool-owned stagingを確認し、同時実行完了・人間復旧後に再実行する。盲目的に削除しない |
| `FAILED` / 1 | `CLONE_FAILED`などのsanitized findingとremediationをcheckpointへ記録する。既存pathや不明なstagingを削除・採用しない |

applyは、全missing cloneをmarker付きstagingで検証してからsame-filesystem renameする。
配置競合・途中失敗ではこのrunが作ったpathだけを逆順rollbackし、既存checkoutを変更しない。
2回目のclean runは全entryが`reused`、`changed_count: 0`になる。`remote_operations`、
`child_mutations`は空で、resultにcredential、token、remote応答本文、child repository本文を残さない。

networklessの検証は、実repoと混ぜず毎回新しいtemporary rootで行う。checked-in manifest pinと
synthetic bare remoteのHEADが異なる場合、CLI初回の`BLOCKED_PIN_DRIFT`/exit 2は失敗ではなく、
pinを自動採用しなかった証拠である。`READY`、idempotent reuse、clone failure、placement race、
rollbackの受入証拠は次で確認する。

~~~bash
BOOTSTRAP_ROOT="$(mktemp -d /tmp/agentic-art-bootstrap.XXXXXX)"
set +e
.venv/bin/python tools/workspace.py bootstrap \
  --offline-fixture \
  --workspace-root "$BOOTSTRAP_ROOT/workspace" \
  --fixture-root "$BOOTSTRAP_ROOT/fixture" --json
BOOTSTRAP_EXIT=$?
set -e
test "$BOOTSTRAP_EXIT" -eq 2
.venv/bin/python -m unittest tests.test_workspace_bootstrap tests.test_workspace tests.test_workspace_guards -v
~~~

既存の`init`、`fetch`、`status`、`guard`、`snapshot`は後方互換で残る。全manifestを検証後に
一括配置する場合だけ`bootstrap`を使い、legacy commandへ暗黙に切り替えない。

## テーマ未指定の制作計画

利用者はテーマ、作品slug、作品titleを指定しなくてよい。制作計画を作るよう依頼されたエージェントは、`--intent`、`--slug`、`--title`を付けずに次を実行する。

~~~bash
.venv/bin/python tools/run.py \
  --workspace-root <verified-child-workspace> \
  --profile-root <external-self-model-profile> \
  --state-root <external-state-root>
~~~

この入口はpin済みsignal snapshotからgate通過候補を決定的に選び、安定したproject identityを生成し、Research requestをGit外へ出力する。結果の`theme_proposal.mode`は`REPOSITORY_DERIVED`であり、`creative_question`が候補から導出した作業テーマである。エージェントはそのrequestを読み、宣言された調査を実行し、既存のhandoff・Production手順を継続して`PLAN_READY`まで進める。明示`--intent`は任意の順位付けであり、必須ではない。

ResearchとProductionの`--research-root`/`--production-root`はmanifestから自動解決される。引数を省略した通常runでも、workspaceがmissingまたはcleanなpin driftだけなら、run state配下に`pinned-workspace`を新規作成し、全manifest entryを宣言済みのqualified commitへ展開してから同じrunを継続する。元のcheckout、manifest、remote refは変更しない。展開されたworkspaceには`manifest-pinned-workspace/v1`マーカーが付き、detached checkoutでも各commit、clean state、workspace所有証拠を再検証する。dirty、symlink、破損、権限不足、既存tree修復が必要な場合はBLOCKEDのまま停止する。

実Self Modelを読む場合、`--profile-root`には利用が認められた外部profileの絶対パスを明示する。
これは出力先の`--destinations-file`とは別の入力であり、Self Modelのexportだけへ渡される。
profileの内容・同意・外部保存境界はSelf Model自身が検証する。親はパスを補完せず、未指定なら
実exportやrun stateの作成前に`BLOCKED`（`PROFILE_ROOT_REQUIRED`、exit 2）を返す。
既存のprofileが使えない場合にrepository内の自己モデルを採用したり、本人データを生成したりしない。

Productionまで進んだ後の再開では、`<state-root>/production/production/<slug>/`がrun-idをまたぐ同一プロジェクトの出力rootになる。各runの`<state-root>/<run-id>/`は実行ごとのcheckpointであり、`<state-root>/production-history.jsonl`はrun-idとproject-idだけを結ぶGit外の追記型メタデータ台帳である。既存プロジェクトを別run-idで続けるときは、初回と同じ`--slug`を明示する。handoffが変わった場合はProduction childのrevision受理へ進み、過去のexecution、quality、resultを新しいrunの空ディレクトリへリセットしない。

実repoを読めない環境では、合成signalだけを使うnetworkless確認として次を明示実行できる。

~~~bash
.venv/bin/python tools/run.py \
  --offline-fixture \
  --state-root <external-state-root>
~~~

`--offline-fixture`は実child checkoutや外部サービスを読まず、checked-in fixtureのsource commitがmanifestとsnapshotのpinに一致する場合だけ進む。実repoの制作計画と取り違えないため、この結果のsourceはfixtureとして扱う。
この経路には`--profile-root`は不要で、指定されてもprofileを読み込まない。

実行開始時には、入口自身がmanifestの全repoについてread-only guardを行い、clean・通常branch・upstream有り・`observed_commit`一致を確認する。いずれかが満たされなければchild exportを実行せず、`BLOCKED`と解除条件を返す。既存checkoutを自動checkout、reset、fetch、pin更新してはならない。`<verified-child-workspace>`はこの検査とchild quality gateを通過したGit外workspaceを指定する。

したがって、別エージェントへ渡す最小指示は次の一文で足りる。

~~~text
このrepoのAGENTS.mdとREADME.mdに従い、テーマ・slug・titleを質問せず、pin済みworkspaceで`tools/run.py`を実行してPLAN_READYまで自律的に進める。
~~~

startupが`BLOCKED`またはpin済みworkspaceを読めない場合は、テーマやPLAN_READYを捏造せず、`<state-root>/<run-id>/run.json`へ未完了状態・観測済み解除条件・保存済みの`resume_command`を記録して返す。`AT_EDGE`、`RESEARCH_PENDING`、`AT_PRODUCTION`はすべて`completion_status: INCOMPLETE`であり、手動制作案へ自動fallbackしてはならない。外部CREATE、merge、releaseなどのhuman gateは別途必要である。

## 出力先プロファイルと決定的な復旧

fresh cloneのagentは、まず`config/output-destinations.example.yaml`をGit外の一時ディレクトリへ
コピーし、`state_root`、`internal_output_root`、任意の`public_projection_root`を、絶対かつ
互いに重ならない外部パスへ置き換える。profile自体もrepoへ保存しない。`state_root`と
`internal_output_root`は必須で、`public_projection_root`を設定した場合は正規runの`PLAN_READY`
またはbatchの`PASSED`で完成制作プランを書き込むlocal public-project worktreeになる。未設定なら
内部成果物を保持したまま`BLOCKED_CONFIGURATION`で停止する。`project --apply`はwork recordや
手動requestのhuman-gated laneとして残り、remote公開・Git操作は行わない。

~~~bash
DESTINATIONS_DIR="$(mktemp -d /tmp/agentic-art-destinations.XXXXXX)"
DESTINATIONS_FILE="$DESTINATIONS_DIR/profile.yaml"
cp config/output-destinations.example.yaml "$DESTINATIONS_FILE"
$EDITOR "$DESTINATIONS_FILE"
.venv/bin/python tools/validate.py --check
.venv/bin/python tools/run.py --offline-fixture --run-id DEST-AGENT-001 \
  --destinations-file "$DESTINATIONS_FILE"
~~~

実行入口のrole対応は次の通りである。

| 入口 | profile未指定時の互換引数 | profile指定時の既定先 |
|---|---|---|
| `tools/run.py` | `--state-root`（任意） | stateは`state_root`、bundleは`internal_output_root/run/<project-id>/` |
| `tools/batch_run.py` | `--output-root`と`--state-root` | `internal_output_root/batch/<run-id>/`と`state_root` |
| `tools/production_exchange.py` | `--output-root`（省略時は一時領域） | `internal_output_root/production-exchange/` |
| `tools/autonomous_runner.py` | `--state-root` | `state_root` |

`--destinations-file`が最優先のprofile選択で、未指定なら
`AGENTIC_ART_DESTINATIONS_FILE`、それも無ければ各入口のlegacy動作になる。直接CLIで同じ
roleを渡した場合は、そのroleだけ直接値が優先される。profileを暗黙検索することはない。
batch、production exchange、autonomous runnerには各既存のmanifest、workspace、export、
workerなどの必須引数が別にあるため、profileがそれらを省略可能にするとは解釈しない。

エラーは停止理由と復旧方針を含む。相対パス・空値・NULは絶対外部パスへ直し、orchestration
repoまたはchild checkout内・filesystem root・role同士の重なりは専用の兄弟ディレクトリへ直す。
create-onlyの派生出力が`not empty`なら既存データを消さず、新しいrun-idまたは空の専用rootを
使う。`destination-resolution.json`が同じrun-idで別内容なら、同じprofileを復元して再開するか
新しいrun-idを選ぶ。失敗を成功扱いにしたり、既存のstate/outputを削除して直したりしない。

profileを外してlegacyへ戻すときは、CLIの`--destinations-file`を外し、設定した
`AGENTIC_ART_DESTINATIONS_FILE`を`unset`する。runは`--state-root`、batchは両方のroot、
autonomous runnerは`--state-root`を明示する。resolution evidenceはGit外のstate root内にだけ
create-onlyで残り、credentials、会話本文、PRIVATE_RAW、RESTRICTED、個人識別情報はprofileや
evidenceへ入れない。

## 公開projectionを自律的に扱う

公開projectionは、正規run/batchの完成planを設定済みpublic projectへ出す自動laneと、work
record・任意requestを扱う人間承認laneに分かれる。エージェントは会話履歴に頼らず、source
report/summary、request、target layout、result evidenceを読み直して再開する。

### 正規run/batchの自動plan投影

`tools/run.py`の最終状態が`PLAN_READY`、または`tools/batch_run.py`のbatch状態が`PASSED`で、選択
profileに`public_projection_root`があると、入口自身が`project_plan_automatic`または
`project_batch_automatic`を呼ぶ。自動authorityは正規sourceのrun/status、destination resolution、
source hash、`record_kind: plan`を拘束する。source report/summaryの
`automatic_plan_authority`（producer、source status/id/hash、destination resolution hash）も完全一致
させる。手書きrequest、任意ファイル、work recordをこの入口へ
渡して公開可にすることはできない。

preflightは公開境界、機密情報、権利・同意、path safety、target Git/layout/index/markerを全件検査
してから、`plans/Pxxxx-<slug>/`の`README.md`、`plan.md`、`metadata.yaml`と`plans/index.yaml`、
管理対象catalog markerを更新する。batchは全件を先にstagingし、100件以上でも決定的なID・順序・bytes
を一つのtransactionで反映する。planのこの自動経路ではレコード単位の`public_share` approvalは
要求せず、result evidenceの`projection_mode`は`AUTOMATIC_PLAN`、`human_gate`は`NOT_REQUIRED`とする。

`public_projection_root`の不足は`BLOCKED_CONFIGURATION`、公開境界違反は`BLOCKED_POLICY`、targetの
dirty/conflict/layout不適合は`BLOCKED_CONFLICT`、途中I/Oまたはrollback不全は`FAILED`である。いずれも
公開targetに部分結果を残さず、内部のcanonical planとstate rootのmetadata-only resultを保持する。
自動laneは`git add`、commit、branch操作、push、PR、merge、release、visibility変更を行わない。

自動経路の再現確認は、実targetではなくsynthetic temporary fixtureで行う。

~~~bash
.venv/bin/python -m unittest tests.test_public_projection tests.test_run tests.test_batch_run -v
~~~

### 手動projection（prepare → dry-run → human approval → apply）

手動projectionでは、`prepare`が`PLAN_READY` runまたは`PASSED` batchから内部candidateとrequestを
create-onlyで作る。draftのvisibility、rights、consentは明示evidenceがない限り`unknown`のままで、
agentは`cleared`へ昇格させない。元のcanonical internal outputも変更せず、更新後のcandidateは
`prepare --refresh`でhashを再計算する。

### 実行順

1. profileの`internal_output_root`から候補を作る。単一runかbatchかに応じて次のどちらかを
   選び、既存候補を変更する場合だけ最後のrefreshを使う。

~~~bash
.venv/bin/python tools/public_projection.py prepare \
  --run-report <run.json> --projection-id <stable-id> \
  --destinations-file "$DESTINATIONS_FILE"
.venv/bin/python tools/public_projection.py prepare \
  --batch-summary <batch-run.json> --projection-id <stable-id> \
  --destinations-file "$DESTINATIONS_FILE"
.venv/bin/python tools/public_projection.py prepare \
  --refresh <draft-request.yaml> --destinations-file "$DESTINATIONS_FILE"
~~~

2. 利用者指定の既存local Git worktreeへ、`init-target --dry-run`でlayout scaffoldを確認する。
   不足layoutのlocal書込みが必要な場合だけ`init-target --apply`を明示する。この操作は
   `public_share` approvalを要求しないが、公開recordは作らない。

~~~bash
.venv/bin/python tools/public_projection.py init-target \
  --destinations-file "$DESTINATIONS_FILE" --target-root <local-public-worktree> --dry-run
.venv/bin/python tools/public_projection.py init-target \
  --destinations-file "$DESTINATIONS_FILE" --target-root <local-public-worktree> --apply
~~~

3. requestをtargetへ当てる前に`project --dry-run`を実行する。approvalは渡さず、targetは
   read-onlyである。成功時は`DRY_RUN_READY`、unknown/内部/restricted clearanceやsecurity
   違反は`BLOCKED_POLICY`、dirty/layout/index/source/content競合は`BLOCKED_CONFLICT`となる。
   resultはstate rootの`<projection-id>/public-projection-result.json`へhash、ID、path、finding
   だけをcreate-onlyで残す。

~~~bash
.venv/bin/python tools/public_projection.py project \
  --request <public-projection-request.yaml> \
  --destinations-file "$DESTINATIONS_FILE" --target-root <local-public-worktree> --dry-run
~~~

4. 人間がcandidateのbytesと公開範囲・権利・同意を確認した後、requestのcanonical SHA-256へ
   結び付いた別ファイルを受け取った場合だけ`project --apply`を実行する。approvalには
   `public_share`、`APPROVED`、`HUMAN`、scope `local-public-project-projection`、有効な
   `approved_at`/`expires_at`が必要で、エージェントはapprovalや`approved_by`を生成・補完しない。

~~~bash
.venv/bin/python tools/public_projection.py project \
  --request <public-projection-request.yaml> \
  --approval <public-projection-approval.yaml> \
  --destinations-file "$DESTINATIONS_FILE" --target-root <local-public-worktree> --apply
~~~

applyの変更先は新規record、対応index、collection READMEのcatalog marker内だけである。root
README、既存record、marker外、Git ref、remote、branch、commit、push、merge、release、visibility
は変更しない。終端は`APPLIED`、同一source/contentの再実行`ALREADY_PROJECTED`、承認問題
`BLOCKED_HUMAN`、policy問題`BLOCKED_POLICY`、target競合`BLOCKED_CONFLICT`、I/O/rollback不全
`FAILED`である。`FAILED`に残存pathがあれば、resetや既存record削除をせずtarget fingerprintを
人間が確認して復旧する。apply後のcommit・push・release・実際のpublic shareも人間の別ゲートで
ある。

合成temporary Git targetだけを使い、会話履歴なしの再現経路を確認するには次を実行する。

~~~bash
.venv/bin/python -m unittest tests.test_public_projection tests.test_security_boundary -v
~~~

## Context loading

manifest記載の全repoを無条件に全文読込しない。task context packは次だけを含める。

1. 親のAGENTS、task、関連contract、state。
2. owner repoのinstructionsとrequirement SSOT。
3. 直接依存するadapter/schema。
4. acceptanceとquality gate。
5. 前回失敗の最小ログと次の再開command。

## Checkpoint

次のいずれかでcheckpointを残す。

- 1 taskの受入条件を満たした。
- repoまたはbranchを跨ぐ直前。
- schema・公開CLI・契約versionを変更した。
- 30分を超えた。
- 外部制約または仕様との差を発見した。
- コンテキスト圧縮またはセッション終了が近い。

checkpointにはtask、repo、branch、HEAD、dirty state、checks、未完了acceptance、次の1commandを含める。

## Failure classification

| Class | 例 | 既定動作 |
|---|---|---|
| transient | network、rate limit | 規定回数retry後checkpoint |
| local-precondition | dependency不足、未clone | 可逆に修復して再実行 |
| repository-state | dirty、diverged、detached | mutationせずBLOCKED |
| contract | schema不一致、major mismatch | adapter/consumer taskへ戻す |
| quality | child test失敗 | owner repoで最小再現、完了禁止 |
| safety | secret、同意違反、公開範囲 | 即時停止、出力へ含めない |
| authority | merge、release、破壊操作 | 人間ゲート |

## Intent付き実行

候補順位へ人のintentを反映する場合は `tools/run.py --intent` を使う。intentは
hard filterではなく、既存の安全・鮮度・根拠gateを通過した候補の順位付けだけに使う。
実行は `intent-rank/v1` のローカル決定的処理で、Unicode NFKC、casefold、空白圧縮を
行った文字bigramのmultiset weighted Jaccardを計算する。intentがない実行は既存の
`research-selection/v1` のままで、intent付き実行だけ `research-selection/v2` を出力する。

生intentは成果物・ログ・Gitへ保存しない。成果物には `intent_sha256`、algorithm名、
kind別score、total scoreだけを残す。CLIの実行結果とselectionのdigestが一致することを
確認し、空白だけのintentは入力エラーとして扱う。intent付き実行の再現確認は次の形で行う。

~~~bash
python3 tools/run.py --bundle <normalized-bundle.json> --project-id <project-id> \
  --seed-input <seed> --intent <intent-text> --output <run.json> --check
~~~

intentがない実行でも、候補空間から最初のgate-passing候補を選び、Research requestの
`intent.creative_question`をテーマ提案として扱う。したがって制作計画の開始に、利用者のテーマ・
slug・titleは不要である。

## 自律Research runner

`tools/run.py`は同期pipelineの結果にraw intentを含めず、`execution_status=RESEARCH_PENDING`と
metadata-onlyの`next_action`を返す。`tools/autonomous_runner.py`はそのaction境界をworkerへ
渡し、Git管理外の明示`state-root/<run-id>/supervisor.json`だけをatomic replaceする。
workerはSDKではなく、絶対パスの実行ファイルをargvで次の形に限定する。

~~~bash
.venv/bin/python tools/autonomous_runner.py \
  --run-id <run-id> --state-root <external-state-root> \
  --worker-command <absolute-worker-path> \
  --source-commit <40-char-commit> --project-path <project-path> \
  --allowed-path project
~~~

workerのrequestは`agent-action/v1`、responseは`agent-result/v1`のclosed metadata-only JSONである。
responseのCOMPLETEDと全check PASSは`RESEARCH_COMPLETE`を記録する。next_actionから正規handoff、Productionの内容検証、knowledge保存へ続ける。worker自己申告では`PLAN_READY`にしない。同じrun-idの再実行はaccepted resultを
再利用する。human gate対象の要求は実行せず`BLOCKED_HUMAN`、外部境界違反は`BLOCKED_EXTERNAL`、
同一stage・error fingerprintの失敗は3回まで再試行して4回目を`FAILED_RETRY_EXHAUSTED`とする。
会話全文、credential、PRIVATE_RAW、RESTRICTED、worker stdout/stderrはstateへ保存しない。

## バッチ進捗と完了レポート

`tools/batch_status.py`はworkspace内の`07_runtime/research-state.json`、Productionのhandoff/plan、
各workspace repoのGit状態をread-onlyで観測する。プロジェクトのstageは
`NOT_STARTED`、`IN_PROGRESS`、`TERMINAL`、`HANDOFF`、`PLANNED`の固定語彙で、入力ファイルの
相対locatorとSHA-256、taskの完了数、認識できない状態を併記する。`HEAD..origin/main`の差分が
取得できない場合は0にせず`UNKNOWN`とする。実行中にstate、claim、Git、外部サービスを書き込まない。

~~~bash
python3 tools/batch_status.py --workspace-root <workspace-root> --format json
python3 tools/batch_status.py --report <state-root>/<run-id>/batch-report.jsonl
~~~

batch driverが作成するJSONLは`batch-report-event/v1`のmetadata-only closed eventをappendする。
集計器は起動、完了、失敗、再試行、所要時間、token数をまとめ、未提供の時間・tokenは`未計測`として
表示する。reportの読み取りも書き込みもGit外の入力を変更しない。

## 知識を次回へ残す統合実行

`tools/run.py --cycle-context <external-context.json> --state-root <external-state-root>` は、AAK04 profileの隔離code/knowledge pin、全owner検索、Production正本検証、owner別保存・索引・再開を接続する。返された`next_action`をエージェントが処理し、`resume_command`で継続する。構成と状態の意味は [knowledge-cycle-runtime.md](knowledge-cycle-runtime.md) を読む。実エージェント受入とfake回帰を区別する。
