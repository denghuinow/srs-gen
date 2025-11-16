"""需求清单数据模型"""
from typing import List, Optional
from pydantic import BaseModel, Field


class Requirement(BaseModel):
    """单个需求条目"""
    id: str = Field(..., description="需求ID，如 REQ-001")
    text: str = Field(..., description="需求文本")
    score: Optional[int] = Field(None, description="评分 (-2到+2)")
    reason: Optional[str] = Field(None, description="评分理由（仅用于审计，不传递给ReqExplore）")
    iteration: Optional[int] = Field(None, description="生成时的迭代轮次")
    evidence: Optional[str] = Field(None, description="评分引用的基准证据")


class RequirementList(BaseModel):
    """需求清单管理"""
    requirements: List[Requirement] = Field(default_factory=list)
    
    def add(self, requirement: Requirement) -> bool:
        """添加需求，如果ID已存在则返回False，否则添加并返回True"""
        # 检查是否已存在相同ID的需求
        for existing_req in self.requirements:
            if existing_req.id == requirement.id:
                return False
        
        # ID不存在，添加需求
        self.requirements.append(requirement)
        return True
    
    def get_next_id(self) -> str:
        """获取下一个连续递增的ID"""
        if not self.requirements:
            return "REQ-001"
        
        # 提取所有ID中的最大数字
        max_num = 0
        for req in self.requirements:
            if req.id.startswith("REQ-"):
                try:
                    num = int(req.id.split("-")[1])
                    max_num = max(max_num, num)
                except (ValueError, IndexError):
                    pass
        
        next_num = max_num + 1
        return f"REQ-{next_num:03d}"
    
    def get_for_explore(self) -> List[dict]:
        """获取用于ReqExplore的需求列表（包含id、score和text，不包含reason）"""
        return [
            {"id": req.id, "score": req.score, "text": req.text}
            for req in self.requirements
            if req.score is not None
        ]
    
    def filter_by_score(self, min_score: int = 0) -> "RequirementList":
        """根据最小分数过滤需求"""
        filtered = RequirementList()
        filtered.requirements = [
            req for req in self.requirements
            if req.score is not None and req.score >= min_score
        ]
        return filtered


class ClarificationResult(BaseModel):
    """澄清评分结果"""
    req_id: str
    score: int = Field(..., ge=-2, le=2, description="评分 (-2到+2)")
    reason: str = Field(..., max_length=60, description="评分理由，不超过60字")
    evidence: Optional[str] = Field(
        default=None,
        description="引用的基准证据信息，用于审计"
    )
