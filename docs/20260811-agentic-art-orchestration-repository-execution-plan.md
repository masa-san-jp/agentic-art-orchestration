# Agentic Art Orchestration リポジトリ完成実行計画

作成日: 2026-08-11  
対象: masa-san-jp/agentic-art-orchestration  
実行者: GPT-5.6 Luna / Claude Sonnet相当以上  
目標: 会話履歴なしでv1.0.0まで自律実装・検証・再開できること

## Purpose / Big Picture

4つの独立repoを単一workspaceへ安全に展開し、取得commit、契約互換性、依存task、品質ゲート、provenance、機微情報境界を機械検査できるcontrol planeを完成させる。

完成時の主要確認コマンド:

~~~bash
python3 tools/workspace.py init
python3 tools/status.py --format markdown
python3 tools/validate.py --check
python3 tools/audit.py --check
python3 -m unittest discover -s tests -v
~~~

## Progress

- [x] 2026-08-11 M0: 設計、計画、規則、manifest、queue、初期validator/test/CIを作成
- [ ] M1: manifestとworkspace lifecycleを完成
- [ ] M2: signal契約、adapter、consumer、traceを完成
- [ ] M3: work item、scheduler、runtime、quality gate、dispatcherを完成
- [ ] M4: status、Project #4同期、audit、security boundaryを完成
- [ ] M5: offline fixtureとE2E障害試験を完成
- [ ] M6: runbookとv1.0判定を完成

## Surprises & Discoveries

- 2026-08-11: 親repoは完全な空repoだったため、既存実装との互換維持は不要。
- 2026-08-11: art-historyとmarketingは既に独自graph/check運用を持つ一方、self-modelとagentic-art-researchは同日に自律実行ブートストラップされた。全repoへ同一内部構造を要求できない。
- 2026-08-11: marketingの鮮度とself-modelの同意は一般的graph relationへ平坦化できない。共通envelope + domain拡張が必要。

## Decision Log

- D-001: vendor copyではなくmanifest駆動の独立clone。
- D-002: submoduleを必須方式にせずsnapshotで再現性を保証。
- D-003: 共通化はnormalized signalの境界だけ。
- D-004: branch/commit/draft PRまで自動、merge/releaseは人間gate。

詳細は execution/decisions.md を正本とする。

## Outcomes & Retrospective

M0時点では構造と実行可能なqueueを確定した。workspace、adapter、schedulerは未実装であり、運用基盤完成とはまだ言わない。次は MANIFEST-001 で設定schemaとinvalid fixtureを固定する。

## Context and Orientation

| ID | Role | Authority | Bootstrap head |
|---|---|---|---|
| self-model | input-kb | 内面の観測・claim・pattern・同意 | 2ac3180 |
| art-history | input-kb | 芸術史entity・relation・evidence | 8370305 |
| marketing-trends | input-kb | trend・practice・鮮度・反証 | edcb49c |
| agentic-art-research | consumer-runtime | 調査DAG・判断・制作要件・成果物 | 9bfa07d |

親repoはこれらの内容を所有しない。repositories.yamlが入口、workspaceがローカル展開先、dataが生成status/audit/traceである。

## Plan of Work

### M1 — Manifest and workspace

MANIFEST-001でmanifest schema、semantic checks、invalid fixturesを作る。WORKSPACE-001でclone/init/fetch/statusを実装し、offline fake remotesでidempotenceを証明する。WORKSPACE-002はdirty、detached、ahead/behind/divergedを作り、既存treeを変更せずblocking stateへ変換する。SNAPSHOT-001は4repoのimmutable input setをJSON/Markdownへ決定的に出す。

M1完了の観察可能な動作は、clean fixtureで2回initし、2回目の変更件数が0、異常fixtureでGit HEADとworking tree hashが変わらないことである。

### M2 — Contracts and provenance

CONTRACT-001でsignal v1 schemaとvalid/invalid matrixを作る。3adapter taskは各子repoの実データschemaを読んでmappingを文書化し、offline fixtureで契約を検証する。子repo変更が必要なら各子に独立PRを作る。CONSUMER-001はimport version、source commit、unknown、domain constraintを保持する。TRACE-001はoutput requirementからsource entity@commitまで逆引きする。

Self Modelのraw voiceはlocatorのみとし、本文がexportされたfixtureは必ず失敗させる。

### M3 — Runtime

WORKITEM-001でowner repo、dependency、allowed paths、checks、risk、terminal criteriaをschema化する。SCHEDULER-001は選択結果と非選択理由を出す。RUNTIME-001はlease expiry前後、process kill、commit済み/PR未作成、PR作成済み/state未更新の各地点から再開する。GATES-001は変更repoだけを実行し、outputをredact・hash化してstateへ保存する。DISPATCH-001はtask-minimal context packを作る。

M3の中核受入は、kill-and-resumeでcommit/PRを重複させず、同じallowed pathへ2workerを割り当てないこと。

### M4 — Visibility and safety

STATUS-001は人間向けMarkdownと機械向けJSONを同一モデルから出す。PROJECT-001はGitHub Projects #4の優先順位・状態とローカルqueueを重複なく同期し、API障害時もローカル実行を継続する。AUDIT-001はstale pin、contract drift、orphan、freshness、consent、重複task、長期blockerを非blockingで報告する。SECURITY-001はsecretだけでなく、aggregate repo固有のPRIVATE_RAW/RESTRICTED/direct identifierを検知し、context packとbundleから排除する。

### M5 — Offline E2E

4つのsynthetic Git repoを一時directoryへ作り、networkなしでclone、snapshot、adapter、consumer、trace、scheduler、quality gate、status、auditを通す。failure injectionはstale、dirty、diverged、major mismatch、child test failure、secret、consent violation、lease expiry、process killを含む。

### M6 — Operations and release qualification

新規agentがrunbookだけで初期化・task実行・障害回復・handoffできるmanual testを行う。release_check.pyは設計仕様19.2を機械判定可能項目へ対応付け、offline E2Eを3回連続実行する。release tagとmergeは人間gateのまま残す。

## Concrete Steps

### Every session

~~~bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
python3 tools/validate.py --check
python3 -m unittest discover -s tests -v
~~~

期待: exit 0。失敗時は最初のruleを修復し、test/checkを削除しない。

### Task start

~~~bash
git status --short
python3 tools/validate.py --check
~~~

queueからtaskを選び、stateにtask/repo/lease/resume pointを書く。workspace実装後はworkspace statusとsnapshotも実行する。

### Task completion

~~~bash
python3 tools/validate.py --check
python3 -m unittest discover -s tests -v
git diff --check
git status --short
~~~

変更子repoではmanifest記載quality gateをそのrepo rootで実行する。結果をrepo、command、exit code、duration、commitとともにstate/handoffへ記録する。

## Validation and Acceptance

各taskは次をすべて満たすまでDONEにしない。

1. acceptanceを実際のcommand/outputで確認。
2. 正常系と禁止/失敗系testを追加。
3. 親validatorと全testがpass。
4. 変更した子repoのquality gateがpass。
5. generated dataを再生成し、意図しないdiffなし。
6. secret、PRIVATE_RAW、RESTRICTED、direct identifierなし。
7. queue/state/handoff/Progressが実際のGit状態と一致。
8. 次taskと最初の1操作が一意。

## Idempotence and Recovery

- init、fetch、snapshot、status、audit、context pack生成は再実行可能にする。
- partial clone/生成物はtemp pathへ作り、検証後atomic renameする。
- 既存repo pathのremote不一致を自動置換しない。
- lease切れ後はbranch、commit、PR、stateを照合してside effect済み地点から再開する。
- 子repo A成功、B失敗の場合、AをresetせずAのevidenceをcheckpointしBだけ再開する。
- schema migrationは旧version fixtureと移行testを持つまで実行しない。
- GitHub書込失敗時はcommit SHAと再実行対象だけを残し、PRを二重作成しない。

## Interfaces and Dependencies

### Initial commands

- tools/validate.py --check
- tools/workspace.py init|fetch|status|snapshot
- tools/status.py --format json|markdown
- tools/audit.py --check
- tools/trace.py --check
- tools/release_check.py --version VERSION --runs N

### Data interfaces

- config/repositories.yaml
- config/orchestration.yaml
- schemas/repository-manifest.schema.json
- schemas/normalized-research-signal.schema.json
- schemas/work-item.schema.json
- schemas/run-state.schema.json
- execution/task-queue.yaml
- generated data/snapshot.json、status.json、audit.json、trace.json

### Dependencies

- Python 3.11+
- Git 2.39+
- PyYAML 6.x
- private repo read権限、実装時はbranch/commit/draft PR権限
- GitHub Projects連携はv1 coreの必須依存にしない

## Agent continuation rule

task完了後に「次に何をしますか」と質問しない。queue上の次taskをREADYにし、state/handoffを更新して継続する。Stop conditionsに該当した場合のみBLOCKEDとし、必要な決定、選択肢、推奨、影響、解除条件を残す。
