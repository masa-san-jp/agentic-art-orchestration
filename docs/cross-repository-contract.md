# Cross-repository contract

## Contract boundary

親repoは子repoの内部schemaを直接結合しない。各子adapterが normalized-research-signal/v1 を出力し、agentic-art-researchが同versionを入力する。

~~~text
self-model-notes -----------\
art-history-notes ----------> normalized research signals -> agentic-art-research
marketing-trends-notes -----/
~~~

## Required signal fields

- contract_version
- signal_id — source repoを跨いで一意
- signal_kind — self / art-history / marketing
- source.repository / source.commit / source.entity_ids / source.locators
- statement — 観測と推論を混ぜない
- evidence_refs / certainty / unknowns / constraints
- adapter.name / adapter.version
- generated_at

## Domain-preserving extensions

### Self Model

- 同意scopeとexport可否
- seeks / protects / avoids / tensions / recurring patterns
- raw voice本文ではなく許可済みlocator
- trait / state / contextの区別

### Art History

- entity kind、time、geo、relation
- relationの根拠と確度
- canonical graphは複製せずstable ID参照

### Marketing Trends

- stage、freshness、expires/revalidate date
- certaintyとretrievedを別軸で保持
- vendor利害、counterevidence、prediction status
- staleは削除せず制約として伝播

## Compatibility

- major version不一致は拒否する。
- minor追加フィールドはconsumerが無視できる。
- required fieldの意味変更はmajorを上げる。
- adapterはsource commitとadapter versionを必ず出す。
- consumer成果物は利用signal IDとsource commit組を保存する。

## Forbidden transformations

- unknownを0、false、low confidenceへ暗黙変換する。
- 同意範囲外のSelf Model情報をexportする。
- marketingのstale/vendor/anecdotalをverifiedへ昇格する。
- art-historyの解釈relationを事実relationへ変換する。
- 原典未読のURLを読了済みとして扱う。
- source repositoryまたはcommitを落とす。

## 器の名前

境界を渡る成果物は、**中身の形だけでなく、それを束ねる器の名前も契約で定める**。中身だけ定めて器を定めずにいると、独立に実装した両側が別の名前を選び、片側の出力をもう片側が読めなくなる。実際に2度起きた。

規則は1つ。**器の名前は消費側の契約が定める。定めが無いときは中身の名詞の複数形にする。**

生産側は複数の相手に出しうるが、消費側は自分が読む形を1つしか持てない。曖昧さのコストは消費側に集中するので、決定権も消費側に置く。

| 成果物 | 器のキー | 定めた場所 |
|---|---|---|
| `source-ref-index.yaml` | `references`（レコードのハッシュは `record_hash`） | production の実装契約 |
| 知識ベースの signal 書き出し | `signals`（契約は `contract_version`、時刻は `generated_at`、件数は `signal_count`） | `schemas/research-signal-export.schema.json` |

signal の書き出しは、封筒だけを検証して**レコードの中身は検証しない**。種別ごとに形が違い、それを吸収するのが `tools/adapters.py` の役目だからである（README の「子の内部形式を共通化せず、境界で翻訳する」）。封筒が保証するのは、誰がいつどの版から出したか、と件数の整合だけ。

## 境界を渡る enum

器の名前と同じ問題が、**中身の語**でも起きる。research が許す語を production が知らないと、受理は通るのに次の工程で落ちる。器の規則をそのまま適用する——**語彙は消費側の契約が定め、生産側がそれに揃える。**

| 値 | 語彙 | 定めた場所 | 生産側 |
|---|---|---|---|
| 受入試験の `result` | `NOT_RUN` / `PASS` / `FAIL` / `EXTERNAL_VALIDATION_REQUIRED` / `BLOCKED` | production `schemas/planning.schema.json` の `$defs.acceptanceTest.result` | research `config/vocabularies.yaml` の `test_results` |

**この表に載る語を増やすときは、消費側の schema を先に変える。**

語彙を揃えるだけでは足りない。**受理は、後の工程が要求する語彙をその場で検査する**（production `tools/new_production.py::_assert_planning_vocabulary`）。受理は「この bundle で仕事ができる」という宣言なので、計画生成が拒む値を含んだまま ACCEPTED にすると、宣言が事実でなくなる。検査は消費側 schema の enum を直接読むので、schema を変えれば検査も同時に動く。
