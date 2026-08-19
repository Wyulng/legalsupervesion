import json
import re
import asyncio
import logging
import threading
from functools import lru_cache
from openai import OpenAI
from ..config import OPENAI_API_KEY, OPENAI_BASE_URL, MODEL_NAME, LLM_MAX_CONCURRENT

logger = logging.getLogger(__name__)

# 全局信号量，跨线程共享，确保 LLM_MAX_CONCURRENT 在批量模式下也生效
_llm_semaphore = threading.BoundedSemaphore(LLM_MAX_CONCURRENT)


async def _acquire_llm_slot():
    """获取全局 LLM 并发槽位（跨线程共享）"""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _llm_semaphore.acquire)


def _release_llm_slot():
    """释放全局 LLM 并发槽位"""
    _llm_semaphore.release()


@lru_cache()
def get_client() -> OpenAI:
    """延迟初始化 OpenAI 客户端，避免模块导入时 API Key 未设置导致失败"""
    return OpenAI(
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL,
        timeout=60.0,
    )


# ========== 函数定义Schema ==========

FUNCTION_SCHEMA_M1 = {
    "name": "analyze_notice_fee",
    "description": "判断法院公告送达是否存在公告费漏判问题",
    "parameters": {
        "type": "object",
        "properties": {
            "has_issue": {
                "type": "boolean",
                "description": "是否存在公告费漏判问题"
            },
            "reason": {
                "type": "string",
                "description": "判断理由，引用原文关键句"
            },
            "risk_level": {
                "type": "string",
                "enum": ["高", "中", "低"],
                "description": "风险等级：高/中/低"
            },
            "suggestion": {
                "type": "string",
                "description": "不超过30字的建议"
            }
        },
        "required": ["has_issue", "reason", "risk_level"]
    }
}

FUNCTION_SCHEMA_M5 = {
    "name": "analyze_court_fee",
    "description": "判断案件受理费是否存在直接支付给胜诉方的问题",
    "parameters": {
        "type": "object",
        "properties": {
            "has_issue": {
                "type": "boolean",
                "description": "是否存在受理费直接支付问题"
            },
            "reason": {
                "type": "string",
                "description": "判断理由，引用原文关键句"
            },
            "risk_level": {
                "type": "string",
                "enum": ["高", "中", "低"],
                "description": "风险等级：高/中/低"
            },
            "suggestion": {
                "type": "string",
                "description": "不超过30字的建议"
            }
        },
        "required": ["has_issue", "reason", "risk_level"]
    }
}

FUNCTION_SCHEMA_M10 = {
    "name": "analyze_interest",
    "description": "判断金钱给付义务是否缺少加倍支付迟延履行利息",
    "parameters": {
        "type": "object",
        "properties": {
            "has_issue": {
                "type": "boolean",
                "description": "是否存在利息条款缺失问题"
            },
            "reason": {
                "type": "string",
                "description": "判断理由，引用原文关键句"
            },
            "risk_level": {
                "type": "string",
                "enum": ["高", "中", "低"],
                "description": "风险等级：高/中/低"
            },
            "suggestion": {
                "type": "string",
                "description": "不超过30字的建议"
            }
        },
        "required": ["has_issue", "reason", "risk_level"]
    }
}

FUNCTION_SCHEMA_M3 = {
    "name": "analyze_contract_dissolution",
    "description": "M3增强版：合同解除时间认定错误检测（应然vs实然比对）",
    "parameters": {
        "type": "object",
        "properties": {
            "scene_type": {
                "type": "string",
                "description": "合同解除场景类型",
                "enum": [
                    "type_a_legal", "type_a_notice", "type_a_breach",
                    "type_a_delay", "type_a_expected", "type_a_expectation",
                    "type_a_force", "type_a_force_majeure",
                    "type_a_prosecution", "type_a_after_demand",
                    "type_a_anticipatory", "type_a_anticipatory_breach",
                    "type_a_negotiation", "type_a_consultation",
                    "type_a_expire", "type_a_expiry", "type_a_contract_expire", "type_a_period_expire",
                    "type_b_judicial", "type_b_deadlock", "type_b_deadlock", "type_b_expire", "type_b_deadlock",
                    "type_b_impossible", "type_b_change",
                    "type_b_fairness", "type_b_goodfaith",
                    "type_b_non_monetary", "unclear"
                ]
            },
            "expected_time_type": {
                "type": "string",
                "description": "应然解除时间类型：通知到达时/起诉状副本送达时/判决生效之日/法院酌定/需综合判断"
            },
            "expected_time_rule": {
                "type": "string",
                "description": "应然解除时间对应规则说明"
            },
            "actual_time_type": {
                "type": "string",
                "description": "实然解除时间类型（从判决书主文提取）"
            },
            "actual_time_text": {
                "type": "string",
                "description": "实然解除时间的原文表述"
            },
            "time_type_match": {
                "type": "boolean",
                "description": "应然与实然时间类型是否一致"
            },
            "reason_match": {
                "type": "boolean",
                "description": "模型推理理由与判决书理由是否一致"
            },
            "risk_level": {
                "type": "string",
                "enum": ["高", "中", "低", "人工复核"],
                "description": "风险等级：高/中/低/人工复核"
            },
            "has_issue": {
                "type": "boolean",
                "description": "是否存在合同解除时间认定错误"
            },
            "reason": {
                "type": "string",
                "description": "综合判断理由，引用原文"
            },
            "suggestion": {
                "type": "string",
                "description": "不超过30字的建议"
            }
        },
        "required": [
            "scene_type", "expected_time_type", "actual_time_type",
            "time_type_match", "reason_match", "risk_level", "has_issue", "reason"
        ]
    }
}

FUNCTION_SCHEMAS = {
    "m1": FUNCTION_SCHEMA_M1,
    "m5": FUNCTION_SCHEMA_M5,
    "m10": FUNCTION_SCHEMA_M10,
    "m3": FUNCTION_SCHEMA_M3,
}


# =============================================================================
# Phase 2: New extract_json pipeline
# =============================================================================

def _strip_reasoning_tags(text: str) -> str:
    """去除 LLM 常见的推理标签（闭合和未闭合均处理）"""
    # 闭合标签（非贪婪）
    for tag in ['think', 'reasoning', 'analysis', 'thought', 'response', 'result']:
        text = re.sub(rf'<{tag}[\s\S]*?</{tag}>', '', text, flags=re.DOTALL)
    # 未闭合标签：删除标签及标签后到第一个 { 之前的内容（保留 JSON）
    for tag in ['think', 'reasoning', 'analysis', 'thought']:
        text = re.sub(rf'<{tag}>[^{{]*', '', text, flags=re.DOTALL)
        text = re.sub(rf'<{tag}\s+[^>]*>[^{{]*', '', text, flags=re.DOTALL)
    return text.strip()


def _find_outermost_json(text: str):
    """使用括号计数器定位文本中最外层的完整 JSON 对象。
    正确处理嵌套对象、数组、字符串内的转义引号和花括号。
    返回 (start, end) 元组，如果找不到则返回 None。"""
    start = text.find('{')
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]

        if escape:
            escape = False
            continue

        if ch == '\\':
            escape = True
            continue

        if ch == '"' and not in_string:
            in_string = True
            continue
        elif ch == '"' and in_string:
            in_string = False
            continue

        if in_string:
            continue

        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i+1]

    return None


def _safe_single_to_double_quotes(text: str) -> str:
    """将单引号 JSON 转换为双引号 JSON。
    只替换作为 JSON 结构引号的单引号，保留字符串内容中的单引号。"""
    result = []
    in_string = False
    escape = False

    for ch in text:
        if escape:
            result.append(ch)
            escape = False
            continue
        if ch == '\\':
            result.append(ch)
            escape = True
            continue
        if ch == "'":
            in_string = not in_string
            result.append('"')
            continue
        result.append(ch)

    return ''.join(result)


def _repair_json_string(json_str: str) -> str:
    """修复 LLM 输出中常见的 JSON 格式问题：中文引号、尾随逗号、单引号结构。"""
    # 中文双引号 → 英文双引号
    # Chinese guillemet quotes are valid Unicode in JSON strings
    # 中文单引号 → 英文单引号
    # Chinese single quotes are valid Unicode in JSON strings
    # 尾随逗号
    json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
    # 单引号 JSON（仅当整个字符串无双引号时）
    if '"' not in json_str and "'" in json_str:
        json_str = _safe_single_to_double_quotes(json_str)
    return json_str


def extract_json(text: str) -> dict:
    """从 LLM 响应文本中提取 JSON 对象。

    采用确定性管道：去除推理标签 → 定位最外层 {} → 修复中文标点 → 解析。
    """
    if not text or not text.strip():
        raise ValueError("内容为空")

    original = text

    # Step 1: 去除推理标签
    text = _strip_reasoning_tags(text)

    # Step 2: 去除 markdown 代码块
    text = re.sub(r'```(?:json)?\s*', '', text, flags=re.IGNORECASE)

    # Step 3: 括号计数定位最外层 JSON 对象
    json_str = _find_outermost_json(text)

    if json_str is None:
        raise ValueError(
            f"无法在响应中定位 JSON 对象，响应前 300 字符: {original[:300]}"
        )

    # Step 4: 修复中文标点
    json_str = _repair_json_string(json_str)

    # Step 5: 解析
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        error_pos = getattr(e, 'pos', 0)
        start = max(0, error_pos - 50)
        end = min(len(json_str), error_pos + 50)
        context = json_str[start:end]
        raise ValueError(
            f"JSON 解析失败: {e.msg}，位置 {error_pos}，"
            f"上下文: ...{context}..."
        )


# =============================================================================
# Phase 3: validate_and_repair
# =============================================================================

def _validate_strict(result: dict, schema_name: str = "") -> tuple:
    if not isinstance(result, dict):
        return False, f"返回值不是 JSON 对象: {type(result).__name__}"

    valid_risk = ["高", "中", "低", "人工复核"]
    risk = result.get("risk_level", "")
    if risk not in valid_risk:
        return False, f"risk_level 无效: {risk}"
    reason = result.get("reason", "")
    has_issue = result.get("has_issue", False)
    if not isinstance(has_issue, bool):
        return False, f"has_issue 类型无效: {type(has_issue).__name__}"
    if not isinstance(reason, str):
        return False, f"reason 类型无效: {type(reason).__name__}"
    # has_issue=false 时 reason 允许为空或短文本（无问题、条文未引用等）
    if has_issue:
        if reason.strip() in ["", "无", "未检出具体理由", "None"]:
            return False, f"reason 无实质内容: {reason}"
        if len(reason.strip()) < 5:
            return False, f"reason 过短: {reason}"

    # M3 特有的字段验证
    if schema_name == "analyze_contract_dissolution":
        if result.get("time_type_match") is None:
            return False, "time_type_match 字段缺失"
        if result.get("reason_match") is None:
            return False, "reason_match 字段缺失"
        scene = result.get("scene_type", "")
        valid_scenes = [
            "type_a_legal", "type_a_notice", "type_a_breach",
            "type_a_delay", "type_a_expected", "type_a_expectation",
            "type_a_force", "type_a_force_majeure",
            "type_a_prosecution", "type_a_after_demand",
            "type_a_anticipatory", "type_a_anticipatory_breach",
            "type_a_negotiation", "type_a_consultation",
            "type_a_expire", "type_a_expiry", "type_a_contract_expire", "type_a_period_expire",
            "type_b_judicial", "type_b_deadlock", "type_b_deadlock", "type_b_expire",
            "type_b_impossible", "type_b_change",
            "type_b_fairness", "type_b_goodfaith",
            "type_b_non_monetary", "unclear"
        ]
        if scene not in valid_scenes:
            return False, f"scene_type 无效: {scene}"

    return True, ""

VALID_SCENES = {
    "type_a_legal", "type_a_notice", "type_a_breach",
    "type_a_delay", "type_a_expected", "type_a_expectation",
    "type_a_force", "type_a_force_majeure",
    "type_a_prosecution", "type_a_after_demand",
    "type_a_anticipatory", "type_a_anticipatory_breach",
    "type_a_negotiation", "type_a_consultation",
    "type_a_expire", "type_a_expiry", "type_a_contract_expire",
    "type_a_period_expire", "type_b_judicial", "type_b_deadlock",
    "type_b_expire", "type_b_impossible", "type_b_change",
    "type_b_fairness", "type_b_goodfaith", "type_b_non_monetary", "unclear"
}

RISK_MAP = {
    "高风险": "高", "高度风险": "高", "high": "高",
    "中等": "中", "中风险": "中", "medium": "中",
    "低风险": "低", "较低": "低", "low": "低",
    "人工复核": "人工复核", "需复核": "人工复核", "待复核": "人工复核",
}


def _repair_m3_fields(result: dict) -> dict:
    """修复 M3 模型的特有字段"""
    scene = result.get("scene_type", "")
    if scene not in VALID_SCENES:
        result["scene_type"] = "unclear"
    if "time_type_match" not in result:
        result["time_type_match"] = None
    if "reason_match" not in result:
        result["reason_match"] = None
    if not result.get("expected_time_type"):
        result["expected_time_type"] = "需综合判断"
    if not result.get("actual_time_type"):
        result["actual_time_type"] = "未提取到"
    return result


def validate_and_repair(result: dict, schema_name: str = "") -> dict:
    """校验 LLM 返回的 JSON 字段，并自动修复语义问题。总是返回合法 dict。"""
    repaired = dict(result) if isinstance(result, dict) else {}

    # --- has_issue 修复 ---
    has_issue = repaired.get("has_issue")
    if isinstance(has_issue, str):
        normalized = has_issue.strip()
        if normalized in ("是", "存在", "有问题", "true", "True", "YES", "yes"):
            repaired["has_issue"] = True
        elif normalized in ("否", "无", "没问题", "false", "False", "NO", "no"):
            repaired["has_issue"] = False
        else:
            repaired["has_issue"] = False
            repaired["_parse_fallback"] = True
    elif not isinstance(has_issue, bool) and has_issue is not None:
        repaired["has_issue"] = False
        repaired["_parse_fallback"] = True
    if "has_issue" not in repaired or repaired["has_issue"] is None:
        repaired["has_issue"] = False

    # --- risk_level 修复 ---
    risk = repaired.get("risk_level", "")
    repaired["risk_level"] = RISK_MAP.get(
        str(risk).strip(),
        risk if risk in ("高", "中", "低", "人工复核") else "低"
    )

    # --- reason 修复 ---
    reason = repaired.get("reason", "")
    has_issue_val = repaired.get("has_issue", False)
    if has_issue_val and (not reason or str(reason).strip() in ("", "无", "None", "未检出", "无问题")):
        repaired["reason"] = "模型未提供具体理由，建议人工复核"
    if not has_issue_val and not repaired.get("reason"):
        repaired["reason"] = ""

    # --- suggestion 修复 ---
    suggestion = repaired.get("suggestion", "")
    if has_issue_val and (not suggestion or str(suggestion).strip() == ""):
        repaired["suggestion"] = "建议人工复核"
    if not has_issue_val and not repaired.get("suggestion"):
        repaired["suggestion"] = ""

    # --- M3 特有字段修复 ---
    if schema_name == "analyze_contract_dissolution":
        repaired = _repair_m3_fields(repaired)

    return repaired



def _do_call_sync(prompt: str, temperature: float, max_tokens: int, function_schema: dict) -> dict:
    """实际的 OpenAI API 调用（同步，在线程池中执行）"""
    try:
        kwargs = {
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if max_tokens > 0:
            kwargs["max_tokens"] = max_tokens

        schema_name = "none"
        if function_schema:
            schema_name = function_schema.get("name", "")
            # 使用 tools API（替代已废弃的 functions/function_call）
            kwargs["tools"] = [{"type": "function", "function": function_schema}]
            kwargs["tool_choice"] = {"type": "function", "function": {"name": schema_name}}

        logger.debug(f"[_do_call_sync] API call started, schema={schema_name}, prompt_len={len(prompt)}")

        response = get_client().chat.completions.create(**kwargs)
        msg = response.choices[0].message

        # 处理 tool_calls（新版 API）
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            raw_args = tool_calls[0].function.arguments
            try:
                result = json.loads(raw_args)
                logger.debug(f"[_do_call_sync] succeeded via tool_calls, schema={schema_name}")
                return result
            except json.JSONDecodeError:
                # 不立即抛异常，尝试用 extract_json 修复
                try:
                    result = extract_json(raw_args)
                    logger.debug(f"[_do_call_sync] succeeded via tool_calls+extract_json repair, schema={schema_name}")
                    return result
                except ValueError:
                    raise ValueError(f"Tool call arguments JSON parse error: {raw_args[:200]}")

        # 向后兼容：仍返回 function_call 格式的 API
        function_call = getattr(msg, "function_call", None)
        if function_call:
            raw_args = function_call.arguments
            try:
                result = json.loads(raw_args)
                logger.debug(f"[_do_call_sync] succeeded via function_call (legacy), schema={schema_name}")
                return result
            except json.JSONDecodeError:
                try:
                    result = extract_json(raw_args)
                    logger.debug(f"[_do_call_sync] succeeded via function_call+extract_json repair, schema={schema_name}")
                    return result
                except ValueError:
                    raise ValueError(f"Function arguments JSON parse error: {raw_args[:200]}")

        # 备用：如果没有 tool_calls 也没有 function_call，尝试从 content 提取
        content = getattr(msg, "content", None)
        if content:
            result = extract_json(content)
            logger.debug(f"[_do_call_sync] succeeded via content extract, schema={schema_name}")
            return result

        raise ValueError("API返回内容为空")

    except json.JSONDecodeError as e:
        raise ValueError(f"API返回非JSON格式: {e}")
    except Exception as e:
        error_str = str(e)
        if "429" in error_str or "rate_limit" in error_str.lower():
            raise ValueError(f"429 限流: {error_str}")
        if "timeout" in error_str.lower() or "timed out" in error_str.lower():
            raise ValueError(f"API调用超时: {error_str}")
        raise ValueError(f"API错误: {error_str}")


async def call_llm_with_retry(
    prompt: str,
    temperature: float = 0,
    max_tokens: int = 0,
    max_retries: int = 2,
    function_schema: dict = None,
) -> dict:
    """
    异步调用 LLM，带并发限制、三级降级重试和自动修复机制。

    三级降级策略：
    - Level 1 (attempt 0): 正常 tool_choice 调用
    - Level 2 (attempt 1): 追加 retry_hint，保持 tool_choice
    - Level 3 (attempt 2): 去掉 tool_choice，纯文本模式 + temperature=0.3
    全部失败后：使用 validate_and_repair 兜底，不再抛异常。
    """
    retry_hint = (
        "\n\n【重要提醒】上一次输出未通过校验，请严格按以下要求重新输出："
        "1. risk_level 只能填写 高 或 中 或 低 或 人工复核，不能填其他任何内容；"
        "2. reason 必须引用原文关键句，不能为空，不能填 无 或 无问题；"
        "3. M3模型还需要确保 scene_type、expected_time_type、actual_time_type、time_type_match、reason_match 字段完整。"
    )

    schema_name = function_schema.get("name", "") if function_schema else ""
    last_result = {}

    # 信号量获取最多等待 60 秒
    acquired = False
    try:
        await asyncio.wait_for(_acquire_llm_slot(), timeout=60)
        acquired = True
    except asyncio.TimeoutError:
        logger.error("Semaphore acquire timeout (60s) for LLM request")
        raise ValueError("等待 AI 并发槽位超时（60秒），请稍后重试")

    try:
        for attempt in range(max_retries + 1):
            try:
                # Level 1-2: 使用 tool_choice；Level 3: 纯文本模式
                use_tool = (function_schema is not None) and (attempt < max_retries)
                use_temp = temperature if attempt < max_retries else 0.3

                result = await asyncio.to_thread(
                    _do_call_sync,
                    prompt,
                    use_temp,
                    max_tokens,
                    function_schema if use_tool else None,
                )

                last_result = result

                # 严格校验
                is_valid, err_msg = _validate_strict(result, schema_name)
                if is_valid:
                    # 通过严格校验后，执行语义修复
                    result = validate_and_repair(result, schema_name)
                    logger.debug(f"[call_llm_with_retry] success on attempt {attempt+1}, schema={schema_name}")
                    return result

                # 校验失败，重试
                if attempt < max_retries:
                    logger.warning(
                        f"LLM validation failed (attempt {attempt+1}/{max_retries+1}, "
                        f"level={'tool' if use_tool else 'text'}): {err_msg}"
                    )
                    prompt = prompt + retry_hint
                    await asyncio.sleep(0.5)
                    continue

                # 全部重试耗尽：用 validate_and_repair 兜底，不抛异常
                logger.warning(
                    f"LLM call failed all {max_retries+1} attempts for {schema_name}, "
                    f"using validate_and_repair fallback"
                )
                result = validate_and_repair(last_result, schema_name)
                result["_parse_fallback"] = True
                return result

            except ValueError as e:
                error_str = str(e)
                is_rate_limit = (
                    "429" in error_str or
                    "限流" in error_str or
                    "529" in error_str or
                    "timeout" in error_str.lower() or
                    "timed out" in error_str.lower()
                )
                if is_rate_limit and attempt < max_retries:
                    logger.warning(
                        f"LLM rate limit/timeout, retry {attempt+1}/{max_retries+1}, "
                        f"waiting {2**(attempt+1)}s"
                    )
                    _release_llm_slot()
                    acquired = False
                    wait_time = 2 ** (attempt + 1)
                    await asyncio.sleep(wait_time)
                    try:
                        await asyncio.wait_for(_acquire_llm_slot(), timeout=60)
                        acquired = True
                    except asyncio.TimeoutError as exc:
                        raise ValueError("等待 AI 并发槽位超时（60秒），请稍后重试") from exc
                    continue

                # 非限流错误且已是最后一轮：兜底修复
                if attempt >= max_retries:
                    logger.warning(
                        f"LLM call error on final attempt for {schema_name}: {error_str}, "
                        f"using validate_and_repair fallback"
                    )
                    result = validate_and_repair(last_result, schema_name)
                    result["_parse_fallback"] = True
                    return result

                raise
    finally:
        if acquired:
            _release_llm_slot()
