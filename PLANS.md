# Execution Plans

ExecPlanは、複数repo・複数セッションにまたがる変更を、会話履歴なしの別エージェントが引き継げる自己完結型計画である。

## 使用条件

- 2つ以上のrepoまたは3ファイル以上を変更する。
- schema、CLI、状態機械、adapter、migration、外部連携を変更する。
- 1セッションで終わらない可能性がある。
- 失敗時に複数repoの回復手順が必要になる。

## 必須セクション

- Purpose / Big Picture
- Progress
- Surprises & Discoveries
- Decision Log
- Outcomes & Retrospective
- Context and Orientation
- Plan of Work
- Concrete Steps
- Validation and Acceptance
- Idempotence and Recovery
- Interfaces and Dependencies

## 実行規則

1. 計画全体と各子repoの規則を読む。
2. Progress、queue、state、実際のGit状態を照合する。
3. 次の未完了milestoneだけを実装する。
4. repo単位で検証・commitし、親の記録commitと混ぜない。
5. 発見と決定を即時に計画へ戻す。
6. 受入条件を満たすまで完了にしない。
7. 終了時にrepo、branch、SHA、dirty状態、次の1commandを残す。
