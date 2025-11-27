"""Checkpoint管理模块，用于保存和恢复工作流状态"""
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any
from ..workflow.state import WorkflowState
from ..models.requirement import RequirementList, ClarificationResult
from ..utils.score_history import ScoreHistory, ScoreRecord
from ..utils.timer import TimerManager, AgentTimer
from ..utils.logger import get_logger


class CheckpointManager:
    """Checkpoint管理器"""
    
    def __init__(self, output_dir: str):
        """
        初始化CheckpointManager
        
        Args:
            output_dir: 输出目录路径
        """
        self.output_dir = Path(output_dir)
        self.checkpoint_dir = self.output_dir / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.logger = get_logger("CheckpointManager")
    
    def save_checkpoint(
        self,
        state: WorkflowState,
        node_name: str,
        iteration: Optional[int] = None
    ) -> Path:
        """
        保存checkpoint
        
        Args:
            state: 工作流状态
            node_name: 节点名称（parse, explore, clarify, generate）
            iteration: 迭代次数（可选）
        
        Returns:
            checkpoint文件路径
        """
        # 构建文件名
        if iteration is not None:
            filename = f"checkpoint_{node_name}_iter{iteration}.json"
        else:
            filename = f"checkpoint_{node_name}.json"
        
        checkpoint_path = self.checkpoint_dir / filename
        
        # 序列化状态
        checkpoint_data = self._serialize_state(state, node_name, iteration)
        
        # 保存到文件
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint_data, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"已保存checkpoint: {checkpoint_path}")
        return checkpoint_path
    
    def load_checkpoint(self, checkpoint_path: Optional[Path] = None) -> Optional[WorkflowState]:
        """
        加载checkpoint
        
        Args:
            checkpoint_path: checkpoint文件路径，如果为None则查找最新的checkpoint
        
        Returns:
            恢复的工作流状态，如果不存在则返回None
        """
        if checkpoint_path is None:
            checkpoint_path = self.get_latest_checkpoint()
        
        if checkpoint_path is None or not checkpoint_path.exists():
            return None
        
        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                checkpoint_data = json.load(f)
            
            # 反序列化状态
            state = self._deserialize_state(checkpoint_data)
            
            self.logger.info(f"已加载checkpoint: {checkpoint_path}")
            return state
        except Exception as e:
            self.logger.error(f"加载checkpoint失败: {checkpoint_path}, 错误: {e}")
            return None
    
    def get_latest_checkpoint(self) -> Optional[Path]:
        """
        获取最新的checkpoint文件
        
        Returns:
            最新的checkpoint文件路径，如果不存在则返回None
        """
        checkpoints = list(self.checkpoint_dir.glob("checkpoint_*.json"))
        if not checkpoints:
            return None
        
        # 按修改时间排序，返回最新的
        checkpoints.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return checkpoints[0]
    
    def get_checkpoint_by_iteration(self, iteration: int) -> Optional[Path]:
        """
        获取指定迭代次数的checkpoint（选择迭代次数最大的）
        
        Args:
            iteration: 迭代次数
        
        Returns:
            checkpoint文件路径，如果不存在则返回None
        """
        # 查找所有小于等于指定迭代次数的checkpoint
        pattern = f"checkpoint_*_iter*.json"
        checkpoints = list(self.checkpoint_dir.glob(pattern))
        
        matching_checkpoints = []
        for cp in checkpoints:
            # 从文件名提取迭代次数
            try:
                # 格式: checkpoint_{node_name}_iter{N}.json
                parts = cp.stem.split("_iter")
                if len(parts) == 2:
                    iter_num = int(parts[1])
                    if iter_num <= iteration:
                        matching_checkpoints.append((iter_num, cp))
            except (ValueError, IndexError):
                continue
        
        if not matching_checkpoints:
            return None
        
        # 返回迭代次数最大的
        matching_checkpoints.sort(key=lambda x: x[0], reverse=True)
        return matching_checkpoints[0][1]
    
    def _serialize_state(
        self,
        state: WorkflowState,
        node_name: str,
        iteration: Optional[int]
    ) -> Dict[str, Any]:
        """序列化工作流状态为字典"""
        data = {
            "node_name": node_name,
            "iteration": iteration,
            "timestamp": time.time(),
            "state": {}
        }
        
        # 序列化各个字段
        state_dict = data["state"]
        
        # 基本字符串字段
        for key in ["raw_input", "baseline_srs", "baseline_gend_srs", 
                   "requirement_structure", "baseline_requirement_structure",
                   "ablation_mode", "output_dir_base", "task_name",
                   "_version_to_generate", "_version_name", "_last_generated_version"]:
            if key in state:
                state_dict[key] = state[key]
        
        # 整数和浮点数字段
        for key in ["iteration_count", "max_iterations", 
                   "max_new_requirements_per_iteration",
                   "_cumulative_clarify_time", "_cumulative_version_gen_time",
                   "_workflow_start_time"]:
            if key in state:
                state_dict[key] = state[key]
        
        # 布尔字段
        if "convergence_reached" in state:
            state_dict["convergence_reached"] = state["convergence_reached"]
        
        # RequirementList (Pydantic模型，可直接序列化)
        if "requirements" in state and state["requirements"]:
            state_dict["requirements"] = state["requirements"].model_dump()
        
        # ScoreHistory (需要手动序列化)
        if "score_history" in state and state["score_history"]:
            state_dict["score_history"] = self._serialize_score_history(state["score_history"])
        
        # TimerManager (需要手动序列化)
        if "timer_manager" in state and state["timer_manager"]:
            state_dict["timer_manager"] = self._serialize_timer_manager(state["timer_manager"])
        
        # req_explore_messages (List[dict])
        if "req_explore_messages" in state and state["req_explore_messages"]:
            state_dict["req_explore_messages"] = state["req_explore_messages"]
        
        # clarification_results (List[ClarificationResult])
        if "clarification_results" in state and state["clarification_results"]:
            state_dict["clarification_results"] = [
                result.model_dump() if hasattr(result, "model_dump") else result
                for result in state["clarification_results"]
            ]
        
        # gen_versions (Set[Union[str, int]])
        if "gen_versions" in state and state["gen_versions"]:
            # Set不能直接序列化，转为list
            state_dict["gen_versions"] = list(state["gen_versions"])
        
        return data
    
    def _deserialize_state(self, data: Dict[str, Any]) -> WorkflowState:
        """从字典反序列化工作流状态"""
        state_data = data.get("state", {})
        state: WorkflowState = {}
        
        # 基本字符串字段
        for key in ["raw_input", "baseline_srs", "baseline_gend_srs",
                   "requirement_structure", "baseline_requirement_structure",
                   "ablation_mode", "output_dir_base", "task_name",
                   "_version_to_generate", "_version_name", "_last_generated_version"]:
            if key in state_data:
                state[key] = state_data[key]  # type: ignore
        
        # 整数和浮点数字段
        for key in ["iteration_count", "max_iterations",
                   "max_new_requirements_per_iteration",
                   "_cumulative_clarify_time", "_cumulative_version_gen_time",
                   "_workflow_start_time"]:
            if key in state_data:
                state[key] = state_data[key]  # type: ignore
        
        # 布尔字段
        if "convergence_reached" in state_data:
            state["convergence_reached"] = state_data["convergence_reached"]  # type: ignore
        
        # RequirementList
        if "requirements" in state_data:
            state["requirements"] = RequirementList.model_validate(state_data["requirements"])  # type: ignore
        
        # ScoreHistory
        if "score_history" in state_data:
            state["score_history"] = self._deserialize_score_history(state_data["score_history"])  # type: ignore
        
        # TimerManager
        if "timer_manager" in state_data:
            state["timer_manager"] = self._deserialize_timer_manager(state_data["timer_manager"])  # type: ignore
        
        # req_explore_messages
        if "req_explore_messages" in state_data:
            state["req_explore_messages"] = state_data["req_explore_messages"]  # type: ignore
        
        # clarification_results
        if "clarification_results" in state_data:
            state["clarification_results"] = [  # type: ignore
                ClarificationResult.model_validate(result)
                for result in state_data["clarification_results"]
            ]
        
        # gen_versions
        if "gen_versions" in state_data:
            state["gen_versions"] = set(state_data["gen_versions"])  # type: ignore
        
        return state
    
    def _serialize_score_history(self, score_history: ScoreHistory) -> Dict[str, Any]:
        """序列化ScoreHistory"""
        history_dict = {}
        for req_id, records in score_history.history.items():
            history_dict[req_id] = [
                {
                    "iteration": r.iteration,
                    "score": r.score,
                    "reason": r.reason,
                    "evidence": r.evidence
                }
                for r in records
            ]
        return history_dict
    
    def _deserialize_score_history(self, data: Dict[str, Any]) -> ScoreHistory:
        """反序列化ScoreHistory"""
        score_history = ScoreHistory()
        for req_id, records_data in data.items():
            records = []
            for r_data in records_data:
                records.append(
                    ScoreRecord(
                        iteration=r_data["iteration"],
                        score=r_data["score"],
                        reason=r_data.get("reason"),
                        evidence=r_data.get("evidence")
                    )
                )
            score_history.history[req_id] = records
        return score_history
    
    def _serialize_timer_manager(self, timer_manager: TimerManager) -> Dict[str, Any]:
        """序列化TimerManager"""
        timers_dict = {}
        for name, timer in timer_manager.timers.items():
            timers_dict[name] = {
                "name": timer.name,
                "start_time": timer.start_time,
                "elapsed_time": timer.elapsed_time,
                "call_count": timer.call_count
            }
        return {
            "total_start_time": timer_manager.total_start_time,
            "timers": timers_dict
        }
    
    def _deserialize_timer_manager(self, data: Dict[str, Any]) -> TimerManager:
        """反序列化TimerManager"""
        timer_manager = TimerManager()
        timer_manager.total_start_time = data.get("total_start_time")
        
        timers_data = data.get("timers", {})
        for name, timer_data in timers_data.items():
            timer = AgentTimer(name=timer_data["name"])
            timer.start_time = timer_data.get("start_time")
            timer.elapsed_time = timer_data.get("elapsed_time", 0.0)
            timer.call_count = timer_data.get("call_count", 0)
            timer_manager.timers[name] = timer
        
        return timer_manager

