"""backend/task_sync/urgency.py（急ぎ・期限表現の規則ベース検出）の試験（B21）。

- 基準日は 2026-10-01（木）に固定。文例はすべて架空（実在の人・団体・寺の文は使わない）。
- 正解（急ぎかどうか）の決め方:
  急ぎ = 否定されていない急ぎの言葉がある、または期日が基準日から7日以内（過ぎた日を含む）。
  急ぎでない = 急ぎの言葉や日付に似た文字はあるが、否定・別の語の一部・期日が8日以上先・期日ではない。
- 合格線: 急ぎの文例での見逃しは0件（全体の一致率とは別に数える）。
- 紛らわしい文での誤検出は、どの文で起きるかを KNOWN_FALSE_POSITIVE に記録し、件数と率を固定する。
  2026-10-01 時点: 紛らわしい文33件のうち誤検出6件（約18.2%）。
- 注意: 文例と検出器を同じ担当（Claude）が書いたので、数字は甘めに出ている可能性がある。
  本番前の評価は、作問者と規則の作成者を分けて行う。
"""
from __future__ import annotations

from datetime import date

import pytest

from backend.task_sync.urgency import URGENT_WITHIN_DAYS, detect_urgency

TODAY = date(2026, 10, 1)  # 木曜日

# (文, 期待する推定期限, 当たった語に含まれるはずの語)
URGENT_CASES = [
    ("明朝までに見積書を送ってください", "2026-10-02", "明朝"),
    ("明朝の会合の資料を印刷しておいてください", "2026-10-02", "明朝"),
    ("今朝お願いした件、確認をお願いします", "2026-10-01", "今朝"),
    ("本日中にご返信いただけますか", "2026-10-01", "本日中"),
    ("今日中に名簿を直してください", "2026-10-01", "今日中"),
    ("今夜、会場の鍵を返しに行きます", "2026-10-01", "今夜"),
    ("明日朝一で印刷所に電話してください", "2026-10-02", "明日朝一"),
    ("明日の朝一に集金袋を届けます", "2026-10-02", "明日の朝一"),
    ("今週中に回覧板を回してください", "2026-10-04", "今週中"),
    ("5日（月）までに出欠を教えてください", "2026-10-05", "5日(月)までに"),
    ("10/2（金）までに書類を提出", "2026-10-02", "10/2(金)までに"),
    ("10月7日までに会費をお振り込みください", "2026-10-07", "10月7日までに"),
    ("8日（木）締め切りです", "2026-10-08", "8日(木)"),  # ちょうど7日後（境目）
    ("お手数ですが折り返しお電話ください", "2026-10-01", "折り返し"),
    ("折り返しご連絡をお願いいたします", "2026-10-01", "折り返し"),
    ("大至急、会場に来てください", "2026-10-01", "大至急"),
    ("至急ご確認ください", "2026-10-02", "至急"),
    ("急ぎでお願いします", "2026-10-02", "急ぎ"),
    ("早めにご返信ください", "2026-10-04", "早めに"),
    ("なるはやで見積もりをお願いします", "2026-10-04", "なるはや"),
    ("なるべく早く折り返してほしいです", "2026-10-01", "折り返し"),
    ("早急に対応をお願いします", "2026-10-02", "早急"),
    ("緊急の連絡です。すぐにお電話ください", "2026-10-01", "すぐに"),
    ("明日までに印刷をお願いします", "2026-10-02", "明日までに"),
    ("明後日の会議の資料を作る", "2026-10-03", "明後日"),
    ("金曜までに備品を発注", "2026-10-02", "金曜までに"),
    ("来週火曜の会合の出欠", "2026-10-06", "来週火曜"),
    ("今週金曜に集金があります", "2026-10-02", "今週金曜"),
    ("9/30締め切りの書類がまだ届いていません", "2026-09-30", "9/30"),  # 期限切れ
    ("期限の9月28日を過ぎています。至急提出を", "2026-09-28", "至急"),
    ("ASAPで返信ください", "2026-10-04", "ASAP"),
    ("一刻も早くご連絡ください", "2026-10-04", "一刻も早く"),
    ("至急対応が必要ではないかと思います", "2026-10-02", "至急"),  # 「ではないか」は否定ではない
    ("簡単ではありませんが、至急お願いします", "2026-10-02", "至急"),  # 否定は前の節だけ
    ("急がなくていいと言いましたが、やはり今日中にお願いします", "2026-10-01", "今日中"),
    ("今晩中に連絡網を回してください", "2026-10-01", "今晩中"),
    ("直ちに会場の電気を消してください", "2026-10-01", "直ちに"),
    ("２日（金）までにお願いします", "2026-10-02", "2日(金)までに"),  # 全角の数字
    ("１０／３までに返送", "2026-10-03", "10/3までに"),
    ("朝イチで鍵を開けてください", "2026-10-02", "朝イチ"),
    ("急いで書類を届けてください", "2026-10-02", "急いで"),
    ("締め切りは明日です", "2026-10-02", "明日"),
    ("本日17時までに提出してください", "2026-10-01", "本日"),
    ("大至急！見積もりの差し替え", "2026-10-01", "大至急"),
    ("10月6日（火）の会合の資料を至急", "2026-10-02", "至急"),
    ("来週月曜の朝までに準備", "2026-10-05", "来週月曜"),
    ("今月3日までに返送をお願いします", "2026-10-03", "今月3日までに"),
    ("早めのご返信をお願いします", "2026-10-04", "早めのご返信"),
    ("急で申し訳ないのですが、お願いできますか", "2026-10-02", "急で"),
    ("期限が迫っています。ご確認ください", None, "期限が迫"),  # 日付は分からない
    ("なる早でお願いします", "2026-10-04", "なる早"),
    ("週内にご返信ください", "2026-10-04", "週内"),
    ("今週末までに回答をください", "2026-10-04", "今週末までに"),
    ("急な依頼で恐縮です", "2026-10-02", "急な"),
]

# (文, 誤検出として記録済みか, 説明)
CONFUSING_CASES = [
    ("急須を洗っておく", False, "急須は別の語"),
    ("急がなくて大丈夫です。来月の会議で使います", False, "否定・期日は来月"),
    ("至急ではありません。手が空いたときにお願いします", False, "否定"),
    ("急ぎの用ではないので、いつでも結構です", False, "否定"),
    ("早めの夕食にしましょう", False, "早めの＋夕食は頼みごとではない"),
    ("明日葉の苗を植え替える", False, "明日葉は植物の名前"),
    ("急行の時刻表を確認する", False, "急行は別の語"),
    ("来月10日までに提出してください", False, "期日が40日先"),
    ("折り返し地点の看板を作る", False, "頼む言葉が続かない折り返し"),
    ("今日中でなくても大丈夫です", False, "否定"),
    ("明日までに終わらなくても構いません", False, "否定"),
    ("救急箱の中身を確認する", False, "救急は別の語"),
    ("今月中にお願いします", False, "期日が30日先（月初めの基準日）"),
    ("年度末までに名簿を整理", False, "期日が半年先"),
    ("12/20までに年賀状の準備", False, "期日が80日先"),
    ("来週まで返事は急ぎません", False, "急ぎません・期日は10日先"),
    ("早めに寝るようにしています", True, "生活の話の「早めに」も拾う（誤検出）"),
    ("今朝の雨で庭がぬれた", False, "文脈の無い今朝"),
    ("今週中は雨が続くそうです", True, "天気の話の「今週中」も拾う（誤検出）"),
    ("先月の至急案件の振り返りを書く", True, "過去の話の「至急」も拾う（誤検出）"),
    ("「大至急」と書かれた古い貼り紙をはがす", True, "引用の「大至急」も拾う（誤検出）"),
    ("日曜大工の本を読む", True, "日曜大工の「日曜」を次の日曜と読む（誤検出）"),
    ("3日前に頼まれた件は済みました", False, "3日前は日付として読まない"),
    ("1日2回、水やりをする", False, "1日2回は日付として読まない"),
    ("10日分の薬を受け取る", False, "10日分は日付として読まない"),
    ("急遽中止になった会の報告書（来月末まで）", False, "急遽は急ぎの言葉ではない・期日は来月末"),
    ("お急ぎでなければ、来月で構いません", False, "否定（でなければ）"),
    ("すぐに使えるテンプレートを探す", False, "頼む言葉が続かない「すぐに」"),
    ("至急便の空き箱を片付ける", True, "至急便の「至急」も拾う（誤検出）"),
    ("2週間後の会合の準備を始める", False, "期日が14日先"),
    ("取り急ぎお礼まで", False, "取り急ぎは「とりあえず」の意味"),
    ("急な坂道に注意する", False, "急な＋坂道は頼みごとではない"),
    ("早く春が来るといいですね", False, "願いの「早く」"),
]

KNOWN_FALSE_POSITIVE_COUNT = 6
MIN_CASES = 60
MIN_CONFUSING = 20


def test_case_counts():
    assert len(URGENT_CASES) + len(CONFUSING_CASES) >= MIN_CASES
    assert len(CONFUSING_CASES) >= MIN_CONFUSING
    texts = [text for text, *_ in URGENT_CASES + CONFUSING_CASES]
    assert len(set(texts)) == len(texts)


@pytest.mark.parametrize(("text", "due", "word"), URGENT_CASES, ids=[c[0] for c in URGENT_CASES])
def test_urgent_case_is_detected(text, due, word):
    result = detect_urgency(text, today=TODAY)
    assert result.is_urgent, text
    assert word in result.matched, result.matched
    assert (result.due_date.isoformat() if result.due_date else None) == due


def test_no_urgent_case_is_missed():
    """合格線: 急ぎの文例での見逃しは0件。"""
    missed = [text for text, *_ in URGENT_CASES if not detect_urgency(text, today=TODAY).is_urgent]
    assert missed == []


@pytest.mark.parametrize(
    ("text", "known_false_positive", "why"), CONFUSING_CASES, ids=[c[0] for c in CONFUSING_CASES]
)
def test_confusing_case(text, known_false_positive, why):
    result = detect_urgency(text, today=TODAY)
    # 誤検出として記録した文だけが急ぎと出る。新しい誤検出も、直った誤検出も、ここで分かる
    assert result.is_urgent is known_false_positive, (why, result)


def test_false_positive_rate_is_recorded():
    """紛らわしい文での誤検出率を記録する（33件中6件 ≈ 18.2%）。"""
    false_positives = [
        text for text, *_ in CONFUSING_CASES if detect_urgency(text, today=TODAY).is_urgent
    ]
    assert len(false_positives) == KNOWN_FALSE_POSITIVE_COUNT
    rate = len(false_positives) / len(CONFUSING_CASES)
    assert round(rate * 100, 1) == 18.2


def test_negated_words_are_reported_separately():
    result = detect_urgency("至急ではありません。今日中でなくても大丈夫です", today=TODAY)
    assert result.is_urgent is False
    assert result.matched == ()
    assert result.negated == ("至急", "今日中")
    assert result.due_date is None


def test_far_date_gives_estimate_but_is_not_urgent():
    result = detect_urgency("来月10日までに提出してください", today=TODAY)
    assert result.is_urgent is False
    assert result.due_date == date(2026, 11, 10)


@pytest.mark.parametrize(
    ("within_days", "expected"),
    [(URGENT_WITHIN_DAYS, True), (5, True), (4, False), (0, False)],
)
def test_within_days_can_be_changed(within_days, expected):
    # 来週火曜（10/6）は基準日から5日後
    assert URGENT_WITHIN_DAYS == 7
    result = detect_urgency("来週火曜の会合の出欠", today=TODAY, within_days=within_days)
    assert result.is_urgent is expected


def test_base_date_changes_the_answer():
    # 同じ文でも基準日で答えが変わる（基準日は引数で渡す）
    text = "10月7日までに会費をお振り込みください"
    assert detect_urgency(text, today=date(2026, 10, 1)).is_urgent is True
    assert detect_urgency(text, today=date(2026, 9, 20)).is_urgent is False  # 17日先
    sunday = detect_urgency("来週火曜の会合の出欠", today=date(2026, 10, 4))
    assert sunday.due_date == date(2026, 10, 6)  # 週は月曜始まり（日曜に書くと2日後）


def test_today_is_required():
    with pytest.raises(TypeError):
        detect_urgency("至急ご確認ください")  # type: ignore[call-arg]


def test_multiline_text_uses_earliest_due():
    text = "来月10日までに名簿の確認。\nそれと、明日の朝一で鍵を開けてください。"
    result = detect_urgency(text, today=TODAY)
    assert result.is_urgent is True
    assert result.due_date == date(2026, 10, 2)
    assert result.matched == ("明日の朝一",)
