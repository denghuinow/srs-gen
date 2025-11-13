"""消融模式支持 (FR-009, FR-010, FR-011)"""
from typing import Literal
from ..config import AblationMode


def should_skip_clarify(mode: AblationMode) -> bool:
    """判断是否跳过澄清阶段"""
    return mode in ["no-clarify", "no-explore-clarify"]


def should_skip_explore(mode: AblationMode) -> bool:
    """判断是否跳过挖掘阶段"""
    return mode == "no-explore-clarify"


def get_mode_description(mode: AblationMode) -> str:
    """获取模式描述"""
    descriptions = {
        "default": "完整流程（解析→挖掘→澄清→生成）",
        "no-clarify": "跳过澄清，默认0分",
        "no-explore-clarify": "跳过挖掘和澄清，原子需求直接映射"
    }
    return descriptions.get(mode, "未知模式")
