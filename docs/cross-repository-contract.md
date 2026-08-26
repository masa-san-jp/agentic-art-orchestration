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

## Self-model export E2E pin

`tests/fixtures/signal/self_export_bundle.json` は、self-model-notes Issue #40 の完了記録を含む固定commit `04095bfa4115ef4fde8a8f475bf31743ecdff962` から `tools/export_signals.py --purpose artistic-research --limit 0` で生成した `research-signal-export/v1` envelopeである。これは親manifestのqualification pinを浮動参照へ置換するものではなく、E2E fixtureが参照するchild source pinを固定する。

E2Eでは、envelopeの`signal_count`・一意な`signal_id`・全recordの`commit`一致を確認した後、全recordを`adapt_self_model_signal()`へ個別に渡し、`validate_signal()`を通してから1回の`import_signals()`へ渡す。入力・normalized・imported・provenanceの件数、ID順、source commit、entity/evidence locator、certainty、unknowns、constraints、freshness、self-model domain fieldsは一致しなければならない。

raw voice本文、直接識別情報、Drive/Telegram locatorはfixtureと変換結果に含めない。`raw_voice_locator`とsource/evidence locatorは`self-model://`のopaque locatorだけを許可する。Issue #90の材料数や多様性の判断、child schema、adapter、consumerの変更はこのE2Eの範囲外である。

## Self-model diversity report

`self-diversity-report/v1` は、利用許可済みnormalized signalの`domain.self_model.tensions`と`recurring_patterns`のunionだけを対象にする。各値は`signal_id`、属性名、canonical valueを改行で連結したSHA-256のopaque anchor IDへ変換し、reportには生のstatement、voice本文、属性値、直接識別情報を保存しない。同一signal内の重複値はanchor IDで一つにまとめる。

`eligible_anchor_count`が3未満の場合は`INSUFFICIENT_SELF_DIVERSITY`とし、候補を複製したり選択数を水増ししたりしない。明示的な多様性要求でselection limitが10以上の場合は、少なくとも3つのdistinct anchorを含み、各anchorのshareを40%以下にする。passing candidateがselection limitに満たない場合も、limitを下げずに拒否する。候補の選択順はanchor単位の決定的round-robinとし、各anchor内では既存のseeded SHA-256 score順を保持する。

reportは`self-model`のsignal IDとsource commitを保持し、候補・選択の既存v1 schemaへ個人情報やanchor生値を追加しない。`status`は`PASS`、`INSUFFICIENT_SELF_DIVERSITY`、`REJECT`のいずれかで、counts・distinct count・最大shareから再計算できなければならない。
