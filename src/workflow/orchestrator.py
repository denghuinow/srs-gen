"""工作流编排 (FR-005, FR-006)"""
import re
import copy
import time
from pathlib import Path
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
from ..utils.checkpoint import CheckpointManager


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
        
        # 版本生成结果管理
        self.version_generation_results: dict = {}  # 存储版本生成结果
        
        # Checkpoint管理器（将在run中初始化）
        self.checkpoint_manager: Optional[CheckpointManager] = None
    
    def _parse_node(self, state: WorkflowState) -> WorkflowState:
        """解析节点"""
        if self.timer_manager is None:
            self.timer_manager = state["timer_manager"]
        
        # requirement_structure 直接使用 raw_input，不再通过 ReqParseAgent 解析
        state["requirement_structure"] = state["raw_input"]  # type: ignore
        
        # 如果存在 baseline_gend_srs，使用 ReqParseAgent 解析它生成需求语义单元
        baseline_gend_srs = state.get("baseline_gend_srs", "")
        if baseline_gend_srs:
            agent = ReqParseAgent(self.client, self.timer_manager, prompt_version=self.prompt_version)
            baseline_requirement_structure = agent.parse(baseline_gend_srs, input_type="基准生成的SRS")
            state["baseline_requirement_structure"] = baseline_requirement_structure  # type: ignore
        else:
            state["baseline_requirement_structure"] = ""  # type: ignore
        
        # 如果gen_versions包含"no-explore-clarify"，设置版本生成标记
        gen_versions = state.get("gen_versions")
        if gen_versions and "no-explore-clarify" in gen_versions:
            state["_version_to_generate"] = "no-explore-clarify"  # type: ignore
            state["_version_name"] = "no-explore-clarify"  # type: ignore
        
        # 保存checkpoint
        if self.checkpoint_manager:
            self.checkpoint_manager.save_checkpoint(state, "parse", state.get("iteration_count"))
        
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

        if self.ablation_mode == "no-explore-clarify":
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
        
        # 计算新增的需求
        req_ids_after = set(req.id for req in state["requirements"].requirements)
        new_req_ids = req_ids_after - req_ids_before
        if new_req_ids:
            self.logger.info(f"[迭代 {state['iteration_count']}] 挖掘阶段新增需求: {sorted(new_req_ids)}")
        
        # 如果gen_versions包含"no-clarify"且是第一次迭代，设置版本生成标记
        gen_versions = state.get("gen_versions")
        if gen_versions and "no-clarify" in gen_versions and state["iteration_count"] == 1:
            state["_version_to_generate"] = "no-clarify"  # type: ignore
            state["_version_name"] = "no-clarify"  # type: ignore
        
        # 保存checkpoint
        if self.checkpoint_manager:
            self.checkpoint_manager.save_checkpoint(state, "explore", state.get("iteration_count"))
        
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
        if self.ablation_mode in ["no-clarify", "no-explore-clarify"]:
            # 跳过澄清，默认0分
            for req in state["requirements"].requirements:
                if req.score is None:
                    req.score = 0
                    state["score_history"].record(
                        req.id,
                        state["iteration_count"],
                        0,
                        "消融模式：默认0分"
                    )
            return state
        
        # 记录澄清开始时间
        clarify_start_time = time.time()
        
        agent = ReqClarifyAgent(self.client, state["timer_manager"], prompt_version=self.prompt_version)
        results = agent.clarify(state["requirements"], state["baseline_srs"])
        
        # 计算本次澄清耗时并累计
        clarify_elapsed_time = time.time() - clarify_start_time
        cumulative_clarify_time = state.get("_cumulative_clarify_time", 0.0)  # type: ignore
        state["_cumulative_clarify_time"] = cumulative_clarify_time + clarify_elapsed_time  # type: ignore
        
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
                    req.score = None
                if not new_requirements.add(req):
                    self.logger.warning(f"需求 {req.id} 在澄清阶段重复添加，已跳过")
        
        state["requirements"] = new_requirements
        
        # 统计负分需求数量
        negative_count = sum(1 for req in state["requirements"].requirements 
                           if req.score is not None and req.score < 0)
        if negative_count > 0:
            self.logger.info(f"[迭代 {state['iteration_count']}] 保留负分需求数量: {negative_count}")
        
        # 如果gen_versions包含当前迭代次数，设置版本生成标记
        gen_versions = state.get("gen_versions")
        iteration = state["iteration_count"]
        if gen_versions and iteration in gen_versions:
            state["_version_to_generate"] = "iter"  # type: ignore
            state["_version_name"] = f"iter{iteration}"  # type: ignore
        
        # 保存checkpoint
        if self.checkpoint_manager:
            self.checkpoint_manager.save_checkpoint(state, "clarify", state.get("iteration_count"))
        
        return state
    
    def _route_after_parse(self, state: WorkflowState) -> Literal["generate_version", "explore"]:
        """parse节点后的路由函数"""
        gen_versions = state.get("gen_versions")
        if gen_versions and "no-explore-clarify" in gen_versions:
            return "generate_version"
        return "explore"
    
    def _route_after_explore(self, state: WorkflowState) -> Literal["generate_version", "clarify"]:
        """explore节点后的路由函数"""
        gen_versions = state.get("gen_versions")
        if gen_versions and "no-clarify" in gen_versions and state["iteration_count"] == 1:
            return "generate_version"
        return "clarify"
    
    def _route_after_clarify(self, state: WorkflowState) -> Literal["generate_version", "continue"]:
        """clarify节点后的路由函数"""
        gen_versions = state.get("gen_versions")
        iteration = state["iteration_count"]
        
        # 如果需要生成当前迭代的版本
        if gen_versions and iteration in gen_versions:
            return "generate_version"
        
        # 检查是否达到最大迭代次数
        max_iterations = state.get("max_iterations", Config.MAX_ITERATIONS)  # type: ignore
        next_iteration = iteration + 1
        
        if next_iteration > max_iterations:
            # 最后一次迭代，应该在gen_versions中（因为最大数字就是迭代次数）
            # 如果不在，说明有bug，但我们仍然尝试生成
            self.logger.warning(f"最后一次迭代 {iteration} 不在gen_versions中，但已达到最大迭代次数，继续生成")
            # 设置版本标记，以便generate节点能生成
            state["_version_to_generate"] = "iter"  # type: ignore
            state["_version_name"] = f"iter{iteration}"  # type: ignore
            return "generate_version"
        
        return "continue"
    
    def _route_after_generate(self, state: WorkflowState) -> Literal["explore", "clarify", "end"]:
        """generate节点后的路由函数"""
        version_name = state.get("_last_generated_version")
        
        # 如果生成了no-explore-clarify版本，需要继续到explore
        if version_name == "no-explore-clarify":
            state["_last_generated_version"] = None  # type: ignore
            return "explore"
        # 如果生成了no-clarify版本，需要继续到clarify
        if version_name == "no-clarify":
            state["_last_generated_version"] = None  # type: ignore
            return "clarify"
        # 如果生成了iter版本，检查是否还有下一轮迭代
        if version_name and version_name.startswith("iter"):
            try:
                iter_num = int(version_name.replace("iter", ""))
                max_iterations = state.get("max_iterations", Config.MAX_ITERATIONS)  # type: ignore
                state["_last_generated_version"] = None  # type: ignore
                if iter_num >= max_iterations:
                    # 最后一次迭代，结束
                    return "end"
                else:
                    # 还有下一轮迭代，继续到explore
                    return "explore"
            except ValueError:
                state["_last_generated_version"] = None  # type: ignore
                return "explore"
        # 否则结束
        state["_last_generated_version"] = None  # type: ignore
        return "end"
    
    def _generate_node(self, state: WorkflowState) -> WorkflowState:
        """生成节点"""
        agent = DocGenerateAgent(self.client, state["timer_manager"], prompt_version=self.prompt_version)
        
        version_to_generate = state.get("_version_to_generate")
        version_name = state.get("_version_name")
        
        # 记录版本生成开始时间（仅计算文档生成时间，不包括文件I/O）
        version_gen_start_time = time.time()
        
        # 根据版本类型处理需求列表
        if version_to_generate == "no-explore-clarify":
            # no-explore-clarify模式：直接使用requirement_structure，不需要requirements
            requirements = RequirementList()
            ablation_mode = "no-explore-clarify"
        elif version_to_generate == "no-clarify":
            # no-clarify模式：使用当前requirements，但所有需求score设为0
            requirements = copy.deepcopy(state.get("requirements", RequirementList()))
            for req in requirements.requirements:
                if req.score is None:
                    req.score = 0
            ablation_mode = "no-clarify"
        elif version_to_generate == "iter":
            # iter版本：筛选历史得分>=1的需求
            requirements = copy.deepcopy(state.get("requirements", RequirementList()))
            score_history = state.get("score_history")
            if score_history:
                filtered_requirements = RequirementList()
                for req in requirements.requirements:
                    best_score = score_history.get_best_score(req.id)
                    if best_score is not None and best_score >= 1:
                        filtered_requirements.requirements.append(req)
                requirements = filtered_requirements
            ablation_mode = "default"
        else:
            # 默认：基于历史得分筛选
            requirements = RequirementList()
            for req in state["requirements"].requirements:
                best_score = state["score_history"].get_best_score(req.id)
                if best_score is not None and best_score >= 1:
                    requirements.requirements.append(req)
            ablation_mode = state.get("ablation_mode", "default")  # type: ignore
        
        # 获取需求结构
        requirement_structure = state.get("requirement_structure", "")  # type: ignore
        baseline_requirement_structure = state.get("baseline_requirement_structure", "")  # type: ignore
        
        # 生成SRS文档
        srs_document = agent.generate(
            requirements,
            raw_input=state["raw_input"],
            requirement_structure=requirement_structure,
            ablation_mode=ablation_mode,
            baseline_requirement_structure=baseline_requirement_structure
        )
        
        # 记录版本生成结束时间（文档生成完成）
        version_gen_end_time = time.time()
        version_gen_elapsed_time = version_gen_end_time - version_gen_start_time
        
        # 如果指定了版本名称，保存到srs_collection目录并计算净耗时
        if version_name:
            output_dir_base = state.get("output_dir_base")
            if output_dir_base:
                output_dir = Path(output_dir_base) / f"srs_document_{version_name}"
                output_dir.mkdir(parents=True, exist_ok=True)
                
                task_name = state.get("task_name", "srs_document")
                doc_name = f"{task_name}.md"
                srs_path = output_dir / doc_name
                
                with open(srs_path, "w", encoding="utf-8") as f:
                    f.write(srs_document)
                
                # 计算净耗时
                start_time = state.get("_workflow_start_time", 0.0)  # type: ignore
                cumulative_clarify_time = state.get("_cumulative_clarify_time", 0.0)  # type: ignore
                cumulative_version_gen_time = state.get("_cumulative_version_gen_time", 0.0)  # type: ignore
                
                current_time = version_gen_end_time
                total_time = current_time - start_time
                net_time = total_time - cumulative_clarify_time - cumulative_version_gen_time
                
                self.version_generation_results[version_name] = {
                    "success": True,
                    "path": str(srs_path),
                    "content": srs_document,
                    "net_time": net_time,
                    "total_time": total_time,
                    "cumulative_clarify_time": cumulative_clarify_time,
                    "cumulative_version_gen_time": cumulative_version_gen_time,
                    "version_gen_time": version_gen_elapsed_time
                }
                
                # 累计版本生成耗时
                state["_cumulative_version_gen_time"] = cumulative_version_gen_time + version_gen_elapsed_time  # type: ignore
        
        # 保存最后生成的版本名称，供路由函数使用
        if version_name:
            state["_last_generated_version"] = version_name  # type: ignore
        
        # 清除版本生成标记
        state["_version_to_generate"] = None  # type: ignore
        state["_version_name"] = None  # type: ignore
        
        # 保存checkpoint
        if self.checkpoint_manager:
            self.checkpoint_manager.save_checkpoint(state, "generate", state.get("iteration_count"))
        
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
        
        # 添加条件边
        workflow.add_conditional_edges(
            "parse",
            self._route_after_parse,
            {
                "generate_version": "generate",
                "explore": "explore"
            }
        )
        
        workflow.add_conditional_edges(
            "explore",
            self._route_after_explore,
            {
                "generate_version": "generate",
                "clarify": "clarify"
            }
        )
        
        workflow.add_conditional_edges(
            "clarify",
            self._route_after_clarify,
            {
                "generate_version": "generate",
                "continue": "explore"
            }
        )
        
        workflow.add_conditional_edges(
            "generate",
            self._route_after_generate,
            {
                "explore": "explore",
                "clarify": "clarify",
                "end": END
            }
        )
        
        return workflow.compile()
    
    def run(
        self,
        raw_input: str,
        max_iterations: int,
        baseline_srs: str = "",
        baseline_gend_srs: str = "",
        ablation_mode: AblationMode = "default",
        max_new_requirements_per_iteration: Optional[int] = None,
        output_dir_base: Optional[str] = None,
        task_name: Optional[str] = None,
        gen_versions: Optional[set] = None,
        resume_from_checkpoint: Optional[str] = None,
        auto_resume: bool = True,
        checkpoint_dir: Optional[str] = None
    ) -> dict:
        """运行工作流"""
        from ..utils.timer import TimerManager
        from ..utils.score_history import ScoreHistory
        from ..models.requirement import RequirementList
        
        self.ablation_mode = ablation_mode
        
        # 初始化checkpoint管理器
        # checkpoint保存在任务自己的输出目录，而不是共享的srs_collection目录
        # 这样可以避免并行任务之间的checkpoint冲突
        if checkpoint_dir:
            self.checkpoint_manager = CheckpointManager(checkpoint_dir)
        else:
            self.checkpoint_manager = None
        
        # 尝试从checkpoint恢复
        initial_state: Optional[WorkflowState] = None
        if resume_from_checkpoint:
            # 手动指定checkpoint路径
            checkpoint_path = Path(resume_from_checkpoint)
            if checkpoint_path.exists():
                initial_state = self.checkpoint_manager.load_checkpoint(checkpoint_path) if self.checkpoint_manager else None
                if initial_state:
                    self.logger.info(f"从指定checkpoint恢复: {checkpoint_path}")
        elif auto_resume and self.checkpoint_manager:
            # 自动查找最新checkpoint
            initial_state = self.checkpoint_manager.load_checkpoint()
            if initial_state:
                self.logger.info("从最新checkpoint自动恢复")
        
        # 如果没有从checkpoint恢复，创建新状态
        if initial_state is None:
            initial_state = {
                "raw_input": raw_input,
                "baseline_srs": baseline_srs,
                "baseline_gend_srs": baseline_gend_srs,
                "requirements": RequirementList(),
                "score_history": ScoreHistory(),
                "timer_manager": TimerManager(),
                "iteration_count": 1,  # 迭代从1开始
                "ablation_mode": ablation_mode,
                "convergence_reached": False,
                "max_iterations": max_iterations,  # type: ignore
                "max_new_requirements_per_iteration": max_new_requirements_per_iteration,  # type: ignore
                "req_explore_messages": None,  # type: ignore
                "clarification_results": None,  # type: ignore
                "output_dir_base": output_dir_base,  # type: ignore
                "task_name": task_name,  # type: ignore
                "gen_versions": gen_versions,  # type: ignore
                "_version_to_generate": None,  # type: ignore
                "_version_name": None,  # type: ignore
                "_last_generated_version": None,  # type: ignore
                "_cumulative_clarify_time": 0.0,  # type: ignore
                "_cumulative_version_gen_time": 0.0  # type: ignore
            }
            
            # 开始计时并保存开始时间
            initial_state["timer_manager"].start_total()
            workflow_start_time = initial_state["timer_manager"].total_start_time
            if workflow_start_time is None:
                workflow_start_time = time.time()
            initial_state["_workflow_start_time"] = workflow_start_time  # type: ignore
        else:
            # 从checkpoint恢复，确保关键字段存在
            if "output_dir_base" not in initial_state:
                initial_state["output_dir_base"] = output_dir_base  # type: ignore
            if "task_name" not in initial_state:
                initial_state["task_name"] = task_name  # type: ignore
            if "gen_versions" not in initial_state:
                initial_state["gen_versions"] = gen_versions  # type: ignore
            # 确保timer_manager已初始化
            if "timer_manager" not in initial_state or initial_state["timer_manager"] is None:
                initial_state["timer_manager"] = TimerManager()
                initial_state["timer_manager"].start_total()
                if "_workflow_start_time" not in initial_state:
                    initial_state["_workflow_start_time"] = time.time()  # type: ignore
        
        # 构建并运行工作流
        graph = self.build_graph()
        
        # 计算递归限制
        max_iterations = initial_state.get("max_iterations", Config.MAX_ITERATIONS)  # type: ignore
        recursion_limit = max(max_iterations * 6 + 50, 100)
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
        
        # 报告版本生成结果
        if self.version_generation_results:
            success_count = sum(1 for r in self.version_generation_results.values() if r.get("success"))
            fail_count = len(self.version_generation_results) - success_count
            if fail_count > 0:
                self.logger.warning(f"版本生成：成功 {success_count}，失败 {fail_count}")
                for version_name, result in self.version_generation_results.items():
                    if not result.get("success"):
                        self.logger.error(f"✗ {version_name}: {result.get('error')}")
            
            # 生成版本耗时TSV表格
            self._generate_version_time_tsv()
        
        return {
            "requirements": final_state["requirements"],
            "comparison_report": comparison_report,
            "total_time": final_state["timer_manager"].get_total_time(),
            "timer_summary": final_state["timer_manager"].get_summary(),
            "version_generation_results": self.version_generation_results
        }
    
    def _generate_version_time_tsv(self) -> None:
        """生成版本耗时TSV表格并写入日志"""
        if not self.version_generation_results:
            return
        
        # 定义版本排序顺序
        def sort_version_key(v):
            if v == "no-explore-clarify":
                return (0, 0)
            elif v == "no-clarify":
                return (0, 1)
            elif v.startswith("iter"):
                try:
                    return (1, int(v.replace("iter", "")))
                except:
                    return (1, 0)
            else:
                return (2, 0)
        
        # 按版本生成顺序排序
        sorted_versions = sorted(self.version_generation_results.keys(), key=sort_version_key)
        
        # 生成TSV表格
        tsv_lines = []
        tsv_lines.append("版本名称\t净耗时(秒)\t总耗时(秒)\t累计澄清耗时(秒)\t累计版本生成耗时(秒)\t版本生成耗时(秒)")
        
        for version_name in sorted_versions:
            result = self.version_generation_results[version_name]
            if result.get("success"):
                net_time = result.get("net_time", 0.0)
                total_time = result.get("total_time", 0.0)
                cumulative_clarify_time = result.get("cumulative_clarify_time", 0.0)
                cumulative_version_gen_time = result.get("cumulative_version_gen_time", 0.0)
                version_gen_time = result.get("version_gen_time", 0.0)
                
                tsv_lines.append(
                    f"{version_name}\t{net_time:.2f}\t{total_time:.2f}\t"
                    f"{cumulative_clarify_time:.2f}\t{cumulative_version_gen_time:.2f}\t{version_gen_time:.2f}"
                )
            else:
                # 失败版本标记
                tsv_lines.append(f"{version_name}\t失败\t-\t-\t-\t-")
        
        # 写入日志
        tsv_content = "\n".join(tsv_lines)
        self.logger.info("\n=== 版本耗时统计 (TSV格式) ===\n" + tsv_content)
