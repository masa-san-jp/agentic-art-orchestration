# Agentic Art Orchestration

Self Model × Art History × Marketing Trends → Agentic Art Research → Agentic Art Production を、独立したリポジトリの正本性を壊さず横断利用し、会話から継続改善するためのメタ・リポジトリ。

## 現在地

- システム設計: [設計仕様書](docs/20260811-agentic-art-orchestration-system-design-specification.md)
- 構想・要求の起点: [先行リポジトリ設計仕様書](docs/20260811-agentic-art-orchestration-repository-design-specification.md)
- 完成実行計画: [実行計画](docs/20260811-agentic-art-orchestration-repository-execution-plan.md)
- エージェント規則: [AGENTS.md](AGENTS.md)
- 運用runbook: [operator-runbook.md](docs/operator-runbook.md)
- 障害・復旧runbook: [incident-runbook.md](docs/incident-runbook.md)
- v1.1 interaction/improvement runbook: [interaction-improvement-runbook.md](docs/interaction-improvement-runbook.md)
- 初期Codex / Claude Code UI: [agent-ui-runbook.md](docs/agent-ui-runbook.md)
- 入力KB→Research開始 / pin採用: [input-pipeline-runbook.md](docs/input-pipeline-runbook.md)
- 機械可読タスクキュー: [task-queue.yaml](execution/task-queue.yaml)
- 統合対象の正本: [repositories.yaml](config/repositories.yaml)

初期ブートストラップからM10のv1.2.0 qualification、M11のProduction追加、v1.2.1 five-repository baseline、v1.3.0 Production exchangeのqualification/releaseまでを完了した。v1.4.0ではCodex/Claude Code向けstartup、retrieval、Drive/Issueのcreate-only境界、interaction E2E、offline aggregate、専用GitHub sandbox evidenceまでを実装・検証済みである。v1.4.0総合qualificationは、検証済みmanifest-pinned workspaceとlive evidenceを同一runで再確認するまで未完了とし、releaseはhuman gateに残す。v1.0は、4つのcore repoと追加repoを再現可能に展開し、互換性・鮮度・依存関係・品質ゲート・出典commitを検査するcontrol-plane基盤である。

親Issue #2と`agentic-art-research` Issue #2の半決定論的な制作研究実行は、v1.1のrelease acceptanceから切り離し、v1.2で実装・qualification済みである。v1.2はrule engine、再現可能なcandidate生成、seeded selection、specificity/genericness gate、provenance、固定commit child quality gateを含む。qualificationはread-onlyで実施し、merge・tag・GitHub Releaseはhuman gateを経て公開済みである。

v1.1では、利用エージェントを人間の会話型ユーザーインターフェースとし、追加可能なrepository-aware retrieval、Google Driveへの追記型成果物保存、明示・推定feedbackのIssue化、自律的なissue-to-draft-PR改善、ユーザー応答と分離した非同期監査を追加した。既存4repoはcore setとして維持し、`agentic-art-production`を追加runtimeとしてmanifestへappendした。追加repoにも同一repo Issue SSOT、明示的な境界契約、snapshot、個別品質ゲートを要求する。

次の実装順は、v1.4.0総合qualificationの再実行、資格記録のproject status化、目的ギャップの実装である。初期UIは、初期改善をIssue作成で止め、Issue後の実装・PR・merge・releaseを自動開始しない。次の親taskは `PROJECT-STATUS-001` である。

~~~text
User <-> Codex / Claude Code -> Child Knowledge Repositories
                    |          -> Append-only Google Drive Artifacts
                    +--------- -> Feedback -> create-only GitHub Issue

Startup update check + audit -> findings / Issue candidate
~~~

## 統合対象

- [self-model-notes](https://github.com/masa-san-jp/self-model-notes) — Self Model入力KB
- [art-history-notes](https://github.com/masa-san-jp/art-history-notes) — 芸術史入力KB
- [marketing-trends-notes](https://github.com/masa-san-jp/marketing-trends-notes) — マーケティング変化入力KB
- [agentic-art-research](https://github.com/masa-san-jp/agentic-art-research) — 制作リサーチ実行・成果物repo
- [agentic-art-production](https://github.com/masa-san-jp/agentic-art-production) — 制作引き渡し受領、制作実行、結果還流repo（要件SSOT: Issue #10）

## 重要な境界

- 子repoのデータ・schema・Issueを親へ複製しない。
- 子の内部形式を共通化せず、境界で normalized research signals に翻訳する。
- 親は横断契約、workspace再現、依存DAG、実行状態、監査結果だけを正本として持つ。
- 子の変更は子repoのbranch/PRで行い、親のcommitへ混ぜない。
- repos/ はローカル生成物でありGit管理しない。
- 会話全文とDrive成果物本文を親Gitへ保存せず、opaque参照・hash・source commitだけを保持する。
- Drive成果物は上書き・削除せず、修正版を新規作成してderived_from/supersedesで結ぶ。
- 推定された不満や欲求はfeedback仮説であり、明示要求やユーザー属性として扱わない。
- 改善・監査は会話応答と非同期に進め、merge・release・公開・同意拡張は人間gateを維持する。
- 起動時は全manifest repoのremote headをread-only確認し、最後のqualified pinと差分を区別する。自動checkout、pin更新、子repo変更は行わない。
- 初期UIは既定でoffline planを実行し、外部CREATEはstartupがREADYで明示確認された単一laneに限定する。DriveとIssueのlive CREATEを同時に実行しない。

## エージェントの開始手順

1. AGENTS.mdを読む。
2. システム設計と実行計画を全文読む。
3. task-queue.yamlから、依存がDONEの最小IDのREADYタスクを選ぶ。
4. 受入条件と検証コマンドを満たすまで実装する。
5. queue、state、handoff、実行計画を更新する。
6. 定義済み停止条件以外では、人間へ次工程を質問せず次のREADYタスクへ進む。

## ブートストラップ検証

~~~bash
python3 -m pip install -r requirements-dev.txt
python3 tools/validate.py --check
python3 -m unittest discover -s tests -v
~~~

## 構造

~~~text
config/       リポジトリ一覧、横断ポリシー、品質ゲート
schemas/      manifest・signal・work item・retrieval・interaction・artifact・feedback・routing・improvement・agent UI・E2E・async auditの契約
docs/         設計、実行計画、横断契約、実行ガイド
execution/    task queue、状態、判断、引継ぎ
tools/        workspace、検証、status、audit、retrieval、agent UI、issue router、improvement、interaction E2E、async auditor、dispatcher
tests/        offline fixtureと障害試験
data/         生成されたstatus・audit・retrieval-result・feedback-routing・improvement-loop・interaction-e2e・async-audit・trace。手編集禁止
repos/        ローカルの子repo展開先。Git管理外
~~~
