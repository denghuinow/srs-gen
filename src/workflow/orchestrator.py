"""工作流编排 (FR-005, FR-006)"""
from typing import Literal, Optional
from langgraph.graph import StateGraph, END
from openai import OpenAI
from ..config import Config, AblationMode
from ..workflow.state import WorkflowState
from ..models.requirement import RequirementList
from ..agents.req_explore import ReqExploreAgent
from ..agents.req_clarify import ReqClarifyAgent
from ..agents.doc_generate import DocGenerateAgent
from ..utils.comparison import ComparisonReporter
from ..utils.logger import get_logger


class WorkflowOrchestrator:
    """工作流编排器"""
    
    def __init__(self, ablation_mode: AblationMode = "default"):
        Config.ABLATION_MODE = ablation_mode
        Config.validate()
        
        self.client = OpenAI(**Config.get_openai_client_kwargs())
        self.ablation_mode = ablation_mode
        self.logger = get_logger("Orchestrator")
        
        # 初始化智能体（计时器将在状态中共享）
        self.timer_manager = None  # 将在run中初始化
    
    def _explore_node(self, state: WorkflowState) -> WorkflowState:
        """裂变挖掘节点"""
        # 检查是否是从clarify节点来的继续迭代
        # 如果requirements非空且至少有一个需求有评分，说明这是继续迭代，需要递增迭代号
        has_scored_requirements = any(
            req.score is not None 
            for req in state["requirements"].requirements
        )
        if has_scored_requirements:
            # 这是继续迭代，递增迭代号
            state["iteration_count"] += 1
            self.logger.info(f"继续迭代，迭代号递增至: {state['iteration_count']}")
        
        # no-explore-clarify 模式：直接设置收敛，返回空列表
        if self.ablation_mode == "no-explore-clarify":
            self.logger.info("no-explore-clarify 模式，跳过裂变挖掘")
            state["convergence_reached"] = True
            state["requirements"] = RequirementList()
            return state
        
        agent = ReqExploreAgent(self.client, state["timer_manager"])
        
        # 记录挖掘前的需求ID集合
        req_ids_before = set(req.id for req in state["requirements"].requirements)
        self.logger.debug(f"[深度 {state['iteration_count']}] 挖掘前需求ID集合: {sorted(req_ids_before)}")
        
        # 调用裂变式挖掘
        state["requirements"] = agent.explore(
            raw_input=state["raw_input"],
            existing_requirements=state["requirements"],
            forbidden_list=state["forbidden_list"],
            iteration=state["iteration_count"],
            ablation_mode=self.ablation_mode
        )
        
        # 记录挖掘后的需求ID集合
        req_ids_after = set(req.id for req in state["requirements"].requirements)
        self.logger.debug(f"[深度 {state['iteration_count']}] 挖掘后需求ID集合: {sorted(req_ids_after)}")
        
        # 计算新增的需求
        new_req_ids = req_ids_after - req_ids_before
        if new_req_ids:
            self.logger.info(f"[深度 {state['iteration_count']}] 挖掘阶段新增需求: {sorted(new_req_ids)}")
        else:
            self.logger.debug(f"[深度 {state['iteration_count']}] 挖掘阶段无新增需求")
        
        return state
    
    def _clarify_node(self, state: WorkflowState) -> WorkflowState:
        """澄清节点"""
        # 记录澄清前的需求ID集合
        req_ids_before = set(req.id for req in state["requirements"].requirements)
        self.logger.debug(f"[深度 {state['iteration_count']}] 澄清前需求ID集合: {sorted(req_ids_before)}")
        
        if self.ablation_mode == "no-explore-clarify":
            # no-explore-clarify 模式不会到达此节点
            return state
        
        if self.ablation_mode == "no-clarify":
            # no-clarify 模式：跳过澄清，默认0分，继续迭代
            self.logger.info(f"[深度 {state['iteration_count']}] no-clarify 模式，跳过澄清阶段")
            # 只对当前迭代新增的需求评分（通过 iteration 字段判断）
            for req in state["requirements"].requirements:
                if req.score is None and req.iteration == state["iteration_count"]:
                    req.score = 0
                    state["score_history"].record(
                        req.id,
                        state["iteration_count"],
                        0,
                        "no-clarify 模式：默认0分"
                    )
            req_ids_after = set(req.id for req in state["requirements"].requirements)
            self.logger.debug(f"[深度 {state['iteration_count']}] 澄清后需求ID集合: {sorted(req_ids_after)}")
            return state
        
        agent = ReqClarifyAgent(self.client, state["timer_manager"])
        
        # 只对当前迭代新增的需求进行评分（通过 iteration 字段判断）
        current_iteration_reqs = [
            req for req in state["requirements"].requirements
            if req.iteration == state["iteration_count"]
        ]
        
        if not current_iteration_reqs:
            self.logger.info("当前迭代没有新增需求，跳过澄清")
            return state
        
        # 创建临时 RequirementList 只包含当前迭代的需求
        temp_requirements = RequirementList()
        temp_requirements.requirements = current_iteration_reqs
        
        results = agent.clarify(temp_requirements, state["baseline_srs"])
        
        # 应用评分结果
        score_map = {r.req_id: r for r in results}
        forbidden_req_ids = []
        
        for req in state["requirements"].requirements:
            if req.id in score_map:
                result = score_map[req.id]
                req.score = result.score
                req.reason = result.reason
                
                # 记录得分历史
                state["score_history"].record(
                    req.id,
                    state["iteration_count"],
                    result.score,
                    result.reason
                )
                
                # 只有-2条目加入禁用清单，但不移除
                # 保留所有需求（包括负分），以便在下一轮迭代中改进
                if result.score == -2:
                    state["forbidden_list"].add(req)
                    forbidden_req_ids.append(req.id)
        
        # 记录澄清后的需求ID集合
        req_ids_after = set(req.id for req in state["requirements"].requirements)
        self.logger.debug(f"[深度 {state['iteration_count']}] 澄清后需求ID集合: {sorted(req_ids_after)}")
        
        # 记录禁用清单的需求
        if forbidden_req_ids:
            self.logger.info(f"[深度 {state['iteration_count']}] 加入禁用清单的需求: {sorted(forbidden_req_ids)}")
        
        # 统计负分需求数量（用于日志）
        negative_count = sum(1 for req in state["requirements"].requirements 
                           if req.score is not None and req.score < 0)
        if negative_count > 0:
            self.logger.info(f"[深度 {state['iteration_count']}] 保留负分需求数量: {negative_count}（将在下一轮迭代中改进）")
        
        return state
    
    def _check_convergence(self, state: WorkflowState) -> Literal["continue", "generate"]:
        """检查收敛条件"""
        iteration = state["iteration_count"]
        req_count = len(state["requirements"].requirements)
        
        # 计算当前迭代的需求变化（需要从状态中获取，这里简化处理）
        self.logger.info(f"[深度 {iteration}] 迭代总结:")
        self.logger.info(f"  当前需求总数: {req_count}")
        
        # no-explore-clarify模式：已在 explore 节点处理，不会到达这里
        if self.ablation_mode == "no-explore-clarify":
            state["convergence_reached"] = True
            self.logger.info(f"[深度 {iteration}] 收敛判断: no-explore-clarify模式，直接生成")
            return "generate"
        
        # no-clarify模式：继续迭代到最大次数（因为没有评分约束，无法提前收敛）
        if self.ablation_mode == "no-clarify":
            max_iterations = state.get("max_iterations", Config.MAX_ITERATIONS)  # type: ignore
            if state["iteration_count"] >= max_iterations:
                state["convergence_reached"] = True
                self.logger.info(f"[深度 {iteration}] 收敛判断: no-clarify模式，达到最大迭代次数 ({max_iterations})")
                return "generate"
            next_iteration = iteration + 1
            self.logger.info(f"[深度 {iteration}] 收敛判断: no-clarify模式，继续迭代 -> 深度 {next_iteration}")
            return "continue"
        
        # default模式：检查是否有负分条目（用于日志记录）
        has_negative = any(
            req.score is not None and req.score < 0
            for req in state["requirements"].requirements
        )
        
        # 检查是否达到最大迭代次数（从状态中获取，如果未设置则使用配置默认值）
        max_iterations = state.get("max_iterations", Config.MAX_ITERATIONS)  # type: ignore
        if state["iteration_count"] >= max_iterations:
            state["convergence_reached"] = True
            self.logger.info(f"[深度 {iteration}] 收敛判断: 达到最大迭代次数 ({max_iterations})")
            return "generate"
        
        # 继续迭代（迭代号递增将在_explore_node中执行）
        # 强制迭代到最大次数，不因无负分条目而提前收敛
        next_iteration = iteration + 1
        negative_info = "存在负分条目" if has_negative else "无负分条目"
        self.logger.info(f"[深度 {iteration}] 收敛判断: {negative_info}，继续迭代 -> 深度 {next_iteration}（强制迭代到最大次数 {max_iterations}）")
        return "continue"
    
    def _generate_node(self, state: WorkflowState) -> WorkflowState:
        """生成节点"""
        agent = DocGenerateAgent(self.client, state["timer_manager"])
        
        # no-explore-clarify 模式：直接使用原始输入生成文档
        if self.ablation_mode == "no-explore-clarify":
            self.logger.info("no-explore-clarify 模式，直接使用原始输入生成文档")
            srs_doc = agent.generate(raw_input=state["raw_input"])
            state["_srs_document"] = srs_doc  # type: ignore
            return state
        
        # 其他模式：只传递评分>=1的需求给文档生成器
        filtered_requirements = state["requirements"].filter_by_score(min_score=1)
        
        # 记录过滤信息
        total_count = len(state["requirements"].requirements)
        filtered_count = len(filtered_requirements.requirements)
        if total_count != filtered_count:
            self.logger.info(f"文档生成：从 {total_count} 个需求中筛选出 {filtered_count} 个评分>=1的需求")
            excluded_ids = [
                req.id for req in state["requirements"].requirements
                if req.score is None or req.score < 1
            ]
            if excluded_ids:
                self.logger.debug(f"被排除的需求ID: {sorted(excluded_ids)}")
        
        srs_doc = agent.generate(requirements=filtered_requirements)
        state["_srs_document"] = srs_doc  # type: ignore
        return state
    
    def build_graph(self) -> StateGraph:
        """构建工作流图"""
        workflow = StateGraph(WorkflowState)
        
        # 添加节点（移除 parse 节点）
        workflow.add_node("explore", self._explore_node)
        workflow.add_node("clarify", self._clarify_node)
        workflow.add_node("generate", self._generate_node)
        
        # 设置入口（从 explore 开始）
        workflow.set_entry_point("explore")
        
        # 添加边
        workflow.add_edge("explore", "clarify")
        workflow.add_conditional_edges(
            "clarify",
            self._check_convergence,
            {
                "continue": "explore",
                "generate": "generate"
            }
        )
        workflow.add_edge("generate", END)
        
        return workflow.compile()
    
    def run(
        self,
        raw_input: str,
        baseline_srs: str = "",
        ablation_mode: AblationMode = "default",
        max_iterations: Optional[int] = None
    ) -> dict:
        """运行工作流"""
        from ..utils.timer import TimerManager
        from ..utils.forbidden_list import ForbiddenList
        from ..utils.score_history import ScoreHistory
        from ..models.requirement import RequirementList
        
        self.ablation_mode = ablation_mode
        
        # 初始化状态
        initial_state: WorkflowState = {
            "raw_input": raw_input,
            "baseline_srs": baseline_srs,
            "requirements": RequirementList(),
            "forbidden_list": ForbiddenList(),
            "score_history": ScoreHistory(),
            "timer_manager": TimerManager(),
            "iteration_count": 0,
            "ablation_mode": ablation_mode,
            "convergence_reached": False,
            "max_iterations": max_iterations if max_iterations is not None else Config.MAX_ITERATIONS  # type: ignore
        }
        
        # 开始计时
        initial_state["timer_manager"].start_total()
        
        # 构建并运行工作流
        graph = self.build_graph()
        final_state = graph.invoke(initial_state)
        
        # 停止计时
        final_state["timer_manager"].get_total_time()
        
        # 生成对比报告
        reporter = ComparisonReporter()
        comparison_report = reporter.generate_report(
            final_state["requirements"].requirements,
            final_state["score_history"],
            final_state["timer_manager"],
            final_state["forbidden_list"].get_count(),
            ablation_mode
        )
        
        return {
            "srs_document": final_state.get("_srs_document", ""),
            "requirements": final_state["requirements"],
            "comparison_report": comparison_report,
            "total_time": final_state["timer_manager"].get_total_time(),
            "timer_summary": final_state["timer_manager"].get_summary()
        }
