# Agentic Art Orchestration

Self Model × Art History × Marketing Trends → Agentic Art Research を、独立した4リポジトリの正本性を壊さず、単一ワークスペースから横断運用するメタ・リポジトリ。

## 現在地

- システム設計: [設計仕様書](docs/20260811-agentic-art-orchestration-system-design-specification.md)
- 構想・要求の起点: [先行リポジトリ設計仕様書](docs/20260811-agentic-art-orchestration-repository-design-specification.md)
- 完成実行計画: [実行計画](docs/20260811-agentic-art-orchestration-repository-execution-plan.md)
- エージェント規則: [AGENTS.md](AGENTS.md)
- 機械可読タスクキュー: [task-queue.yaml](execution/task-queue.yaml)
- 統合対象の正本: [repositories.yaml](config/repositories.yaml)

初期ブートストラップはM0を完了し、M1の MANIFEST-001 から実装を開始できる状態にする。v1.0の完成とは、4リポジトリを再現可能に展開し、互換性・鮮度・依存関係・品質ゲートを検査し、入力シグナルから agentic-art-research の成果物まで出典commitを逆引きできることをいう。

## 統合対象

- [self-model-notes](https://github.com/masa-san-jp/self-model-notes) — Self Model入力KB
- [art-history-notes](https://github.com/masa-san-jp/art-history-notes) — 芸術史入力KB
- [marketing-trends-notes](https://github.com/masa-san-jp/marketing-trends-notes) — マーケティング変化入力KB
- [agentic-art-research](https://github.com/masa-san-jp/agentic-art-research) — 制作リサーチ実行・成果物repo

## 重要な境界

- 子repoのデータ・schema・Issueを親へ複製しない。
- 子の内部形式を共通化せず、境界で normalized research signals に翻訳する。
- 親は横断契約、workspace再現、依存DAG、実行状態、監査結果だけを正本として持つ。
- 子の変更は子repoのbranch/PRで行い、親のcommitへ混ぜない。
- repos/ はローカル生成物でありGit管理しない。

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
schemas/      manifest・signal・work item・run stateの契約
docs/         設計、実行計画、横断契約、実行ガイド
execution/    task queue、状態、判断、引継ぎ
tools/        workspace、検証、status、audit、dispatcher
tests/        offline fixtureと障害試験
data/         生成されたstatus・audit・trace。手編集禁止
repos/        ローカルの子repo展開先。Git管理外
~~~
