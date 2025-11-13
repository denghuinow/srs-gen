"""禁用清单管理"""
from typing import List, Set
from ..models.requirement import Requirement


class ForbiddenList:
    """禁用清单管理器"""
    
    def __init__(self):
        self.forbidden_ids: Set[str] = set()
        self.forbidden_directions: Set[str] = set()
    
    def add(self, requirement: Requirement) -> None:
        """添加被禁用需求（-2分）"""
        self.forbidden_ids.add(requirement.id)
        # 提取需求方向（简单启发式：提取关键词）
        direction = self._extract_direction(requirement.text)
        if direction:
            self.forbidden_directions.add(direction)
    
    def _extract_direction(self, text: str) -> str:
        """从需求文本中提取方向关键词"""
        # 简单的关键词提取逻辑
        keywords = [
            "用户登录", "用户注册", "权限管理", "数据备份", "数据恢复",
            "支付", "退款", "订单", "商品", "库存", "搜索", "推荐"
        ]
        text_lower = text.lower()
        for keyword in keywords:
            if keyword in text_lower:
                return keyword
        # 如果没有匹配，返回前20个字符作为方向标识
        return text[:20].strip()
    
    def is_forbidden(self, requirement: Requirement) -> bool:
        """检查需求是否被禁用"""
        if requirement.id in self.forbidden_ids:
            return True
        
        direction = self._extract_direction(requirement.text)
        if direction and direction in self.forbidden_directions:
            return True
        
        return False
    
    def filter_requirements(self, requirements: List[Requirement]) -> List[Requirement]:
        """过滤掉被禁用的需求"""
        return [req for req in requirements if not self.is_forbidden(req)]
    
    def get_count(self) -> int:
        """获取禁用ID数量"""
        return len(self.forbidden_ids)
