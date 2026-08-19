from pydantic import BaseModel, Field
from typing import Optional, List


class ReviewResult(BaseModel):
    filename: str
    # ---------- M1 ----------
    model1_candidate: bool = Field(False, description="正则初筛是否命中")
    model1_status: Optional[str] = Field(None, description="处理状态：success/api_error/processing_error/file_error/skipped")
    model1_issue: Optional[str] = Field(None, description="最终结论：存在问题/无问题")
    model1_reason: Optional[str] = Field(None, description="判断理由，引用原文关键句")
    model1_risk: Optional[str] = Field(None, description="风险等级：高/中/低/人工复核")
    model1_suggestion: Optional[str] = Field(None, description="检察建议，不超过50字")
    # ---------- M5 ----------
    model5_candidate: bool = Field(False, description="正则初筛是否命中")
    model5_status: Optional[str] = Field(None, description="处理状态：success/api_error/processing_error/skipped")
    model5_issue: Optional[str] = Field(None, description="最终结论：存在问题/无问题")
    model5_reason: Optional[str] = Field(None, description="判断理由，引用原文关键句")
    model5_risk: Optional[str] = Field(None, description="风险等级：高/中/低/人工复核")
    model5_suggestion: Optional[str] = Field(None, description="检察建议，不超过50字")
    # ---------- M10 ----------
    model10_candidate: bool = Field(False, description="正则初筛是否命中")
    model10_status: Optional[str] = Field(None, description="处理状态：success/api_error/processing_error/skipped")
    model10_issue: Optional[str] = Field(None, description="最终结论：存在问题/无问题")
    model10_reason: Optional[str] = Field(None, description="判断理由，引用原文关键句")
    model10_risk: Optional[str] = Field(None, description="风险等级：高/中/低/人工复核")
    model10_suggestion: Optional[str] = Field(None, description="检察建议，不超过50字")
    # ---------- M3（通用字段在前，扩展字段在后） ----------
    model3_candidate: bool = Field(False, description="正则初筛是否命中")
    model3_status: Optional[str] = Field(None, description="处理状态：success/api_error/processing_error/skipped")
    model3_issue: Optional[str] = Field(None, description="最终结论：存在问题/无问题")
    model3_reason: Optional[str] = Field(None, description="判断理由，引用原文关键句")
    model3_risk: Optional[str] = Field(None, description="风险等级：高/中/低/人工复核")
    model3_suggestion: Optional[str] = Field(None, description="检察建议，不超过50字")
    # M3 扩展字段（应然vs实然比对）
    model3_scene_type: Optional[str] = Field(None, description="合同解除场景类型，如 type_a_notice、type_b_deadlock 等")
    model3_expected_time_type: Optional[str] = Field(None, description="应然解除时间类型")
    model3_actual_time_type: Optional[str] = Field(None, description="实然解除时间类型（从判决书提取）")
    model3_time_type_match: Optional[bool] = Field(None, description="应然与实然时间类型是否一致")
    model3_reason_match: Optional[bool] = Field(None, description="推理理由与判决书理由是否一致")


class BatchReviewResponse(BaseModel):
    total: int
    results: List[ReviewResult]
