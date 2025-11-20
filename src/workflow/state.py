"""工作流状态管理"""
from typing import TypedDict, List, Optional
from ..models.requirement import RequirementList
from ..utils.score_history import ScoreHistory
from ..utils.timer import TimerManager


class WorkflowState(TypedDict, total=False):
    """工作流状态"""
    raw_input: str
    baseline_srs: str
    baseline_gend_srs: str  # 基准生成的SRS文件内容
    requirements: RequirementList
    score_history: ScoreHistory
    timer_manager: TimerManager
    iteration_count: int
    ablation_mode: str
    convergence_reached: bool
    max_iterations: int
    max_new_requirements_per_iteration: Optional[int]  # 每轮迭代新增需求数量（可选，如果未指定则使用Config中的默认值）
    requirement_structure: str  # 需求结构（Markdown格式）
    baseline_requirement_structure: str  # 基准需求语义单元（通过ReqParseAgent解析baseline_gend_srs得到）
    _srs_document: str  # 临时存储生成的SRS文档
