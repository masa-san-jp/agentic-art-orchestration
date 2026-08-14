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

## Envelope naming rules

The name of a cross-repository container is defined by the consuming contract. When no consumer contract exists, use the plural noun for the contents. Producers may keep their internal schema; only the boundary envelope is governed here.

| Boundary artifact | Canonical key | Meaning |
| --- | --- | --- |
| `source-ref-index.yaml` | `references` | Source-reference records consumed by Production |
| `source-ref-index.yaml` record | `record_hash` | Canonical non-zero hash produced by Research; a consumer must not invent or silently zero-fill it |
| `research-signal-export/v1` | `signals` / `signal_count` | Pre-adapter signal payload and its count |
| Signal envelope metadata | `contract_version` / `generated_at` | Contract version and generation time |

`record_hash` identifies the canonical source-record snapshot computed by the producer. Production validates its format and presence, but cannot claim to verify the source record when the record body is intentionally not copied into the handoff.

The parent-owned `normalized-research-signal-bundle/v1` is a separate consumer-side aggregate and intentionally uses `records`; that internal aggregate name does not override the producer envelope rule above. Adapters translate child-specific internal forms at the boundary, so `entities`, `graph`, and other KB-internal schemas are not forced to share names.

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
