"""
M3 八步分析器
对应8步流程步骤1-2（规则引擎初筛）
步骤3-8的逻辑在 build_prompt_m3 的 prompt 中实现
"""

import re
from typing import Tuple
from .section_extractor import extract_judgment_reason, extract_judgment_result


def m3_step1_extract_sections(full_text: str) -> dict:
    """
    步骤1：篇章切分
    识别"裁判理由/本院认为"部分 和 "裁判结果/主文"部分
    """
    reason = extract_judgment_reason(full_text)
    result = extract_judgment_result(full_text)

    return {
        "reason": reason or "",
        "result": result or "",
    }


def m3_step2_screen(full_text: str) -> Tuple[bool, str]:
    """
    步骤2：初筛纳入/排除（规则引擎，不调LLM）

    条件：裁判理由有563/565 条文  且  裁判结果有合同解除类表述
    返回：(是否纳入检测范围, 排除原因)
    """
    sections = m3_step1_extract_sections(full_text)
    reason = sections["reason"]
    result = sections["result"]

    # 步骤2-a：检查裁判理由中是否有563/565条文
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
    has_article = any(re.search(p, reason) for p in article_patterns)

    # 步骤2-b：检查裁判结果中是否有合同关系消灭类表述
    dissolution_patterns = [
        r'解除',
        r'解除合同',
        r'合同解除',
        r'终止履行',
        r'终止合同权利义务关系',
        r'终止.*权利义务',
    ]
    has_dissolution = any(re.search(p, result) for p in dissolution_patterns)

    if has_article and has_dissolution:
        return True, ""
    elif not has_article:
        return False, "裁判理由中未出现第563条/第565条"
    else:
        return False, "裁判结果中未出现合同解除类表述"


def is_candidate_m3(full_text: str) -> bool:
    """
    M3初筛入口函数
    对应8步流程步骤2：规则引擎快速判断是否进入8步流程
    返回 True 表示纳入M3检测范围
    """
    in_scope, _ = m3_step2_screen(full_text)
    return in_scope
