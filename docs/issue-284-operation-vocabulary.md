# Issue 284: 操作の選択と本文タグの照合

設計正本は [element harness design](20261007-element-harness-design.md)。#283 の本文 export と照合を保ち、owner が `operation-vocabulary/v1` と `operation_tags` を渡す新しい signal では A3 を選択式にします。語彙の内容・タグ本文は art-history owner の正本であり親のconfigへ複製しません。

A3 は本人の素材と操作の短い定義一覧だけを渡し、一つのIDを選びます。選択後、別要素 `A3.evidence.N` が素材の根拠を一箇所抜き書きするよう依頼します。`exact_input_excerpt` が素材との文字列完全一致を検査します。失敗は同じ要素だけ再依頼します。選択理由と操作を一括回答しません。

A4 の美術候補は採用操作IDと owner タグIDの共通部分を数えます。作品名、URL、関係名や偶然の文字列一致を操作の根拠に変換しません。一致タグのowner根拠とlocatorを matching history / provenance に残します。市場候補は従来の本文照合を操作ラベルで行います。ownerの異なる語彙・新旧語彙の混在は開始前に拒否します。

一致候補が0件なら成功を装わず、採用済み操作と根拠を保持して残る一覧から次の操作を一つ依頼します。「これ以上なし」は理由付き停止になります。候補が正になるよう操作を誘導しません。旧pinと明示offline fixtureは従来の自由文A3・本文A4を保持し、無言の契約移行はしません。新exportを受け入れるには別途owner pinの資格確認が必要です。

実地確認はユーザー指定素材一件だけです。親履歴は素材・根拠のhashと機械結果を保持し、本文・個人profile・子KB全文を取り込みません。確認対象はA3/A4でありProduction完走やownerによる実出力承認を意味しません。検証結果は `execution/issue-284-verification.json`、実地結果は `execution/issue-284-matching.json` に記録します。push・PR・merge・Issue更新・pin採用はオーケストレーター担当です。
