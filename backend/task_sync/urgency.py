"""
============================================================
urgency.py — 急ぎ・期限表現の規則ベース検出（B21）
============================================================
寺務などの下仕分けの補助として、文の中から「急ぎ」の手がかりを拾う。
LLM の判定の見逃しを、計算で確かめられる規則で補うための独立した部品。
画面や API にはまだつないでいない。外部への送信も、外部 API の利用もしない。

急ぎ（is_urgent=True）とするもの:
- 否定されていない急ぎの言葉
  （大至急・至急・早急・緊急・急ぎで・急いで・急で申し訳ない・急なお願い・期限が迫って・
    直ちに・本日中・今日中・今夜・今晩・明朝・明日朝一・朝一・今週中・週内・早めに・
    なるはや・なる早・なるべく早く・ASAP・
    折り返し（＋連絡・電話・お願い など）・すぐに（＋ください など）・
    今朝（＋まで・お願いした・いただいた など））
- 推定期限が基準日から URGENT_WITHIN_DAYS 日以内（過ぎた日を含む）の日付の書き方
  （5日（月）まで・10/2まで・明日まで・金曜まで・来週火曜 など。日付の読み方は
    date_rules と同じ規則）

急ぎにしないもの:
- 否定（至急ではありません・今日中でなくても大丈夫・急ぎません・お急ぎでなければ）
- 別の語の一部（急須・急行・救急・明日葉・取り急ぎ）、文脈の無い「折り返し」「すぐに」「今朝」
- 期日が URGENT_WITHIN_DAYS 日より先（来月10日まで・年度末まで・今月中（月初め））

見逃し0を優先しているので、紛らわしい文で急ぎと出ること（誤検出）がある。
試験の文例と誤検出率は tests/test_urgency.py にある。
基準日 today は必ず引数で渡す（実行日に依存させない）。
============================================================
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from .date_rules import find_due_mentions
from .models import DueType

# ═══════════════════════════════════════════════════════════════
# 定数
# ═══════════════════════════════════════════════════════════════

# 推定期限が基準日から何日以内なら急ぎとするか（0 = 今日。過ぎた日も急ぎ）
URGENT_WITHIN_DAYS = 7

# 急ぎの言葉ごとの推定期限（基準日から何日後か）。"week" は今週の日曜、None は日付が分からない
_TODAY = 0
_TOMORROW = 1
_SOON = 3  # date_rules.SOON_OFFSET_DAYS と同じ
_THIS_WEEK = "week"

# 「折り返し」「すぐに」が急ぎになるのは、後ろに頼む言葉が続くとき
_REQUEST = r"(?=[^。!?\n]{0,8}?(?:連絡|電話|返信|返事|お願い|くださ|下さ|願い|ほしい|欲しい|対応|来て|送って))"

# 上から順に当てる（長い語を先に。当たった部分は次の語の対象から外す）
_KEYWORDS: tuple[tuple[str, object], ...] = (
    (r"大至急", _TODAY),
    (r"至急", _TOMORROW),
    (r"早急", _TOMORROW),
    (r"緊急", _TODAY),
    (r"急用", _TODAY),
    (r"(?<!取り)(?:お|大)?急ぎ(?!ません)|急いで", _TOMORROW),  # 取り急ぎ（とりあえずの連絡）は数えない
    (r"急で(?=申し訳|すみません|恐縮|悪い)|急な(?=お願い|ご?依頼|お話|話|ご?連絡|変更)", _TOMORROW),
    (r"(?:期限|締め切り|締切|〆切)(?:が|は)?(?:迫|近づ|近い)", None),  # 日付は分からない
    (r"直ちに|ただちに", _TODAY),
    (r"本日中|今日中", _TODAY),
    (r"今夜中?|今晩中?", _TODAY),
    (r"明日の?朝一|明日の?朝イチ|明朝", _TOMORROW),
    (r"朝一|朝イチ", _TOMORROW),
    (r"今週中|今週内|(?<![来再])週内", _THIS_WEEK),
    (r"早めに|早めの(?:ご|お)?(?:対応|返信|連絡|返事|提出|確認)", _SOON),
    (r"なるはや|なる早|ナルハヤ|(?:なるべく|できるだけ|できる限り|一刻も|一日も)早く"
     r"|早く(?:ご|お)?(?:返信|連絡|対応|確認|返事)", _SOON),
    (r"ASAP", _SOON),
    (r"折り返し" + _REQUEST, _TODAY),
    (r"すぐに?" + _REQUEST, _TODAY),
    (r"今朝(?=まで|中|の件|の分|の(?:ご|お)?依頼|頼まれ|お願いし|いただい|頂い)", _TODAY),
)
_KEYWORD_RES = tuple((re.compile(pattern, re.IGNORECASE), offset) for pattern, offset in _KEYWORDS)

# 急ぎの言葉としては数えない日付の種類（言葉のほうで数える）
_SKIP_MENTION_TYPES = {DueType.URGENT, DueType.SOON}

# 当たった語の後ろの「否定」（同じ節の中だけを見る）。「ではないか」は否定にしない
_NEGATION_RE = re.compile(
    r"(?:では|じゃ|で)(?:なく|ない(?!か)|ありません(?!か)|ございません)"
    r"|(?:なくても|なくて)(?:いい|よい|良い|大丈夫|結構|構いません|かまいません|問題ありません)"
    r"|でなければ"
)

# 節の区切り（否定がどこまで届くか）
_CLAUSE_RE = re.compile(r"[^。!?\n、,;]+")

# 日付の後ろの曜日の注記と「まで」（当たった語の表示に含める）
_MENTION_TAIL_RE = re.compile(r"\s*(?:\([月火水木金土日](?:・?祝)?\))?\s*(?:までに|まで|迄)?")


# ═══════════════════════════════════════════════════════════════
# 結果
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class UrgencyResult:
    """急ぎの検出結果"""
    is_urgent: bool  # 急ぎか
    matched: tuple[str, ...]  # 急ぎと判断した語（文の中の順）
    due_date: Optional[date]  # 推定期限（否定されていない手がかりのうち、いちばん早い日）。無ければ None
    negated: tuple[str, ...] = ()  # 否定されていたので数えなかった語


@dataclass(frozen=True)
class _Hit:
    text: str
    start: int
    end: int
    due: Optional[date]
    is_keyword: bool


# ═══════════════════════════════════════════════════════════════
# 検出
# ═══════════════════════════════════════════════════════════════

def _keyword_due(offset: object, today: date) -> Optional[date]:
    if offset is None:
        return None
    if offset == _THIS_WEEK:
        return today + timedelta(days=6 - today.weekday())  # 今週の日曜（月曜始まり）
    assert isinstance(offset, int)
    return today + timedelta(days=offset)


def _find_hits(text: str, today: date) -> list[_Hit]:
    hits: list[_Hit] = []
    work = text
    for pattern, offset in _KEYWORD_RES:
        for match in pattern.finditer(work):
            hits.append(_Hit(match.group(0), match.start(), match.end(), _keyword_due(offset, today), True))
        work = pattern.sub(lambda match: "\x00" * len(match.group(0)), work)

    for mention in find_due_mentions(text, today=today):
        if mention.due_type in _SKIP_MENTION_TYPES:
            continue
        if any(hit.start < mention.end and mention.start < hit.end for hit in hits if hit.is_keyword):
            continue  # 急ぎの言葉と重なる（今夜・明朝など）ものは言葉のほうで数える
        tail = _MENTION_TAIL_RE.match(text, mention.end)
        end = tail.end() if tail else mention.end
        hits.append(_Hit(text[mention.start:end].strip(), mention.start, end, mention.due_date, False))

    hits.sort(key=lambda hit: hit.start)
    return hits


def _is_negated(text: str, hit: _Hit) -> bool:
    """当たった語の後ろ、同じ節の中に否定があるか"""
    for clause in _CLAUSE_RE.finditer(text):
        if clause.start() <= hit.start < clause.end():
            return bool(_NEGATION_RE.search(text, hit.end, clause.end()))
    return False


def detect_urgency(
    text: str,
    today: date,
    within_days: int = URGENT_WITHIN_DAYS,
) -> UrgencyResult:
    """
    文から急ぎかどうか・当たった語・推定期限を求める。

    Parameters
    ----------
    text : str
        調べる文（1件分。複数行でもよい）
    today : date
        基準日（必ず渡す）。推定期限と「何日以内か」はこの日から数える
    within_days : int
        推定期限が何日以内なら急ぎとするか（既定 URGENT_WITHIN_DAYS）

    Returns
    -------
    UrgencyResult
    """
    normalized = unicodedata.normalize("NFKC", text)
    limit = today + timedelta(days=within_days)

    matched: list[str] = []
    negated: list[str] = []
    dates: list[date] = []
    for hit in _find_hits(normalized, today):
        if _is_negated(normalized, hit):
            negated.append(hit.text)
            continue
        if hit.due is not None:
            dates.append(hit.due)
        if hit.is_keyword or (hit.due is not None and hit.due <= limit):
            matched.append(hit.text)

    return UrgencyResult(
        is_urgent=bool(matched),
        matched=tuple(matched),
        due_date=min(dates) if dates else None,
        negated=tuple(negated),
    )
