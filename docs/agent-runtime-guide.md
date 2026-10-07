# Agent runtime guide

## READMEからの最短ルート

fresh cloneの環境準備と、実データ不要で合成制作プランまで完走するコマンド列は
[READMEの最短ルート](../README.md#利用者向けの最短ルート)を正準入口とする。
`--offline-fixture`だけの例は入口なしでもよい。合成ゲート報告はfixture専用であり、
実childの品質確認やProject納品の証拠には使わない。
制作runは開発taskを選ばず、下のヒアリング → テーマ未指定run → agent action → 再開へ進む。

## 開発用の共通起動プロンプト

~~~text
このメタ・リポジトリを自律的に完成させてください。

AGENTS.mdを読み、20260811-agentic-art-orchestration-repository-execution-plan.mdを
ExecPlanとして実行してください。task-queue.yamlで依存がDONEの最小IDのREADYタスクを
選び、親の受入条件と変更した全子repoの品質ゲートを満たしてください。

子repoの要件とschemaは子repoを正本とし、親へ複製しないでください。完了後はqueue、
state、handoff、ExecPlanを更新し、次のREADYタスクへ進んでください。Stop conditionsに
該当する場合だけBLOCKEDにし、観測事実、選択肢、推奨、影響、解除条件を残してください。
~~~

## 資格情報なしの制作session（Issue #250 S4）

PUBLIC の子repoを読む制作runには、GitHub tokenの発行やloginは不要である。
ヒアリング、制作run、返されたagent action・resume commandは、次の入口から実行する。
agent session自体も、同じ入口の `--` 後にagentの起動コマンドを渡して起動できる。

~~~bash
.venv/bin/python tools/credential_free.py --state-root <external-state-root> -- <command...>
~~~

入口はstate root配下に呼び出しごとに空の`GH_CONFIG_DIR`（700）、空の`GIT_CONFIG_GLOBAL`、
空の`HOME`/`XDG_CONFIG_HOME`を作る。GitHub/Enterprise token、継承Git config、askpass、SSH agentを
除き、system config・credential helper・extraheader・SSH鍵/対話認証を無効にする。
`~/.netrc`も継承せず、既存のlogin・keychain・Git設定は変更しない。profile、workspace、必要な
agent設定は明示した絶対pathを使う。標準入出力と終了コードはそのまま渡し、一時設定は実行後に片付ける。
Project-owned v2のrun stateを初めて作る場合、入口のstate rootには別の外部一時rootを使い、
Project配下の作成は既存resolverの検証後に行う。

子repoをprivateへ戻した場合だけ、[operator runbook §2](operator-runbook.md#privateに戻した場合の代替read-only-token)の
専用`GH_CONFIG_DIR`とread-only tokenを使う。開発・PR作成・mergeは別sessionで行う。

## Fresh cloneから全repository workspaceを準備する

会話履歴がなく、child workspaceがまだ無い場合は、repo名を質問したり個別cloneしたりせず、
manifest駆動の`bootstrap`を一回実行する。PUBLIC の実repoは資格情報なしで読み、
credential本文や認証確認の出力をstate、Issue、Gitへ貼り付けない。

~~~bash
EXTERNAL_STATE_ROOT="/absolute/path/outside/credential-free-state"
WORKSPACE_ROOT="/absolute/path/outside/agentic-art-orchestration"
.venv/bin/python tools/credential_free.py --state-root "$EXTERNAL_STATE_ROOT" -- \
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
| `READY` / 0 | 全entryが`cloned`または`reused`、guard PASS、pin MATCHED。`status`/startupを再確認し、制作ならヒアリングへ、開発ならtaskへ進む |
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

## 制作run前のself-modelヒアリング

制作runを始めるagentは、`tools/run.py`の前に次のwrapperを一度だけ実行する。これはagentの会話で
使うpacketをstdoutへ返すが、親repoはpacket、anchors、回答、entity idをstateやlogへ保存しない。
子CLIが旧pin・非零終了・timeout・不在でもwrapperはexit 0で`HEARING_UNAVAILABLE`を記録する。

~~~bash
.venv/bin/python tools/credential_free.py --state-root <external-state-root> -- \
  .venv/bin/python tools/self_hearing.py open \
  --run-id <run-id> --state-root <external-state-root> \
  --workspace-root <verified-child-workspace>
~~~

`outcome: offered`なら、packetの`intent`を全行（言い換え可・省略不可）、`why`、`anchors`（あれば
「前に『…』と話していたけど」の形）、`question`を一問だけ本人へ示す。テーマ・依頼文・slug・titleは
聞かない。本人が答えたらself-model-notesの `docs/acquisition-protocol.md` のannotated blockへ構造化し、
packetの`task_id`を使って次へ標準入力をそのまま渡す。下は`answer_format: event-block`用のtemplateで、`slot-values`の場合は子ownerの`docs/operations.md`の形式を同じheredocで渡す。

~~~bash
cat <<'ANNOTATED_BLOCK' | .venv/bin/python tools/credential_free.py \
  --state-root <external-state-root> -- .venv/bin/python tools/self_hearing.py answer <task-id> \
  --run-id <run-id> --state-root <external-state-root> \
  --workspace-root <verified-child-workspace> \
  --expected-queue-sha256 <packet-queue-sha256>
[event: hearing-response]
observed_at: "<observed RFC3339 timestamp>"
precision: minute
domain: creative-practice
social: null
uncertainty: null
control: null
fatigue: null
stress: null
trigger: null
observed_fact: <observed fact from response>
raw_voice: "<minimal response quote>"
appraisal: null
emotion: null
body: null
cognition: null
action: null
immediate_outcome: null
delayed_outcome: null
ANNOTATED_BLOCK
~~~

回答を一時ファイルに書かず、標準入力から直接渡す。placeholderは実回答・観測で置き換え、未取得は`null`、確認済み空は`[]`、評価不能は`unknown`とする。

断られた、「面倒」等の反応、無応答は次で記録する。どの結果でも、必ず同じrunの`tools/run.py`を実行し、
ヒアリング結果でrunを止めない。回答文はIssue、PR、commit、handoff、Drive、state、logへ書かない。

~~~bash
.venv/bin/python tools/credential_free.py --state-root <external-state-root> -- \
  .venv/bin/python tools/self_hearing.py skip <task-id> --reason skipped \
  --run-id <run-id> --state-root <external-state-root> \
  --workspace-root <verified-child-workspace>
~~~

制作runを行うsessionは、`config/issue-delivery-policy.yaml`のallowlisted repositoryへ書き込める資格情報を
持たないよう、`tools/credential_free.py`で起動する。PUBLIC の子repoにはtokenもloginも不要である。
run.jsonには従来どおり`git_write_credentials: absent|present|unknown`だけを記録し、`present`でもrunは止めない。
保存済みresume commandも同じ入口の`--`後へ渡す。

## テーマ未指定の制作計画

利用者はテーマ、作品slug、作品titleを指定しなくてよい。制作計画を作るよう依頼されたエージェントは、`--intent`、`--slug`、`--title`を付けずに次を実行する。

~~~bash
.venv/bin/python tools/credential_free.py --state-root <external-state-root> -- \
  .venv/bin/python tools/run.py \
  --workspace-root <verified-child-workspace> \
  --state-root <external-state-root>
~~~

この入口はpin済みsignalから本人の素材を一件選び、段階Aの要素を一件ずつ依頼する。答えを受理して同じrunを再開すると、中心の問いをResearch requestへ渡す。`theme_proposal.source: phase-a-elements`がこの経路の出所である。Research以降は宣言された調査と既存のhandoff・Production手順を継続する。旧候補空間・gate・ハッシュ選定は通常runで使わない。`--intent`は任意の素材順位づけです。使用回数が同じ素材の本文との語の重なりだけに使い、素材選定stateには生文を保存せずhashを保持します。素材が固定された後のresume commandにも生文を残しません。中心の問いはA7が作ります。

新規の通常runは`delivery-contract/v1`を生成してrun stateへ保存する。明示したProject checkoutを
`--project-root`または`AGENTIC_ART_PROJECT_ROOT`で選ぶ場合のtargetは`project-local`であり、
Projectの受取検証までが同じ通常経路に含まれる。保存済みlegacy contextは、契約を追加しても
既存の`project-committed`やinternalの意味を自動変更せず、同じrunの保存済み入力から再開する。

ResearchとProductionの`--research-root`/`--production-root`はmanifestから自動解決される。引数を省略した通常runでも、workspaceがmissingまたはcleanなpin driftだけなら、run state配下に`pinned-workspace`を新規作成し、全manifest entryを宣言済みのqualified commitへ展開してから同じrunを継続する。元のcheckout、manifest、remote refは変更しない。展開されたworkspaceには`manifest-pinned-workspace/v1`マーカーが付き、detached checkoutでも各commit、clean state、workspace所有証拠を再検証する。dirty、symlink、破損、権限不足、既存tree修復が必要な場合はBLOCKEDのまま停止する。

実Self Modelの profile root のパスを人に聞かない。未設定ならオーナーに次の設定コマンドを
本人の機械で1回実行してもらう。パスを会話・Issue・ログに書かない。設定は HOME を隔離する
`credential_free.py` の外で行う。

~~~bash
.venv/bin/python tools/profile_root_config.py set <絶対パス> --workspace-root <pin済みworkspace>
.venv/bin/python tools/profile_root_config.py show --redacted
# 設定を削除する場合のみ
.venv/bin/python tools/profile_root_config.py clear
~~~

解決順は `--profile-root` → `AGENTIC_ART_PROFILE_ROOT` → 利用者設定
`${XDG_CONFIG_HOME:-~/.config}/agentic-art/profile-root`。設定は絶対パス1行・0600であり、
Git配下やsymlinkを拒否して owner の `profile_root.py resolve` に検証を委ねる。
これは出力先の `--destinations-file` と別の入力で、profileの内容・同意はSelf Modelが検証する。
`credential_free.py` は HOME 差し替え前に設定を解決し、子へ環境変数と解決元を渡す。
stdout/stderr/run stateには `profile_root_source: argument|env|user-config|none` だけを記録する。
再開コマンドにもパスを保存しない。引数だけで開始した別sessionの再開は、オーナーが設定するか
環境変数を用意する。未設定の通常runは `BLOCKED / PROFILE_ROOT_REQUIRED`（exit 2）と上記の
remediationを返す。ヒアリングは従来のbest-effort契約どおり unavailable / exit 0 のままrunへ進む。
`--self-export` と offline経路では profile root を解決しない。既存profileが使えない場合に
repository内の自己モデルを採用したり、本人データを生成したりしない。

Productionまで進んだ後の再開では、`<state-root>/production/production/<slug>/`がrun-idをまたぐ同一プロジェクトの出力rootになる。各runの`<state-root>/<run-id>/`は実行ごとのcheckpointであり、`<state-root>/production-history.jsonl`はrun-idとproject-idだけを結ぶGit外の追記型メタデータ台帳である。既存プロジェクトを別run-idで続けるときは、初回と同じ`--slug`を明示する。handoffが変わった場合はProduction childのrevision受理へ進み、過去のexecution、quality、resultを新しいrunの空ディレクトリへリセットしない。

実repoを読めない環境では、合成signalだけを使うnetworkless確認として次を明示実行できる。

~~~bash
.venv/bin/python tools/credential_free.py --state-root <external-state-root> -- \
  .venv/bin/python tools/run.py \
  --offline-fixture \
  --state-root <external-state-root>
~~~

`--offline-fixture`は実child checkoutや外部サービスを読まず、checked-in fixtureのsource commitがmanifestとsnapshotのpinに一致する場合だけ進む。実repoの制作計画と取り違えないため、この結果のsourceはfixtureとして扱う。
この経路には`--profile-root`は不要で、指定されてもprofileを読み込まない。

実行開始時には、入口自身がmanifestの全repoについてread-only guardを行い、clean・通常branch・upstream有り・`observed_commit`一致を確認する。いずれかが満たされなければchild exportを実行せず、`BLOCKED`と解除条件を返す。既存checkoutを自動checkout、reset、fetch、pin更新してはならない。`<verified-child-workspace>`はこの検査とchild quality gateを通過したGit外workspaceを指定する。

したがって、別エージェントへ渡す最小指示は次の一文で足りる。

~~~text
このrepoのAGENTS.mdとREADME.mdに従い、テーマ・slug・titleを質問せず、pin済みworkspaceで`tools/credential_free.py`から`tools/run.py`を実行してPLAN_READYまで自律的に進める。
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
.venv/bin/python tools/credential_free.py --state-root <external-state-root> -- \
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

旧bundle互換APIで候補順位へ人のintentを反映する場合は `.venv/bin/python tools/credential_free.py --state-root <external-state-root> -- .venv/bin/python tools/run.py --intent` を使う。intentは
hard filterではなく、既存の安全・鮮度・根拠gateを通過した候補の順位付けだけに使う。
実行は `intent-rank/v1` のローカル決定的処理で、Unicode NFKC、casefold、空白圧縮を
行った文字bigramのmultiset weighted Jaccardを計算する。intentがない実行は既存の
`research-selection/v1` のままで、intent付き実行だけ `research-selection/v2` を出力する。

生intentは成果物・ログ・Gitへ保存しない。成果物には `intent_sha256`、algorithm名、
kind別score、total scoreだけを残す。CLIの実行結果とselectionのdigestが一致することを
確認し、空白だけのintentは入力エラーとして扱う。intent付き実行の再現確認は次の形で行う。

~~~bash
.venv/bin/python tools/credential_free.py --state-root <external-state-root> -- \
  .venv/bin/python tools/run.py --bundle <normalized-bundle.json> --project-id <project-id> \
  --seed-input <seed> --intent <intent-text> --output <run.json> --check
~~~

旧bundle互換APIと明示offline fixtureでは、候補空間からgate-passing候補を選び、Research requestの
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

`.venv/bin/python tools/credential_free.py --state-root <external-state-root> -- .venv/bin/python tools/run.py --cycle-context <external-context.json> --state-root <external-state-root>` は、AAK04 profileの隔離code/knowledge pin、全owner検索、Production正本検証、owner別保存・索引・再開を接続する。返された`next_action`をエージェントが処理し、`resume_command`で継続する。構成と状態の意味は [knowledge-cycle-runtime.md](knowledge-cycle-runtime.md) を読む。実エージェント受入とfake回帰を区別する。

## Requested delivery completion (Issue 217)

In a session launched through `tools/credential_free.py`, for a request to output to Project, run `.venv/bin/python tools/credential_free.py --state-root <external-state-root> -- .venv/bin/python tools/run.py --cycle-context <external-context.json> --project-root <project-checkout> --state-root <project-checkout>/.agentic-art/state --delivery-target project-local`. The context/profile must explicitly authorize public-catalog projection and select the Project root; an internal profile mismatch is an error, never silent SKIPPED success. The saved context records `project_root`, `delivery_contract: {contract_version: delivery-contract/v1, target: project-local}`, the repo-local `destination-resolution/v2` in run state, and the exact resume command. Legacy contexts keep their existing internal/committed-catalog semantics; no profile is silently migrated.

Continue the returned agent actions through Production plan generation, the closed automatic plan attestation, canonical projection, native Project lineage initialization and local receiver validation. The automatic plan lane performs Production's renderer, content, asset and provenance checks and records `publication_review.authority: AUTOMATIC_PLAN`; it never waits for human approval and never authorizes an external effect. Work/manual requests use the separate native review lane. If an automatic check fails, the agent receives the exact repair finding and resumes the same run. Run the native runtime bootstrap when a freshly built plan has not yet initialized its event log. Do not fabricate approvals. A human wait applies only to a separately requested work/manual publication and does not consume the no-progress retry budget.

`PLAN_READY` and batch `PASSED` describe stages, not final delivery. For the cycle entry, only `delivery_completion.status=COMPLETED` with the requested target is the overall completion report. Required knowledge saves, receiver hashes and creator/origin must verify. A local receipt does not prove Git commit or remote synchronization. GitHub Actions, account billing and a built-in provider are not required. Existing AAK internal evidence is not public-catalog acceptance.

## AP-06 external-agent acceptance

AP-06 evidence is an external, metadata-only manifest. Run
`.venv/bin/python tools/verify_autonomous_plan_acceptance.py --manifest <absolute-evidence-manifest.json>`
with an absolute manifest outside the repository. The verifier checks the closed
`autonomous-plan-acceptance/v1` schema, fixed code and knowledge refs, every
referenced file hash, owner revalidation, delivery completion, operation trace,
provider execution record, and separate second-run knowledge content checks.
The manifest's success fields are compared with those observations; they are not
accepted as proof on their own. A model probe or synthetic/fake run is not a
six-run acceptance. If a compliant provider-backed external-agent lane is
unavailable, record `status=NOT_RUN` and `acceptance.ac11=NOT_RUN` with the
observed blocker and resume command. Do not close the Issue or promote AP-07.

## Project checkoutだけで動かす（output-destinations/v2）

clone/fork利用者は、明示した`agentic-art-project` checkoutを次のように指定できます。

```bash
.venv/bin/python tools/credential_free.py --state-root <external-state-root> -- \
  .venv/bin/python tools/run.py --project-root /path/to/agentic-art-project \
  --workspace-root /path/to/pinned-workspace
```

または`AGENTIC_ART_PROJECT_ROOT=/path/to/agentic-art-project`を設定します。v2は`.agentic-art/state`、`.agentic-art/internal`、`.agentic-art/staging`を導出し、公開rootはProject checkout自身です。既存の`--destinations-file`や個別rootと同時に指定すると`AMBIGUOUS_DESTINATION_MODE`で書込み前に停止します。Projectのvalidator、ignore、tracked-private、symlink、tracked変更を先に検査し、失敗時にworkspaceを作成しません。v1のGit外profile方式はそのまま利用できます。

## 要素の依頼への答え方（Issue #278）

要素ハーネスは、短い指示と、その答えに必要な材料だけを一件ずつ渡します。
答える人・エージェント・ローカルモデルは、一つの値だけを返してください。
次の要素へ進めるかどうかはプログラムが確認します。現在はデモ専用の入口で、
このデモ入口は合成の短い列です。通常の制作runのテーマ生成は下の段階Aへ置き換えています。Research以降の段階B〜Dは子ownerの既存経路を使います。

まず、Git checkoutの外に専用の保存場所を作り、同じrun IDで始めます。
以下の`EXTERNAL_STATE_ROOT`は、その保存場所の絶対pathを表します。

~~~bash
.venv/bin/python tools/credential_free.py --state-root "$EXTERNAL_STATE_ROOT" -- \
  .venv/bin/python tools/run.py --element-demo \
  --run-id element-demo --state-root "$EXTERNAL_STATE_ROOT"
~~~

出力の`next_action.kind`が`element`なら、`next_action.request`を読みます。
`instruction`が指示、`inputs`が材料、`answer_format`が答えの形です。
`text`は指定文字数以内の文字列、`choice`は選択肢そのものを一つ、
`boolean_with_reason`は`{"answer": true, "reason": "理由を一文。"}`
（否定なら`false`）、`url`はHTTP(S) URLの文字列です。
答えの`run_id`、`element_id`、`attempt`は依頼からそのまま写します。

例えばデモの最初の依頼への答えは、次のように標準入力で渡します。

~~~bash
.venv/bin/python tools/credential_free.py --state-root "$EXTERNAL_STATE_ROOT" -- \
  .venv/bin/python tools/element.py answer \
  --run-id element-demo --state-root "$EXTERNAL_STATE_ROOT" <<'JSON'
{"contract_version":"element-answer/v1","run_id":"element-demo","element_id":"demo.operation","attempt":1,"value":"先送り"}
JSON
~~~

通れば次の依頼が返ります。落ちれば同じ要素の`attempt`が増え、
`previous_failure`に検査名と短い修正理由が返ります。その要素だけを答え直してください。
空の文字列・空白だけの値や理由は受理されません。既定では五回目の答えも検査に
落ちると`BLOCKED`（exit 2）になり、要素名と最後の失敗検査を返します。
五回目に通れば進めます。保存した答えと完全に同じ答えの再送は、試行数を増やさず
現在の状態を返します（通常はexit 0、`BLOCKED`ならexit 2）。
値の違う古いattemptの答えや別のrunの答え、形式の壊れたJSONは
入力エラー（exit 1）で、保存済みの依頼も試行数も変えません。

中断後は最初と同じ入口で`run.py`の`--element-demo`を再実行すれば再開できます。
`tools/element.py next`でも次の依頼を取得でき、`status`でも保存済みの進行を確認できます。
どちらも`--run-id`と`--state-root`を指定し、同じ資格情報なしの入口で実行します。
再開では材料・登録定義を読み直さず、保存済み依頼のbyteを再現します。
`COMPLETED`はこのデモ列の完了です。制作プランやProject納品の完了を表しません。
BLOCKEDになったrunを書き換えて続けず、原因を直した定義で新しいrunを開始してください。

### 検索の依頼と根拠の抜き書き

`request.contract_version`が`search-request/v1`なら、`query`で検索し、
上位から`limit`件までのURL・題名・取得本文を返してください。
答えは`search-answer/v1`で、同じ識別子とattempt、
`results: [{"url": "…", "title": "…", "body": "取得した本文そのまま"}]`を持ちます。
少なくとも一件必要です。返した本文をハーネスがhash化してrunの台帳に固定します。
根拠の抜き書きはその本文の連続した部分と完全一致する必要があり、空白の変更も通りません。
URLの実在検査はこの取得台帳との照合です。ハーネス自身によるウェブの独立確認ではありません。
同じURLへ異なる本文を返して既存の根拠を上書きすることはできません。

### ローカルの答え手で試す

`tools/element_answerer.py --fake`は依頼JSON一件をstdinで読み、
デモ用の決定的な答えJSON一件をstdoutへ返します。
この答えを上と同じ`element.py answer`へ渡せば、同じ検査を受けられます。
実際のローカルモデルでは`--config <absolute-config-file>`を使います。
[設定例](../config/element-answerer.example.yaml)の`command`を自分のモデル用ラッパーの
引数列に替えてください。ラッパーはstdinに依頼一件、stdoutに答え一件を出す必要があります。
ログはstderrへ出します。shell式は使わず、呼び出し方とタイムアウトだけを設定で指定します。
adapter自体も`credential_free.py`経由で起動します。モデルの起動失敗やタイムアウトでは
答えを受理せず、保存された同じ依頼を再度使えます。

### 要素を登録する開発者向け

`config/elements/*.yaml`へ`element-sequence/v1`の列を宣言すると、
`tools/validate.py --check`がschema・重複ID・入力参照順・検査名を検証します。
`element.py next --registry <file>`で新規runに選択できます（保存済みrunの定義は変更しません）。
`max_attempts`はデモの既定値5から変更できます。
入力は`{literal: 値}`、`{answer: 先に受理された要素ID}`、`{context: キー}`、
または`{search_result: {element_id: 検索ID, index: 0, field: url}}`で組み立てます。
検索のfieldは`url`・`title`・`body`です。contextはプログラムAPIで渡す固定材料で、
必要なキーだけが依頼へ入ります。入力の組み立て失敗は空値で埋めず`input_build`で止まり、
すでに受理した答えを保持します。指示は一〜二文、最大400文字、組み立てたinputsは
最大4096 UTF-8 byteに収め、長い原文全体を一度にモデルへ渡さないでください。

検査は以下の文字列を宣言します。すべてプログラムによる判定です。

| 検査 | 意味 |
| --- | --- |
| `non_empty` | 空白だけの値も拒否（宣言なしでも必須） |
| `min_chars:N` / `max_chars:N` | Unicode文字数の下限・上限 |
| `ends_with_question` | 末尾が`?`か`？` |
| `contains_terms:a,b` | inputsキーの文字列、または文字通りの語を全部含む |
| `forbidden:a,b` | 指定語を一つも含まない |
| `one_of:a,b` | 列挙値のどれかと完全一致 |
| `reference_exists:key` | inputsのkeyが指すIDリスト・辞書に値が存在 |
| `url_shape` / `url_in_ledger` | HTTP(S) URLの形 / 取得台帳に存在 |
| `exact_excerpt:key` | inputsのkeyのURLが指す台帳本文から完全一致の抜き書き |
| `not_similar:0.8` | 既出の受理済み答えとの類似度が指定値未満 |

類似度はNFKC・大文字小文字・連続空白を正規化した文字bigramのJaccard比です。
閾値と同じ比も拒否します。文字数と引用は正規化せず元の文字列で判定します。
booleanの検査は理由文へ適用します。不明な検査や入力参照は黙って無視しません。
材料・答え・取得本文の保存先は外部stateのみで、親のGit証跡へ転記しません。


## 段階Aの要素

通常のテーマ未指定runは、同意済みexportの全content項目から空でない素材を一件選びます。
consent/scope/opaque raw locatorは素材ではありません。同じ外部state rootのA3を受理済みのrunで
使用回数の少ない素材を優先し、同率なら項目・本文・signal ID順に選びます。
同じrunの再開では入力・素材・照合順を固定します。

`next_action.kind: element`なら、共通ハーネスの依頼を読んで一つの値を返します。
A3は短い操作語一つ、A5は素材と参照一件ごとのbooleanと理由一文、A7は三つの素材を
含む120字以内の問い一文です。各依頼のrun ID・element ID・attemptをそのまま答えへ写します。
以下は合成例で、実行では返された識別子と自分の答えに置き換えます。

~~~bash
.venv/bin/python tools/credential_free.py --state-root "$EXTERNAL_STATE_ROOT" -- \
  .venv/bin/python tools/element.py answer \
  --run-id "$RUN_ID" --state-root "$EXTERNAL_STATE_ROOT" <<'JSON'
{"contract_version":"element-answer/v1","run_id":"<returned-run-id>","element_id":"A3.operation","attempt":1,"value":"先送り"}
JSON
~~~

回答後は最初の`run.py`または返された`resume_command`を同じcredential-free入口で実行します。
A5の「はい」が足りない領域は次の5件へ照合順に広げ、既に受理した答えは捨てません。
全件で接続がない場合はA6でBLOCKEDとなり、否定理由を保持します。
A7受理後の要素列`COMPLETED`はテーマ段階の完了で、制作・納品の完了ではありません。

RRの`creative_question`はA7の答えそのものです。`requests/phase-a-provenance.json`は
素材・選んだsignal・それぞれのA5理由を構造化して保持し、既存RRの
`source.artifact_uri`と`references`のhash付きURNから参照します。子の閉じたRR schemaへ
独自fieldを追加しません。両artifactはcreate-onlyで、再開時も同じbyteを再利用します。
回答待ちの`run.json`は依頼本文・A3/A5の答えを保存せず、保護された要素stateに同意済み派生素材を保持します。受理した中心の問いはテーマ出力として保存します。
明示offline fixtureと旧bundle APIは互換経路であり、実段階Aの完了証拠ではありません。

### privateな子ヒアリング

pin済みSelf Modelが`growth_tasks.py element next|answer`を持つ場合、`self_hearing.py`のopen操作が
その依頼を`private: true`としてstdoutへ中継します。旧pinは従来のhearingへ戻ります。
private依頼は`element.py`の永続Engineへ渡さず、子ownerへ直接答えます。

~~~bash
.venv/bin/python tools/credential_free.py --state-root "$EXTERNAL_STATE_ROOT" -- \
  .venv/bin/python tools/self_hearing.py answer \
  --run-id "$RUN_ID" --state-root "$EXTERNAL_STATE_ROOT" \
  --workspace-root "$WORKSPACE_ROOT" <<'JSON'
{"contract_version":"element-answer/v1","run_id":"<child-run-id>","element_id":"<child-element-id>","attempt":1,"value":"<one-owner-answer>"}
JSON
~~~

親が保存するのはprivate/status/識別子/attemptだけです。本人のEvent、質問、packet、回答本文、
子の診断文は親のstate・log・Issue・PR・handoffに保存しません。ヒアリングのoutcomeに
かかわらず制作runを継続します。本人の実profileで意味のある問いかを確認するオーナー判定は、
合成テスト・要素形式検査・PLAN_READYで代用しません。

追加検査 `one_sentence` は改行・複数文を拒否します。
`contains_source_terms:self,signal` は各入力本文と理由の共通content語を要求します。
語はLatin単語・日本語2/3字shingle（単独のcontent文字も可）で決定的に抽出し、汎用の接続語を除外します。
`not_similar_to:material` は入力素材と語が類似しすぎる場合に拒否します（bigram Jaccard 0.8）。


Project repo-local契約で始めたrunの要素回答は、入口側の外部rootを維持し、
`element.py answer --run-id <run> --project-root <selected-project-checkout>`へ渡します。
`--state-root`と`--project-root`は同時指定せず、Project validatorとGit境界を再検証して
同じrepo-local rootを導出します。パスの形だけでProject保存を許可しません。


privateヒアリングで断り・無応答を受けた場合、同じ入口から
`self_hearing.py`のskip操作（reasonはskippedまたはno-response）（同じrun/state/workspace指定、task ID不要）を
呼びます。親は進行metadataをSKIPPEDにし、子の未完了要素・本人の記録は削除しません。
制作runはどのoutcomeでも続けます。

Researchの受入契約はfile URI・絶対パスを拒否するため、sidecarはRRの隣にcreate-onlyで保存し、名前とhash付きURNで結びます。研究を担うエージェントはその出所artifactも参照します。

通常の段階Aで返すtheme_proposalのmodeは`ELEMENT_INFERRED`です。明示offline fixtureでintent未指定の場合は、従来の`REPOSITORY_DERIVED`を維持します。

通常runは一つの素材・中心の問いを扱うため、`--limit`は1です。複数テーマは同じstate rootに独立run IDで起動します。旧bundle APIの複数選定は維持します。

実在する公開参照URLのpath内に`ark:/`のような表記がある場合、native receiverが絶対パスと
誤認するため、当該参照だけhash URNにします。元URLとRRのURNの対応はsidecarの
`reference_aliases`に保持し、権利状態は変えません。query/fragment付きURLはこの変換をせず、
既存のnative検査へ渡します。素材固定後は任意intentの生文をrun reportにも残しません。
