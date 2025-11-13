"""耗时统计工具"""
import time
from typing import Dict, Optional
from dataclasses import dataclass, field


@dataclass
class AgentTimer:
    """单个代理的计时器"""
    name: str
    start_time: Optional[float] = None
    elapsed_time: float = 0.0
    call_count: int = 0
    
    def start(self) -> None:
        """开始计时"""
        self.start_time = time.time()
    
    def stop(self) -> float:
        """停止计时并返回耗时"""
        if self.start_time is None:
            return 0.0
        elapsed = time.time() - self.start_time
        self.elapsed_time += elapsed
        self.call_count += 1
        self.start_time = None
        return elapsed


class TimerManager:
    """计时器管理器"""
    
    def __init__(self):
        self.timers: Dict[str, AgentTimer] = {}
        self.total_start_time: Optional[float] = None
    
    def start_total(self) -> None:
        """开始总计时"""
        self.total_start_time = time.time()
    
    def get_total_time(self) -> float:
        """获取总耗时"""
        if self.total_start_time is None:
            return 0.0
        return time.time() - self.total_start_time
    
    def get_timer(self, agent_name: str) -> AgentTimer:
        """获取或创建代理计时器"""
        if agent_name not in self.timers:
            self.timers[agent_name] = AgentTimer(name=agent_name)
        return self.timers[agent_name]
    
    def get_summary(self) -> Dict[str, float]:
        """获取各代理耗时汇总"""
        summary = {}
        for name, timer in self.timers.items():
            summary[name] = timer.elapsed_time
        summary["total"] = self.get_total_time()
        return summary
