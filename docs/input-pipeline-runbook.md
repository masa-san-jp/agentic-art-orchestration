# Input KB → Research 開始 runbook

親リポジトリの入力境界は、各KBから `normalized-research-signal/v1` を1件以上受け取り、`normalized-research-signal-bundle/v1` の1つの封筒へ集約する。候補選定、provenance、Research依頼は同じ封筒の同じcommit情報から生成する。

## 実行

承認済みの子DTOを各リポジトリのcommit固定作業領域から用意した後、次の順で実行する。

```sh
python3 tools/export_signal.py --kind self \
  --input /path/to/approved-self-record.json --output /tmp/self-signal.json
python3 tools/export_signal.py --kind art-history \
  --input /path/to/approved-art-record.json --output /tmp/art-signal.json
python3 tools/export_signal.py --kind marketing \
  --input /path/to/approved-marketing-record.json --output /tmp/marketing-signal.json

python3 tools/signal_bundle.py \
  --self /tmp/self-signal.json \
  --art-history /tmp/art-signal.json \
  --marketing /tmp/marketing-signal.json \
  --generated-at 2026-08-14T00:00:00+09:00 \
  --output /tmp/signal-bundle.json

python3 tools/research_start.py \
  --bundle /tmp/signal-bundle.json \
  --project-id example-project \
  --project-slug example-project \
  --seed-input default \
  --request-id RR001 \
  --requested-at 2026-08-14T00:00:00+09:00 \
  --research-root /path/to/agentic-art-research \
  --output-dir /tmp/research-start
```

`research_start.py` は候補選定から `research-request.yaml` を生成し、Researchの `accept_research_request.py --dry-run` を呼ぶ。子リポジトリへapplyせず、受理が終端状態にならなければ失敗する。Researchへの実適用、Productionへのhandoff、公開・送信・購入などの外部作用はこのrunbookの範囲外で、人間の承認と各子リポジトリの正本CLIが必要である。

## 境界と再実行

- bundleの全source repositoryはcommit SHAを持ち、1 repositoryにつき1 commitだけ許可する。
- 3種類のsignalが揃わない、同一IDが重複する、signalの個別schemaが不正、またはcommit対応が崩れる場合はfail closedする。
- Research requestには選定候補IDとopaqueな参照URIだけを渡し、signal本文・raw payload・ローカルパスはコピーしない。
- 同じbundle、seed、request ID、requested_atを使えば候補とrequestは再生成できる。`research_start.py` はdry-runなのでResearch projectを作らない。
- `export_signal.py` はadapterをテスト専用にせず、実行時の入力境界として呼び出すための唯一の入口である。
