# Incident and recovery runbook

障害時の目的は、失敗を正常値へ変換せず、観測事実・安全な終端状態・復旧条件を残して再開可能にすることである。最初に [operator-runbook.md](operator-runbook.md) の安全境界を確認する。

## 共通フロー

~~~text
observe → classify → checkpoint → terminal state → repair/approval → revalidate → resume
~~~

1. `git status --short`、`tools/workspace.py guard --json`、`execution/state.yaml`、直近のquality gate出力を読む。
2. 実行中task、repo ID、source commit、branch、attempt、lease、checkpointを記録する。
3. 自動修復できるかを分類する。破壊操作、外部公開、同意拡張、merge、releaseが必要ならhuman gateへ渡す。
4. 失敗をqueue/state/handoffへ記録し、修復前に成功したrepoや証拠を巻き戻さない。
5. 修復後は同じacceptanceと全required checksを再実行する。

## 事象別対応

| 事象 | 終端状態 | してよいこと | してはいけないこと | 復旧条件 |
| --- | --- | --- | --- | --- |
| dirty checkout | `BLOCKED_EXTERNAL` | statusとguardのreason、対象path、source commitを記録 | reset、stash、commit、pullを代理実行 | ownerが意図した変更を確認しclean化した後にguard pass |
| detached HEAD | `BLOCKED_EXTERNAL` | branch/HEADを記録し人間へ返す | checkout、branch移動、reset | ownerが正しいbranchを選びguard pass |
| unpushed / behind / diverged | `BLOCKED_EXTERNAL` | ahead/behindとupstreamを記録 | force push、merge、rebase、hard reset | 子repo ownerが履歴方針を決め、再取得後にguard pass |
| remote不一致・repo欠落 | `BLOCKED_EXTERNAL` | manifest path、observed remote、reasonを記録 | pathを削除して再clone | remote/pathを人間が確認し、安全なinitを再実行 |
| signal major mismatch | `NEEDS_REPAIR` | consumer errorとexpected/actual majorを記録 | v2をv1として解釈 | 子adapterでv1へ適合しvalidatorとconsumerがpass |
| marketing stale / freshness expired | `COMPLETE_WITH_GAPS` | stale status、revalidate期限、制約を成果物へ残す | current/verifiedへ昇格、削除、推測 | owning adapterで再検証し、fresh signalで再実行 |
| self consent violation | `BLOCKED_HUMAN` | finding code/location/remediationだけを記録 | raw voiceや同意範囲外データをコピー | approved-derived-onlyの明示同意と再検証 |
| art evidence不足 | `COMPLETE_WITH_GAPS` または `NEEDS_REPAIR` | unknown、evidence locator不足、要求を記録 | relationをconfirmedへ昇格 | child canonical sourceで根拠を補いadapterを再実行 |
| child quality gate failure | `NEEDS_REPAIR` | gate status、exit code、redacted output hashを記録 | gate削除、skip、失敗testの変更 | owner repoで修復しmanifest gateがpass |
| secret / forbidden data | `BLOCKED_HUMAN` | sanitized findingとlocation/remediationだけを記録 | secret/raw値をstate、log、PRへ転載 | 値を除去し必要ならrotation、security boundaryがpass |
| lease expiry | `READY` | checkpoint、decision、execution IDを保持 | 同じ作業を新規executionとして重複開始 | expiry後に同じexecution IDで再acquireし再開 |
| worker process kill | `READY` | leaseを解放しcheckpointとevidenceを保持 | commit/PR/evidenceを二重作成 | checkpointを読み同じexecution IDでidempotentに再開 |
| Project API unavailable | `LOCAL_ONLY` | local queueを正本として実行継続、操作空を記録 | remote APIを正本扱い、認証情報を保存 | API復旧後にmetadata-only syncを再計画 |

## leaseとcheckpointの回復

runtime state transitionは`tools/runtime.py`の関数を使い、元stateをdeep copyした結果を検証してから保存する。

- `acquire_lease`: `READY`を`IN_PROGRESS`へし、owner、expires_at、execution IDを設定する。
- `save_checkpoint`: 次の安全な操作、decision、last resultを記録する。
- `expire_lease`または`release_lease`: leaseをavailableにし、作業を`READY`へ戻す。checkpointは破棄しない。
- `record_evidence`: commit、PR、test、pathを重複追加しない。
- `complete_work_item`: passed checkpointとcommit/test evidenceが揃った場合だけ`DONE`にする。
- retry budgetを使い切った同一失敗は`BLOCKED`とし、無限retryしない。

再開時は、まず`execution_id`、decision、evidenceの重複を確認する。side effectがどこまで済んだか不明なら新しいcommit/PRを作らず、human gateへ渡す。

## BLOCKEDにする停止条件

次の場合だけ自動実装を止める。

- 子repoのIssue SSOTがadapterで両立しない。
- 機微情報の外部送信、同意拡張、公開範囲変更が必要。
- merge、release、強制push、branch削除など不可逆な操作が必要。
- データ損失や不可逆schema migrationが疑われる。
- 認証・権限不足でread-only代替も受入条件を満たさない。
- acceptanceが保守的既定値でも両立しない。

BLOCKED記録には、観測事実、選択肢、推奨、影響、解除条件を含める。質問だけを残さない。

## インシデント後の検証

~~~bash
.venv/bin/python tools/workspace.py guard --offline-fixture --json
.venv/bin/python tools/validate.py --check
.venv/bin/python tools/status.py --check --offline-fixture
.venv/bin/python tools/audit.py --check --offline-fixture
.venv/bin/python tools/security.py --offline-fixture
.venv/bin/python -m unittest discover -s tests -v
git diff --check
~~~

変更子repoがある場合は、manifest記載のchild quality gateをそのrepo rootで別途実行する。失敗中のgateを親testの成功で相殺しない。
