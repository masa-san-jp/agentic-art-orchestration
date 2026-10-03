# Cross-repository contract

## Contract boundary

親repoは子repoの内部schemaを直接結合しない。各子adapterが normalized-research-signal/v1 を出力し、agentic-art-researchが同versionを入力する。

~~~text
self-model-notes -----------\
art-history-notes ----------> normalized research signals -> agentic-art-research
marketing-trends-notes -----/
~~~

## Viewer response boundary

`viewer-response-notes`は、既存の4repo core setを置き換えない独立した入力repoである。viewer repoが`viewer-response-record/v1`、`viewer-response-assessment/v1`、`research-signal-export/v1`のdomain SSOTを持ち、Productionは明示的なaggregate DTOだけを`production-result/v1`へ運び、ResearchはそのDTOをviewer repoへappend-onlyで変換する。親repoはassessment boundaryとroutingだけを検証し、viewerの内部record schemaを正本化しない。

viewer response recordは`work_id`、`requirement_id`、表示モード、要件タグ、`pass`/`fail`/`unknown`の集計、opaqueな証拠参照、source commit、`aggregate-only`の同意scopeに限定する。名前、連絡先、自由文、心理・医療推測、RAW、asset body、credentialは全repoで拒否する。`sample_size`とoutcome合計が一致しない入力、external evidenceに測定標本を付けた入力、重複dedup keyの内容差はfail closedとする。

assessmentは完全一致のwork/requirement/presentation modeとタグ交差だけを対象にし、測定標本5未満は`UNKNOWN`、Wilson 95% lower boundが0.60以上だけを`SUPPORTED`、upper boundが0.60未満だけを`CONTRADICTED`とする。測定なしで独立external参照が2件以上の場合は`EXTERNALLY_SUPPORTED`だが`SUPPORTED`とは同一視しない。測定とexternalの衝突は測定を判定に優先し、衝突状態を保持する。`UNKNOWN`、`CONTRADICTED`、`EXTERNALLY_SUPPORTED`はblind/frame reviewなしに要件受入へ昇格させない。

viewer responseはgenericな`tools/ingest_signals.py`のnormalized signal列には混ぜない。子repo固有のrecord/export schemaを`tools/viewer_response_gate.py`で検証し、Production/Researchのviewer boundaryでaggregate DTOとして扱う。viewerをself、art-history、marketingのいずれかへ変換して多様性・候補選択へ流すことは禁止する。

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

`self-diversity-report/v1` は、利用許可済みnormalized signalの`domain.self_model.tensions`と`recurring_patterns`のunionだけを対象にする。各値は`signal_id`、属性名、canonical valueを改行で連結したSHA-256のopaque anchor IDへ変換し、reportには生のstatement、voice本文、属性値、直接識別情報を保存しない。同一signal内の重複値はanchor IDで一つにまとめる。R17は`tensions`を`personal_tension`、`recurring_patterns`を`personal_pattern`という別々のslotへそれぞれ結線する。各slotは自分の属性に適格アンカーが1個以上あれば候補へ入り、その属性の適格アンカーが0個ならそのslotだけ値なしのまま保持する（`無し`として扱い、候補生成を止めない）。両属性とも0個（`eligible_anchor_count`が0）の場合にのみ、候補を個人アンカー付きとして生成しない。

`eligible_anchor_count`が0の場合は`INSUFFICIENT_SELF_DIVERSITY`として停止し、候補を複製したり選択数を水増ししたりしない。1〜2個の場合は`PASS_LIMITED_DIVERSITY`として実行を許可するが、3個未満であることを証跡に残す。3個以上の場合は`PASS`とし、明示的な多様性要求でselection limitが10以上の場合は、少なくとも3つのdistinct anchorを含み、各anchorのshareを40%以下にする。1〜2個の場合はこの完全多様性条件を適用せず、限定的な多様性として扱う。passing candidateがselection limitに満たない場合も、limitを下げずに拒否する。候補の選択順はanchor単位の決定的round-robinとし、各anchor内では既存のseeded SHA-256 score順を保持する。

reportは`self-model`のsignal IDとsource commitを保持し、候補・選択の既存v1 schemaへ個人情報やanchor生値を追加しない。`status`は`PASS`、`PASS_LIMITED_DIVERSITY`、`INSUFFICIENT_SELF_DIVERSITY`、`REJECT`のいずれかで、counts・distinct count・最大shareから再計算できなければならない。

## Candidate lineage diversity

`tools/candidate_space.py --report diversity` は `candidate-diversity-report/v2` を出力する。
`distinct_lineage_count` は、候補が使う self 側の anchor 組、art-history 側の操作の組、
marketing 側の normalized signal/attribute 組の順序付き三つ組の数である。
v1 の二軸の数は `distinct_self_marketing_lineage_count` として残す。
`distinct_art_history_anchor_combinations` は歴史操作の組の数を示す。self 側は同意済みの値
そのものではなく属性ごとの opaque anchor ID だけを使い、他の二軸は slot 名、`signal_id`、
束縛属性名だけを使う。report に本人の文言・方法本文・出典本文を出さない。

### 出典付き方法の候補入口（Issue #262）

art-history owner の method concept を、4つめの signal kind を増やさず
`domain.art_history.method`（`fixes / varies / requires / origin_domain`）と
`source_refs`（実際の出典URL）で受け取る。正準グラフや source 本文を複製しない。
方法は各記述が空でなく、出典URLが common `evidence_refs` にも存在することを adapter と
normalized validator で検証する。関係が空の signal はこの方法経路だけに許可する。

R17 の歴史操作は従来どおり `relations` を使い、R18 は `method` を使う。
方法 signal に関係もある場合は R18 へ割り当て、同じ3入力から重複した研究を生成しない。
関係 metadata は signal 内に保持する。
各ルールは束縛した歴史操作がある signal のみを候補にする。method がなければ R18 は
候補を作らず、既存の3入力による R17 の composition と input provenance を保つ。
どちらも self / art-history / marketing の3入力が必要である。
出典付き draft 方法は `validity: unknown` と解釈の不確実性を保持したまま、方法候補として
gate を通せる。これは verified な歴史的影響や美術への適用の認定ではない。
stale な方法は gate を通さない。Research の問いには method の3記述と起源領域を使い、
出典URLはそのまま参照へ渡す。源のない思いつきを方法へ変換しない。

v2 の系統数は、同じ self / marketing の fixture に方法 signal を1件加えると1→2となる。
その際、従来の二軸数は1のままである。同内容の方法でも別の signal ID は別系統となるため、
この数はテキストの意味的多様性の測定ではない。契約と前後比較は
`tests/test_method_seeds.py` で検証する。

R17 は self の `tensions` と `recurring_patterns` を `personal_tension` / `personal_pattern` の別 slot として組み合わせる。`recurring_patterns` が空でも slot は保持し、候補生成は停止しない。marketing 側は `stage` だけを composition slot として束縛する。`counterevidence` は `attribute_bindings.marketing` に宣言済みで provenance（`inputs.marketing`）には残るが、composition slot としては使わない — marketing-trends-notes の read-only clone（2026-09-28 観測）で全65 trend の `counterevidence` が空配列であることを確認しており、これを slot にしても取りうる値が増えないため（本節末尾の限界を参照）。

**この指標の限界**: 系統は `(signal_id, 属性名)` の組の distinct 数であり、属性の**値**の distinct 数ではない。異なる marketing signal が同じ `stage` 値（例: `growing`）を持っていても、`signal_id` が違えば別系統として数える。逆に、全 signal で値が空の属性を slot にしても系統は増えない（`counterevidence` を外した理由）。したがって、この指標で measure される marketing 側の「解像度」は、スナップショットに含まれる distinct な marketing signal の数であり、`stage` の語彙数（marketing-trends-notes 全体では3語）ではない。生成される `creative_question` の文言そのものの多様性は別の層の問題で、`tools/build_research_request.py` が bound attribute の実際の値（self 側は選ばれた opaque anchor に対応する具体的な値）を読むことで担保する。

## 器の名前

境界を渡る成果物は、**中身の形だけでなく、それを束ねる器の名前も契約で定める**。中身だけ定めて器を定めずにいると、独立に実装した両側が別の名前を選び、片側の出力をもう片側が読めなくなる。

規則は1つ。**器の名前は消費側の契約が定める。定めが無いときは中身の名詞の複数形にする。** 生産側は複数の相手に出しうるが、消費側は自分が読む形を1つしか持てないためである。

| 成果物 | 器のキー | 定めた場所 |
|---|---|---|
| `source-ref-index.yaml` | `references`（レコードのハッシュは `record_hash`） | production の実装契約 |
| 知識ベースの signal 書き出し | `signals`（契約は `contract_version`、時刻は `generated_at`、件数は `signal_count`） | `schemas/research-signal-export.schema.json` |

signal の書き出しは、封筒だけを検証して**レコードの中身は検証しない**。種別ごとに形が違い、それを吸収するのが adapter の役目である。封筒が保証するのは、誰がいつどの版から出したかと件数の整合だけである。

## 境界を渡る enum

器の名前と同じ問題が、**中身の語**でも起きる。語彙は消費側の契約が定め、生産側がそれに揃える。

| 値 | 語彙 | 定めた場所 | 生産側 |
|---|---|---|---|
| 受入試験の `result` | `NOT_RUN` / `PASS` / `FAIL` / `EXTERNAL_VALIDATION_REQUIRED` / `BLOCKED` | production `schemas/planning.schema.json` の `$defs.acceptanceTest.result` | research `config/vocabularies.yaml` の `test_results` |

**この表に載る語を増やすときは、消費側の schema を先に変える。** 受理は後の工程が要求する語彙をその場で検査し、計画生成が拒む値を含む bundle を ACCEPTED にしない。
# AAK累積知識境界

AAK-03は子repoのdomain schemaを置換せず、`artifact-record/v1`、`knowledge-write-receipt/v1`、`reuse-trace/v1`だけを横断境界として所有する。正準registryは`config/knowledge-owners.yaml`、adapterは`tools/knowledge_cycle.py`である。

- `prepare`は候補bundleを作るだけで正本を変更しない。
- `validate`はowner、collection、lifecycle、path、hashをfail-closedで確認する。
- `commit`は期待knowledge parentをCAS検査し、operation IDによる再送を二重適用しない。
- `index`失敗はcommitを残して`INDEX_PENDING`とし、失敗ownerだけ再開する。
- `retrieve`はactive、許可scopeの参照だけを返し、利用判断を`reuse-trace/v1`に記録する。
- code commitとknowledge commitは別snapshotである。Projectのcatalog参照はread-onlyで、公開projectionとは別能力である。
