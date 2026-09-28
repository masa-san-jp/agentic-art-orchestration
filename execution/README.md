# 実行証跡から公開カタログを辿る

`execution/` の実行証跡は、その実行時点で観測した公開カタログのパスを
履歴として保持します。Project 側で plan directory の slug が改名されても、証跡の
本文やJSONを書き換えません。

旧パスを現在のパスへ解決するには、親repoの登録簿を使います。

```bash
.venv/bin/python tools/resolve_catalog_path.py \
  plans/P0008-aak07-agent-20260910-p4
# plans/P0008-interrupted-interval-installation
```

登録簿は [`config/catalog-path-aliases.yaml`](../config/catalog-path-aliases.yaml) で、
改名の理由と Project 側の rename commit も保持します。解決は登録された別名を
連鎖して辿り、循環がある場合はエラーで停止します。登録されていないパスは、
改名されていない現在のパスとしてそのまま返します。

同種の改名を追加するときは、Project checkout の Git 履歴から候補を read-only で
生成できます。`--since` は履歴範囲の開始commitで、候補は `since..HEAD` から出力
されます。出力を確認してから、登録簿へ追記します。

```bash
.venv/bin/python tools/resolve_catalog_path.py \
  --from-project-git /absolute/path/to/agentic-art-project \
  --since <known-commit> --format yaml
```

候補生成は登録簿もProject checkoutも変更しません。検証時は次を実行します。

```bash
.venv/bin/python tools/validate.py --check
.venv/bin/python -m unittest tests.test_catalog_path_aliases -v
```
