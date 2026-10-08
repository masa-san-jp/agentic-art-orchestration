# Issue 283: 出典付き本文による A4 照合

orchestration と art-history-notes のローカル実装。push / PR / merge / Issue 更新と owner pin の採用はオーケストレーターが担当する。割り当て済み隔離 clone で作業し、execution lease は取得していない。

## 変更と判断

- owner export の `content[]` は原文の text、source_locator、source_refs を持つ。定義・方法などの節のうち、出典 URL が entity の sources と完全一致する段落、その直後の引用、既存の出典付き method の固定・変動・成立条件を決定的に抜き出す。合計 2400 文字で打ち切る。出典のない段落は、節全体に別の出典があっても採用しない。
- normalized 境界は content と entity_labels を任意の追加情報として保持する。本文だけの movement も根拠のある候補として扱う。draft / unknown は候補の種として保持し、verified / valid に昇格させない。stale の除外は維持する。
- 美術史の採点は content、または旧 method export の出典付き fixes / varies / requires だけを使う。statement の名前・関係件数、関係先の ID や公開ラベル、URL の文字列、entity 自身の名前を採点しない。運動と方法を同じ集合へ入れる。
- 加点は一致する語彙アンカーの文字数の合計。Latin words と日本語の 2/3 文字アンカーを使い、共通の助詞等をまたぐ「の言」「を保」などには点を与えない。一致語の集合、語ごとの点、合計を保存する。source の確認用チェックの語彙規則は変更しない。
- どちらかの domain の候補が全件 0 点なら、A4 の各候補の点と診断理由（本文不足 / 本文と操作語の一致なし）を保存する。A3.operation.2 以降で一つの操作語だけを追加要求し、受理済みの語の集合で同じ run を再照合する。既存の素材・答えは保存し、同じ語を再受理しない。既定の最大 5 回の照合で一致がなければ A4.matching を BLOCKED にする。
- 0 点候補は A5 に渡さない。正の同点については安定 ID を tie-break に使う。全件 0 点を ID 順で進めることだけを廃止する。接続の意味の採否は引き続き A5 の一要素推論が担当する。

## 提示された素材での確認

本人が報告への利用を許可した素材を標準入力で与えた。操作語は、この検証でエージェントがその素材の状態を **意識的な決定を留保** と解釈して一件だけ与えたもの。過去の実 run の受理済み操作語や、全 profile の Production run を再現したという主張ではない。素材そのものや self signal は Git に保存せず、sha256 だけを記録する。

art-history owner の clean commit `360eb99bc8c5deab45c9e607653f61decc17dceb` から実際に export した 182 件のうち、162 件に本文があり、method は 4 件。通常入口と同じ鮮度・確度条件で 176 件（movement 172 / method 4）を照合し、5 件が正の点を持った。

| 順位 | 候補 | 点 | 一致語と内訳 |
|---|---|---:|---|
| 1 | オートマティスム / concept/automatism | 9 | 意識 2、意識的 3、識的 2、決定 2 |
| 2 | バグダード派（写本挿絵） | 2 | 留保 2 |
| 3 | コンゴ・キリスト教美術 | 2 | 意識 2 |
| 4 | キト派 | 2 | 留保 2 |
| 5 | 海上画派 | 2 | 留保 2 |

ID 順の先頭は抽象表現主義などであり、内容の一致が最も強い method がそれより上に来る。2〜5 位は正の同点なので ID 順。語彙一致は歴史的影響や素材との意味的接続の認定ではない。

全候補の点、一致語、本文 hash、相対 locator、owner commit と export hash は [matching evidence](../execution/issue-283-matching.json) に保持する。owner の本文は複製しない。20 件の export に本文がないことは未確認の文章を埋めずに省いた結果であり、0 点で明示する。

再実行は clean な art-history 候補 checkout で `python tools/export_signals.py --purpose artistic-research --output <external-export.json>` を実行し、親で次を行う。素材を置く external ファイルは本人の承認済みの文だけとし、パスを証跡に記録しない。

```bash
python execution/issue-283-matching-probe.py \
  --export "$ART_HISTORY_EXPORT" --operation 意識的な決定を留保 \
  < "$AUTHORIZED_MATERIAL"
```

検証結果と origin/main の失敗集合比較は [verification evidence](../execution/issue-283-verification.json) に記録する。通常 workspace の pin は変更していないため、新しい owner export を本番入口で使う pin adoption はレビュー後の別操作となる。
