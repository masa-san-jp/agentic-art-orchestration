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

## Observation provenance

リポジトリの状態を根拠にする決定・レビュー・検証記録は、実測対象ごとに次の4項目を必須で保持する。`observed_ref` は40桁のcommit SHAであり、manifestのpinと子repoの現在を同一視しない。

| 項目 | 記録する内容 |
|---|---|
| `repository` | `config/repositories.yaml` の安定したrepo ID |
| `observed_ref` | 実際に観測した40桁のcommit SHA |
| `observed_via` | `manifest_pin` / `remote_head` / `local_worktree` のいずれか |
| `observed_at` | RFC3339形式の観測時刻 |

qualification reportのfindingは、上記に加えて `source_repository`、`source_commit`、`evidence_locator` またはopaqueな `evidence_ref`、`unknowns` を保持する。証拠が取得できない場合は `null` や `NOT_OBSERVED` として残し、false・空の正常値・推測したcommitへ変換しない。

`observed_via: manifest_pin` は「最後にqualifiedとなった入力pin」を表し、remoteの先端ではない。`observed_via: remote_head` は宣言されたdefault branchのread-only観測、`observed_via: local_worktree` は手元checkoutの観測である。local worktreeを使う場合は、そのHEAD SHAとremote headとの一致を `true` / `false` / `unknown` のいずれかで併記し、比較を実施していないときは `unknown` と `unknowns` に明記する。

qualificationはpinを専用workspaceへmaterializeして実行し、source checkoutのstate（MATCHED / STALE / DIRTY / DETACHED / UNAVAILABLE）と、materialize後のcommitを別々に記録する。sourceが新しい、dirty、detachedであっても、pinを黙って追従させない。取得不能なpinやremote観測不能はblocking findingまたは明示的unknownとして残す。

`execution/state.yaml` に記録する `command` は、別環境から再実行できるrepo相対のinterpreter、workspace、output pathだけを使う。一時workspaceやinterpreterで過去に実行した事実は `historical_provenance` として残せるが、その絶対パスを再実行commandへ混ぜてはならない。

## Forbidden transformations

- unknownを0、false、low confidenceへ暗黙変換する。
- 同意範囲外のSelf Model情報をexportする。
- marketingのstale/vendor/anecdotalをverifiedへ昇格する。
- art-historyの解釈relationを事実relationへ変換する。
- 原典未読のURLを読了済みとして扱う。
- source repositoryまたはcommitを落とす。
