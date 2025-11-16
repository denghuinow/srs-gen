"""得分历史管理"""
from typing import Dict, List, Optional
from dataclasses import dataclass
from ..models.requirement import Requirement


@dataclass
class ScoreRecord:
    """单次得分记录"""
    iteration: int
    score: int
    reason: Optional[str] = None


class ScoreHistory:
    """得分历史管理器"""
    
    def __init__(self):
        self.history: Dict[str, List[ScoreRecord]] = {}
    
    def record(self, req_id: str, iteration: int, score: int, reason: Optional[str] = None) -> None:
        """记录需求得分"""
        if req_id not in self.history:
            self.history[req_id] = []
        self.history[req_id].append(ScoreRecord(iteration=iteration, score=score, reason=reason))
    
    def get_history(self, req_id: str) -> List[ScoreRecord]:
        """获取需求的得分历史"""
        return self.history.get(req_id, [])
    
    def get_summary(self) -> Dict[str, List[Dict]]:
        """获取所有需求的得分历史概览"""
        summary = {}
        for req_id, records in self.history.items():
            summary[req_id] = [
                {
                    "iteration": r.iteration,
                    "score": r.score,
                    "reason": r.reason[:30] + "..." if r.reason and len(r.reason) > 30 else r.reason
                }
                for r in records
            ]
        return summary
    
    def get_total_requirements(self) -> int:
        """获取总需求数（有历史记录的需求数）"""
        return len(self.history)
    
    def get_final_requirements(self, final_requirements: List[Requirement]) -> int:
        """获取进入最终清单的需求数"""
        final_ids = {req.id for req in final_requirements}
        return len([req_id for req_id in self.history.keys() if req_id in final_ids])
    
    def has_score_above_or_equal(self, req_id: str, min_score: int = 1) -> bool:
        """检查需求是否在历史中曾经有过 >= min_score 的得分"""
        if req_id not in self.history:
            return False
        records = self.history[req_id]
        return any(record.score >= min_score for record in records)