"""工作流编排 (FR-005, FR-006)"""
import re
from typing import Literal, Optional, List
from langgraph.graph import StateGraph, END
from openai import OpenAI
from ..config import Config, AblationMode
from ..workflow.state import WorkflowState
from ..models.requirement import RequirementList, Requirement
from ..agents.req_parse import ReqParseAgent
from ..agents.req_explore import ReqExploreAgent
from ..agents.req_clarify import ReqClarifyAgent
from ..agents.doc_generate import DocGenerateAgent
from ..utils.comparison import ComparisonReporter
from ..utils.logger import get_logger
from ..utils.token_counter import count_text_tokens


class WorkflowOrchestrator:
    """工作流编排器"""
    
    def __init__(self, ablation_mode: AblationMode = "default", prompt_version: str = None):
        Config.ABLATION_MODE = ablation_mode
        Config.validate()
        
        self.client = OpenAI(**Config.get_openai_client_kwargs())
        self.ablation_mode = ablation_mode
        self.prompt_version = prompt_version or Config.PROMPT_VERSION
        self.logger = get_logger("Orchestrator")
        
        # 初始化智能体（计时器将在状态中共享）
        self.timer_manager = None  # 将在run中初始化
    
    def _parse_node(self, state: WorkflowState) -> WorkflowState:
        """解析节点"""
        if self.timer_manager is None:
            self.timer_manager = state["timer_manager"]
        
        # requirement_structure 直接使用 raw_input，不再通过 ReqParseAgent 解析
        state["requirement_structure"] = state["raw_input"]  # type: ignore
        raw_input_tokens = count_text_tokens(state['raw_input'])
        raw_input_token_str = f"{raw_input_tokens} tokens" if raw_input_tokens is not None else f"{len(state['raw_input'])} 字符"
        self.logger.info(f"需求结构直接使用用户输入，长度: {raw_input_token_str}")
        
        # 如果存在 baseline_gend_srs，使用 ReqParseAgent 解析它生成需求语义单元
        baseline_gend_srs = state.get("baseline_gend_srs", "")
        if baseline_gend_srs:
            agent = ReqParseAgent(self.client, self.timer_manager, prompt_version=self.prompt_version)
            baseline_requirement_structure = agent.parse(baseline_gend_srs, input_type="基准生成的SRS")
            state["baseline_requirement_structure"] = baseline_requirement_structure  # type: ignore
            baseline_tokens = count_text_tokens(baseline_requirement_structure)
            baseline_token_str = f"{baseline_tokens} tokens" if baseline_tokens is not None else f"{len(baseline_requirement_structure)} 字符"
            self.logger.info(f"基准需求语义单元生成完成，长度: {baseline_token_str}")
        else:
            state["baseline_requirement_structure"] = ""  # type: ignore
        
        return state
    
    def _explore_node(self, state: WorkflowState) -> WorkflowState:
        """挖掘节点"""
        # 如果不是第一次迭代（有score_history记录），递增迭代次数
        # 迭代从1开始，第一次调用时已经是1，不需要递增
        has_history = bool(state["score_history"].history)
        if has_history:
            state["iteration_count"] += 1
        
        raw_input = state["raw_input"]
        baseline_requirement_structure = state.get("baseline_requirement_structure", "")  # type: ignore

        # 记录挖掘前的需求ID集合
        req_ids_before = set(req.id for req in state["requirements"].requirements)
        self.logger.debug(f"[迭代 {state['iteration_count']}] 挖掘前需求ID集合: {sorted(req_ids_before)}")

        if self.ablation_mode == "no-explore-clarify":
            self.logger.info(
                f"[迭代 {state['iteration_count']}] no-explore-clarify 模式：跳过 ReqExplore，直接映射需求结构"
            )
            requirement_structure = state.get("requirement_structure", "")  # type: ignore
            state["requirements"] = self._build_requirements_from_structure(
                requirement_structure,
                raw_input,
                state["iteration_count"]
            )
        else:
            agent = ReqExploreAgent(self.client, state["timer_manager"], prompt_version=self.prompt_version)
            max_new_requirements = state.get("max_new_requirements_per_iteration")  # type: ignore
            
            # 从 state 获取对话历史和评分结果
            req_explore_messages = state.get("req_explore_messages")  # type: ignore
            clarification_results = state.get("clarification_results")  # type: ignore
            
            # 调用 explore，传入对话历史和评分结果
            new_requirements, updated_messages = agent.explore(
                raw_input,
                state["requirements"],
                state["iteration_count"],
                baseline_requirement_structure,
                max_new_requirements_per_iteration=max_new_requirements,
                messages=req_explore_messages,
                clarification_results=clarification_results
            )
            
            # 保存返回的需求清单和对话历史
            state["requirements"] = new_requirements
            state["req_explore_messages"] = updated_messages  # type: ignore
        
        # 记录挖掘后的需求ID集合
        req_ids_after = set(req.id for req in state["requirements"].requirements)
        self.logger.debug(f"[迭代 {state['iteration_count']}] 挖掘后需求ID集合: {sorted(req_ids_after)}")
        
        # 计算新增的需求
        new_req_ids = req_ids_after - req_ids_before
        if new_req_ids:
            self.logger.info(f"[迭代 {state['iteration_count']}] 挖掘阶段新增需求: {sorted(new_req_ids)}")
        else:
            self.logger.debug(f"[迭代 {state['iteration_count']}] 挖掘阶段无新增需求")
        
        return state

    def _build_requirements_from_structure(
        self,
        requirement_structure: str,
        raw_input: str,
        iteration: int,
    ) -> RequirementList:
        """将需求结构直接转换为基础需求列表（no-explore-clarify模式专用）"""
        requirement_texts = self._extract_list_entries(requirement_structure)

        if not requirement_texts:
            self.logger.warning(
                "no-explore-clarify: 需求结构未识别出条目，退回原始输入做切分"
            )
            requirement_texts = self._fallback_requirements_from_raw_input(raw_input)

        req_list = RequirementList()
        for index, text in enumerate(requirement_texts, start=1):
            req = Requirement(
                id=f"REQ-{index:03d}",
                text=text,
                iteration=iteration,
            )
            req_list.add(req)

        self.logger.info(
            f"no-explore-clarify: 由需求结构生成 {len(req_list.requirements)} 条原子需求"
        )
        return req_list

    def _extract_list_entries(self, requirement_structure: str) -> List[str]:
        """从需求结构Markdown中提取列表项并附带上下文标题"""
        entries: List[str] = []
        seen = set()
        heading_stack: list[str] = []

        for raw_line in requirement_structure.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                title = line[level:].strip(" -\t")
                if not title:
                    continue
                while len(heading_stack) >= level:
                    heading_stack.pop()
                heading_stack.append(title)
                continue

            content = self._parse_list_item(line)
            if not content:
                continue

            context = " / ".join(heading_stack).strip()
            text = f"{context}: {content}" if context else content
            normalized = text.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                entries.append(normalized)

        return entries

    def _parse_list_item(self, line: str) -> Optional[str]:
        """识别Markdown列表项内容（支持有序/无序/任务列表）"""
        checkbox_match = re.match(r"^[-*+]\s*\[[xX ]\]\s*(.+)$", line)
        if checkbox_match:
            return checkbox_match.group(1).strip()

        bullet_match = re.match(r"^[-*+]\s+(.+)$", line)
        if bullet_match:
            return bullet_match.group(1).strip()

        ordered_match = re.match(r"^\d+[\.)]\s+(.+)$", line)
        if ordered_match:
            return ordered_match.group(1).strip()

        return None

    def _fallback_requirements_from_raw_input(self, raw_input: str) -> List[str]:
        """当结构化文本为空时，退回原始输入拆分句子，保证至少有需求输出"""
        candidates = []
        for chunk in re.split(r"[\n\r]+", raw_input):
            cleaned = chunk.strip(" -•\t")
            if len(cleaned) >= 8:
                candidates.append(cleaned)

        if not candidates and raw_input:
            sentences = re.split(r"[。！？!?.]", raw_input)
            candidates = [s.strip() for s in sentences if len(s.strip()) >= 8]

        return candidates
    
    def _clarify_node(self, state: WorkflowState) -> WorkflowState:
        """澄清节点"""
        # 记录澄清前的需求ID集合
        req_ids_before = set(req.id for req in state["requirements"].requirements)
        self.logger.debug(f"[迭代 {state['iteration_count']}] 澄清前需求ID集合: {sorted(req_ids_before)}")
        
        if self.ablation_mode in ["no-clarify", "no-explore-clarify"]:
            # 跳过澄清，默认0分
            self.logger.info(f"[迭代 {state['iteration_count']}] 消融模式，跳过澄清阶段")
            for req in state["requirements"].requirements:
                if req.score is None:
                    req.score = 0
                    state["score_history"].record(
                        req.id,
                        state["iteration_count"],
                        0,
                        "消融模式：默认0分"
                    )
            # 在消融模式下，不进行负分过滤，所有需求都保留
            req_ids_after = set(req.id for req in state["requirements"].requirements)
            self.logger.debug(f"[迭代 {state['iteration_count']}] 澄清后需求ID集合: {sorted(req_ids_after)}")
            return state
        
        agent = ReqClarifyAgent(self.client, state["timer_manager"], prompt_version=self.prompt_version)
        results = agent.clarify(state["requirements"], state["baseline_srs"])
        
        # 保存评分结果到 state，供下次 explore 使用
        state["clarification_results"] = results  # type: ignore
        
        # 应用评分结果
        score_map = {r.req_id: r for r in results}
        new_requirements = RequirementList()
        
        for req in state["requirements"].requirements:
            if req.id in score_map:
                result = score_map[req.id]
                req.score = result.score
                req.reason = result.reason
                req.evidence = result.evidence
                
                # 记录得分历史
                state["score_history"].record(
                    req.id,
                    state["iteration_count"],
                    result.score,
                    result.reason,
                    result.evidence
                )
                
                # 所有需求都保留（包括负分），以便在下一轮迭代中改进
                if not new_requirements.add(req):
                    self.logger.warning(f"需求 {req.id} 在澄清阶段重复添加，已跳过")
            else:
                # 没有评分结果的需求保留
                # 如果原需求 score < 2，将 score 设为 None，以便下次迭代时重新评分
                if req.score is not None and req.score < 2:
                    old_score = req.score
                    req.score = None
                    self.logger.debug(f"需求 {req.id} 原评分 {old_score} < 2，但未获得新评分，将 score 设为 None 以便下次重新评分")
                if not new_requirements.add(req):
                    self.logger.warning(f"需求 {req.id} 在澄清阶段重复添加，已跳过")
        
        state["requirements"] = new_requirements
        
        # 记录澄清后的需求ID集合
        req_ids_after = set(req.id for req in state["requirements"].requirements)
        self.logger.debug(f"[迭代 {state['iteration_count']}] 澄清后需求ID集合: {sorted(req_ids_after)}")
        
        # 统计负分需求数量（用于日志）
        negative_count = sum(1 for req in state["requirements"].requirements 
                           if req.score is not None and req.score < 0)
        if negative_count > 0:
            self.logger.info(f"[迭代 {state['iteration_count']}] 保留负分需求数量: {negative_count}（将在下一轮迭代中改进）")
        
        return state
    
    def _check_convergence(self, state: WorkflowState) -> Literal["continue", "generate"]:
        """检查收敛条件"""
        iteration = state["iteration_count"]
        req_count = len(state["requirements"].requirements)
        
        # 计算当前迭代的需求变化（需要从状态中获取，这里简化处理）
        self.logger.info(f"[迭代 {iteration}] 迭代总结:")
        self.logger.info(f"  当前需求总数: {req_count}")
        
        # no-explore-clarify模式：第一次迭代后直接生成
        if self.ablation_mode == "no-explore-clarify":
            state["convergence_reached"] = True
            self.logger.info(f"[迭代 {iteration}] 收敛判断: no-explore-clarify模式，直接生成")
            return "generate"
        
        # 检查是否有负分条目（用于日志记录）
        has_negative = any(
            req.score is not None and req.score < 0
            for req in state["requirements"].requirements
        )
        
        # 检查是否达到最大迭代次数（从状态中获取，如果未设置则使用配置默认值）
        max_iterations = state.get("max_iterations", Config.MAX_ITERATIONS)  # type: ignore
        
        # 计算下一轮迭代的迭代号（当前迭代号+1）
        next_iteration = iteration + 1
        
        # 如果下一轮迭代号超过最大迭代次数，则停止（迭代从1开始）
        if next_iteration > max_iterations:
            state["convergence_reached"] = True
            self.logger.info(f"[迭代 {iteration}] 收敛判断: 达到最大迭代次数 ({max_iterations})，下一迭代将是 {next_iteration}，停止迭代")
            return "generate"
        
        negative_info = "存在负分条目" if has_negative else "无负分条目"
        self.logger.info(f"[迭代 {iteration}] 收敛判断: {negative_info}，继续迭代 -> 迭代 {next_iteration}（强制迭代到最大次数 {max_iterations}）")
        return "continue"
    
    def _generate_node(self, state: WorkflowState) -> WorkflowState:
        """生成节点"""
        agent = DocGenerateAgent(self.client, state["timer_manager"], prompt_version=self.prompt_version)
        
        # 基于历史得分筛选：只要历史中曾经有过>=1的得分，就进入文档生成
        filtered_requirements = RequirementList()
        excluded_ids = []
        
        for req in state["requirements"].requirements:
            best_score = state["score_history"].get_best_score(req.id)
            if best_score is not None and best_score >= 1:
                filtered_requirements.requirements.append(req)
            else:
                excluded_ids.append(req.id)
        
        # 记录过滤信息
        total_count = len(state["requirements"].requirements)
        filtered_count = len(filtered_requirements.requirements)
        if total_count != filtered_count:
            self.logger.info(f"文档生成：从 {total_count} 个需求中筛选出 {filtered_count} 个历史得分>=1的需求")
            if excluded_ids:
                self.logger.debug(f"被排除的需求ID: {sorted(excluded_ids)}")
        
        # 获取需求结构（用于no-explore-clarify模式）
        requirement_structure = state.get("requirement_structure", "")  # type: ignore
        ablation_mode = state.get("ablation_mode", "default")  # type: ignore
        baseline_requirement_structure = state.get("baseline_requirement_structure", "")  # type: ignore
        
        srs_doc = agent.generate(
            filtered_requirements,
            raw_input=state["raw_input"],
            requirement_structure=requirement_structure,
            ablation_mode=ablation_mode,
            baseline_requirement_structure=baseline_requirement_structure
        )
        state["_srs_document"] = srs_doc  # type: ignore
        return state
    
    def build_graph(self) -> StateGraph:
        """构建工作流图"""
        workflow = StateGraph(WorkflowState)
        
        # 添加节点
        workflow.add_node("parse", self._parse_node)
        workflow.add_node("explore", self._explore_node)
        workflow.add_node("clarify", self._clarify_node)
        workflow.add_node("generate", self._generate_node)
        
        # 设置入口
        workflow.set_entry_point("parse")
        
        # 添加边
        workflow.add_edge("parse", "explore")
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
        baseline_gend_srs: str = "",
        ablation_mode: AblationMode = "default",
        max_iterations: Optional[int] = None,
        max_new_requirements_per_iteration: Optional[int] = None
    ) -> dict:
        """运行工作流"""
        from ..utils.timer import TimerManager
        from ..utils.score_history import ScoreHistory
        from ..models.requirement import RequirementList
        
        self.ablation_mode = ablation_mode
        
        # 初始化状态
        initial_state: WorkflowState = {
            "raw_input": raw_input,
            "baseline_srs": baseline_srs,
            "baseline_gend_srs": baseline_gend_srs,
            "requirements": RequirementList(),
            "score_history": ScoreHistory(),
            "timer_manager": TimerManager(),
            "iteration_count": 1,  # 迭代从1开始
            "ablation_mode": ablation_mode,
            "convergence_reached": False,
            "max_iterations": max_iterations if max_iterations is not None else Config.MAX_ITERATIONS,  # type: ignore
            "max_new_requirements_per_iteration": max_new_requirements_per_iteration,  # type: ignore
            "req_explore_messages": None,  # type: ignore
            "clarification_results": None  # type: ignore
        }
        
        # 开始计时
        initial_state["timer_manager"].start_total()
        
        # 构建并运行工作流
        graph = self.build_graph()
        
        # 计算递归限制：
        # - parse 节点：1次
        # - 每次迭代：explore (1) + clarify (1) + check_convergence (1) + 可能的额外节点 = 至少4-5次
        # - generate 节点：1次
        # 考虑到条件边和可能的额外调用，使用更保守的计算方式
        max_iterations = initial_state.get("max_iterations", Config.MAX_ITERATIONS)  # type: ignore
        # 每次迭代按 6 个节点计算（包含条件边可能触发的额外节点），加上更大的安全缓冲
        recursion_limit = max(max_iterations * 6 + 50, 100)  # 至少保证 100 的递归限制
        self.logger.info(f"设置 LangGraph 递归限制: {recursion_limit} (最大迭代次数: {max_iterations})")
        
        # 设置 LangGraph 配置，增加递归限制
        config = {"recursion_limit": recursion_limit}
        final_state = graph.invoke(initial_state, config=config)
        
        # 停止计时
        final_state["timer_manager"].get_total_time()
        
        # 生成对比报告
        reporter = ComparisonReporter()
        comparison_report = reporter.generate_report(
            final_state["requirements"].requirements,
            final_state["score_history"],
            final_state["timer_manager"],
            ablation_mode
        )
        
        return {
            "srs_document": final_state.get("_srs_document", ""),
            "requirements": final_state["requirements"],
            "comparison_report": comparison_report,
            "total_time": final_state["timer_manager"].get_total_time(),
            "timer_summary": final_state["timer_manager"].get_summary()
        }
