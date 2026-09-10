# AAK07 provider run P1 — Projectローカル投影レビュー

この資料は、`AAK07-AGENT-20260910-P1` のProjectローカル投影を判断するための、全ての判断項目を含む公開可能な派生レビュー資料です。Productionの内部schema、raw入力、実行ログ、秘密情報は複製していません。これは正本`production-plan.md`の代替ではなく、元の一時workspaceがなくても承認対象を検証できるようにしたものです。

## 実行状態

| 項目 | 値 |
| --- | --- |
| run | `AAK07-AGENT-20260910-P1` |
| profile | `synthetic-provider-new-clone` |
| provider | ローカルOllama `qwen2.5:0.5b`（課金不要） |
| providerの判断 | `USE_PINNED_HANDOFF` |
| Research | `COMMITTED`（receiptあり） |
| Production | `COMMITTED`（receiptあり） |
| Production plan | `PLAN_READY` |
| Project投影 | 未実施。`PRODUCTION_REVIEW_PENDING` |
| 物理制作・購入・契約・外部送信 | 未実施 |

## 投影される計画の内容

### 完成像

等間隔に並んだ要素を端から順に目で追い、途中の一箇所だけ間隔が崩れていることに出会う。その後、鑑賞者が列を見直すことで、先に見えていなかった規則を知覚する。

- 鑑賞者の位置：列の正面を、端から端まで2mの距離を保って歩く
- 最初の数秒：一定間隔の列として認識する
- 30秒後：一度だけ崩れた位置を見つける
- 3分後：崩れた場所が規則の知覚を生んだと残る

### テーマと機構

- テーマ：反復の規則と、それが破れた一点
- 主張：規則は、それが破れた瞬間にだけ知覚される
- 機構：一定間隔の要素を並べ、一箇所だけ間隔を変える
- 既存技法なしでは：`CEASES_TO_WORK`
- 固有性：中断を見どころとして提示するのではなく、中断に当たって初めて規則が遡って知覚される順序を作る

### 提案されている最初の工程

これは実行済みの制作記録ではなく、Productionが生成した提案です。

1. 12個の紙要素を等間隔の12位置へ置き、1個だけ欠落させる（一割縮尺の試験モデル）。
2. 固定照明・固定露出で3視点を記録する。
3. 3視点すべてで間隔と中断が識別できるかを確認する。

材料の実在性・数量・権利・利用可能性、会場条件、日程、費用、実地の視認性は未確認です。計画内でも`PROPOSED`または`UNKNOWN`として残っています。

## 要件と根拠

| 要件ID | 優先度 | 内容 | 計画上の対応 | 状態 |
| --- | --- | --- | --- | --- |
| `RQ001` | mandatory | 試作で反復する間隔と一箇所の中断を観測可能にする | `DL001`、`TS001`、`AT001`、`TK001`、`TK002`へ接続 | COVERED |

採択仮説は`PH001`（`A single omission in a repeated structure becomes visible through viewer movement.`）です。選択権限は`AGENT`、選択状態は`PROVISIONAL`で、人間が仮説を確定した記録はありません。

## 参照の状態

| 出所 | 内容 | 状態 |
| --- | --- | --- |
| `EV001` | primary_public、rights_status=public-use、PUBLIC_CITABLE | URLあり。ただしこのrunが権利を再確認したものではない |
| `EV002` | independent-secondary、rights_status=public-use、PUBLIC_CITABLE | URLあり。ただしこのrunが権利を再確認したものではない |
| `DC001` | 二つの資料が知覚上の規則を支持し、反対仮説も残す判断 | URL未提供。gap |
| `IN001` | 説明文なしでも反復が概念を運べるという洞察 | URL未提供。gap |

## 成果物・技術仕様

- 成果物は`DL001`「Interrupted interval installation」。担当能力は`physical-prototype-agent`、状態は`PLANNED`です。
- `TS001`は、`RQ001`を対象とする定性的な`frame_review`仕様です。許容差は未設定、状態は`PROVISIONAL`です。
- Production planに記載されたboardとmockupは、受理済みhandoffから生成したsynthetic fixtureです。外部画像の取得・採用、物理制作、外部検証はありません。
- mockupは`CONCEPTUAL`、`Not to scale`です。物理寸法・材料選定は確定していません。
- 材料registerとresource planは空です。12個の紙要素、固定照明、3視点という提案はありますが、数量・権利・在庫・会場は未確認です。

## 作業グラフと現在地

| ID | 内容 | 効果種別 | 前提 | 承認 | 状態 |
| --- | --- | --- | --- | --- | --- |
| `TK001` | 12位置の一割縮尺モデルを作り、1要素を欠落させる | `PHYSICAL_EXTERNAL` | なし | `AR001` | BLOCKED |
| `TK002` | 固定露出で3視点を記録する | `PHYSICAL_EXTERNAL` | `TK001` | `AR001` | BLOCKED |
| `TK004` | 導出planの依存グラフと要件coverageを検証する | `READ_ONLY` | なし | なし | READY |

クリティカルパスは`TK001 → TK002`です。`TK001`と`TK002`は物理・外部効果のため、Production runtimeの`AR001`承認なしには実行できません。承認対象は`03_plan/task-plan.yaml#TK001,TK002`、hashは`sha256:d271ac7be772acc6c02e5719103965a2dd301694edaaa95faeaf34dc630b6bc6`です。

## 受入、日程、予算

- `AT001`は「3フレームすべてで間隔と中断を識別できること」。計画ファイル上の結果は`PASS`ですが、これは受入条件の定義・plan validation上の値であり、物理フレームの実測結果ではありません。
- `MS001`（開始）と`MS002`（完了）は相対日程で、`MS002`は`BLOCKED`です。カレンダー日、担当者の空き、会場は未提供です。
- タスク所要時間の提案は`TK001=1h`、`TK002=1h`、`TK004=15min`です。開始・期限は未設定です。
- 通貨はJPY、予算状態は`ESTIMATED`です。総額、予備費、承認閾値、見積、供給者、予約、支払い約束はありません。費用帯`LOW`はhandoff由来の推定で、実測ではありません。

## リスクと未解決事項

主なリスクは、3視点すべてで中断が見えるか不明なこと（`RK001`、重要度`MAJOR`、可能性`UNKNOWN`、状態`OPEN`）です。未解決事項には、材料の権利・数量・可用性、参照URL欠落、物理タスクの承認不足、相対日程、予算未設定が含まれます。物理タスクの承認不足（`PG010`、`PG011`）だけが計画上のblocking gapです。

## 公開・制作の境界

計画の除外範囲は`publish`、`submit`、`send`、`purchase`、`contract`、`delete`です。計画生成は、物理作業、購入、契約、支払い、公開、応募、連絡、削除、Drive共有を許可しません。Projectローカル投影の承認は、物理工程`AR001`の承認とは別です。

## 再現性と引き継ぎ

計画は`HO003`、`PH001`、`RQ001`、`AT001`、`PP001`へトレースされています。handoff hashは`sha256:b203e5972c32d8ab3abfeaf2b0357f050e17e7c3089a17e19d05333604d2c5bf`、plan integrity hashは`sha256:8fb3e092b10ff6c7557a52821c03e9d8cc706ec4ffb40895f75aafd75b4090e2`です。実施時には、失敗・差分・変更要求を既存計画へ上書きせず、実行台帳へ追記します。

## 参照とvisual asset

Productionが生成した決定論的なsynthetic SVGです。外部画像を取得・採用していません。

| asset | 状態 | byte length | SHA-256 |
| --- | --- | ---: | --- |
| `03_plan/media/concept-mockup.svg` | synthetic / PROJECT_INTERNAL | 1,985 | `sha256:9c017f6910cf6032956a76ef3bf5dad7fdc7c57fa4649f6ff7714f83d52476be` |
| `03_plan/media/visual-reference-board.svg` | synthetic / PROJECT_INTERNAL | 3,664 | `sha256:6696ccd280f6712956a76ef3bf5dad7fdc7c57fa4649f6ff7714f83d52476be` |

参照欄には、次の公開参照URLが記載されています。取得済みであることや、外部参照の権利が確定したことを意味しません。

- `https://example.invalid/harmony/source-001`
- `https://example.invalid/harmony/source-002`

参照`DC001`と`IN001`はURL未提供のgapとして残っています。実地の観察記録はありません。

## 対象hash

| 対象 | SHA-256 |
| --- | --- |
| Production plan本文 | `sha256:e784aaacfa98c4636ad73e0fae6abcbb9a86988a5e555ca3b9db6d102c91f0b7` |
| Production plan構造化aggregate | `sha256:43d0ca7dc1ee1175a3f5874f44ee2928f93ba4b6d6ae42b50fbfa6e990b21ec1` |
| handoff | `sha256:908ed32bae8407fd196007028a4cc2b47a312bb56888c344ed7c931ef18af321` |
| **レビュー対象（aggregate・本文・assetの束）** | **`sha256:9396873f118ee41ef6c998aaf86fa669831110edad8b0d806435c4a3d86f7c5a`** |

レビュー対象の参照名は`public-plan-review/PL001`です。

## 現在の安全境界

- `content_safety`、`rights`、`consent`のProduction native承認は未登録です。
- 物理工程の承認も未登録です。
- 公開Projectへの投影、Git commit、push、外部公開はまだ行っていません。
- この資料自体は承認ではなく、承認対象を確認するための要約です。

## 必要な判断

Projectローカル投影を実行する場合、上記レビュー対象について、次の3項目を明示してください。

```text
public-plan-review/PL001（SHA sha256:9396873f118ee41ef6c998aaf86fa669831110edad8b0d806435c4a3d86f7c5a）について、content_safety・rights・consent を PASSED としてProjectローカル投影を承認する。
```

承認を受けた後も、物理制作・購入・契約・応募・外部送信は別工程として実行しません。承認の記録後、同じrunを再開し、canonical projection、Project owner receipt、系譜、完了verifierを順に検証します。

## 親repoでの証拠

- Issue: <https://github.com/masa-san-jp/agentic-art-orchestration/issues/217>
- 実行証拠: `execution/delivery-cycle-v2-evidence.json`
- 再開情報: `execution/state.yaml` と `execution/handoff.md`
