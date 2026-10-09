# Issue 284: 操作の選択と本文タグの照合

設計正本は [element harness design](20261007-element-harness-design.md)。#283 の本文 export と照合を保ち、owner が `operation-vocabulary/v1` と `operation_tags` を渡す新しい signal では A3 を選択式にします。語彙の内容・タグ本文は art-history owner の正本であり親のconfigへ複製しません。

A3 は本人の素材と操作の短い定義一覧だけを渡し、一つのIDを選びます。選択後、別要素 `A3.evidence.N` が素材の根拠を一箇所抜き書きするよう依頼します。`exact_input_excerpt` が素材との文字列完全一致を検査します。失敗は同じ要素だけ再依頼します。選択理由と操作を一括回答しません。

A4 は絞り込みをせず、並べ方と窓の区切りだけを決めます。美術史と市場の候補を決定的な順に並べ、順は「本人の素材の操作と同じ・補完・対比の関係にあるタグを持つもの → 残りは決定的な順」です。タグと文字の一致は並び順のヒントであり、候補を外す条件ではありません（作品名、URL、関係名や偶然の文字列一致を操作の根拠に変換しない点は従来どおり）。並べた候補は一度に k 件（`config/phase-a-windowing.yaml` の `window_size`、5〜10）の窓に区切ります。判定できる本文を持たない候補だけは数えて除き、BLOCKED の理由に件数を出します。ownerの異なる語彙・新旧語彙の混在は開始前に拒否します。

A5 は窓の中の候補1件ずつに「つながるか＋理由1文」を推論させます（理由に双方の語が入っていることを検査）。A6 は「はい」が無い分野だけ次の窓へ進め、判定は捨てません。本文のある全候補を見ても「はい」が無い分野があるときだけ、分野名・候補数・判定数を付けて BLOCKED にします。市場側も同じ形で、文字の照合が0件でも停止しません。1 run の推論数の最良・最悪と上限 `max_inferences` は [element harness design 4.1](20261007-element-harness-design.md) にあります。上限に達したら理由付きで BLOCKED です。

A3 で「これ以上なし」を選んだ場合は、従来どおり理由付きで停止します。旧pinと明示offline fixture（語彙なし）は従来の自由文A3・本文照合A4・0件時の再依頼を保持し、無言の契約移行はしません。新exportを受け入れるには別途owner pinの資格確認が必要です。

実地確認はユーザー指定素材一件だけです。親履歴は素材・根拠のhashと機械結果を保持し、本文・個人profile・子KB全文を取り込みません。確認対象はA3/A4でありProduction完走やownerによる実出力承認を意味しません。検証結果は `execution/issue-284-verification.json`、実地結果は `execution/issue-284-matching.json` に記録します。push・PR・merge・Issue更新・pin採用はオーケストレーター担当です。
