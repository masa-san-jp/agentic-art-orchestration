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
responseのCOMPLETEDと全check PASSだけが`PLAN_READY`へ進み、同じrun-idの再実行はaccepted resultを
再利用する。human gate対象の要求は実行せず`BLOCKED_HUMAN`、外部境界違反は`BLOCKED_EXTERNAL`、
同一stage・error fingerprintの失敗は3回まで再試行して4回目を`FAILED_RETRY_EXHAUSTED`とする。
会話全文、credential、PRIVATE_RAW、RESTRICTED、worker stdout/stderrはstateへ保存しない。
