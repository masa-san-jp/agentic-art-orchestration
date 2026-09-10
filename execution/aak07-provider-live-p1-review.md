# AAK07 provider run P1 — Projectローカル投影レビュー

この資料は、`AAK07-AGENT-20260910-P1` のProjectローカル投影を判断するための公開可能なレビュー要約です。Productionの内部schema、raw入力、実行ログ、秘密情報は複製していません。元の一時workspaceがなくても、ここに記載した内容・hash・状態で承認対象を特定できます。

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
