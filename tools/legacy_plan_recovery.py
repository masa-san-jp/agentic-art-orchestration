"""Build explicit recovery handoff bundles from historical Project candidates.

The historical records are inputs only.  This utility never calls an old plan
canonical, and never writes to the Project checkout; current Production owns
the regenerated plan and attestation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import yaml


PROJECT = Path("/Users/masa/マイドライブ/Dev/agentic-art-project")
FIXTURE = Path("/private/tmp/aak07-provider-live-20260910-1/production-merged/tests/fixtures/handoff/minimal")

CANDIDATES = {
    "P0001": ("owner-of-choice", "選択の所有 — Owner of Choice", "e5ff621769a9828ac867cf3fb55e859c79bb46fb", "plans/P0001-owner-of-choice"),
    "P0002": ("moving-gap", "移動する空白 — Moving Gap", "e5ff621769a9828ac867cf3fb55e859c79bb46fb", "plans/P0002-moving-gap"),
    "P0003": ("yohaku-breath", "余白の呼吸 — Yohaku Breath", "e5ff621769a9828ac867cf3fb55e859c79bb46fb", "plans/P0003-yohaku-breath"),
    "P0005": ("close-but-cannot-reach", "近いが届かない — Close but Cannot Reach", "e5ff621769a9828ac867cf3fb55e859c79bb46fb", "plans/P0005-close-but-cannot-reach"),
    "P0006": ("distance-selects-boundary", "距離が境界を選ぶ — Distance Selects Boundary", "dbfa65c33fc254ee4787a9e04cbfc0b5971a7e5a", "plans/P0006-distance-selects-boundary"),
    "P0007": ("near-not-received", "近くても受領されない — Near, Not Received", "d6928e5f7a33dbeb90c5e62ef3899fe65f17373d", "plans/P0007-near-not-received"),
}


# These profiles are the recovery decisions extracted from each historical
# plan.  They intentionally describe different observable works; the
# historical bytes remain provenance only and are never copied as a current
# Production plan.
RECOVERY_PROFILES: dict[str, dict[str, Any]] = {
    "P0001": {
        "completion_image": {
            "encounter": [
                "一つの抽象入力が三枚の半透明パネル上で別々の短い状態列へ分岐して見える。",
                "観客は三面を回り、採用・保留・拒否の三つの手動スイッチから一つを選ぶ。",
                "拒否と保留を選んだ後も、その状態と空白が消えずに残る。",
            ],
            "position": "三面パネルの周囲を歩き、各パネルのラベルとスイッチへ個別に手が届く位置。",
            "first_seconds": "出典・観測・翻訳案・未確定・拒否の役割ラベルと三つの分岐が見える。",
            "after_30s": "同じ入力から複数の翻訳案が生じ、どれも唯一の人物の真実を確定しないと分かる。",
            "after_3min": "採用だけでなく保留と拒否も有効な選択として残り、提案者と選択者が別だと理解できる。",
        },
        "theme": {
            "field": "エージェントの翻訳案と人間が選択を所有する三面の翻訳室",
            "stands_against": "エージェントの出力を本人の内面や唯一の正解として提示し、選択責任を自動提案へ戻す表現。",
            "difference": "三面パネルと採用・保留・拒否スイッチで、拒否と保留を欠陥ではなく保存される状態にする。",
            "why_now": "自動提案が増えるほど、提案を出す者と最終判断を担う者を分けて経験できる必要がある。",
        },
        "message": {
            "claim": "翻訳案を提示する者と、最後に選択する者は同じではない。拒否と保留も選択として残る。",
            "who_disagrees": "自動出力には一つの正解があり、拒否は失敗だと考える立場。",
            "denies": "本作が人物の内面や個人原資料を正しく代弁すること、観客の操作履歴を保存すること。",
            "shown_not_told": "三案の分岐、役割ラベル、三つの操作系、拒否後も消えない空白で示す。",
        },
        "concept": {
            "mechanism": "半透明パネル三面に異なる光と短い状態ラベルを配置し、三つの手動スイッチを採用・保留・拒否へ対応させる。",
            "without_the_technique": "CEASES_TO_WORK",
            "self_repetition_risk": {"reference": "legacy-recovery/repetition-review", "assessment": "他候補の距離や空白を借用せず、分岐と選択状態の持続を固有の検証軸にする。"},
        },
        "research_questions": ["三つの翻訳案の差を、個人情報なしにどのラベルと状態で観察できるか。", "保留と拒否を消去せず残すことで、選択の所有関係は読めるか。"],
        "research_reading": "旧本文の三つの翻訳提案、採用・保留・拒否、役割ラベル、拒否後の保存という記述を制作上の観察条件へ分解した。",
        "research_outcome": "旧候補の選択問題を、三面パネル・三状態スイッチ・持続する空白として再構成した。",
        "requirement": "Construct a three-panel translation room where one abstract input branches into three labeled proposals and a viewer can choose adopt, hold, or reject; hold and reject remain visible states and no personal source is retained.",
        "prototype_title": "Three-state translation room",
        "materials": "Three translucent panels, low-luminance labels, three manual switches, non-personal abstract input cards, and a state display that preserves HOLD and REJECT.",
        "task_title": "Build and test the three-state translation room",
        "acceptance_condition": "A reviewer can trace one input into three proposals and observe ADOPT, HOLD, and REJECT as distinct persistent states without personal source material.",
    },
    "P0002": {
        "completion_image": {
            "encounter": ["異なる二つの伝統を示す二層の面が離れて見え、二方向の接近経路が用意されている。", "観客が一方から近づくと片方の記号が読みやすくなり、中央の局所的な隙間が交換を止めている。", "反対方向へ移ると別の面が現れるが、接触や融合は起こらない。"],
            "position": "二つの進入方向と中央の停止点を、座ったままでも比較できる位置。",
            "first_seconds": "二層の面、異なる記号系、中央の隙間、二つの進入方向が一度に見える。",
            "after_30s": "接近で得られる知識は増えるが、相手の面へ介入できるわけではないと分かる。",
            "after_3min": "二つの伝統を均質な系譜へ混ぜず、隙間を保ったまま限定的に交換できる経験が残る。",
        },
        "theme": {"field": "異なる二つの伝統のあいだに残る局所的な隙間と限定的な交換", "stands_against": "異なる文化的形式を一つの均質な起源へ混ぜ、接近を同化や介入として扱う見方。", "difference": "二方向の移動、二層の面、中央の局所的な隙間を組み合わせ、接触なしの交換を構成する。", "why_now": "参照元が近接する時代ほど、知ることと介入することを分けた観察の形式が必要になる。"},
        "message": {"claim": "近づくと知識は増えるが、近づいた者が相手の形式を動かせるとは限らない。", "who_disagrees": "二つの伝統は接近すれば自然に融合し、差異は消えると考える立場。", "denies": "特定の伝統を代表したり、霧・鏡・監視カメラ・再演で文化的経験を代用したりすること。", "shown_not_told": "二つの非対称な面、二方向の読解、中央の隙間、触れない停止点で示す。"},
        "concept": {"mechanism": "異なる記号を載せた二層の平面とフレームをずらして重ね、二方向の低速な接近経路と中央の局所的な隙間を設ける。", "without_the_technique": "CEASES_TO_WORK", "self_repetition_risk": {"reference": "legacy-recovery/repetition-review", "assessment": "P0001の分岐スイッチや他候補の空間移動を使わず、二方向の読解と非接触の隙間を評価する。"}},
        "research_questions": ["二つの伝統を混同せずに、二方向から得る知識の差をどう可視化できるか。", "局所的な隙間は接触なしの交換の限界として読めるか。"],
        "research_reading": "旧本文の丸山と四条という異なる参照、二つの接近経路、層状の面、局所的な停止点、非接触の観察条件を抽出した。",
        "research_outcome": "二つの伝統を均質化しない二層平面と、方向ごとに異なる読解を生む隙間を採用した。",
        "requirement": "Construct a two-direction layered plane study in which two distinct traditions remain visibly separate, a local gap limits exchange, and observers gain different knowledge by moving slowly from either side without touching or performing the traditions.",
        "prototype_title": "Two-direction moving gap",
        "materials": "Two separately authored abstract mark systems, offset translucent planes, a rigid frame, floor direction markers, and a marked non-contact stop point; no fog, mirror, CCTV, or reenactment.",
        "task_title": "Test two-direction reading without contact",
        "acceptance_condition": "Blind reviewers identify two non-identical mark systems and the local gap, and report different readable information from the two approach directions without physical contact.",
    },
    "P0003": {
        "completion_image": {"encounter": ["入口からは構成全体が読めるが、近づくと細部の線や欠けだけが大きく見える。", "観客が横へ移動すると細部と全体のどちらを得るかが変わり、固定された鑑賞順はない。", "離れて別の角度へ戻ると、先ほど見えなかった全体の関係が再び現れる。"], "position": "観客が自由に前後左右へ移動し、距離と角度を自分で選べる範囲。", "first_seconds": "全体像と、近づくと隠れる一部のディテールが同時に予告される。", "after_30s": "細部を得る代わりに全体を失い、離れると全体を得る代わりに細部を失うと分かる。", "after_3min": "最初の立ち位置が唯一の正解ではなく、見る位置を選び直すこと自体が作品の構造だと残る。"},
        "theme": {"field": "近さの細部と距離の全体を選び直す鑑賞", "stands_against": "作品には一つの正しい立ち位置や、順番どおりに進む鑑賞ルートがあるという見方。", "difference": "距離と角度に応じて細部と全体の可視性を交換し、観客の自由な再配置を必須の機構にする。", "why_now": "画面上の拡大縮小が容易な時代に、身体の位置を変えることで失うものと得るものを再び経験させる。"},
        "message": {"claim": "近づけば細部が、離れれば全体が見える。どちらを選ぶかに唯一の正解はない。", "who_disagrees": "近くで詳しく見るほど、作品全体も同時に理解できると考える立場。", "denies": "本作が治療効果や健康上の利益を約束すること、観客に固定ルートや演技を要求すること。", "shown_not_told": "距離・角度ごとの遮蔽、細部の拡大、全体の回復、自由な移動の痕跡で示す。"},
        "concept": {"mechanism": "視線の高さを越える線群と部分的な遮蔽を配置し、近距離では細部、遠距離では全体の構図が優先される視覚的トレードオフを作る。", "without_the_technique": "CEASES_TO_WORK", "self_repetition_risk": {"reference": "legacy-recovery/repetition-review", "assessment": "固定停止線や状態スイッチを設けず、自由な位置変更と細部/全体の交換を固有の条件にする。"}},
        "research_questions": ["細部と全体の交換を、観客が身体で再現できる遮蔽として設計できるか。", "固定ルートなしでも、距離と角度の選択が作品として読めるか。"],
        "research_reading": "旧本文の近接で細部、遠景で全体、観客が位置と角度を変える、固定された道筋を置かないという条件を抽出した。",
        "research_outcome": "距離と角度で可視情報が交換される、自由移動型の視覚配置として再構成した。",
        "requirement": "Construct a freely navigable visual arrangement where moving close reveals detail while moving away restores the whole, and changing angle changes the available information; no fixed route or forced performance is allowed.",
        "prototype_title": "Detail/whole repositioning study",
        "materials": "Layered line drawings, freestanding translucent screens, low-contrast occluders, and floor space allowing free front/back/side movement; no health claims or scripted route.",
        "task_title": "Observe the detail/whole trade-off from free positions",
        "acceptance_condition": "Reviewers can demonstrate at least two positions where detail and whole are exchanged, without a prescribed route, performance, or therapeutic claim.",
    },
    "P0005": {
        "completion_image": {"encounter": ["遠くに匿名の人影または抽象像が見え、観客はその前に置かれた枠へ近づく。", "近づくほど、枠や窓が描かれた側ではなく観客側に属していると分かる。", "相手側には梯子・階段・ロープ・到達目標がなく、近さだけでは届かない配置が残る。"], "position": "枠の手前で、枠を通して像を見る位置と、枠の構造自体を見る位置の両方。", "first_seconds": "像と枠の距離が見えるが、枠の所有側はすぐには確定しない。", "after_30s": "枠を越える方法ではなく、観客の立場が届かなさを作っていると気づく。", "after_3min": "自分の身体位置が作品の構成要素であり、相手の物語を所有していないと理解できる。"},
        "theme": {"field": "観客側に置かれた枠がつくる、近いのに届かない関係", "stands_against": "届かなさを距離の不足や努力不足として扱い、相手側に到達用の装置や物語を置く表現。", "difference": "枠/窓を観客側へ置き、相手側には到達目標を置かず、身体位置と視界の関係だけで不達を構成する。", "why_now": "画像や他者を見られることと、その他者へアクセスできることが混同されやすいため、見る側の立場を可視化する。"},
        "message": {"claim": "届かないのは距離だけの問題ではなく、誰が枠を持ち、誰を見ているかの問題である。", "who_disagrees": "努力して近づけば、見る側は相手へ到達できると考える立場。", "denies": "描かれた人物の同定、借用画像の内容、相手側にある梯子や目標による物語の誘導。", "shown_not_told": "観客側の枠、匿名像、空の向こう側、位置による遮蔽で示す。"},
        "concept": {"mechanism": "匿名の遠景像の手前に観客側の物理フレーム/窓を置き、像へ近づくほどフレームの縁と自分の位置が視界を占めるようにする。", "without_the_technique": "CEASES_TO_WORK", "self_repetition_risk": {"reference": "legacy-recovery/repetition-review", "assessment": "他候補の停止線やセル配置を避け、観客側の枠の所有と匿名性を盲検で確認する。"}},
        "research_questions": ["枠を観客側に置いたとき、届かなさを距離以外の関係として読めるか。", "像の匿名性と盲検レビューで、他者の同定や借用内容への依存を避けられるか。"],
        "research_reading": "旧本文の遠景像、観客側に属する枠、相手側に梯子等を置かない条件、身体位置の一部化、盲検と借用画像禁止を抽出した。",
        "research_outcome": "到達装置を置かず、観客側の枠と匿名像の関係を中心に据えた。",
        "requirement": "Construct a viewer-side frame or window in front of an anonymous distant figure or abstract image so that the figure remains near but unreachable because of the viewing position; no ladder, stairs, rope, goal, identifying person, or borrowed image content may be used.",
        "prototype_title": "Viewer-side frame study",
        "materials": "Original anonymous silhouette or abstract image, a rigid frame/window mounted on the viewer side, neutral backing, and position markers; no identifying person or borrowed image.",
        "task_title": "Blind-review the ownership of the frame",
        "acceptance_condition": "Blind reviewers locate the frame on the viewer side and describe the unreachable relation without inventing an access device or identifying the depicted figure.",
    },
    "P0006": {
        "completion_image": {"encounter": ["観客は透明なポリカーボネート面の450mm手前で止まり、面の向こうに歪んだ線画が見える。", "4枚以上の線画と低彩度の色が、30秒周期の暖色光の変化と10秒以上の静止区間でゆっくり切り替わる。", "1200mmの通路を歩いても触れられず、静止して見る時間が残る。"], "position": "幅1200mm以上の通路から面へ近づき、450mm停止線の手前で非接触に観察する位置。", "first_seconds": "透明面、停止線、向こう側の歪んだ線画、通路の幅が同時に読める。", "after_30s": "光の変化と静止区間が線画の見え方を変えるが、観客の接触やセンサー反応ではないと分かる。", "after_3min": "近づくほど見えるが、手は届かない距離が注意をつくり、健康効果ではなく境界の経験として残る。"},
        "theme": {"field": "近接・休止・非接触を、透明面と光の静止区間で測る境界", "stands_against": "没入や接触の強さを健康効果や睡眠改善の数値で正当化する展示。", "difference": "450mm停止線、4枚以上の歪んだ線画、30秒光周期と10秒以上の静止、1200mm通路を同時に検証する。", "why_now": "近接を促す展示ほど、近づいても触れない安全な距離と、変化しない時間を設計条件として明示する必要がある。"},
        "message": {"claim": "近づくほど見えるが、手は届かない距離が注意をつくる。休止は効果ではなく構成である。", "who_disagrees": "体験の価値は接触、没入、健康指標で測るべきだと考える立場。", "denies": "治療・睡眠・身体状態への効果、カメラ/マイク/生体計測、観客の接触を前提にすること。", "shown_not_told": "停止線、透明面、歪んだ線画、暖色光の静止区間、非接触の通路で示す。"},
        "concept": {"mechanism": "1800x2100mmの透明ポリカーボネート面の向こうへ4枚以上の歪んだ線画を置き、450mmの停止線と30秒周期の暖色光（10秒以上静止）を組み合わせる。", "without_the_technique": "CEASES_TO_WORK", "self_repetition_risk": {"reference": "legacy-recovery/repetition-review", "assessment": "P0005の枠/匿名像やP0003の自由移動を再利用せず、寸法・停止線・光周期・通路幅を固有のゲートにする。"}},
        "research_questions": ["停止線と透明面は、近接と非接触を同時に読ませられるか。", "10秒以上の光の静止区間は、効果を主張せず休止の構成として観察できるか。"],
        "research_reading": "旧本文の透明ポリカーボネート寸法、450mm停止線、4枚以上の歪んだ線画、低彩度、30秒光周期、10秒静止、1200mm通路、センサー禁止を採用条件へ戻した。",
        "research_outcome": "寸法と時間のゲートを持つ、非接触の光学インスタレーションとして再構成した。",
        "requirement": "Prototype a non-contact installation with a transparent 1800x2100mm surface, a 450mm stop line, at least four distorted line drawings, a 30-second warm-light cycle with a still interval of at least 10 seconds, a 1200mm access path, and no cameras, microphones, biometric data, or health claims.",
        "prototype_title": "450mm non-contact light boundary",
        "materials": "Transparent polycarbonate 1800x2100mm, four or more original distorted line drawings, low-saturation pigment, warm light source with a 30-second timer, floor stop-line tape, and a 1200mm access layout.",
        "task_title": "Measure the non-contact light boundary",
        "acceptance_condition": "A safety reviewer measures the 450mm stop line and 1200mm path, observes a 30-second cycle including a 10-second still interval, and confirms no sensing or health claim is present.",
    },
    "P0007": {
        "completion_image": {"encounter": ["A3サイズの浅い透明な閉箱の36セルに、35個の紙包みと一つの空セルが並ぶ。", "一つの包みは観客に近いが、箱を開けずには触れられず、状態カードの語だけが変化を示す。", "電池式LEDと固定された影板が、送付や受領を実行せず、近さと受領不能を卓上で閉じる。"], "position": "箱を動かさず、外周から全36セルと状態カードを比較できる卓上の位置。", "first_seconds": "35個の包み、一つの空セル、近いが届かない包み、閉じた箱が一望できる。", "after_30s": "APPROACHやHELDなどの状態語は見えても、実際の配送先や受取人は存在しないと分かる。", "after_3min": "近くにあることは届いたことでも介入できたことでもなく、NOT RECEIVEDが完成状態として残る。"},
        "theme": {"field": "近接と受領を切り分ける、閉じた卓上の不在構造", "stands_against": "近いものは受け取られ、状態表示は現実の配送や相手への介入を意味すると考える見方。", "difference": "6x6の36セル、35包みと空セル、一つの近いが不可触な包み、9状態カード、固定光源を一つの閉箱に収める。", "why_now": "通知や送信の近さが受領と混同されやすい中、相手の個人情報なしに不受領を完成状態として観察できる。"},
        "message": {"claim": "近くにいることは、届いたことでも介入できたことでもない。受領されない状態も完成している。", "who_disagrees": "接近・送信・表示があれば、相手への到達と受領が成立すると考える立場。", "denies": "実在の配送、受取人、追跡番号、開閉機構、動く機械、LEDを相手の反応として読むこと。", "shown_not_told": "36セルの数、空セル、閉箱、状態語、固定影、動かないLEDで示す。"},
        "concept": {"mechanism": "A3卓上の浅い閉じた透明箱を6x6=36セルに区切り、35個の同型紙包みと一つの空セルを置く。近いが不可触の包み、9状態カード、電池式LED、固定影板を添える。", "without_the_technique": "CEASES_TO_WORK", "self_repetition_risk": {"reference": "legacy-recovery/repetition-review", "assessment": "他候補の歩行・停止線・分岐を使わず、卓上の固定配置、36セル、受領状態語、予算/時間制約を固有の軸にする。"}},
        "research_questions": ["36セル中の一つの空白は、受領不能を物理的な完成状態として読ませられるか。", "状態カードを実配送や受取人なしで使うとき、介入と受領の混同を避けられるか。"],
        "research_reading": "旧本文のA3卓上物、浅い閉透明箱、6x6=36セル、35包みと空セル、近いが不可触の包み、9状態カード、固定LED/影、予算15,000円以下・10時間以下を抽出した。",
        "research_outcome": "外部送信を行わない閉箱の数的配置として、受領不能を卓上で完結させた。",
        "requirement": "Build an A3 tabletop closed box with a 6x6 grid of 36 cells, 35 identical paper packets plus one empty cell, one closer but inaccessible packet, nine state cards, a battery LED, and a fixed shadow plate; keep budget at or below JPY 15,000, work at or below 10 hours, and perform no real shipping.",
        "prototype_title": "36-cell near-not-received box",
        "materials": "A3 shallow transparent closed box, dividers for 36 cells, 35 identical original paper packets, one empty cell, nine printed state cards, battery LED, and fixed shadow plate.",
        "task_title": "Assemble and count the closed receipt box",
        "acceptance_condition": "A reviewer counts 36 cells, 35 packets, and one empty cell; identifies the inaccessible near packet and NOT RECEIVED state; and confirms budget/time and no real recipient or shipment data.",
    },
}


def sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def dump_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")


def git_show(commit: str, locator: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(PROJECT), "show", f"{commit}:{locator}"], stderr=subprocess.STDOUT)


def make_brief(title: str, legacy_id: str, old_body: str) -> dict[str, Any]:
    profile = RECOVERY_PROFILES[legacy_id]
    first_lines = [line.strip() for line in old_body.splitlines() if line.strip() and not line.startswith("#")]
    historical_signal = " ".join(first_lines[:2])[:300]
    return {
        "schema_version": "1.0.0", "brief_id": "PB" + legacy_id[1:], "revision": 1,
        "completion_image": profile["completion_image"],
        "theme": profile["theme"],
        "message": profile["message"],
        "concept": {
            **profile["concept"],
            "precedents": [{"reference": f"legacy/{legacy_id}/historical-plan", "difference": "歴史的候補の固有条件を由来として保持し、現行Productionの構造化された制作判断と検証可能な工程へ置き換える。"}],
        },
        "research_summary": {
            "questions": profile["research_questions"],
            "what_was_read": f"Projectの履歴commit {legacy_id} の公開plan本文とmetadataを由来資料として読み、旧候補の主題と未確定事項を分離した。固有条件は {profile['research_reading']} 主要な旧記述は {historical_signal}。",
            "what_came_out": profile["research_outcome"],
            "what_is_not_settled": "会場条件、物理試作、歴史的参照の最終妥当性、日程と費用は人間の制作前レビュー前である。",
        },
    }


def make_bundle(legacy_id: str, out_root: Path) -> dict[str, str]:
    slug, title, commit, plan_dir = CANDIDATES[legacy_id]
    old_body = git_show(commit, plan_dir + "/plan.md").decode("utf-8")
    old_body_hash = hashlib.sha256(old_body.encode("utf-8")).hexdigest()
    bundle = out_root / "bundles" / legacy_id
    if bundle.exists():
        shutil.rmtree(bundle)
    shutil.copytree(FIXTURE, bundle)
    artifacts = bundle / "artifacts"
    brief = make_brief(title, legacy_id, old_body)
    dump_yaml(artifacts / "production-brief.yaml", brief)
    profile = RECOVERY_PROFILES[legacy_id]
    direction = f"# Legacy recovery: {title}\n\nThis is a regenerated Production input for historical Project candidate {legacy_id}. The historical body is evidence only and is not treated as a canonical Production artifact.\n\nDistinct production direction: {profile['concept']['mechanism']}\n\nThe regenerated plan must preserve this candidate-specific question while recording all unresolved venue, rights, safety, schedule, and budget checks.\n"
    (artifacts / "creative-direction.md").write_text(direction, encoding="utf-8")
    requirement = profile["requirement"]
    dump_yaml(artifacts / "production-requirements.yaml", {"requirements": [{"id": "RQ001", "statement": requirement, "priority": "mandatory", "deliverable_title": title, "deliverable_type": "production-plan", "owner_capability": "artist and venue-safety reviewer", "parameter": "observable-proposition", "acceptance_test_ids": ["AT001"]}]})
    dump_yaml(artifacts / "production-hypotheses.yaml", {"hypotheses": [{"id": "PH001", "title": title, "proposition": requirement, "owner_capability": "artist and venue-safety reviewer", "source_decision_ids": ["DC001"], "status": "ADOPTED"}]})
    dump_yaml(artifacts / "prototype-plans.yaml", {"prototype_plans": [{"id": "PP001", "title": profile["prototype_title"], "owner_capability": "artist and venue-safety reviewer", "requirement_ids": ["RQ001"], "deliverable_ids": ["DL001"], "resources": [{"id": "RSRC001", "type": "PERSON_CAPABILITY", "capability": "artist and venue-safety reviewer", "quantity": {"value": "1", "unit": "item"}, "availability": "REQUIRES_CONFIRMATION"}], "materials": [{"id": "MTRL001", "name": profile["prototype_title"], "specification": profile["materials"], "quantity": {"value": "1", "unit": "item"}, "rights_status": "PROJECT_INTERNAL", "safety_status": "REVIEW_REQUIRED", "status": "CANDIDATE"}], "tasks": [{"id": "PT001", "title": profile["task_title"], "effect_type": "PHYSICAL_EXTERNAL", "duration": {"value": "2", "unit": "h"}, "required_resource_ids": ["RSRC001"], "required_material_ids": ["MTRL001"], "acceptance_condition": profile["acceptance_condition"], "status": "READY"}, {"id": "PT002", "title": "Validate the regenerated plan references", "effect_type": "READ_ONLY", "duration": {"value": "10", "unit": "min"}, "acceptance_condition": "The recovered source reference and current plan graph remain traceable.", "status": "READY", "depends_on": ["PT001"]}]}]})
    dump_yaml(artifacts / "acceptance-tests.yaml", {"acceptance_tests": [{"id": "AT001", "target_requirement": "RQ001", "method": "structured-plan-and-prototype-review", "pass_condition": profile["acceptance_condition"], "result": "NOT_RUN"}]})
    dump_yaml(artifacts / "hypothesis-comparison.yaml", {"comparisons": [{"id": "HC001", "hypothesis_ids": ["PH001"], "rationale": "The candidate-specific physical arrangement is retained as the testable proposition; no generic substitute is introduced."}]})
    # Production's source-reference contract requires HTTPS.  Keep the
    # commit and locator in the structured provenance fields, while exposing
    # only the repository root at the public-plan boundary.
    opaque_ref = "https://github.com/masa-san-jp/agentic-art-project"
    dump_yaml(artifacts / "source-ref-index.yaml", {"source_project": f"legacy-recovery/{legacy_id.lower()}", "references": [{"id": "DC001", "kind": "decision", "source_path": plan_dir + "/plan.md", "reference_categories": ["CONCEPT"], "access_url": opaque_ref, "record_hash": "sha256:" + old_body_hash, "summary": f"Historical Project candidate {legacy_id}; evidence only, not current Production canonical."}, {"id": "IN001", "kind": "insight", "source_path": plan_dir + "/metadata.yaml", "reference_categories": ["METHOD"], "access_url": opaque_ref, "record_hash": "sha256:" + hashlib.sha256(git_show(commit, plan_dir + "/metadata.yaml")).hexdigest(), "summary": "Historical metadata used to preserve provenance while regenerating the plan."}]})
    handoff = {"schema_version": "1.0.0", "handoff_id": "HO" + legacy_id[1:], "revision": 1, "status": "READY", "research_project_id": f"legacy-recovery/{legacy_id.lower()}", "research_project_version": "1.0.0", "research_commit": commit, "generated_at": "2026-09-10T16:00:00+09:00", "selection": {"status": "AGENT_RECOMMENDED", "selected_hypothesis_id": "PH001", "alternative_hypothesis_ids": [], "authority": "AGENT", "human_approval_required": False}, "creative_direction_ref": "artifacts/creative-direction.md", "requirements": [{"id": "RQ001", "statement": requirement, "priority": "mandatory", "source_decision_ids": ["DC001"], "acceptance_test_ids": ["AT001"]}], "prototype_plan_ids": ["PP001"], "constraints": {"rights": ["Use only original, non-sensitive plan and prototype material."], "safety": ["No physical or external effect is authorized by plan generation."], "privacy": ["Do not use names, addresses, tracking numbers, or real recipient data."], "prohibited_actions": ["Do not purchase, contract, publish, send, contact, delete, or perform physical work automatically."]}, "open_gaps": [{"id": "GP001", "statement": f"The original accepted Production handoff for {legacy_id} is unavailable; this is an explicitly regenerated recovery plan, not byte-identical recovery.", "impact": "Historical meaning and current Production provenance must remain distinguishable.", "blocking": False, "resolution_owner": "artist and production reviewer", "resolution_condition": "Review the regenerated plan and record any new accepted handoff revision."}], "replan_triggers": ["venue_changed", "rights_or_privacy_change", "new_historical_evidence"], "source_refs": {"decision_ids": ["DC001"], "insight_ids": ["IN001"], "evidence_ids": []}}
    handoff["integrity"] = {"content_sha256": sha256(canonical(handoff))}
    dump_yaml(bundle / "production-handoff.yaml", handoff)
    provenance = {"source_commit": commit, "source_tree_clean": True, "source_schema": {"path": "schemas/production-handoff.schema.json", "sha256": sha256((bundle / "schemas/production-handoff.schema.json").read_bytes())}, "generated_at": handoff["generated_at"], "source_repository": "masa-san-jp/agentic-art-project", "source_locator": plan_dir}
    dump_yaml(bundle / "provenance.yaml", provenance)
    files = []
    roles = {"production-handoff.yaml": "HANDOFF", "provenance.yaml": "PROVENANCE", "schemas/production-handoff.schema.json": "SCHEMA", "artifacts/acceptance-tests.yaml": "ACCEPTANCE_TESTS", "artifacts/creative-direction.md": "CREATIVE_DIRECTION", "artifacts/hypothesis-comparison.yaml": "HYPOTHESIS_COMPARISON", "artifacts/production-brief.yaml": "PRODUCTION_BRIEF", "artifacts/production-hypotheses.yaml": "HYPOTHESES", "artifacts/production-requirements.yaml": "REQUIREMENTS", "artifacts/prototype-plans.yaml": "PROTOTYPE_PLANS", "artifacts/source-ref-index.yaml": "SOURCE_REF_INDEX"}
    for relative in sorted(roles):
        raw = (bundle / relative).read_bytes()
        files.append({"path": relative, "role": roles[relative], "media_type": "text/markdown" if relative.endswith(".md") else ("application/schema+json" if relative.startswith("schemas/") else "application/yaml"), "size_bytes": len(raw), "sha256": sha256(raw)})
    manifest = {"bundle_schema_version": "1.0.0", "bundle_id": f"HB-HO{legacy_id[1:]}-R1", "entrypoint": "production-handoff.yaml", "handoff_key": {"handoff_id": handoff["handoff_id"], "revision": 1}, "files": files}
    manifest["integrity"] = {"file_set_sha256": sha256(canonical([{key: item[key] for key in ("path", "size_bytes", "sha256")} for item in files]))}
    dump_yaml(bundle / "manifest.yaml", manifest)
    return {"legacy_id": legacy_id, "slug": slug, "title": title, "source_commit": commit, "source_locator": plan_dir + "/plan.md", "source_body_sha256": old_body_hash, "bundle": str(bundle)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--candidate", choices=sorted(CANDIDATES))
    args = parser.parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    ids = [args.candidate] if args.candidate else list(CANDIDATES)
    result = [make_bundle(identifier, args.output_root) for identifier in ids]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
