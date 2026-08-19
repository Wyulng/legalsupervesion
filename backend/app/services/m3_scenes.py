"""
M3 合同解除场景类型定义
对应8步流程步骤4：合同解除场景识别
"""

from enum import Enum
from typing import Dict, List


class DissolutionSceneType(Enum):
    """解除场景主类型"""
    # 类型A：法定解除/单方解除
    TYPE_A_LEGAL = "type_a_legal"           # 法定解除（一般性援引563）
    TYPE_A_NOTICE = "type_a_notice"         # 通知解除
    TYPE_A_BREACH = "type_a_breach"         # 根本违约
    TYPE_A_DELAY = "type_a_delay"           # 迟延履行
    TYPE_A_EXPECTED = "type_a_expected"     # 预期违约
    TYPE_A_FORCE = "type_a_force"           # 不可抗力
    TYPE_A_PROSECUTION = "type_a_prosecution"  # 起诉主张解除
    TYPE_A_AFTER_DEMAND = "type_a_after_demand"  # 催告后解除

    # 类型B：司法终局处理/特殊边界
    TYPE_B_JUDICIAL = "type_b_judicial"     # 司法终局处理（一般性）
    TYPE_B_DEADLOCK = "type_b_deadlock"     # 合同僵局
    TYPE_B_IMPOSSIBLE = "type_b_impossible" # 继续履行不能
    TYPE_B_CHANGE = "type_b_change"         # 情势变更
    TYPE_B_FAIRNESS = "type_b_fairness"     # 公平原则
    TYPE_B_GOODFAITH = "type_b_goodfaith"   # 诚信原则
    TYPE_B_NON_MONETARY = "type_b_non_monetary"  # 非金钱债务无需继续履行

    UNCLEAR = "unclear"                     # 无法判断


# 类型A关键词（法定解除/单方解除）
TYPE_A_KEYWORDS: Dict[str, List[str]] = {
    "通知解除": ["通知解除", "解除函", "解除通知", "送达解除", "通知到达", "解除通知已送达"],
    "根本违约": ["根本违约", "根本不能实现合同目的", "致合同目的无法实现", "合同目的无法实现"],
    "迟延履行": ["迟延履行", "逾期履行", "经催告后仍不履行", "催告后仍不履行", "经催告"],
    "预期违约": ["预期违约", "明确表示不履行", "以行为表明不履行", "明确表示将不履行"],
    "不可抗力": ["不可抗力", "不能预见", "不能避免且不能克服"],
    "起诉解除": ["起诉解除", "主张解除", "请求解除合同", "诉请解除", "起诉主张解除"],
    "法定解除": ["法定解除", "法定解除权", "依据第563条", "依据民法典563"],
    "催告后解除": ["催告后解除", "催告不履行", "催告期限"],
}

# 类型B关键词（司法终局处理/特殊边界）
TYPE_B_KEYWORDS: Dict[str, List[str]] = {
    "合同僵局": ["合同僵局", "陷入僵局", "无法继续履行", "继续履行困难", "双方均不履行"],
    "继续履行不能": ["继续履行不能", "履行不能", "事实上不可能履行", "法律上不可能", "第580条第1款"],
    "情势变更": ["情势变更", "第580条第2款", "显失公平", "继续履行显失公平", "情势变更原则"],
    "公平原则": ["公平原则", "显失公平", "权利义务严重失衡", "公平处理"],
    "诚信原则": ["诚信原则", "违背诚信", "违反诚信原则", "诚实信用原则"],
    "非金钱债务": ["非金钱债务", "无需继续履行", "第580条第1款第3项", "非金钱债务履行"],
}

# 类型A对应的应然解除时间规则
TYPE_A_TIME_RULES: Dict[str, str] = {
    "通知解除": "通知到达对方时解除（解除函送达生效）",
    "根本违约": "违约事实发生时解除（对方违约导致合同目的无法实现）",
    "迟延履行": "催告期满或违约事实发生时解除",
    "预期违约": "明确表示不履行时解除",
    "不可抗力": "不可抗力事件发生时解除",
    "起诉解除": "起诉状副本送达对方时解除",
    "法定解除": "解除权成就时解除（需结合具体事实判断）",
    "催告后解除": "催告期满时解除",
}

# 类型B对应的应然解除时间规则
TYPE_B_TIME_RULES: Dict[str, str] = {
    "合同僵局": "法院判决确定之日解除（司法终局）",
    "继续履行不能": "法院判决确定之日解除（司法终局）",
    "情势变更": "法院判决确定之日解除（司法酌定）",
    "公平原则": "法院酌定之日解除（需综合判断）",
    "诚信原则": "法院酌定之日解除（需综合判断）",
    "非金钱债务": "法院判决确定之日解除",
}


def classify_scene_type(reason: str, result: str, trial: str = "") -> DissolutionSceneType:
    """
    根据判决书内容识别合同解除场景类型
    返回类型A（法定解除/单方解除）、类型B（司法终局）或 UNCLEAR
    """
    combined_text = f"{reason} {result} {trial}"

    # 检查类型A特征
    for scene, keywords in TYPE_A_KEYWORDS.items():
        for kw in keywords:
            if kw in combined_text:
                return _map_to_type_a(scene)

    # 检查类型B特征
    for scene, keywords in TYPE_B_KEYWORDS.items():
        for kw in keywords:
            if kw in combined_text:
                return _map_to_type_b(scene)

    return DissolutionSceneType.UNCLEAR


def _map_to_type_a(scene: str) -> DissolutionSceneType:
    mapping = {
        "通知解除": DissolutionSceneType.TYPE_A_NOTICE,
        "根本违约": DissolutionSceneType.TYPE_A_BREACH,
        "迟延履行": DissolutionSceneType.TYPE_A_DELAY,
        "预期违约": DissolutionSceneType.TYPE_A_EXPECTED,
        "不可抗力": DissolutionSceneType.TYPE_A_FORCE,
        "起诉解除": DissolutionSceneType.TYPE_A_PROSECUTION,
        "法定解除": DissolutionSceneType.TYPE_A_LEGAL,
        "催告后解除": DissolutionSceneType.TYPE_A_AFTER_DEMAND,
    }
    return mapping.get(scene, DissolutionSceneType.TYPE_A_LEGAL)


def _map_to_type_b(scene: str) -> DissolutionSceneType:
    mapping = {
        "合同僵局": DissolutionSceneType.TYPE_B_DEADLOCK,
        "继续履行不能": DissolutionSceneType.TYPE_B_IMPOSSIBLE,
        "情势变更": DissolutionSceneType.TYPE_B_CHANGE,
        "公平原则": DissolutionSceneType.TYPE_B_FAIRNESS,
        "诚信原则": DissolutionSceneType.TYPE_B_GOODFAITH,
        "非金钱债务": DissolutionSceneType.TYPE_B_NON_MONETARY,
    }
    return mapping.get(scene, DissolutionSceneType.TYPE_B_JUDICIAL)


def get_expected_time_info(scene_type: DissolutionSceneType) -> tuple:
    """
    根据场景类型返回（应然时间类型, 应然时间规则）
    """
    type_a_scenes = [
        DissolutionSceneType.TYPE_A_NOTICE,
        DissolutionSceneType.TYPE_A_BREACH,
        DissolutionSceneType.TYPE_A_DELAY,
        DissolutionSceneType.TYPE_A_EXPECTED,
        DissolutionSceneType.TYPE_A_FORCE,
        DissolutionSceneType.TYPE_A_LEGAL,
        DissolutionSceneType.TYPE_A_PROSECUTION,
        DissolutionSceneType.TYPE_A_AFTER_DEMAND,
    ]
    type_b_scenes_judicial = [
        DissolutionSceneType.TYPE_B_DEADLOCK,
        DissolutionSceneType.TYPE_B_IMPOSSIBLE,
        DissolutionSceneType.TYPE_B_NON_MONETARY,
    ]
    type_b_scenes_discretion = [
        DissolutionSceneType.TYPE_B_FAIRNESS,
        DissolutionSceneType.TYPE_B_GOODFAITH,
        DissolutionSceneType.TYPE_B_CHANGE,
    ]

    if scene_type in type_a_scenes:
        return ("通知到达/起诉状副本送达之时", "类型A：法定解除/单方解除，解除时间由当事人行为触发")
    elif scene_type in type_b_scenes_judicial:
        return ("判决生效之日", "类型B：司法终局处理，解除时间由法院判决终局确定")
    elif scene_type in type_b_scenes_discretion:
        return ("法院酌定之日", "类型B：公平/诚信/情势变更，法院酌定解除时间")
    return ("需综合判断", "需结合具体案情判断")


def get_scene_type_label(scene_type: DissolutionSceneType) -> str:
    """获取场景类型的中文标签"""
    labels = {
        DissolutionSceneType.TYPE_A_LEGAL: "法定解除",
        DissolutionSceneType.TYPE_A_NOTICE: "通知解除",
        DissolutionSceneType.TYPE_A_BREACH: "根本违约",
        DissolutionSceneType.TYPE_A_DELAY: "迟延履行",
        DissolutionSceneType.TYPE_A_EXPECTED: "预期违约",
        DissolutionSceneType.TYPE_A_FORCE: "不可抗力",
        DissolutionSceneType.TYPE_A_PROSECUTION: "起诉主张解除",
        DissolutionSceneType.TYPE_A_AFTER_DEMAND: "催告后解除",
        DissolutionSceneType.TYPE_B_JUDICIAL: "司法终局处理",
        DissolutionSceneType.TYPE_B_DEADLOCK: "合同僵局",
        DissolutionSceneType.TYPE_B_IMPOSSIBLE: "继续履行不能",
        DissolutionSceneType.TYPE_B_CHANGE: "情势变更",
        DissolutionSceneType.TYPE_B_FAIRNESS: "公平原则",
        DissolutionSceneType.TYPE_B_GOODFAITH: "诚信原则",
        DissolutionSceneType.TYPE_B_NON_MONETARY: "非金钱债务",
        DissolutionSceneType.UNCLEAR: "无法判断",
    }
    return labels.get(scene_type, "未知")
