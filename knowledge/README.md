# Orchestration knowledge

検証済みの実行失敗・復旧・運用知識を保存するowner領域。記録は改善候補であり、権限、同意、実行規則を自動変更しない。会話全文、credential、PRIVATE_RAW、子ownerのpayload本文は保存しない。

Orchestrationのpayloadは `operational-knowledge/v1`。外部の明示storeを
`tools/knowledge_cycle.py init --owner agentic-art-orchestration --store <absolute-store>
--creator <creator> --collection <collection> --code-commit <qualified-sha>` で初期化する。
共通引数を維持し、`commit` へ `--record`、`--payload-root`、
`--operation-id`、`--run-id`、initで得た `--knowledge-commit` を渡す。
出力receiptを外部stateへ保存し、`index --receipt <receipt-file>` で索引を作る。
子ownerのpayloadは各子の正規CLIで検証する。この入口は親の運用知識だけを扱う。

storeのobjects.gitが実Git正本。recordsとpayloadは同じcommitへ入れ、refは親SHAの
CASで更新する。operation ledgerを同commitへ保存するので、receipt保存直前の中断も
二重commitなしで再開できる。index.jsonは再生成cacheであり、検索は固定Git snapshotから
再読込する。既存の未登録storeや異なるcreator/collectionのstoreを自動採用しない。

dispatchの外部outboxは入力bundleのhashと期待parentを保存し、完了ownerを保持して
pendingだけ再開する。retrieveには明示時点とscopeを渡し、実際の判断・理由・影響先を
記録したdecisionsがない取得をREUSEDにしない。合成fixtureの意思決定は実エージェント
受入の代わりにしない。
