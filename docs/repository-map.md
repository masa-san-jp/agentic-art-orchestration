# Agentic Artの8リポジトリと利用方法

このページは、Agentic Artを初めて見る人が、8リポジトリの役割、データの流れ、最初に開く入口を理解するための人間向けの案内です。機械的なrepo定義、各repoのschema、実行stateの正本ではありません。機械契約は [`config/repositories.yaml`](../config/repositories.yaml)、公開Projectとの関係は [`config/repository-relationships.yaml`](../config/repository-relationships.yaml)、8 ownerのread/write境界は [`config/knowledge-owners.yaml`](../config/knowledge-owners.yaml) を参照してください。

## 全体の流れ

```text
self-model-notes ─┐
art-history-notes ├─ normalized research signal ─┐
marketing-trends ┘                               │
                                                 ▼
viewer-response-notes ─ aggregate feedback ─→ agentic-art-orchestration
                                                 │
                                                 ▼
                                       agentic-art-research
                                                 │ production-handoff
                                                 ▼
                                       agentic-art-production
                                                 │ canonical plan
                                                 ▼
                                       agentic-art-project
                                           公開カタログ
```

3つの入力ナレッジrepoと鑑賞者反応repoは、それぞれの正本と検証規則を保ったまま、境界契約に従うsignalまたはfeedbackとしてOrchestrationへ渡ります。Orchestrationは各repoの内容を親へコピーせず、固定したsource commit、hash、locator、実行stateを使ってResearchとProductionを進めます。Researchは調査、仮説、要件、判断を作り、Productionへhandoffします。Productionの検証済みcanonical planだけが、Orchestrationのexport-only projectionを経てProjectの公開カタログへ届きます。Projectは入力knowledgeや実行stateを書き戻しません。

鑑賞者反応は、公開作品から得られた集計可能な根拠を次回のResearchへ戻すフィードバックです。生の会話、個人識別情報、心理推定、credential、内部logはこの流れに含めません。

## 8リポジトリの役割

| リポジトリ | 役割 | 主な受け渡し |
|---|---|---|
| [`agentic-art-orchestration`](https://github.com/masa-san-jp/agentic-art-orchestration) | 全体のcontrol plane。workspace、pin、retrieval、実行、再開、検証を管理する | 各ownerから読み、Research・Productionを実行し、Projectへ公開projectionする |
| [`self-model-notes`](https://github.com/masa-san-jp/self-model-notes) | 本人の明示的・同意済みの自己モデルを管理する | 承認済みのnormalized research signalをOrchestration/Researchへ渡す |
| [`art-history-notes`](https://github.com/masa-san-jp/art-history-notes) | 美術史上の作品、技法、関係、source、evidenceを管理する | 根拠付きのnormalized research signalをOrchestration/Researchへ渡す |
| [`marketing-trends-notes`](https://github.com/masa-san-jp/marketing-trends-notes) | 社会・市場の変化、practice、鮮度、counterevidenceを管理する | 鮮度と再検証状態付きのnormalized research signalを渡す |
| [`agentic-art-research`](https://github.com/masa-san-jp/agentic-art-research) | 入力knowledgeとfeedbackを使い、調査、仮説、要件、判断、evidenceを作る | `production-handoff`をProductionへ渡し、研究知識を次回へ残す |
| [`agentic-art-production`](https://github.com/masa-san-jp/agentic-art-production) | handoffを受け、制作プラン、試作、実行、品質結果、制作結果を管理する | 検証済みcanonical planとproduction resultをOrchestrationへ返す |
| [`viewer-response-notes`](https://github.com/masa-san-jp/viewer-response-notes) | 作品と展示条件に対する鑑賞者反応を集計し、保守的なassessmentを管理する | 個人の生データを公開せず、次回Researchで使えるfeedback signalを渡す |
| [`agentic-art-project`](https://github.com/masa-san-jp/agentic-art-project) | 公開された制作プラン、作品、制作記録を読むためのcatalog | Orchestrationから検証済みrecordを`export-only`で受け取る。知識ownerとしてはread-only |

`agentic-art-project`が [`config/repositories.yaml`](../config/repositories.yaml) の入力pin一覧に含まれないのは欠落ではありません。Projectは入力knowledgeを読むmanifest repoではなく、公開projectionの受信先です。その関係は [`config/repository-relationships.yaml`](../config/repository-relationships.yaml) に記録されています。

## 利用者の入口

利用者は通常、8リポジトリを順番に手操作しません。目的に合う入口からOrchestrationが必要なownerを読みます。

| 目的 | 最初に開く場所 | その後 |
|---|---|---|
| 制作プランを作る | [READMEの利用者向け最短ルート](../README.md#利用者向けの最短ルート)、[`docs/agent-runtime-guide.md`](agent-runtime-guide.md) | 固定済みworkspaceで`tools/run.py`を実行し、ResearchからProductionまで進める |
| テーマを指定せず制作を始める | [`docs/agent-runtime-guide.md#テーマ未指定の制作計画`](agent-runtime-guide.md#テーマ未指定の制作計画) | pin済みsignalから候補を選び、外部エージェントが`next_action`と`resume_command`を処理する |
| 入力knowledgeを更新する | 対象owner repoのREADME、Issue、PR | ownerのvalidatorと品質ゲートを通し、次回のretrievalで参照する |
| ResearchやProductionの内容を確認する | [`agentic-art-research`](https://github.com/masa-san-jp/agentic-art-research)、[`agentic-art-production`](https://github.com/masa-san-jp/agentic-art-production) | 各repoのREADMEとIssue SSOTを正本として読む。親へ内部schemaをコピーしない |
| 公開プランや作品を見る | [`agentic-art-project`](https://github.com/masa-san-jp/agentic-art-project) の[`plans/`](https://github.com/masa-san-jp/agentic-art-project/tree/main/plans) と[`works/`](https://github.com/masa-san-jp/agentic-art-project/tree/main/works) | 公開recordのmetadata、plan、制作記録を読む |
| 鑑賞者反応を次の制作へ戻す | [`viewer-response-notes`](https://github.com/masa-san-jp/viewer-response-notes) | 集計・assessmentをownerの規則で保存し、次回Researchで再検証する |
| 公開projectionを行う | Orchestrationの[`docs/agent-runtime-guide.md`](agent-runtime-guide.md#公開projectionを自律的に扱う) | Productionのcanonical planを検証し、Projectへ投影する。remote公開、merge、releaseは既存のhuman gateに従う |

## 正本と境界

- 親の人間向け全体案内はこのページ、機械的なrepo定義は`config/repositories.yaml`が正本です。
- 子repoのschema、knowledge本文、Issue、品質ゲートは各子repoが正本です。親はそれらをvendor copyしません。
- ResearchとProductionの内部資料、handoff、会話、prompt、実行logはProjectへ公開しません。
- Projectへ出るplanはProductionのcanonical planをOrchestrationが検証したexport-only recordです。Project側で本文を要約・改変して正本にしません。
- Viewer反応は集計された根拠だけを扱い、反応が無い場合は新しい証拠を捏造しません。
- READMEのこの案内と機械契約が食い違った場合は、機械契約と各ownerの正本を優先し、この案内を更新します。

## 関連README更新

各repoのREADMEにも、この共通案内へのリンクと自repo固有の入口を追加します。変更はrepoごとに独立したIssue、branch、commit、PRで追跡します。

- [self-model-notes #96](https://github.com/masa-san-jp/self-model-notes/issues/96)
- [art-history-notes #388](https://github.com/masa-san-jp/art-history-notes/issues/388)
- [marketing-trends-notes #88](https://github.com/masa-san-jp/marketing-trends-notes/issues/88)
- [agentic-art-research #98](https://github.com/masa-san-jp/agentic-art-research/issues/98)
- [agentic-art-production #67](https://github.com/masa-san-jp/agentic-art-production/issues/67)
- [viewer-response-notes #9](https://github.com/masa-san-jp/viewer-response-notes/issues/9)
- [agentic-art-project #14](https://github.com/masa-san-jp/agentic-art-project/issues/14)
