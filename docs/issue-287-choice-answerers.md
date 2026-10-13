# 選択式の答え手と並べ替え検査（Issue 287）

段階A v2は、関係を推論が判断し、プログラムが提示順と受理条件を管理する。#284の操作タグ一致による候補選別は採用しない（[v2移行判断](20261010-phase-a-v2-design.md#9-移行計画)）。閉じた旧Issue280/283のタスクは、旧受入条件が成功したという意味ではなく、Issue288による置換として整理する。

`tools/element_answerer.py --config <設定>` は従来の `element-answerer/v1` と、新しい `element-answerer/v2` を受け取る。新形式の `default` は通常のLLM等、`formats.choice` は選択式の答え手に割り当てる。各commandはshell文字列ではなくargvの配列。stdinの依頼一件にstdoutの回答一件を返す外部コマンドであり、providerやdaemonは親Engineへ内蔵しない。

[設定例](../config/element-answerer-choice.example.yaml)で `answerer_kind: judge-...` と指定した選択式は、元の順序と、run/element/attemptから決まる異なる循環順序で、二つの新しいprocessへ渡す。数値カードは内容を入れ替えて番号を付け直し、「どれにも当たらない」の番号もinstructionと一緒に動かす。関係名の選択肢は名前の意味を保って並べ替える。一つしか選択肢がない場合は並べ替え比較を行えないため、このadapterへ渡さない。

回答の `choice_observations` は提示順、依頼hash、返された値、所要時間、報告可能なAPI費用を保持する。Engineが二つの提示を再計算し、値を元の意味へ戻して一致を確かめる。自己申告のstableフラグは使わない。judge回答の証跡欠落、提示hash改変、二つの意味の不一致は受理しない。不一致は既存の最大5回の要素再依頼に入り、5回とも不一致ならBLOCKED。証跡はGit外の要素historyへ保存し、再開と回答replayを維持する。

型が異なる通常のLLM回答と旧設定には二重推論を追加しない。judge-only backendをtext等のdefaultへ設定することは拒否する。freshの依頼は二つとも独立processで扱い、一つ目の答えを二つ目に渡さない。

## 比較

```bash
python tools/element_benchmark.py --requests /absolute/permitted-choice-requests.json \
  --llm-config /absolute/llm-v1.yaml --judge-config /absolute/judge-v1.yaml
```

最大100依頼の同じ入力を、両backendに各2回ずつ提示する。表示位置の分布、元の選択肢へ戻した初回の一致率、各backendの並べ替え一致率、所要時間、API費用を集計する。request本文と回答本文はreportへコピーせずhashにする。未報告の費用はnullであり、無料扱いにしない。途中失敗があるbackendの総費用もnullにし、所要時間のscopeをcompleted_pairs_onlyと明示する（失敗したcallの時間・費用を全測定したと扱わない）。費用はbackendの報告したAPI料金で、ローカル機械の電力・償却費は含めない。reportは一貫性と相互一致の測定であり、正解率ではない。

Jevの実比較は[公式API](https://docs.typesafe.ai/api)と[固定モデル・入力token料金](https://docs.typesafe.ai/models)に合わせる。比較用providerは外部workerとして用意でき、API keyを設定やGitへ入れない。本人の素材を外部サービスへ渡す許可をこの設定から推測しない。今回の実測には公開Art HistoryのKBだけを使い、本人の素材・private runは使わない。結果と採用判断はexecutionのIssue287証跡へ記録する。既定の答え手はLLMを維持し、judgeの使用は明示設定に限る。
