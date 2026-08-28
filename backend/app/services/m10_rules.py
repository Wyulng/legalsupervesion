"""M10 迟延履行期间债务利息规则与法律版本识别。"""

from dataclasses import dataclass
from datetime import date
import re
from typing import List, Optional, Tuple

from .section_extractor import extract_judgment_result


_DIGITS = {
    "〇": 0,
    "○": 0,
    "零": 0,
    "Ｏ": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


@dataclass(frozen=True)
class M10LawContext:
    """M10 使用的法律版本上下文。"""

    judgment_date: Optional[date]
    version: Optional[str]
    article: Optional[int]
    date_source: str = ""

    @property
    def known(self) -> bool:
        return self.judgment_date is not None and self.article is not None


_ARABIC_DATE_PATTERNS = (
    re.compile(
        r"(?P<year>19\d{2}|20\d{2})\s*年\s*"
        r"(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日?"
    ),
    re.compile(
        r"(?P<year>19\d{2}|20\d{2})\s*[./-]\s*"
        r"(?P<month>\d{1,2})\s*[./-]\s*(?P<day>\d{1,2})"
    ),
)
_CHINESE_DATE_PATTERN = re.compile(
    r"(?P<year>[〇○零Ｏ一二两三四五六七八九]{4})年\s*"
    r"(?P<month>[〇○零Ｏ一二两三四五六七八九十百廿卅\d]{1,3})月\s*"
    r"(?P<day>[〇○零Ｏ一二两三四五六七八九十百廿卅\d]{1,3})日?"
)
_SIGNATURE_MARKER_PATTERN = re.compile(r"审判长|审判员|书记员|法官助理|执行员")


def _parse_chinese_number(value: str) -> Optional[int]:
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    if all(char in _DIGITS for char in value):
        return int("".join(str(_DIGITS[char]) for char in value))

    # 月、日中常见的“十”“二十五”“三十一”等写法。
    if value in {"廿", "卅"}:
        return {"廿": 20, "卅": 30}[value]
    if "十" in value:
        left, right = value.split("十", 1)
        tens = _DIGITS.get(left, 1) if left else 1
        ones = _DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    if "百" in value:
        left, right = value.split("百", 1)
        hundreds = _DIGITS.get(left, 1) if left else 1
        remainder = _parse_chinese_number(right) if right else 0
        return hundreds * 100 + (remainder or 0)
    return None


def _safe_date(year: int, month: int, day: int) -> Optional[date]:
    if year < 1900 or year > 2100:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _extract_date_matches(text: str) -> List[Tuple[int, date]]:
    matches: List[Tuple[int, date]] = []
    for pattern in _ARABIC_DATE_PATTERNS:
        for match in pattern.finditer(text):
            parsed = _safe_date(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
            )
            if parsed is not None:
                matches.append((match.start(), parsed))

    for match in _CHINESE_DATE_PATTERN.finditer(text):
        year = _parse_chinese_number(match.group("year"))
        month = _parse_chinese_number(match.group("month"))
        day = _parse_chinese_number(match.group("day"))
        if year is not None and month is not None and day is not None:
            parsed = _safe_date(year, month, day)
            if parsed is not None:
                matches.append((match.start(), parsed))
    return sorted(matches, key=lambda item: item[0])


def extract_judgment_date(text: str) -> Optional[date]:
    """从文书末尾提取唯一的裁判落款日期。

    不使用案情部分日期。若末尾存在多个不同日期，返回 None，交由人工复核。
    """

    if not text:
        return None

    matches = _extract_date_matches(text)
    if not matches:
        return None

    # 裁判落款通常位于审判员、书记员等签名行之后；只在文书末尾区域内查找。
    tail_start = max(0, len(text) - 1000)
    tail_matches = [item for item in matches if item[0] >= tail_start]
    markers = list(_SIGNATURE_MARKER_PATTERN.finditer(text))
    if markers:
        # 审判员、书记员等签名行后的日期才是落款候选。保留所有签名
        # 标记后的日期，若出现不同日期则不作猜测，交由人工复核。
        after_signature = [item for item in tail_matches if item[0] >= markers[0].end()]
        if after_signature:
            tail_matches = after_signature

    # 同一落款日期可能因文本层或页眉重复出现，重复日期不构成歧义。
    unique_dates = list(dict.fromkeys(item[1] for item in tail_matches))
    if len(unique_dates) == 1:
        return unique_dates[0]
    return None


def resolve_m10_law_context(text: str) -> M10LawContext:
    judgment_date = extract_judgment_date(text)
    if judgment_date is None:
        return M10LawContext(
            judgment_date=None,
            version=None,
            article=None,
            date_source="无法从文书末尾确认唯一裁判落款日期",
        )

    if judgment_date < date(2022, 1, 1):
        version, article = "2017年修正版", 253
    elif judgment_date < date(2024, 1, 1):
        version, article = "2021年修正版", 260
    else:
        version, article = "2023年修正版", 264
    return M10LawContext(
        judgment_date=judgment_date,
        version=version,
        article=article,
        date_source="文书末尾裁判落款日期",
    )


def format_m10_law_context(context: M10LawContext) -> str:
    if not context.known:
        return "裁判日期无法确认，不能自动确定适用的民事诉讼法版本。"
    return (
        f"裁判落款日期：{context.judgment_date.isoformat()}；"
        f"按项目版本映射，适用{context.version}《民事诉讼法》第{context.article}条。"
    )


_ARTICLE_PATTERN = re.compile(
    r"(?:《?\s*(?:中华人民共和国)?民事诉讼法\s*》?|民诉法|"
    r"依据|依照|按照|适用)\s*(?:[（(][^）)]{0,20}[）)])?\s*第\s*"
    r"(?P<article>253|260|264|二百五十三|二百六十|二百六十四)\s*条"
)
_BARE_ARTICLE_PATTERN = re.compile(
    r"第\s*(?P<article>253|260|264|二百五十三|二百六十|二百六十四)\s*条"
)
_NON_M10_LAW_PATTERN = re.compile(r"民法典|刑法|合同法|公司法|行政诉讼法")
_FULL_INTEREST_PATTERNS = (
    re.compile(r"加倍\s*支付\s*迟延履行(?:期间)?(?:的)?(?:债务)?利息"),
    re.compile(r"加倍\s*支付\s*迟延履行期间(?:的)?(?:债务)?利息"),
)
_ARTICLE_506_PATTERN = re.compile(
    r"(?:民事诉讼法|民诉法).{0,80}(?:第\s*506\s*条|第五百零六条)"
)
_M10_CLAUSE_SPLIT_PATTERN = re.compile(r"[；;。\n]")
_MONEY_ACTION_PATTERN = re.compile(r"给付|支付|赔偿|返还|退还|补偿|偿还")
_MONEY_INDICATOR_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s*元|人民币|货款|借款|工程款|本金|款项|费用|损失|违约金|金额|按[^；。\n]{0,20}计算"
)
_BEHAVIOR_PATTERN = re.compile(
    r"(?:交付|返还|腾空).{0,12}(?:房屋|房产|土地|车辆|设备|原物|物品|场地)|"
    r"(?:房屋|房产|土地|车辆|设备|原物|物品|场地).{0,12}(?:交付|返还|腾空)|"
    r"继续履行|恢复原状|排除妨害|协助过户|交付使用权"
)


def _article_number(value: str) -> int:
    mapped = {
        "二百五十三": 253,
        "二百六十": 260,
        "二百六十四": 264,
    }.get(value)
    return mapped if mapped is not None else int(value)


def extract_m10_article_refs(text: str) -> List[int]:
    refs: List[int] = []
    source = text or ""
    explicit_spans = []
    for match in _ARTICLE_PATTERN.finditer(source):
        article = _article_number(match.group("article"))
        if article not in refs:
            refs.append(article)
        explicit_spans.append(match.span())

    # 有些主文只写“依据第264条”，或在同一迟延利息句中省略法律全称。
    # 仅在附近有 M10 语义且没有其他法律名称时采用这种裸编号，避免把
    # 《民法典》等其他法律的同号条文误识别为民事诉讼法条文。
    for match in _BARE_ARTICLE_PATTERN.finditer(source):
        if any(start <= match.start() < end for start, end in explicit_spans):
            continue
        context = source[max(0, match.start() - 80): min(len(source), match.end() + 80)]
        if not re.search(r"迟延履行|债务利息|加倍支付|金钱给付", context):
            continue
        if _NON_M10_LAW_PATTERN.search(context):
            continue
        article = _article_number(match.group("article"))
        if article not in refs:
            refs.append(article)
    return refs


def has_full_m10_interest_clause(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in _FULL_INTEREST_PATTERNS)


def has_m10_article_506(text: str) -> bool:
    return bool(_ARTICLE_506_PATTERN.search(text or ""))


def _is_money_obligation_clause(clause: str) -> bool:
    """判断一个主文分句是否包含明确的金钱给付项目。"""
    if not _MONEY_ACTION_PATTERN.search(clause):
        return False
    if re.search(r"迟延履行金", clause) and not re.search(
        r"货款|借款|工程款|本金|款项|费用|损失|违约金", clause
    ):
        return False
    if _BEHAVIOR_PATTERN.search(clause) and not _MONEY_INDICATOR_PATTERN.search(clause):
        return False
    return bool(_MONEY_INDICATOR_PATTERN.search(clause))


def m10_precheck(full_text: str) -> Optional[dict]:
    """返回确定性结果；返回 None 时继续执行 LLM 分析。"""

    context = resolve_m10_law_context(full_text)
    if not context.known:
        return {
            "issue": "待人工复核",
            "reason": (
                "无法从文书确定裁判日期或适用法律版本，"
                "法条引用及迟延利息条款需要人工核对"
            ),
            "risk": "人工复核",
            "suggestion": "核对裁判日期及适用法律版本",
            "status": "skipped",
        }

    result_text = extract_judgment_result(full_text)
    if not result_text:
        return None

    clauses = [
        clause.strip()
        for clause in _M10_CLAUSE_SPLIT_PATTERN.split(result_text)
        if clause.strip()
    ]
    money_clauses = [clause for clause in clauses if _is_money_obligation_clause(clause)]
    if not money_clauses:
        return None

    refs = extract_m10_article_refs(result_text)
    if refs:
        mismatches = [article for article in refs if article != context.article]
        if mismatches:
            return {
                "issue": "存在问题",
                "reason": (
                    f"裁判落款日期为{context.judgment_date.isoformat()}，"
                    f"适用{context.version}《民事诉讼法》第{context.article}条，"
                    f"但裁判结果引用了第{','.join(str(item) for item in mismatches)}条，"
                    "法条版本不匹配"
                ),
                "risk": "中",
                "suggestion": "核对裁判日期并改用对应版本条文",
                "status": "skipped",
            }
        return {
            "issue": "无问题",
            "reason": (
                f"裁判落款日期为{context.judgment_date.isoformat()}，"
                f"裁判结果引用的《民事诉讼法》第{context.article}条与适用版本一致"
            ),
            "risk": "低",
            "suggestion": "",
            "status": "skipped",
        }

    if has_full_m10_interest_clause(result_text):
        # 混合主文中，只有行为义务分句出现“加倍支付”时不能直接放行；
        # 交由 LLM 对各项金钱义务分别判断。单独的行为义务通常不会进入
        # M10 候选，但这里仍保持前置判断的边界。
        interest_clauses = [
            clause for clause in clauses if has_full_m10_interest_clause(clause)
        ]
        if money_clauses and not any(
            _is_money_obligation_clause(clause) for clause in interest_clauses
        ):
            return None
        return {
            "issue": "无问题",
            "reason": "裁判结果明确载明加倍支付迟延履行期间的债务利息",
            "risk": "低",
            "suggestion": "",
            "status": "skipped",
        }

    if has_m10_article_506(result_text):
        return {
            "issue": "存在问题",
            "reason": "裁判结果仅引用《民诉法解释》第506条，该条规定起算时间，未单独载明加倍支付迟延履行期间的债务利息",
            "risk": "中",
            "suggestion": "补充适用版本的法定加倍利息条款",
            "status": "skipped",
        }

    return None
