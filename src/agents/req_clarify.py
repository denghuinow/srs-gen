"""需求澄清智能体 (FR-003)"""
import re
from typing import List
from openai import OpenAI
from ..config import Config
from ..models.requirement import Requirement, RequirementList, ClarificationResult
from ..utils.timer import TimerManager
from ..utils.forbidden_list import ForbiddenList
from ..utils.logger import get_logger
from ..utils.streaming import stream_with_continuation


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
           
            results = []
            
            # 批量处理以提高效率
            requirements_text = "\n".join([
                f"{req.id}: {req.text}"
                for req in requirements.requirements
            ])
            
            prompt = f"""你是一个专业的需求评审专家，擅长评估需求与基准文档的一致性。
请对以下需求清单进行一致性评分，对照基准SRS文档。

基准SRS文档（完整）：
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
3. 为每条需求提供不超过80字的证据引用，可包含章节标题、原文摘录或页码提示
4. 输出格式：每行一个结果，格式为 "REQ-XXX | 评分: <score> | 理由: <text> | 证据: <evidence>"

请逐条评分。"""
            
            # 记录完整请求内容
            self.logger.debug("完整请求内容:")
            self.logger.debug(f"  User: {prompt}")
            
            # 始终使用流式响应
            self.logger.info("开始流式生成需求澄清结果...")
            
            # 构建消息列表用于续接
            messages = [
                {"role": "user", "content": prompt}
            ]
            
            # 构建API调用基础参数
            base_api_params = {
                "model": Config.OPENAI_MODEL,
                "temperature": 0.0,
            }
            max_tokens = Config.get_max_tokens()
            if max_tokens is not None:
                base_api_params["max_tokens"] = max_tokens
            
            # 记录API调用参数
            self.logger.debug(f"API调用基础参数: {base_api_params}")
            
            # 使用统一的流式响应和续接处理
            content = stream_with_continuation(
                client=self.client,
                base_api_params=base_api_params,
                messages=messages,
                task_name="需求澄清"
            )
            
            # 记录完整响应内容
            if not content:
                self.logger.warning("API响应为空")
                return []
            
            self.logger.debug("完整响应内容:")
            for line in content.split("\n"):
                self.logger.debug(f"  {line}")
            
            # 解析输出
            score_distribution = {2: 0, 1: 0, 0: 0, -1: 0, -2: 0}
            
            for line in content.split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                
                if "|" not in line:
                    continue
                
                parts = [part.strip() for part in line.split("|")]
                req_part = parts[0]
                if ":" in req_part:
                    req_part = req_part.split(":", 1)[0].strip()
                req_id = req_part.replace("**", "").replace("*", "").strip()
                if not req_id.startswith("REQ-"):
                    continue
                
                score_val = None
                reason = ""
                evidence = ""
                
                for part in parts[1:]:
                    normalized = part.replace("：", ":").strip()
                    lower = normalized.lower()
                    if lower.startswith("评分"):
                        match = re.search(r"[-+]?\d+", normalized)
                        if match:
                            score_val = int(match.group())
                    elif lower.startswith("理由"):
                        reason_text = normalized.split(":", 1)[-1].strip()
                        reason = reason_text[:60]
                    elif lower.startswith("证据"):
                        evidence_text = normalized.split(":", 1)[-1].strip()
                        evidence = evidence_text[:80]
                
                if score_val is None:
                    score_val = 0
                
                score_distribution[score_val] = score_distribution.get(score_val, 0) + 1
                
                results.append(ClarificationResult(
                    req_id=req_id,
                    score=score_val,
                    reason=reason,
                    evidence=evidence or None
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
