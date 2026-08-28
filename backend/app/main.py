import asyncio
import csv
import logging
import os
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Thread
from typing import List, Optional, Callable

logger = logging.getLogger(__name__)

# 初始化日志配置
from app.logging_config import setup_logging
setup_logging()

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from .config import UPLOAD_DIR, RESULT_DIR
from .models.schemas import ReviewResult
from .services.file_parser import parse_file
from .services.regex_filter import is_candidate_m1, is_candidate_m5, is_candidate_m10, is_candidate_m3
from .services.task_store import create_task, get_task, process_task_async, TaskStatus
from .services.llm_caller import LLMCaller
from .services.m10_rules import M10LawContext, format_m10_law_context

# 初始化 FastAPI
app = FastAPI(title="法律监督模型API", description="针对民事判决书的公告费、诉讼费直接支付、加倍利息缺失问题审查", version="1.0.0")

# ---------- 配置 CORS ----------
# 根据环境选择允许的来源
_allowed_origins = os.environ.get("CORS_ORIGINS", "*").split(",") if os.environ.get("CORS_ORIGINS") else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- 优雅停机 ----------
# 通过 uvicorn 生命周期钩子处理 SIGTERM
@app.on_event("shutdown")
def on_shutdown():
    from app.services.task_store import request_shutdown
    request_shutdown()

# ---------- 提示词模板 ----------
def build_prompt_m1(trial: str, result: str) -> str:
    return f"""【重要】你只能输出纯JSON格式，不要输出任何其他文字。

你是一位民事检察监督专家。请分析以下判决书片段，判断是否存在"法院采用公告送达但未判决公告费"的问题。

【审理经过】
{trial}

【裁判结果】
{result}

判断流程（分两步判断）：

第一步：判断是否采用了法院公告送达
- 全文检索以下关键词组合：
  - "公告送达"、"本院公告送达"、"法院公告送达"、"登报公告送达"、"公告期满"
  - "本院依法公告"、"法院依法公告"
- 排除以下非法院公告情形：
  - 当事人自行登报的"停业公告"、"清算公告"、"注销公告"
  - 当事人张贴的"停业通知"、"搬迁通知"
- 判断依据：须为主语是"本院/法院"的主动句，如"本院依法公告送达"有效，"当事人自行登报"无效

第二步：检查公告费是否已在裁判结果中明确处理
在裁判结果中检索"公告费"：
- 裁判结果完全没有提及公告费 → 属于"存在问题"
- 裁判结果写了"公告费由被告/原告/当事人承担"但未写明具体金额 → 属于"存在问题"
- 裁判结果写了"公告费xxx元，由xxx承担"（有具体金额）→ 无问题
- 驳回全部诉请的案件，若审理经过中有公告送达，仍需处理公告费，属于"存在问题"

风险等级：
- 高：涉及多名被告（2人及以上）的公告送达，且公告费漏判
- 中：单一被告的公告送达，公告费漏判
- 低：公告送达后驳回全部诉请，但公告费已在其他文书中处理

【示例1 - 两步均有问题】
审理经过：本院立案后，依法适用简易程序审理本案，因被告下落不明，本院依法公告送达起诉状副本及开庭传票，公告期满后被告未到庭，本院依法缺席审理。
裁判结果：被告应于判决生效后十日内给付原告货款人民币50000元。
输出：{{"has_issue": true, "reason": "本院依法公告送达起诉状副本及开庭传票，但裁判结果中未判决公告费", "risk_level": "高", "suggestion": "建议补充判决公告费由被告承担"}}

【示例2 - 第一步有问题（驳回诉请但漏判公告费）】
审理经过：经查，被告李四住址不明，本院通过《人民法院报》登报公告送达应诉通知书，公告期60日届满，被告未提出答辩。
裁判结果：驳回上诉，维持原判。案件受理费由原告承担。
输出：{{"has_issue": true, "reason": "本院通过《人民法院报》登报公告送达应诉通知书，但裁判结果未处理公告费", "risk_level": "中", "suggestion": "建议补充公告费负担条款"}}

【示例3 - 两步均无问题】
审理经过：被告经合法传票传唤，无正当理由拒不到庭，本院依法缺席审理。
裁判结果：一、被告于判决生效后十五日内给付原告借款本金人民币30000元及利息；二、公告费人民币300元由被告承担。
输出：{{"has_issue": false, "reason": "审理经过中无法院公告送达情形，裁判结果中已明确公告费负担", "risk_level": "低", "suggestion": ""}}

【示例4 - 无问题（非法院公告）】
审理经过：本院立案后，原告向本院提交被告停业公告一份，公告期已满，本院依法缺席审理。
裁判结果：被告应于判决生效后十日内给付原告货款20000元。
输出：{{"has_issue": false, "reason": ""停业公告"为当事人自行登报，非法院公告送达", "risk_level": "低", "suggestion": ""}}

【示例5 - 无问题（公告费已处理）】
审理经过：本院立案后，因被告下落不明，本院依法在《人民法院报》登报公告送达应诉通知书和开庭传票，公告期届满后被告未到庭。
裁判结果：一、被告给付原告借款本金50000元；二、公告费500元由被告承担。
输出：{{"has_issue": false, "reason": "裁判结果已明确公告费500元由被告承担", "risk_level": "低", "suggestion": ""}}

输出要求：
- 必须只输出JSON，不要任何解释、推理或备注文字
- JSON格式：{{"has_issue": true或false, "reason": "引用原文关键句", "risk_level": "高/中/低", "suggestion": "不超过50字的建议"}}
"""


def build_prompt_m5(result: str) -> str:
    return f"""【重要】你只能输出纯JSON格式，不要输出任何其他文字。

你是一位民事检察监督专家。请分析以下判决书片段，判断是否存在"诉讼费用由败诉方直接支付给胜诉方"的不规范情形。

【裁判结果】
{result}

判断标准：
1. 在裁判结果中定位包含"案件受理费"或"申请费"的完整句段（向前向后各扩展50字）。
2. 以下费用必须向人民法院交纳，不能直接支付给胜诉方：
   - 案件受理费：必须由败诉方向法院缴纳
   - 申请费：必须由败诉方向法院缴纳
   - 证人、鉴定人、翻译人员、理算人员在人民法院指定日期出庭发生的交通费、住宿费、生活费、误工补贴：必须由败诉方向法院缴纳
3. 以下费用可以直接支付给胜诉方（属于正常情形）：
   - 公告费：可直付胜诉方
   - 鉴定费、评估费：可直付胜诉方
   - 其他程序性费用
4. 违规判断：案件受理费或申请费出现"直接支付"、"径向"、"径付"、"支付给"等关键词，且未写明向法院缴纳
5. 合规情形（不属于问题）：
   - "案件受理费xxx元，由被告于判决生效后十日内向法院缴纳"（向法院缴纳 ✓）
   - "申请费xxx元，由被告向法院缴纳"（向法院缴纳 ✓）
   - "公告费xxx元由被告直接支付给原告"（公告费可直付 ✓）
   - "鉴定费xxx元由被告支付给原告"（鉴定费可直付 ✓）
6. 风险等级：
   - 高：涉及金额较大或批量案件
   - 中：单案金额一般
   - 低：金额较小

【示例1 - 有问题】
裁判结果：案件受理费人民币1500元，由被告张三直接支付给原告李四，于判决生效后十日内付清。
输出：{{"has_issue": true, "reason": "案件受理费由被告直接支付给原告，未向法院缴纳", "risk_level": "高", "suggestion": "建议改判由被告向法院缴纳案件受理费"}}

【示例2 - 有问题】
裁判结果：一、被告偿还原告借款本金50000元；二、申请费1200元由被告径付原告。
输出：{{"has_issue": true, "reason": "申请费1200元由被告径付原告，未向法院缴纳", "risk_level": "高", "suggestion": "建议纠正为向法院缴纳申请费"}}

【示例3 - 无问题（公告费可直付）】
裁判结果：一、被告应于判决生效后十日内给付原告货款50000元；二、公告费300元由被告直接支付给原告。
输出：{{"has_issue": false, "reason": "公告费可由败诉方直接支付给胜诉方，符合规范", "risk_level": "低", "suggestion": ""}}

【示例4 - 无问题（鉴定费可直付）】
裁判结果：被告应于判决生效后十五日内支付原告鉴定费1500元。
输出：{{"has_issue": false, "reason": "鉴定费可由败诉方直接支付给胜诉方，符合规范", "risk_level": "低", "suggestion": ""}}

【示例5 - 无问题（向法院缴纳）】
裁判结果：案件受理费人民币2000元（原告已预交），由被告于判决生效后十日内向法院缴纳。
输出：{{"has_issue": false, "reason": "案件受理费由被告向法院缴纳，符合规范", "risk_level": "低", "suggestion": ""}}

【示例6 - 无问题（申请费向法院缴纳）】
裁判结果：申请费500元，由被告于判决生效后十日内向法院缴纳。
输出：{{"has_issue": false, "reason": "申请费由被告向法院缴纳，符合规范", "risk_level": "低", "suggestion": ""}}

输出要求：
- 必须只输出JSON，不要任何解释、推理或备注文字
- JSON格式：{{"has_issue": true或false, "reason": "引用原文关键句", "risk_level": "高/中/低", "suggestion": "不超过50字的建议"}}
"""

def build_prompt_m10(result: str, law_context: Optional[M10LawContext] = None) -> str:
    """组装 M10 提示词；法律版本信息由调用方从文书落款日期传入。"""
    context_text = format_m10_law_context(law_context) if law_context is not None else "未提供裁判日期，不能自行推断适用版本。"
    return f"""【重要】你只能输出纯JSON格式，不要输出任何其他文字。

你是一位民事检察监督专家。请分析以下判决书片段，判断金钱给付义务是否载明了适用版本下的“加倍支付迟延履行期间的债务利息”。

【裁判日期与适用版本】
{context_text}

版本对应关系：
- 2022年1月1日前的裁判日期：2017年修正版《民事诉讼法》第253条；
- 2022年1月1日至2023年12月31日：2021年修正版《民事诉讼法》第260条；
- 2024年1月1日以后：2023年修正版《民事诉讼法》第264条。
裁判日期以文书末尾审判员、书记员等落款后的日期为准。日期缺失、存在多个无法区分的日期，或适用时间无法确定时，不得自行推断，输出待人工复核。

【裁判结果】
{result}

判断标准：
1. 先逐项识别金钱给付义务，包括给付、支付、赔偿、返还、退还、补偿、偿还等明确金额或计算方式的义务。仅有继续履行、恢复原状、排除妨害、交付物品等行为义务时，不进入金钱利息判断；同时存在行为义务和金钱义务时，分别判断金钱义务。
   - 精神损害赔偿中的精神抚慰金不单独作为本项金钱给付义务。
   - 诉讼费、保全费、鉴定费、评估费和合同违约金是否属于需要审查的给付项目，应结合主文确定的收款对象、给付方式和适用法律逐项判断，不直接推定。
2. 对每项金钱给付义务，重点检查是否明确写出“加倍支付迟延履行期间的债务利息”，或引用了与裁判日期相匹配的第253、260、264条。法条编号与裁判日期不匹配时，判定为存在问题。
   - 《民事诉讼法》第253、260、264条分别对应上列三个版本，不能脱离裁判日期笼统适用。
   - 《民事诉讼法解释》第506条只规定迟延履行期间债务利息的起算时间；单独引用第506条不能替代加倍利息条款。
   - “迟延履行金”用于其他义务的迟延履行，不等同于金钱给付义务的“迟延履行期间的债务利息”。
   - 普通逾期利息、LPR利息或合同违约金不能单独替代法定加倍利息。
3. 金钱给付已经明确即时履行且无履行期限的，可结合主文判断是否仍有迟延履行期间；再审文书已经明确利息计算方式的，引用原文作出判断。
4. 风险等级：高为有金额、有履行期限但未载明法定加倍利息；中为法条版本不匹配、只引用第506条或其他条款不完整；低为条款完整或不涉及金钱给付。

【示例1 - 有问题】
裁判结果：被告应于判决生效后十日内给付原告货款人民币80000元。
输出：{{"has_issue": true, "reason": "被告应于判决生效后十日内给付货款80000元，但未载明加倍支付迟延履行期间的债务利息", "risk_level": "高", "suggestion": "建议补充适用版本的法定加倍利息条款"}}

【示例2 - 有问题】
裁判日期：2024年5月1日；裁判结果：被告应于判决生效后十日内支付工程款300000元，依据《民事诉讼法》第253条加倍支付迟延履行期间的利息。
输出：{{"has_issue": true, "reason": "2024年裁判应适用2023年修正版第264条，但主文引用第253条", "risk_level": "中", "suggestion": "核对裁判日期并改用对应版本条文"}}

【示例3 - 无问题】
裁判日期：2024年5月1日；裁判结果：被告应于判决生效后十五日内返还货款50000元，并依据《民事诉讼法》第264条加倍支付迟延履行期间的债务利息。
输出：{{"has_issue": false, "reason": "裁判日期与第264条版本匹配，且主文明确载明加倍支付迟延履行期间的债务利息", "risk_level": "低", "suggestion": ""}}

【示例4 - 有问题】
裁判日期无法确认；裁判结果：被告应于判决生效后十五日内返还货款50000元，并加倍支付迟延履行期间的债务利息。
输出：{{"has_issue": true, "reason": "无法确定裁判日期及适用法律版本", "risk_level": "中", "suggestion": "待人工复核裁判日期和法条版本"}}

【示例5 - 非金钱给付】
裁判日期：2024年5月1日；裁判结果：被告应于判决生效后三十日内将涉案房屋腾空并返还原告。
输出：{{"has_issue": false, "reason": "裁判结果仅包含行为义务，不涉及金钱给付义务", "risk_level": "低", "suggestion": ""}}

输出要求：
- 必须只输出JSON，不要任何解释、推理或备注文字；
- JSON格式：{{"has_issue": true或false, "reason": "引用原文关键句", "risk_level": "高/中/低", "suggestion": "不超过50字的建议"}}。
"""


def build_prompt_m3(reason: str, result: str, trial: str = "") -> str:
    return f"""【重要】你只能输出纯JSON格式，不要输出任何其他文字。

你是一位民事检察监督专家。请对合同解除时间进行审查，直接输出JSON。

【审理经过】
{trial}

【裁判理由】
{reason}

【裁判结果】
{result}

【审查维度】

一、场景识别
根据裁判理由，判断合同解除属于以下哪种情形：
- 类型A（当事人触发）：通知解除、根本违约、迟延履行、预期违约、不可抗力、起诉解除、催告后解除
- 类型B（司法终局）：合同僵局、情势变更、继续履行不能、公平原则、诚信原则、非金钱债务无需继续履行

识别规则：
- 主要援引第563条/第565条，且有通知/催告/违约触发事件 → 类型A
- 主要援引第580条（继续履行不能/合同僵局）、情势变更、公平原则、诚信原则 → 类型B
- 同时出现563和580条表述，以580条为主 → 类型B

二、时间判定
- 类型A应然解除时间：通知到达时/起诉状副本送达时/违约事实发生时（不是判决生效之日）
- 类型B应然解除时间：判决生效之日（合理）；公平/诚信原则：法院酌定

三、实然提取
从裁判结果中提取实际写的解除时间（关键词：判决生效之日起、通知到达之日起、起诉状副本送达之日起等）

四、一致性比对
- 时间类型是否一致（应然 vs 实然）
- 理由是否一致（模型判断理由 vs 判决书理由）

五、法条一致性检查【重点】
- Type A场景（通知解除/根本违约/预期违约）→ 应主要援引563条/565条
- Type B场景（合同僵局/继续履行不能）→ 应主要援引580条或公平原则
- 特别注意：当裁判理由中出现"合同僵局"、"目的无法实现"、"继续履行不能"等表述时：
  - 若仅援引563条（非580条），即使时间写"判决生效之日"，也存在法律依据张力
  - 应识别为"有疑点"，建议人工复核

六、风险等级
- 高风险：时间类型不一致（如类型A却写"判决生效之日解除"），或法条与场景明显不匹配
- 中风险：时间类型一致但理由不一致（如合同僵局，判决正确但理由机械）
- 低风险：类型和理由都基本一致
- 人工复核：案情复杂，涉及多种法律关系或边界特征，或法条援引存在张力

【输出格式】
{{
    "scene_type": "类型标识（type_a_notice / type_a_breach / type_b_deadlock 等）",
    "expected_time_type": "应然解除时间（通知到达时 / 判决生效之日 / 法院酌定）",
    "expected_time_rule": "应然解除时间的规则依据",
    "actual_time_type": "实然解除时间（从判决书提取）",
    "actual_time_text": "实然解除时间的原文",
    "time_type_match": true或false,
    "reason_match": true或false,
    "risk_level": "高/中/低/人工复核",
    "has_issue": true或false,
    "reason": "判断理由，引用原文关键句",
    "suggestion": "不超过50字的建议"
}}

【示例1 - 高风险（时间类型不一致）】
裁判理由：本院认为，根据《民法典》第563条，原告有权解除合同。原告于2024年1月15日向被告发送解除函，被告于2024年1月20日签收。
裁判结果：判决生效之日起解除合同。
输出：{{"scene_type": "type_a_notice", "expected_time_type": "通知到达时解除", "expected_time_rule": "通知解除情形，解除函到达对方时生效，无需法院判决确认", "actual_time_type": "判决生效之日解除", "actual_time_text": "判决生效之日起解除合同", "time_type_match": false, "reason_match": false, "risk_level": "高", "has_issue": true, "reason": "原告已于2024年1月20日收到解除函，合同自通知到达时解除，但判决书仍写'判决生效之日解除'，时间认定错误", "suggestion": "建议更正为解除函到达被告之日起解除"}}

【示例2 - 中风险（类型一致但理由不一致）】
裁判理由：本院认为，双方合同陷入僵局，继续履行对被告显失公平，依据公平原则，判决解除合同。
裁判结果：判决生效之日起解除合同。
输出：{{"scene_type": "type_b_deadlock", "expected_time_type": "判决生效之日解除", "expected_time_rule": "合同僵局属司法终局处理，法院判决解除具有终局性", "actual_time_type": "判决生效之日解除", "actual_time_text": "判决生效之日起解除合同", "time_type_match": true, "reason_match": false, "risk_level": "中", "has_issue": true, "reason": "合同僵局判决'判决生效之日解除'本身合理，但理由机械援引公平原则而非580条，且未充分说理", "suggestion": "建议补充合同僵局认定的说理"}}

【示例3 - 低风险（基本一致）】
裁判理由：本院认为，被告迟延履行主要债务，经催告后仍未履行，原告有权依据第563条第1款第3项解除合同。
裁判结果：判决生效之日起解除合同。
输出：{{"scene_type": "type_a_delay", "expected_time_type": "催告期满时解除", "expected_time_rule": "迟延履行情形，催告期满后解除权生效", "actual_time_type": "判决生效之日解除", "actual_time_text": "判决生效之日起解除合同", "time_type_match": false, "reason_match": true, "risk_level": "低", "has_issue": false, "reason": "虽时间表述为'判决生效之日'，但理由部分已明确迟延履行和催告事实，时间差异系表述习惯，风险低", "suggestion": ""}}

【示例4 - 人工复核（复杂边界）】
裁判理由：本院认为，涉案合同既存在被告迟延履行的违约行为，又存在情势变更因素，继续履行对原告显失公平。
裁判结果：判决生效之日起解除合同。
输出：{{"scene_type": "type_b_change", "expected_time_type": "判决生效之日解除", "expected_time_rule": "情势变更属司法终局处理，法院酌定解除时间", "actual_time_type": "判决生效之日解除", "actual_time_text": "判决生效之日起解除合同", "time_type_match": true, "reason_match": true, "risk_level": "人工复核", "has_issue": true, "reason": "案件同时涉及563条违约和580条情势变更，边界特征明显，建议人工复核", "suggestion": "建议人工复核确定解除时间和法律依据"}}

【示例5 - 高风险（法条与场景不匹配）】
裁判理由：本院认为，现双方合同目的无法实现，为防止合同僵局，依据《民法典》第五百六十三条第一款判决解除合同。
裁判结果：于本判决生效之日解除。
输出：{{"scene_type": "type_b_deadlock", "expected_time_type": "判决生效之日解除", "expected_time_rule": "合同僵局属司法终局处理", "actual_time_type": "判决生效之日解除", "actual_time_text": "于本判决生效之日解除", "time_type_match": true, "reason_match": false, "risk_level": "高", "has_issue": true, "reason": "裁判理由描述'合同僵局'、'目的无法实现'，但仅援引563条而非580条，存在法条与场景不匹配的时间张力，建议人工复核", "suggestion": "建议人工复核法条援引准确性及解除时间认定"}}

【绝对禁止】
- 不要输出任何分析、推理、思考过程
- 不要输出任何非JSON的内容
- 只输出一个JSON对象
"""


# ---------- 辅助函数 ----------
def _map_common_result(result_obj, model_prefix: str, status: str, data: dict):
    """通用 LLM 结果映射，适用于 M1/M5/M10"""
    if status == "skipped":
        reason = data["reason"]
        risk = data["risk"]
        setattr(result_obj, f"{model_prefix}_issue", data["issue"])
        setattr(result_obj, f"{model_prefix}_reason", reason)
        setattr(result_obj, f"{model_prefix}_risk", risk)
        setattr(result_obj, f"{model_prefix}_status", data["status"])
        setattr(result_obj, f"{model_prefix}_suggestion", data.get("suggestion", ""))
    elif status == "success":
        has_issue = data.get("has_issue")
        reason = data.get("reason", "") or "不存在问题"
        risk = data.get("risk_level", "") or "低"
        setattr(result_obj, f"{model_prefix}_issue", "存在问题" if has_issue else "无问题")
        setattr(result_obj, f"{model_prefix}_reason", reason)
        setattr(result_obj, f"{model_prefix}_risk", risk)
        setattr(result_obj, f"{model_prefix}_status", "success")
        setattr(result_obj, f"{model_prefix}_suggestion", data.get("suggestion", ""))
    else:  # api_error / prompt_error 等
        setattr(result_obj, f"{model_prefix}_issue", "存在问题")
        setattr(result_obj, f"{model_prefix}_reason", data.get("error", f"API错误: {status}"))
        setattr(result_obj, f"{model_prefix}_risk", "未知")
        setattr(result_obj, f"{model_prefix}_status", status)
        setattr(result_obj, f"{model_prefix}_suggestion", "")


# ---------- 核心处理函数 ----------
def process_single_file(file_path: Path) -> ReviewResult:
    """处理单个文件，返回审查结果"""
    start_time = time.time()
    full_text = parse_file(file_path)
    if not full_text:
        logger.warning(f"File parse failed: {file_path.name}")
        return ReviewResult(
            filename=file_path.name,
            model1_candidate=False,
            model5_candidate=False,
            model10_candidate=False,
            model3_candidate=False,
            model1_status="file_error",
            model1_issue="文件读取失败",
            model1_reason="",
            model1_risk="未知",
            model1_suggestion="",
            model5_status="file_error",
            model5_issue="文件读取失败",
            model5_reason="",
            model5_risk="未知",
            model5_suggestion="",
            model10_status="file_error",
            model10_issue="文件读取失败",
            model10_reason="",
            model10_risk="未知",
            model10_suggestion="",
            model3_status="file_error",
            model3_issue="文件读取失败",
            model3_reason="",
            model3_risk="未知",
            model3_suggestion="",
            model3_scene_type="",
            model3_expected_time_type="",
            model3_actual_time_type="",
            model3_time_type_match=None,
            model3_reason_match=None
        )

    # 正则初筛
    is_m1 = is_candidate_m1(full_text)
    is_m5 = is_candidate_m5(full_text)
    is_m10 = is_candidate_m10(full_text)
    is_m3 = is_candidate_m3(full_text)

    result = ReviewResult(
        filename=file_path.name,
        model1_candidate=is_m1,
        model5_candidate=is_m5,
        model10_candidate=is_m10,
        model3_candidate=is_m3,
        model1_status="success" if is_m1 else None,
        model5_status="success" if is_m5 else None,
        model10_status="success" if is_m10 else None,
        model3_status="success" if is_m3 else None,
    )

    # ----- 收集并并发执行各模型 LLM 任务 -----
    async def _run_llm_concurrent():
        await asyncio.sleep(0)  # 让出控制权，确保在事件循环中

        tasks = []
        if is_m1:
            tasks.append(LLMCaller("m1").call(full_text))
        if is_m5:
            tasks.append(LLMCaller("m5").call(full_text))
        if is_m10:
            tasks.append(LLMCaller("m10").call(full_text))
        if is_m3:
            tasks.append(LLMCaller("m3").call(full_text))

        if not tasks:
            logger.info(f"No model triggered for {file_path.name}")
            return

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        # 记录异常
        exceptions = [item for item in results_list if isinstance(item, Exception)]
        if exceptions:
            logger.error(f"{len(exceptions)} model(s) failed for {file_path.name}: {[str(e) for e in exceptions]}")

        results_map = {}
        for item in results_list:
            if isinstance(item, Exception):
                continue
            model_name, status, data = item
            results_map[model_name] = (status, data)

        # M1 结果映射
        if "m1" in results_map:
            _map_common_result(result, "model1", *results_map["m1"])

        # M5 结果映射
        if "m5" in results_map:
            _map_common_result(result, "model5", *results_map["m5"])

        # M10 结果映射
        if "m10" in results_map:
            _map_common_result(result, "model10", *results_map["m10"])

        if "m3" in results_map:
            status, d = results_map["m3"]
            if status == "success":
                reason = d.get("reason") or "不存在合同解除时间认定错误"
                risk = d.get("risk_level", "") or "低"
                result.model3_issue = "存在问题" if d.get("has_issue") else "无问题"
                result.model3_reason = reason
                result.model3_risk = risk
                result.model3_status = "success"
                result.model3_scene_type = d.get("scene_type", "")
                result.model3_expected_time_type = d.get("expected_time_type", "")
                result.model3_actual_time_type = d.get("actual_time_type", "")
                result.model3_time_type_match = d.get("time_type_match", False)
                result.model3_reason_match = d.get("reason_match", False)
                result.model3_suggestion = d.get("suggestion", "")
            else:
                status_label = status
                if status == "skipped":
                    status_label = "skipped"
                elif status == "prompt_error":
                    status_label = "prompt_error"
                else:
                    status_label = "api_error"
                result.model3_issue = "存在问题"
                result.model3_reason = d.get("error", f"API错误: {status}")
                result.model3_risk = "未知"
                result.model3_status = status_label
                result.model3_scene_type = ""
                result.model3_expected_time_type = ""
                result.model3_actual_time_type = ""
                result.model3_time_type_match = None
                result.model3_reason_match = None
                result.model3_suggestion = ""

        logger.debug(f"Processed {file_path.name} in {time.time() - start_time:.2f}s")

    asyncio.run(_run_llm_concurrent())

    return result

def process_batch(file_paths: List[Path], progress_callback: Optional[Callable[[int, int], None]] = None) -> List[ReviewResult]:
    """批量处理文件，文件级并发

    Args:
        file_paths: 要处理的文件路径列表
        progress_callback: 每完成一个文件后调用的回调，签名为 (completed: int, total: int) -> None
    """
    results = []
    total = len(file_paths)
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(process_single_file, fp): fp for fp in file_paths}
        for i, future in enumerate(as_completed(futures)):
            fp = futures[future]
            try:
                results.append(future.result())
                if progress_callback:
                    progress_callback(i + 1, total)
            except KeyboardInterrupt:
                # 系统关机信号，停止处理
                raise
            except Exception as e:
                results.append(ReviewResult(
                    filename=fp.name,
                    model1_candidate=False,
                    model5_candidate=False,
                    model10_candidate=False,
                    model3_candidate=False,
                    model1_status="processing_error",
                    model1_issue=f"处理异常: {str(e)}",
                    model5_status="processing_error",
                    model5_issue=f"处理异常: {str(e)}",
                    model10_status="processing_error",
                    model10_issue=f"处理异常: {str(e)}",
                    model3_status="processing_error",
                    model3_issue=f"处理异常: {str(e)}",
                    model3_scene_type="",
                    model3_expected_time_type="",
                    model3_actual_time_type="",
                    model3_time_type_match=None,
                    model3_reason_match=None
                ))
            logger.info(f"Batch progress: {i+1}/{total} files")
    return results

def save_results_to_csv(results: List[ReviewResult], csv_path: Path):
    """将结果保存为 CSV"""
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        fieldnames = [
            "文件名",
            "模型1_状态", "模型1_候选", "模型1_最终问题", "模型1_理由", "模型1_风险", "模型1_建议",
            "模型5_状态", "模型5_候选", "模型5_最终问题", "模型5_理由", "模型5_风险", "模型5_建议",
            "模型10_状态", "模型10_候选", "模型10_最终问题", "模型10_理由", "模型10_风险", "模型10_建议",
            "模型3_状态", "模型3_候选", "模型3_场景类型", "模型3_应然类型", "模型3_实然类型",
                "模型3_类型匹配", "模型3_理由匹配", "模型3_最终问题", "模型3_理由", "模型3_风险", "模型3_建议"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({
                "文件名": r.filename,
                "模型1_状态": r.model1_status,
                "模型1_候选": r.model1_candidate,
                "模型1_最终问题": r.model1_issue,
                "模型1_理由": r.model1_reason,
                "模型1_风险": r.model1_risk,
                "模型1_建议": r.model1_suggestion,
                "模型5_状态": r.model5_status,
                "模型5_候选": r.model5_candidate,
                "模型5_最终问题": r.model5_issue,
                "模型5_理由": r.model5_reason,
                "模型5_风险": r.model5_risk,
                "模型5_建议": r.model5_suggestion,
                "模型10_状态": r.model10_status,
                "模型10_候选": r.model10_candidate,
                "模型10_最终问题": r.model10_issue,
                "模型10_理由": r.model10_reason,
                "模型10_风险": r.model10_risk,
                "模型10_建议": r.model10_suggestion,
                "模型3_状态": r.model3_status,
                "模型3_候选": r.model3_candidate,
                "模型3_场景类型": r.model3_scene_type or "",
                "模型3_应然类型": r.model3_expected_time_type or "",
                "模型3_实然类型": r.model3_actual_time_type or "",
                "模型3_类型匹配": r.model3_time_type_match if r.model3_time_type_match is not None else "",
                "模型3_理由匹配": r.model3_reason_match if r.model3_reason_match is not None else "",
                "模型3_最终问题": r.model3_issue,
                "模型3_理由": r.model3_reason,
                "模型3_风险": r.model3_risk,
                "模型3_建议": r.model3_suggestion or ""
            })


# ---------- API 端点 ----------
@app.get("/health", tags=["系统"])
async def health_check():
    return {"status": "ok"}

@app.post("/review/batch", tags=["审查"])
async def review_batch_files(files: List[UploadFile] = File(...)):
    """
    批量上传多个判决书文件，立即返回 task_id。
    前端通过 GET /review/batch/{task_id} 轮询结果。
    """
    file_paths = []
    failed_files = []
    MAX_SIZE = 100 * 1024 * 1024
    for file in files:
        file.file.seek(0, 2)
        size = file.file.tell()
        file.file.seek(0)
        if size > MAX_SIZE:
            failed_files.append(f"{file.filename} (超大)")
            continue
        file_path = None
        try:
            file_path = _create_upload_path(file.filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            file_paths.append(file_path)
        except Exception as e:
            import logging
            logging.warning(f"文件保存失败 {file.filename}: {e}")
            failed_files.append(file.filename or "<未命名文件>")
            if file_path is not None:
                _cleanup_upload_path(file_path)

    if not file_paths:
        raise HTTPException(status_code=400, detail=f"没有成功保存任何文件，失败文件: {', '.join(failed_files) if failed_files else '未知'}")

    task = create_task(total=len(file_paths))

    # 启动后台处理（非 daemon 线程，SIGTERM 时会等待完成）
    Thread(
        target=process_task_async,
        args=(task.task_id, file_paths),
    ).start()

    return {
        "task_id": task.task_id,
        "status": task.status,
        "total": task.total
    }


@app.get("/review/batch/{task_id}", tags=["审查"])
async def get_batch_result(task_id: str):
    """
    轮询批量任务状态和结果。
    status: pending → processing → completed / failed
    """
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")

    return {
        "task_id": task.task_id,
        "status": task.status,
        "progress": task.progress,
        "completed": task.completed,
        "total": task.total,
        "results": task.results if task.status == TaskStatus.COMPLETED.value else [],
        "csv_filename": task.csv_filename,
        "error": task.error
    }


@app.get("/review/stream/{task_id}", tags=["审查"])
async def stream_task(task_id: str):
    """
    SSE 实时推送任务状态和调试日志。
    连接建立后，任务状态变化时会主动推送事件。
    """
    # 防止路径遍历
    if ".." in task_id or "/" in task_id or "\\" in task_id:
        raise HTTPException(status_code=400, detail="非法任务ID")
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")

    from app.services.task_store import create_sse_signal, close_sse_signal, get_sse_signal, clear_sse_signal, get_task_logs
    from app.logging_config import DEBUG_LOG_ENABLED

    evt = get_sse_signal(task_id)
    if evt is None:
        evt = create_sse_signal(task_id)

    async def event_generator():
        try:
            # 立即发送当前状态
            current = get_task(task_id)
            if current:
                yield _make_sse_event(current)
                clear_sse_signal(task_id)
                if current.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value):
                    close_sse_signal(task_id)
                    return

            # 持续等待更新直到任务结束
            while True:
                # 在 asyncio 线程中等待 threading.Event（最多60秒）
                # 后台线程调用 _save() 时会 set() 此事件
                def wait_for_signal():
                    evt.wait(timeout=60)
                    return evt.is_set()

                signaled = await asyncio.to_thread(wait_for_signal)

                if signaled:
                    # 事件被触发，读取最新任务状态
                    current = get_task(task_id)

                    # 推送积压的调试日志（仅 DEBUG_LOG 开启时）
                    if DEBUG_LOG_ENABLED:
                        logs = get_task_logs(task_id)
                        for log_entry in logs:
                            yield f"event: log\ndata: {log_entry}\n\n".encode()

                    if current:
                        yield _make_sse_event(current)
                        clear_sse_signal(task_id)
                        if current.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value):
                            break
                else:
                    # 超时，发送心跳
                    yield b"event: ping\ndata: {}\n\n"

                    # 同时推送积压日志（仅 DEBUG_LOG 开启时）
                    if DEBUG_LOG_ENABLED:
                        logs = get_task_logs(task_id)
                        for log_entry in logs:
                            yield f"event: log\ndata: {log_entry}\n\n".encode()

                    # 同时检查任务是否已结束（防止事件遗漏）
                    current = get_task(task_id)
                    if not current or current.status in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value):
                        break
        finally:
            close_sse_signal(task_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


def _make_sse_event(task: "Task") -> bytes:
    import json
    data = {
        "task_id": task.task_id,
        "status": task.status,
        "progress": task.progress,
        "completed": task.completed,
        "total": task.total,
        "results": task.results if task.status == TaskStatus.COMPLETED.value else [],
        "csv_filename": task.csv_filename,
        "error": task.error,
    }
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


def _create_upload_path(filename: Optional[str]) -> Path:
    """创建安全且唯一的上传路径，同时保留原始文件名用于结果展示。"""
    if not filename or "\x00" in filename:
        raise HTTPException(status_code=400, detail="缺少合法文件名")
    if filename in (".", "..") or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="非法文件名")

    # 每个文件使用独立目录：既避免同名上传覆盖，也能让 ReviewResult 继续使用
    # 原始 basename，而不是暴露临时 UUID 文件名。
    upload_dir = UPLOAD_DIR / f".upload_{uuid.uuid4().hex}"
    upload_dir.mkdir(parents=True, exist_ok=False)
    return upload_dir / filename


def _cleanup_upload_path(file_path: Path) -> None:
    """删除上传文件及其受控临时目录。"""
    try:
        file_path.unlink(missing_ok=True)
    except OSError:
        logger.warning("清理上传文件失败: %s", file_path)
    parent = file_path.parent
    if parent.name.startswith(".upload_"):
        try:
            parent.rmdir()
        except OSError:
            # 后台批处理仍在使用时，留待下次清理；不影响任务结果。
            pass


def _sanitize_filename(filename: str, base_dir: Path) -> Path:
    """防止路径遍历：拒绝危险字符，并校验解析后路径在 base_dir 内"""
    if not filename or "\x00" in filename or ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    resolved = (base_dir / filename).resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        raise HTTPException(status_code=400, detail="非法文件名")
    return resolved


@app.get("/review/download/{filename}", tags=["审查"])
async def download_csv(filename: str):
    """下载 CSV 结果文件"""
    file_path = _sanitize_filename(filename, RESULT_DIR)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="text/csv"
    )


# ---------- 历史记录 API ----------
from fastapi import Query
from app.services.task_store import get_history_list, get_history_task, delete_history_task, clear_all_history


@app.get("/review/history", tags=["历史记录"])
async def get_history(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """获取历史记录列表"""
    items, total = get_history_list(limit=limit, offset=offset)
    return {
        "items": items,
        "total": total,
        "has_more": offset + len(items) < total
    }


@app.get("/review/history/{task_id}", tags=["历史记录"])
async def get_history_detail(task_id: str):
    """获取历史记录详情"""
    # 防止路径遍历
    if ".." in task_id or "/" in task_id or "\\" in task_id:
        raise HTTPException(status_code=400, detail="非法任务ID")
    task = get_history_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="历史记录不存在")
    results = task.get("results", [])
    issue_count = sum(
        1 for r in results
        if r.get("model1_issue") == "存在问题"
        or r.get("model5_issue") == "存在问题"
        or r.get("model10_issue") == "存在问题"
        or r.get("model3_issue") == "存在问题"
    )
    error_count = sum(
        1 for r in results
        if r.get("model1_issue") not in ("存在问题", "无问题", None)
        or r.get("model5_issue") not in ("存在问题", "无问题", None)
        or r.get("model10_issue") not in ("存在问题", "无问题", None)
        or r.get("model3_issue") not in ("存在问题", "无问题", None)
    )
    return {
        "task_id": task["task_id"],
        "status": task.get("status", "unknown"),
        "created_at": task.get("created_at"),
        "file_count": len(results),
        "results": results,
        "csv_filename": task.get("csv_filename"),
        "stats": {
            "total": len(results),
            "issue_count": issue_count,
            "ok_count": len(results) - issue_count - error_count,
            "error_count": error_count
        }
    }


@app.delete("/review/history/{task_id}", tags=["历史记录"])
async def delete_history(task_id: str):
    """删除单条历史记录"""
    # 防止路径遍历
    if ".." in task_id or "/" in task_id or "\\" in task_id:
        raise HTTPException(status_code=400, detail="非法任务ID")
    success = delete_history_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="历史记录不存在")
    return {"success": True}


@app.delete("/review/history", tags=["历史记录"])
async def clear_history():
    """清除全部历史记录"""
    count = clear_all_history()
    return {"success": True, "deleted_count": count}
