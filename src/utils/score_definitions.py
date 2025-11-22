"""统一的5级评分定义和处理方式"""

# 5级评分含义定义（基于需求与基准SRS的符合程度）
SCORE_MEANINGS = {
    2: "完全符合",
    1: "基本符合",
    0: "部分符合",
    -1: "存在偏差",
    -2: "明显冲突"
}

# 评分处理方式定义
SCORE_ACTIONS = {
    2: "保持不变，不需要再次输出",
    1: "可以保持不变或轻微优化",
    0: "需要改进以提升符合度",
    -1: "需要较大改进以消除偏差",
    -2: "需要重新设计以解决冲突"
}

# 评分完整描述（含义 + 处理方式）
SCORE_DESCRIPTIONS = {
    2: f"{SCORE_MEANINGS[2]} - {SCORE_ACTIONS[2]}",
    1: f"{SCORE_MEANINGS[1]} - {SCORE_ACTIONS[1]}",
    0: f"{SCORE_MEANINGS[0]} - {SCORE_ACTIONS[0]}",
    -1: f"{SCORE_MEANINGS[-1]} - {SCORE_ACTIONS[-1]}",
    -2: f"{SCORE_MEANINGS[-2]} - {SCORE_ACTIONS[-2]}"
}

# 有效的评分范围
VALID_SCORES = [-2, -1, 0, 1, 2]

# 需要改进的评分（<= 0）
SCORES_NEED_IMPROVEMENT = [-2, -1, 0]

# 可以保持的评分（> 0）
SCORES_CAN_KEEP = [1, 2]

# 必须保持不变的评分（= 2）
SCORES_MUST_KEEP = [2]


def get_score_meaning(score: int) -> str:
    """获取评分的含义"""
    return SCORE_MEANINGS.get(score, "未知")


def get_score_action(score: int) -> str:
    """获取评分的处理方式"""
    return SCORE_ACTIONS.get(score, "未知")


def get_score_description(score: int) -> str:
    """获取评分的完整描述（含义 + 处理方式）"""
    return SCORE_DESCRIPTIONS.get(score, "未知")


def is_valid_score(score: int) -> bool:
    """检查评分是否有效"""
    return score in VALID_SCORES


def needs_improvement(score: int) -> bool:
    """判断是否需要改进（<= 0）"""
    return score <= 0


def can_keep(score: int) -> bool:
    """判断是否可以保持（> 0）"""
    return score > 0


def must_keep(score: int) -> bool:
    """判断是否必须保持不变（= 2）"""
    return score == 2


def format_score_for_log(score: int) -> str:
    """格式化评分用于日志输出"""
    meaning = get_score_meaning(score)
    sign = "+" if score > 0 else ""
    return f"{sign}{score} ({meaning})"


def format_score_for_message(score: int) -> str:
    """格式化评分用于消息输出"""
    description = get_score_description(score)
    return f"Score: {score} ({description})"


def get_processing_instructions() -> list[str]:
    """获取处理方式说明列表"""
    return [
        f"对于 Score <= 0 的需求（部分符合、存在偏差或明显冲突），必须重新生成改进版本，使用相同的ID",
        f"对于 Score = 1 的需求（基本符合），可以保持不变或轻微优化，使用相同的ID",
        f"对于 Score = 2 的需求（完全符合），保持不变，不需要再次输出"
    ]

