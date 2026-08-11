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
