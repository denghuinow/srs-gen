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
        """对需求清单进行澄清评分，只对新增和修改的需求（score为None）进行评分"""
        self.timer.start()
        
        try:
            # 筛选出需要评分的需求（score为None的，即新增或修改的）
            needs_scoring = [req for req in requirements.requirements if req.score is None]
            already_scored = [req for req in requirements.requirements if req.score is not None]
            
            self.logger.info(f"开始澄清评分，总需求数量: {len(requirements.requirements)}")
            self.logger.info(f"  需要评分（新增/修改）: {len(needs_scoring)}")
            self.logger.info(f"  已评分（跳过）: {len(already_scored)}")
            
            if not needs_scoring:
                self.logger.info("没有需要评分的新增或修改需求，跳过澄清阶段")
                return []
            
            # 记录需要评分的需求ID列表
            req_ids = [req.id for req in needs_scoring]
            self.logger.debug(f"待评分需求ID: {req_ids}")
            
            # 记录基准SRS信息
            baseline_len = len(baseline_srs)
            self.logger.info(f"基准SRS长度: {baseline_len} 字符")
           
            results = []
            
            # 批量处理以提高效率，只处理需要评分的需求
            requirements_text = "\n".join([
                f"{req.id}: {req.text}"
                for req in needs_scoring
            ])
            
            prompt = f"""你是“需求验收专家”，站在验收方立场对照基准SRS为需求清单中的每条需求打分，只依赖基准SRS中的明确证据，不猜测范围。

[基准SRS]：
{baseline_srs}

[需求清单]：
{requirements_text}

评分规则：
+2: 高度一致  +1: 基本一致  0: 中性  -1: 轻微冲突  -2: 明确冲突

输出格式（每行一条）：
REQ-XXX | 评分: <score> | 说明: <简短说明30字内，引用基准SRS中的明确证据，指出需求与基准SRS的一致/不一致点，不给建议>

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
                reason_parts = []
                
                for part in parts[1:]:
                    normalized = part.replace("：", ":").strip()
                    lower = normalized.lower()
                    if lower.startswith("评分"):
                        match = re.search(r"[-+]?\d+", normalized)
                        if match:
                            score_val = int(match.group())
                    elif lower.startswith("说明"):
                        # 新格式：直接使用说明
                        reason_text = normalized.split(":", 1)[-1].strip()
                        reason_parts = [reason_text[:30]]
                        break  # 说明字段优先级最高，找到后不再处理其他字段
                    elif lower.startswith("理由") or lower.startswith("证据"):
                        # 兼容旧格式：合并理由和证据
                        reason_text = normalized.split(":", 1)[-1].strip()
                        if reason_text:
                            reason_parts.append(reason_text)
                
                # 合并所有理由和证据部分
                reason = " ".join(reason_parts)[:30] if reason_parts else ""
                
                if score_val is None:
                    score_val = 0
                
                # 验证并限制分数在有效范围内 (-2 到 +2)
                if score_val > 2:
                    self.logger.warning(f"需求 {req_id} 的分数 {score_val} 超出上限，限制为 2")
                    score_val = 2
                elif score_val < -2:
                    self.logger.warning(f"需求 {req_id} 的分数 {score_val} 超出下限，限制为 -2")
                    score_val = -2
                
                score_distribution[score_val] = score_distribution.get(score_val, 0) + 1
                
                results.append(ClarificationResult(
                    req_id=req_id,
                    score=score_val,
                    reason=reason,
                    evidence=None  # 证据已合并到reason中
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
