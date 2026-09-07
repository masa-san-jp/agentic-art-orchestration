# 利用者別初期設定と再開

要件はAAK-SPEC v1のinstance-profile節、実装順はAAK-PLAN v1のAAK-04が正本。
この文書は `workspace.py bootstrap` の操作説明です。

共有profileは `schemas/instance-profile.schema.json` に適合させ、全8 ownerを宣言します。
本人のinstance ID、creator ID、同意、owner別store IDとsource collectionを明示します。
`new-clone` は空の本人領域を作ります。`fork` も新しい本人領域を作り、継承元の
`origin_instance_id` と利用者自身の `fork_remote` を指定します。
このCLIはremoteへpush・Issue作成・PR作成を行いません。
`resume` は保存済みsetupの本人・帰属・同意・保存先を照合します。

外部local configは `schemas/instance-local-config.schema.json` に適合させます。
次は1 owner分だけを示した説明例です。実際には全ownerのstore/code設定が必要です。
絶対pathを含むlocal configと実行stateを共有Gitへcommitしないでください。

```yaml
contract_version: instance-local-config/v1
stores:
  research-memory-b:
    owner: agentic-art-research
    instance_id: instance-b
    creator_id: creator-b
    knowledge_ref: knowledge/creator-b
    path: /absolute/external/research-memory-b
code_sources:
  example/agentic-art-research:
    path: /absolute/external/research-code
    qualified_commits: [<ownerの検証済み40文字commit>]
collections:
  shared-history:
    creator_id: creator-a
    origin_instance_id: instance-a
    readers: [creator-b]
output_destinations:
  contract_version: output-destinations/v1
  profile: local
  destinations:
    state_root: /absolute/external/state
    internal_output_root: /absolute/external/internal
```

ownerの受入証拠を確認してから `qualified_commits` とprofileの `code_commit` を一致させます。
外部local設定は本人のsetup入力であり、資格や同意をコードから自動推定しません。
`source_collections` はread grantと元作者・originを持つ参照で、本人履歴へのコピーではありません。
本人履歴のGit storeはAAK-03のowner契約で初期化します。知識本文の保存は各ownerの正規CLIが行います。
親が子のdomain validatorを代行しません。knowledge refはcreatorの論理refで、
専用storeの `objects.git` にある `refs/heads/knowledge` と固定commitに解決します。

setup成功後、`state/instances/<instance-id>/setup.json` に選択を保存します。
同じrunを再開するときは同じprofile（modeはresumeへ変更可）とrun IDを渡します。
`runs/<run-id>/instance-resolution.json` はcodeとknowledgeを別commitで固定します。
各code checkoutはそのrunの `code/<owner>` です。元のdirty/diverged worktreeには書き込みません。
知識追加後の新runは新しいknowledge commitを読み、過去runは過去commitを維持します。
code更新時は検証済みcommitをprofile/local設定へ追加し、新run IDを使います。
`--dry-run` は変更前の確認専用で、既存履歴の移設や削除をしません。
Pythonの `migration_plan(saved, candidate)` はcode/knowledge別の差分を返し、identity変更を拒否します。

部分初期化後の再実行は成功済みGit storeを保持します。同時bootstrapはstate lockで拒否します。
保存済みidentity、帰属、同意、path、同じrunのcode pin変更は自動採用しません。
変更が必要なら新しい明示setupまたは別途レビューしたmigrationを使用します。

internalはpublic projectionをSKIPPEDと記録します。public-catalogは明示出力先と
public_projection権限が必要で、bootstrap段階はNOT_RUNです。プラン検証と投影を
実行したという意味ではありません。public-seed-onlyはUNMET_PUBLIC_SEED_ONLYです。

前提#190の `repository-relationships/v1` はowner candidate
`bfe777e165a2f9edb19415b6f40f83c901dbaf44` のregistry/schema/validatorを使用します。
Projectはexport-onlyの公式出力先であり、従来の入力manifestへ追加しません。
AAK-04はsynthetic ownerで検証します。実owner統合、実Masa profile、実エージェントの
制作プラン・再利用受入はAAK-02で別に確認します。
