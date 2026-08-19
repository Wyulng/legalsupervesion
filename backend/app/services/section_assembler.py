"""
分板块组装模块
职责：定义各模型所需截面配方 + 从判决书全文中提取对应板块
（prompt 组装已迁移至调用方，不再由此模块负责）
"""

import logging
import re
from typing import Dict, List, Optional, Callable

from .section_extractor import (
    extract_trial_process,
    extract_judgment_reason,
    extract_judgment_result,
    is_dismissal_no_payment,
)

logger = logging.getLogger(__name__)

# =============================================================================
# 截面配方：定义每个模型需要哪些板块
# =============================================================================
SECTION_RECIPES: Dict[str, List[str]] = {
    "m1": ["trial_process", "judgment_result"],
    "m5": ["judgment_result"],
    "m10": ["judgment_result"],
    "m3": ["trial_process", "judgment_reason", "judgment_result"],
}

# 截面提取函数映射
SECTION_EXTRACTORS: Dict[str, Callable] = {
    "trial_process": extract_trial_process,
    "judgment_reason": extract_judgment_reason,
    "judgment_result": extract_judgment_result,
}


# =============================================================================
# 特殊前置检查（M1 专用）
# =============================================================================
def check_special_m1(full_text: str) -> Optional[dict]:
    """
    M1 特殊兜底：驳回诉请且无金钱给付，直接返回无问题，跳过 LLM 调用。
    若返回 None 表示不命中该特殊路径，应继续正常 LLM 调用。
    若返回 dict 表示命中，直接返回该结果。
    返回字段：issue / reason / risk / status（与 llm_caller.py 约定一致，保持不变）
    """
    judgment = extract_judgment_result(full_text)
    if not judgment:
        return None
    if is_dismissal_no_payment(judgment):
        return {
            "issue": "无问题",
            "reason": "驳回原告全部诉讼请求且无金钱给付义务，公告费漏判风险低",
            "risk": "低",
            "status": "skipped",
        }
    return None


# =============================================================================
# 板块提取
# =============================================================================
def assemble_sections(full_text: str, model_name: str) -> Dict[str, str]:
    """
    根据 model_name 从 full_text 中提取对应板块。

    返回 dict，key 为板块名，value 为提取的文本。
    若某板块提取结果为空字符串，该 key 不出现在返回 dict 中，
    避免空文本干扰 prompt 组装。
    若有缺失板块，记录警告日志。
    """
    recipe = SECTION_RECIPES.get(model_name, [])
    result = {}
    for section_name in recipe:
        extractor = SECTION_EXTRACTORS.get(section_name)
        if not extractor:
            continue
        text = extractor(full_text)
        if text:
            result[section_name] = text

    # 日志输出各板块提取长度
    lengths = {k: len(v) for k, v in result.items()}
    logger.debug(f"[assemble_sections] model={model_name}, sections={list(result.keys())}, lengths={lengths}")

    # 检查缺失板块并记录警告
    missing = [s for s in recipe if s not in result]
    if missing:
        logger.warning(f"Missing sections for {model_name}: {missing}")

    return result


def check_m10_skip_condition(full_text: str) -> Optional[Dict]:
    """
    M10 快速退出条件：裁判结果中已明确载明加倍支付迟延履行利息条款。
    若命中，返回与 check_special_m1 相同格式的结果字典；否则返回 None。
    """
    result_text = extract_judgment_result(full_text)
    if not result_text:
        return None

    # 合规表述模式：已写明加倍利息或引用法条
    patterns = [
        r'加倍支付迟延履行(?:期间)?(?:的)?(?:债务)?利息',
        r'迟延履行(?:期间)?(?:的)?利息.*?加倍',
        r'加倍支付迟延履行金',
        r'《民事诉讼法》\s*第\s*253\s*条',
        r'《民事诉讼法》\s*第二百五十三条',
        r'逾期.*?按日万分之五.*?利息',
    ]
    for pat in patterns:
        if re.search(pat, result_text):
            return {
                "issue": "无问题",
                "reason": "裁判结果已明确载明加倍支付迟延履行利息条款",
                "risk": "低",
                "status": "skipped",
            }
    return None