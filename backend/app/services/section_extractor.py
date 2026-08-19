import re
import logging

logger = logging.getLogger(__name__)


def extract_section(text: str, start_patterns, end_patterns) -> str:
    """
    从 text 中提取[start_patterns]之后、[end_patterns]之前的段落。

    终点匹配取所有模式中最晚出现的行结尾位置，
    宁可多包含内容也不截断。

    - 若无法找到 start，返回空
    - 若 end_patterns 为空或无匹配，返回到文档末尾
    - 结果过短（<20字符）时返回空
    """
    start_match = None
    matched_pat = None
    for pat in start_patterns:
        start_match = re.search(pat, text, re.IGNORECASE | re.DOTALL)
        if start_match:
            matched_pat = pat
            break
    if not start_match:
        logger.debug(f"[extract_section] no start_pattern matched")
        return ""

    start = start_match.end()

    # 无 end_patterns 时，直接返回到文档末尾
    if not end_patterns:
        result = text[start:].strip()
        logger.debug(f"[extract_section] no end_patterns, returning all, length={len(result)}")
        return result

    # 找最后一个 end_pattern 匹配的整行结尾（保留完整行，包含更多内容）
    latest_line_end = -1
    for pat in end_patterns:
        match = re.search(pat, text[start:], re.IGNORECASE | re.DOTALL)
        if match:
            line_end = text.find('\n', start + match.start())
            if line_end == -1:
                line_end = len(text)
            if line_end > latest_line_end:
                latest_line_end = line_end

    if latest_line_end == -1:
        latest_line_end = len(text)

    result = text[start:latest_line_end].strip()
    logger.debug(
        f"[extract_section] matched start='{matched_pat}', "
        f"result_len={len(result)}"
    )

    # 长度校验：避免送入 LLM 空段落
    if result and len(result) < 20:
        logger.debug(f"Section too short ({len(result)} chars), returning empty")
        return ""

    return result


def extract_trial_process(text: str) -> str:
    """
    提取审理经过 / 事实描述 部分。
    依次尝试四种策略：主提取、fallback1、fallback2、fallback3。
    """
    start_patterns = [
        r'本院立案后',
        r'本院受理后',
        r'本院受理',
        r'审理经过',
        r'依法适用',
        r'经审理查明',
        r'立案后',
        r'原告.*与被告.*一案，本院立案后',
    ]
    end_patterns = [
        r'向本院提出诉讼请求',
        r'原告诉称',
        r'被告诉称',
        r'经审理认定',
        r'判决如下',
        r'答辩状',
    ]
    trial = extract_section(text, start_patterns, end_patterns)
    if trial:
        logger.debug(f"[extract_trial_process] main extract succeeded, length={len(trial)}")
    if not trial:
        # 兜底1：从本院立案后匹配到第一个终止词前
        fallback = re.search(r'本院立案后(.*?)(?:本案现已审理终结|判决如下)', text, re.DOTALL)
        if fallback:
            trial = fallback.group(1).strip()
            logger.debug(f"[extract_trial_process] fallback1 matched, length={len(trial)}")
    if not trial:
        # 兜底2：直接从开头取到"本院认为"或"判决如下"
        fallback2 = re.search(r'^(.{100,})(?=本院认为|判决如下)', text, re.DOTALL)
        if fallback2:
            trial = fallback2.group(1).strip()
            logger.debug(f"[extract_trial_process] fallback2 matched, length={len(trial)}")
    if not trial:
        # 兜底3：取前500字符作为兜底
        fallback3 = text[:500].strip()
        if fallback3 and len(fallback3) >= 50:
            trial = fallback3
            logger.debug(f"[extract_trial_process] fallback3 matched, length={len(trial)}")
    if trial and len(trial.strip()) < 10:
        logger.warning(f"Extracted trial process too short: {len(trial)} chars")
        return ""
    return trial


def extract_judgment_result(text: str) -> str:
    """提取裁判结果 / 主文 部分"""
    start_patterns = [
        r'判决如下',
        r'本院判决如下',
        r'裁判结果',
        r'裁定如下',
        r'裁决如下',
        r'主文',
    ]
    end_patterns = [
        r'本判决为终审判决',
        r'本裁定为终审裁定',
        r'\n审判员\s+',  # 换行后的审判员（签名行）
        r'\n执行员\s+',
        r'\n书记员\s+',
        r'\n二[〇零]\d{2}年(?:\s*[月日]|[^\d\u4e00-\u9fff])',  # 换行后的年份日期
        r'\n(?:一九|二[〇零])\d{2}年\s*[月日]',  # 换行后的年份日期
        r'\n\d{4}年\d{1,2}月\d{1,2}[日署]',  # 换行后的日期（文书签署日期）
        r'不服本判决',
        r'审\s*判\s*员',  # 宽松匹配作为兜底
    ]
    result = extract_section(text, start_patterns, end_patterns)
    if result:
        logger.debug(f"[extract_judgment_result] succeeded, length={len(result)}")
    if not result:
        # 兜底：非贪婪匹配到明确的终止标记前；若找不到则贪婪取到文末
        fallback_patterns = [
            r'判决如下(.*?)(?:本判决为终审判决|\n审判员|\n执行员|\n书记员|二[〇零])',
            r'本院判决如下(.*?)(?:本判决为终审判决|\n审判员|\n执行员|\n书记员|二[〇零])',
            r'裁定如下(.*?)(?:本裁定为终审裁定|\n审判员|\n执行员|\n书记员)',
        ]
        for pat in fallback_patterns:
            fallback = re.search(pat, text, re.DOTALL)
            if fallback and len(fallback.group(1).strip()) >= 20:
                result = fallback.group(1).strip()
                break
        # 如果兜底仍未找到足够长的内容，贪婪取到文末
        if not result:
            fallback = re.search(r'判决如下(.*)', text, re.DOTALL)
            if fallback:
                result = fallback.group(1).strip()
    if result and len(result.strip()) < 20:
        logger.warning(f"Extracted judgment result too short: {len(result)} chars")
        return ""
    return result


def extract_judgment_reason(text: str) -> str:
    """提取裁判理由部分（本院认为）"""
    start_patterns = [
        r'本院认为',
        r'本院经审理认为',
        r'本院审理认为',
        r'本院审查认为',
        r'经审理认为',
        r'经审查认为',
    ]
    end_patterns = [
        r'判决如下',
        r'裁定如下',
        r'裁判结果',
    ]
    reason = extract_section(text, start_patterns, end_patterns)
    if reason:
        logger.debug(f"[extract_judgment_reason] succeeded, length={len(reason)}")
    if not reason:
        # 兜底：匹配各种"认为"表述到终止词
        fallback_patterns = [
            r'本院认为(.*?)(?:判决如下|裁定如下|裁判结果|$)',
            r'本院经审理认为(.*?)(?:判决如下|裁定如下|裁判结果|$)',
            r'本院审理认为(.*?)(?:判决如下|裁定如下|裁判结果|$)',
            r'本院审查认为(.*?)(?:判决如下|裁定如下|裁判结果|$)',
        ]
        for pat in fallback_patterns:
            fallback = re.search(pat, text, re.DOTALL)
            if fallback:
                reason = fallback.group(1).strip()
                break
    if reason and len(reason.strip()) < 20:
        logger.warning(f"Extracted judgment reason too short: {len(reason)} chars")
        return ""
    return reason


def is_dismissal_no_payment(judgment_text: str) -> bool:
    """
    宽泛匹配所有驳回诉请的表达，不遗漏变体。
    进一步确认裁判结果中无金钱给付义务（排除部分驳回+金钱给付的情况）。
    """
    if re.search(r'驳回(?:原告|申请人|起诉人|当事人).{0,20}(?:诉讼请求|诉请|请求|起诉|主张)', judgment_text, re.DOTALL):
        if not re.search(r'(?:支付|给付|赔偿|返还|补偿|退还).{0,10}元', judgment_text):
            return True
    return False