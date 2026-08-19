import re
import logging
from typing import Optional
from .section_extractor import extract_judgment_reason, extract_judgment_result

logger = logging.getLogger(__name__)


def _extract_case_type(text: str) -> str:
    """
    从文书首部提取案由。
    支持多种格式：
    1. "案由：xxx"
    2. "原告xxx与被告xxx...xxx纠纷"
    3. 管道符表格格式：|案由 | |xxx/yyy/zzz/民间借贷纠纷 |
    """
    # 只在前2000字符搜索（文书首部）
    search_text = text[:2000]

    # 模式1：案由[：:]\s*xxx
    patterns1 = [
        r'案由[：:]\s*([^\n|]+)',  # 排除管道符
        r'案由[：:]\s*(.+?)(?:\n|$)',
    ]
    for pat in patterns1:
        match = re.search(pat, search_text)
        if match:
            result = match.group(1).strip()
            if result:
                return result

    # 模式2：管道符表格格式 |案由 | |xxx/yyy/zzz/民间借贷纠纷 |
    pipe_pattern = r'\|案由\s*\|.*?\|\s*(.+?)\s*\|'
    pipe_match = re.search(pipe_pattern, search_text)
    if pipe_match:
        path = pipe_match.group(1).strip()
        # 取路径最后一个部分（最具体的案由）
        parts = path.split('/')
        if parts:
            return parts[-1].strip()

    # 模式3：从原被告关系中提取案由
    patterns3 = [
        r'原告.{0,30}与被告.{0,30}([^案\n]{2,20}?)一?案',
        r'上诉人.{0,30}与被上诉人.{0,30}([^案\n]{2,20}?)一?案',
    ]
    for pat in patterns3:
        match = re.search(pat, search_text)
        if match:
            result = match.group(1).strip()
            # 过滤掉明显不是案由的结果
            if result and len(result) >= 2 and len(result) <= 20:
                return result

    return ""


def is_candidate_m1(text: str) -> bool:
    """
    M1初筛：法院公告送达但未判公告费问题。
    宽泛匹配正向模式，再通过负向排除减少误报。
    """
    positive_patterns = [
        r'(?:本院|法院|登报)公告(?:送达)?',
        r'公告送达',
        r'公告费',
    ]
    has_positive = False
    for pat in positive_patterns:
        if re.search(pat, text):
            has_positive = True
            break
    if not has_positive:
        logger.debug(f"[M1 filter] no positive pattern matched")
        return False

    negative_patterns = [
        r'(?:停业|清算|注销|搬迁|债权申报)\s*公告',
        r'公告送达\s*(?:判决书|裁定书)',
    ]
    for pat in negative_patterns:
        if re.search(pat, text):
            logger.debug(f"[M1 filter] matched negative pattern, excluded")
            return False
    logger.debug(f"[M1 filter] passed, text_length={len(text)}")
    return True


def is_candidate_m5(text: str) -> bool:
    """
    M5初筛：诉讼费（案件受理费、申请费）直接支付给胜诉方的不规范情形。

    只有以下费用不能直接支付给胜诉方（必须向法院交纳）：
    1. 案件受理费
    2. 申请费
    3. 证人、鉴定人、翻译人员、理算人员在人民法院指定日期出庭发生的
       交通费、住宿费、生活费和误工补贴

    其他费用（如公告费、鉴定费、评估费等）可以直接支付给胜诉方，无需法院转付。
    """
    # 诉讼费条款位于裁判结果时只检查该段，避免把裁判理由/事实部分的
    # 无关“直接支付”误关联到诉讼费。旧文书没有明确主文标题时再退回全文。
    result_text = extract_judgment_result(text) or text

    # 只针对案件受理费和申请费进行检查
    fee_keywords = ['案件受理费', '申请费']
    clauses = [clause for clause in re.split(r'[；;。\n]', result_text) if clause.strip()]
    for clause in clauses:
        if not any(fee_kw in clause for fee_kw in fee_keywords):
            continue

        # 明确写明向法院缴纳的条款属于合规情形。
        paid_to_court = re.search(
            r'(?:向|交至|缴至|交纳至|缴纳至|上缴至?).{0,20}'
            r'(?:人民法院|法院|本院|法院账户|诉讼费专户)',
            clause,
        )

        # 只有明确出现“支付/给付给某一方”才认定为候选；不能把“直接”
        # 单独作为信号，否则同一段的无关律师费等语句会触发 M5。
        paid_to_party = re.search(
            r'(?:直接\s*)?(?:支付|给付)\s*(?:给|向|至)?\s*'
            r'(?:原告|被告|申请人|被申请人|胜诉方|对方当事人)'
            r'|(?:径付|径向)\s*(?:原告|被告|申请人|被申请人|胜诉方|对方当事人)',
            clause,
        )
        if paid_to_party:
            logger.debug(f"[M5 filter] matched party payment: clause={clause[:80]}")
            return True
        if paid_to_court:
            continue

        # 兼容 OCR 把条款拆得很碎的文书，仅在同一费用词附近寻找明确的
        # “支付给/径付”结构，不再使用宽泛的全文窗口。
        for fee_kw in fee_keywords:
            match = re.search(fee_kw, clause)
            if match and re.search(
                r'(?:支付给|给付给|径付|径向)\s*(?:原告|被告|申请人|被申请人|胜诉方)',
                clause[match.start():],
            ):
                return True
    logger.debug(f"[M5 filter] no pattern matched, text_length={len(text)}")
    return False


def is_candidate_m10(text: str, case_type: Optional[str] = None) -> bool:
    """
    M10初筛：金钱给付义务但未载明加倍支付迟延履行利息。
    匹配范围：仅限裁判结果段落。
    负向排除：精神抚慰金等非金钱给付义务，以及即时履行情形。
    """
    result_text = extract_judgment_result(text)
    if not result_text:
        logger.debug(f"[M10 filter] result_text empty, skipped")
        return False

    money_patterns = [
        r'给付', r'支付', r'赔偿', r'返还', r'退还', r'补偿', r'偿还',
        r'退还.*款', r'返还.*款', r'赔偿.*损失', r'偿还.*借款',
        r'违约金',
    ]
    has_money = False
    for pat in money_patterns:
        if re.search(pat, result_text):
            has_money = True
            break
    if not has_money:
        logger.debug(f"[M10 filter] no money pattern matched in result")
        return False

    exclude_patterns = [
        r'精神抚慰金',
        r'当庭履行',
        r'即时履行',
        r'已?当庭给付',
    ]
    for pat in exclude_patterns:
        if re.search(pat, result_text):
            logger.debug(f"[M10 filter] excluded by pattern: {pat}")
            return False

    logger.debug(f"[M10 filter] passed, result_length={len(result_text)}")
    return True


def is_candidate_m3(text: str) -> bool:
    """
    M3初筛：合同解除时间认定错误问题。
    需同时满足：
    1. 裁判理由段落包含法条引用（民法典563/565或合同法94/96）
    2. 裁判结果段落包含异常解除表述
    """
    reason_text = extract_judgment_reason(text)
    result_text = extract_judgment_result(text)

    if not reason_text or not result_text:
        return False

    # 使用与 m3_analyzer.py 中 m3_step2_screen() 一致的宽松 article 匹配模式
    article_patterns = [
        r'第五百六十三条',
        r'第五百六十五条',
        r'第五六三条',
        r'第五六五条',
        r'第563条',
        r'第565条',
        r'\b563\b',
        r'\b565\b',
        r'563条',
        r'565条',
        r'第五百六十三条[的之]?规定',
        r'第五百六十五条[的之]?规定',
        r'第563条规定',
        r'第565条规定',
        r'民法典第563条',
        r'民法典第565条',
        r'民法典563条',
        r'民法典565条',
        r'《民法典》第563条',
        r'《民法典》第565条',
        r'《民法典》563条',
        r'《民法典》565条',
        r'第五百六十三条规定',
        r'第五百六十五条规定',
        r'563条规定',
        r'565条规定',
        r'民法典第563条第\d款',
        r'民法典第565条第\d款',
        r'第五百六十三条[第（]\d款',
        r'第五百六十五条[第（]\d款',
    ]
    has_article = any(re.search(p, reason_text) for p in article_patterns)
    logger.debug(f"[M3初筛] reason长度={len(reason_text)}, has_article={has_article}, reason前100字={reason_text[:100]}")
    if not has_article:
        logger.debug(f"[M3初筛] 裁判理由中未匹配到563/565条文")
        return False

    # 使用与 m3_analyzer.py 中 m3_step2_screen() 一致的宽松匹配模式
    dissolution_patterns = [
        r'解除',
        r'解除合同',
        r'合同解除',
        r'终止履行',
        r'终止合同权利义务关系',
        r'终止.*权利义务',
    ]
    has_dissolution = any(re.search(p, result_text) for p in dissolution_patterns)
    logger.debug(f"[M3初筛] result长度={len(result_text)}, has_dissolution={has_dissolution}, result前100字={result_text[:100]}")
    if not has_dissolution:
        logger.debug(f"[M3初筛] 裁判结果中未匹配到合同解除类表述")
        return False

    logger.debug(f"[M3初筛] 通过！reason={has_article}, result={has_dissolution}")
    return True
