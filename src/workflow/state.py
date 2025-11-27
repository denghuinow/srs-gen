"""工作流状态管理"""
from typing import TypedDict, List, Optional, Set, Union
from ..models.requirement import RequirementList, ClarificationResult
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
    max_new_requirements_per_iteration: Optional[int]  # 每轮迭代需改进需求+新增需求的总数（可选，如果未指定则使用Config中的默认值）
    requirement_structure: str  # 需求结构（Markdown格式）
    baseline_requirement_structure: str  # 基准需求语义单元（通过ReqParseAgent解析baseline_gend_srs得到）
    _srs_document: str  # 临时存储生成的SRS文档
    req_explore_messages: Optional[List[dict]]  # ReqExploreAgent 的对话历史
    clarification_results: Optional[List[ClarificationResult]]  # 评分结果，用于在 explore 和 clarify 之间传递
    output_dir_base: Optional[str]  # 输出目录基础路径，用于版本生成（srs_collection目录）
    task_name: Optional[str]  # 任务名称，用于版本生成时的文件命名
    gen_versions: Optional[Set[Union[str, int]]]  # 需要生成的版本集合
    _version_to_generate: Optional[str]  # 当前要生成的版本类型
    _version_name: Optional[str]  # 版本名称
    _last_generated_version: Optional[str]  # 最后生成的版本名称（用于路由判断）
    _cumulative_clarify_time: float  # 累计澄清耗时
    _cumulative_version_gen_time: float  # 累计版本生成耗时
    _workflow_start_time: float  # 工作流开始时间
