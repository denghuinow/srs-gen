"""对比信息输出"""
from typing import Dict, List
from ..models.requirement import Requirement
from ..utils.score_history import ScoreHistory
from ..utils.timer import TimerManager


class ComparisonReporter:
    """对比信息报告生成器"""
    
    @staticmethod
    def generate_report(
        requirements: List[Requirement],
        score_history: ScoreHistory,
        timer_manager: TimerManager,
        forbidden_count: int,
        ablation_mode: str
    ) -> str:
        """生成对比报告"""
        
        report = f"""# 消融实验对比报告

## 运行模式
- 模式: {ablation_mode}

## 需求统计
- 总需求数: {score_history.get_total_requirements()}
- 进入最终清单数: {score_history.get_final_requirements(requirements)}
- 被禁用ID数: {forbidden_count}

## 各代理耗时汇总
"""
        
        timer_summary = timer_manager.get_summary()
        for agent, time_cost in timer_summary.items():
            report += f"- {agent}: {time_cost:.2f}秒\n"
        
        report += "\n## 各需求得分历史轨迹概览\n\n"
        
        history_summary = score_history.get_summary()
        for req_id, records in history_summary.items():
            report += f"### {req_id}\n"
            for record in records:
                report += f"- 迭代{record['iteration']}: 得分 {record['score']}"
                if record['reason']:
                    report += f" - {record['reason']}"
                if record.get("evidence"):
                    report += f" | 证据: {record['evidence']}"
                report += "\n"
            report += "\n"
        
        return report
