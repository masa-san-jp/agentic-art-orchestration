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

全4repoを無条件に全文読込しない。task context packは次だけを含める。

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
