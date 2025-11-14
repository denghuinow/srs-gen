"""工作流状态管理"""
from typing import TypedDict, List, Optional
from ..models.requirement import RequirementList
from ..utils.forbidden_list import ForbiddenList
from ..utils.score_history import ScoreHistory
from ..utils.timer import TimerManager


class WorkflowState(TypedDict, total=False):
    """工作流状态"""
    raw_input: str
    baseline_srs: str
    requirements: RequirementList
    forbidden_list: ForbiddenList
    score_history: ScoreHistory
    timer_manager: TimerManager
    iteration_count: int
    ablation_mode: str
    convergence_reached: bool
    max_iterations: int
    _srs_document: str  # 临时存储生成的SRS文档
