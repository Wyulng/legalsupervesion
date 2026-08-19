"""
LLM 调用封装模块
统一封装"截面提取 → 组装 prompt → 发送 LLM → 解析结果"完整流程
"""

import logging
from typing import Dict, Tuple, Optional

from .section_assembler import (
    assemble_sections,
    check_special_m1,
    check_m10_skip_condition,
)
from .llm_client import call_llm_with_retry, FUNCTION_SCHEMAS

logger = logging.getLogger(__name__)


class LLMCaller:
    """
    统一封装单个模型的审查完整流程。
    """

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.function_schema = FUNCTION_SCHEMAS.get(model_name)

    async def call(self, full_text: str) -> Tuple[str, str, Dict]:
        """
        执行完整的单模型审查流程。

        Returns:
            (model_name, status, result_dict)
            - model_name: "m1" / "m5" / "m10" / "m3"
            - status: "success" / "api_error" / "skipped"
            - result_dict: 各模型返回字段
        """
        logger.debug(f"[LLMCaller.{self.model_name}] call entered")

        # 特殊前置检查（仅 M1 有效）
        if self.model_name == "m1":
            special_result = check_special_m1(full_text)
            if special_result is not None:
                logger.debug(f"[LLMCaller.{self.model_name}] skipped by special_m1 check")
                return self.model_name, "skipped", special_result

        # M10 快速退出检查
        if self.model_name == "m10":
            skip_result = check_m10_skip_condition(full_text)
            if skip_result is not None:
                logger.debug(f"[LLMCaller.{self.model_name}] skipped by m10_skip_condition")
                return self.model_name, "skipped", skip_result

        # 步骤1：提取板块
        sections = assemble_sections(full_text, self.model_name)
        logger.debug(f"[LLMCaller.{self.model_name}] sections extracted: {list(sections.keys())}")

        # 板块提取结果为空时的降级处理
        if not sections:
            logger.debug(f"[LLMCaller.{self.model_name}] sections empty, skipped")
            return self.model_name, "skipped", {
                "issue": "无法分析",
                "reason": "文书结构异常，未提取到有效板块",
                "risk": "低",
                "status": "skipped",
            }

        # 步骤2：组装 prompt
        prompt = self._build_prompt(sections)
        if prompt is None:
            logger.debug(f"[LLMCaller.{self.model_name}] prompt build failed")
            return self.model_name, "prompt_error", {"error": f"Prompt build failed for model: {self.model_name}"}

        # 步骤3：发送 LLM
        logger.debug(f"[LLMCaller.{self.model_name}] calling LLM, prompt_len={len(prompt)}")
        try:
            llm_out = await call_llm_with_retry(prompt, 0, max_tokens=4096, function_schema=self.function_schema)
            logger.debug(f"[LLMCaller.{self.model_name}] LLM succeeded, result_keys={list(llm_out.keys())}")
            # 最终兜底结果代表模型输出未通过校验或 API 调用失败，不能继续
            # 作为“无问题”映射，否则真实的分析失败会被静默漏报。
            if llm_out.get("_parse_fallback"):
                return self.model_name, "api_error", {
                    "error": "AI返回结果未通过校验，建议人工复核",
                }
            return self.model_name, "success", llm_out
        except ValueError as e:
            logger.debug(f"[LLMCaller.{self.model_name}] LLM api_error: {e}")
            return self.model_name, "api_error", {"error": str(e)}
        except Exception as e:
            # 不让单个模型的意外异常被 asyncio.gather 静默丢弃，
            # 否则 ReviewResult 会保留初始 success 状态并误显示未检测。
            logger.exception(f"[LLMCaller.{self.model_name}] unexpected error")
            return self.model_name, "api_error", {"error": f"模型处理异常: {e}"}

    def _build_prompt(self, sections: Dict[str, str]) -> Optional[str]:
        """根据模型名和板块字典组装 prompt，异常时返回 None"""
        try:
            if self.model_name == "m1":
                from app.main import build_prompt_m1
                return build_prompt_m1(
                    sections.get("trial_process", ""),
                    sections.get("judgment_result", ""),
                )
            elif self.model_name == "m5":
                from app.main import build_prompt_m5
                return build_prompt_m5(sections.get("judgment_result", ""))
            elif self.model_name == "m10":
                from app.main import build_prompt_m10
                return build_prompt_m10(sections.get("judgment_result", ""))
            elif self.model_name == "m3":
                from app.main import build_prompt_m3
                return build_prompt_m3(
                    sections.get("judgment_reason", ""),
                    sections.get("judgment_result", ""),
                    sections.get("trial_process", ""),
                )
            else:
                return None
        except Exception:
            return None


def call_single_model(model_name: str, full_text: str) -> Tuple[str, Dict]:
    """
    同步版本入口，供 ThreadPoolExecutor 批量处理调用。
    注意：内部使用 asyncio.run，仅适合在无运行中事件循环的同步上下文中调用。
    """
    import asyncio
    _, status, data = asyncio.run(LLMCaller(model_name).call(full_text))
    return status, data
