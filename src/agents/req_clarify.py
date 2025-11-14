"""需求澄清智能体 (FR-003)"""
from typing import List
from openai import OpenAI
from ..config import Config
from ..models.requirement import Requirement, RequirementList, ClarificationResult
from ..utils.timer import TimerManager
from ..utils.forbidden_list import ForbiddenList
from ..utils.logger import get_logger


class ReqClarifyAgent:
    """需求澄清智能体：加载基准SRS，进行一致性评分"""
    
    def __init__(self, client: OpenAI, timer_manager: TimerManager):
        self.client = client
        self.timer = timer_manager.get_timer("ReqClarify")
        self.logger = get_logger("ReqClarify")
    
    def clarify(
        self,
        requirements: RequirementList,
        baseline_srs: str
    ) -> List[ClarificationResult]:
        """对需求清单进行澄清评分"""
        self.timer.start()
        
        try:
            self.logger.info(f"开始澄清评分，待评分需求数量: {len(requirements.requirements)}")
            
            # 记录需求ID列表
            req_ids = [req.id for req in requirements.requirements]
            self.logger.debug(f"待评分需求ID: {req_ids}")
            
            # 记录基准SRS信息
            baseline_len = len(baseline_srs)
            self.logger.info(f"基准SRS长度: {baseline_len} 字符")
            if baseline_srs:
                baseline_summary = baseline_srs[:500] + "..." if len(baseline_srs) > 500 else baseline_srs
                self.logger.debug(f"基准SRS摘要: {baseline_summary}")
            
            results = []
            
            # 批量处理以提高效率
            requirements_text = "\n".join([
                f"{req.id}: {req.text}"
                for req in requirements.requirements
            ])
            
            system_message = "你是一个专业的需求评审专家，擅长评估需求与基准文档的一致性。"
            prompt = f"""请对以下需求清单进行一致性评分，对照基准SRS文档。

基准SRS文档：
{baseline_srs}

需求清单：
{requirements_text}

要求：
1. 对每条需求给出一致性评分，评分集为 {{+2, +1, 0, -1, -2}}
   - +2: 与基准SRS高度一致，完全符合
   - +1: 与基准SRS基本一致，略有补充
   - 0: 与基准SRS无关或中性
   - -1: 与基准SRS存在轻微冲突
   - -2: 与基准SRS明确冲突，必须禁用
2. 提供不超过60字的评分理由
3. 输出格式：每行一个结果，格式为 "REQ-XXX: 评分 理由"

请逐条评分。"""
            
            # 记录API调用参数
            api_params = {
                "model": Config.OPENAI_MODEL,
                "temperature": 0.0
            }
            self.logger.debug(f"API调用参数: {api_params}")
            
            # 记录完整请求内容
            self.logger.debug("完整请求内容:")
            self.logger.debug(f"  System: {system_message}")
            self.logger.debug(f"  User: {prompt}")
            
            response = self.client.chat.completions.create(
                model=Config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0
            )
            
            # 记录完整响应内容
            content = response.choices[0].message.content
            if not content:
                self.logger.warning("API响应为空")
                return []
            
            self.logger.debug("完整响应内容:")
            for line in content.split("\n"):
                self.logger.debug(f"  {line}")
            
            # 记录Token使用情况（如果可用）
            if hasattr(response, 'usage') and response.usage:
                usage = response.usage
                self.logger.debug(f"Token使用情况: prompt_tokens={usage.prompt_tokens}, completion_tokens={usage.completion_tokens}, total_tokens={usage.total_tokens}")
            
            # 解析输出
            score_distribution = {2: 0, 1: 0, 0: 0, -1: 0, -2: 0}
            
            for line in content.split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                
                # 解析格式 "REQ-XXX: 评分 理由"
                if ":" in line:
                    parts = line.split(":", 1)
                    req_id = parts[0].strip()
                    rest = parts[1].strip()
                    
                    # 提取评分和理由
                    score = None
                    reason = rest
                    
                    # 尝试提取评分数字
                    for score_val in [2, 1, 0, -1, -2]:
                        if f"评分 {score_val}" in rest or f"得分 {score_val}" in rest or f"{score_val}分" in rest:
                            score = score_val
                            # 移除评分部分，保留理由
                            reason = rest.replace(f"评分 {score_val}", "").replace(f"得分 {score_val}", "").replace(f"{score_val}分", "").strip()
                            break
                    
                    if score is None:
                        # 如果没有明确评分，尝试从文本中推断
                        if "+2" in rest or "高度一致" in rest:
                            score = 2
                        elif "+1" in rest or "基本一致" in rest:
                            score = 1
                        elif "-1" in rest or "轻微冲突" in rest:
                            score = -1
                        elif "-2" in rest or "明确冲突" in rest or "必须禁用" in rest:
                            score = -2
                        else:
                            score = 0
                    
                    # 限制理由长度
                    if len(reason) > 60:
                        reason = reason[:57] + "..."
                    
                    score_distribution[score] = score_distribution.get(score, 0) + 1
                    
                    results.append(ClarificationResult(
                        req_id=req_id,
                        score=score,
                        reason=reason
                    ))
            
            # 记录评分结果统计
            self.logger.info("评分结果统计:")
            self.logger.info(f"  +2 (高度一致): {score_distribution[2]}")
            self.logger.info(f"  +1 (基本一致): {score_distribution[1]}")
            self.logger.info(f"  0 (中性): {score_distribution[0]}")
            self.logger.info(f"  -1 (轻微冲突): {score_distribution[-1]}")
            self.logger.info(f"  -2 (明确冲突): {score_distribution[-2]}")
            
            removed_count = score_distribution[-1] + score_distribution[-2]
            if removed_count > 0:
                self.logger.info(f"将被移除的需求数量: {removed_count}")
            
            return results
        
        except Exception as e:
            self.logger.error(f"澄清过程中发生错误: {e}", exc_info=True)
            raise
        
        finally:
            self.timer.stop()
