# Issue 283: 出典付き本文による A4 照合（レビュー修正）

orchestration のローカル修正。承認済み art-history-notes commit `360eb99bc8c5deab45c9e607653f61decc17dceb` は変更していない。push / PR / merge / Issue 更新と owner pin の採用はオーケストレーターが担当する。execution lease は取得していない。

## 採点と診断

- owner の `content[]` は出典付き原文を決定的に抜き出し、合計2400文字で打ち切る既存の承認済み契約を使う。親は本文を複製しない。movement と method を同じ候補集合へ入れ、unknown / draft を valid に昇格させず、stale を除外する。
- A4 は content、または旧 method export の出典付き fixes / varies / requires だけを使う。名前、関係の件数・相手、ID、URL は採点しない。日本語の共通助詞等を区切りとして、2文字以上の語彙アンカーを照合する。Latin は単語全体を照合する。source 確認用チェックの語彙規則は変更しない。
- 長い一致から順に本文と操作語双方の一致範囲を確保する。同じ位置の重なった断片、同じ操作語範囲の重複、本文での同じ一致語の反復を加点しない。例えば「意識的」は3点で、「意識」「識的」を重ねて7点にしない。3文字を超える最長の一致も保持する。
- 正の点には「3文字以上の一致」または「操作語を区切った異なる語彙語が2つ以上、かつ異なる一致断片が2つ以上」を必要とする。ここで語彙語は助詞・空白等で決定的に区切った単位であり、形態素推論はしない。同じ2字語の繰り返しや一つの語からの断片2つでは下限を満たさない。下限未満は0点とする。
- `matched_terms` と `matches` は重ならない最長一致を示す。`raw_score_breakdown` / `raw_score` は下限適用前の文字数、`score_breakdown` / `score` は適用後の点を示す。下限未満では一致語の加点は0であり、内訳の合計は必ず score と一致する。
- 同点は、一致した別々の受理済み A3 操作語数、操作語の語彙文字の被覆率、最長一致、異なる語彙語数の順で並べる。すべて同じ場合は照合本文の正規化文字列で再現可能に並べ、ID は使わない。本文まで同一の候補には内容による優劣がない。
- domain ごとの `MISSING_SOURCED_CONTENT` / `NO_CONTENT_TERM_OVERLAP` / `BELOW_MINIMUM_CONTENT_MATCH` を保存する。`matching_history[].reason` は失敗分野の診断が一種類ならその理由、複数なら `MULTIPLE_CONTENT_MATCH_FAILURES` とする。追加要求の previous_failure は各分野の理由を含む。
- どちらかの domain に正の候補がなければ A5 に進めず、A3.operation.2 以降で一つだけ追加要求する。受理済みの素材・語は保持し、同じ語を再受理しない。既定の最大5回で照合が成立しなければ A4.matching を BLOCKED にする。

## 実 run の受理語での確認

レビューで明示された実 run の受理済み A3 **「確定の保留」** を、そのまま使った。前回のエージェント選定語「意識的な決定を留保」による9点の結果は、この確認の根拠から取り下げる。追加語は選定・回答していない。

本人が利用を許可した素材を標準入力に渡した。素材そのもの・self signal・owner 本文は Git に保存せず、素材と本文の hash だけを記録する。実 export は182件、本文あり162件、method 4件。鮮度・確度条件を適用した176件（movement 172 / method 4）を照合した。

**正の候補は0件。4件が「確定」の単独2字一致で下限未満となり、残り172件には一致がない。** 以下は診断表示の先頭5件であり、A5 へ渡す上位候補ではない。5件目には一致による優位がない。

| 診断表示 | 候補 | 下限適用後の点 | 適用前 | 一致語 |
|---|---|---:|---:|---|
| 1 | シエナ派 / movement/sienese-school | 0 | 2 | 確定 |
| 2 | ンガーティ・タラーワイの彫刻 / movement/ngati-tarawhai-whakairo | 0 | 2 | 確定 |
| 3 | ノク彫刻 / movement/nok-sculpture | 0 | 2 | 確定 |
| 4 | バグダード派（写本挿絵） / movement/baghdad-school-of-illustration | 0 | 2 | 確定 |
| 5 | 安堅派 / movement/an-gyeon-school | 0 | 0 | なし |

probe は実 owner art export と承認済み素材を native Engine に入力し、A3 を実際に受理させ、再開結果が同一であることも確認した。self の envelope は既存の合成 fixture に素材だけを載せた輸送用で、market は変更していない既存の合成 fixture。合成 fixture の有効な generated_at をハーネス時計に使う。実 owner の market や full profile / Production run を再現したという主張ではない。美術史の選別は通常入口と同じ current / valid または出典付き unknown の条件であり、この時計には依存しない。

native checkpoint は **WAITING / accepted_count: 1 / A3.operation.2**。美術史は `BELOW_MINIMUM_CONTENT_MATCH`、合成 market は `NO_CONTENT_TERM_OVERLAP`、全体は `MULTIPLE_CONTENT_MATCH_FAILURES`。previous_failure に両方の診断が残り、prior_operations は「確定の保留」。追加の一要素要求を記録し、追加語には回答せず、A5 の判定は作成していない。素材入力だけは hash に置き換えて証跡から省いている。

全候補の点・一致範囲・同点指標・相対 locator・owner commit / export hash と native 要求は [matching evidence](../execution/issue-283-matching.json) に保持する。通常 workspace の pin は変更していない。

```bash
python execution/issue-283-matching-probe.py \
  --export "$ART_HISTORY_EXPORT" --operation 確定の保留 \
  < "$AUTHORIZED_MATERIAL"
```

probe の終了コード0は追加要求を観測した検証の成功であり、照合や Production の完了を意味しない。指定語以外を probe に渡すことはできない。

## 残る完了条件

採点・順位・診断・追加要求のレビュー修正は実装した。しかし、実素材で意味のある正の上位候補を示す完了条件は **未達**。実 run の次の A3 語がないため、結果を改善するための語を作って先へ進めない。ISSUE-283 の queue / checkpoint は BLOCKED に戻し、以前の DONE / 4/4 完了主張を取り下げた。ISSUE-280 の owner 確認 gate は維持する。

全検証、各終了コード・件数、origin/main との失敗集合比較は [verification evidence](../execution/issue-283-verification.json) に記録する。
