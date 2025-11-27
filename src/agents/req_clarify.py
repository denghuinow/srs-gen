"""需求澄清智能体 (FR-003)"""
import re
import csv
import io
from typing import List
from openai import OpenAI
from ..config import Config
from ..models.requirement import Requirement, RequirementList, ClarificationResult
from ..utils.timer import TimerManager
from ..utils.logger import get_logger
from ..utils.streaming import stream_with_continuation
from ..utils.prompt_loader import PromptLoader
from ..utils.token_counter import count_text_tokens
from ..utils.score_definitions import (
    SCORE_MEANINGS,
    VALID_SCORES,
    format_score_for_log
)


class ReqClarifyAgent:
    """需求澄清智能体：加载基准SRS，进行一致性评分"""
    
    def __init__(self, client: OpenAI, timer_manager: TimerManager, prompt_version: str = None):
        self.client = client
        self.timer = timer_manager.get_timer("ReqClarify")
        self.logger = get_logger("ReqClarify")
        self.prompt_loader = PromptLoader(
            prompt_version=prompt_version or Config.PROMPT_VERSION
        )
    
    def clarify(
        self,
        requirements: RequirementList,
        baseline_srs: str
    ) -> List[ClarificationResult]:
        """对需求清单进行澄清评分，只对新增和修改的需求（score为None）进行评分"""
        self.timer.start()
        
        try:
            # 筛选出需要评分的需求（score为None的，或score < 2的，即新增、修改或需要重新评分的）
            needs_scoring = [req for req in requirements.requirements if req.score is None or (req.score is not None and req.score < 2)]
            already_scored = [req for req in requirements.requirements if req.score is not None and req.score >= 2]
            
            self.logger.info(f"开始澄清评分，总需求数量: {len(requirements.requirements)}")
            self.logger.info(f"  需要评分（新增/修改/小于2分）: {len(needs_scoring)}")
            self.logger.info(f"  已评分且>=2分（跳过）: {len(already_scored)}")
            
            if not needs_scoring:
                self.logger.info("没有需要评分的新增或修改需求，跳过澄清阶段")
                return []
            
            # 记录需要评分的需求ID列表
            req_ids = [req.id for req in needs_scoring]
            self.logger.debug(f"待评分需求ID: {req_ids}")
            
            # 记录基准SRS信息
            baseline_tokens = count_text_tokens(baseline_srs)
            baseline_token_str = f"{baseline_tokens} tokens" if baseline_tokens is not None else f"{len(baseline_srs)} 字符"
            self.logger.info(f"基准SRS长度: {baseline_token_str}")
           
            results = []
            
            # 批量处理以提高效率，只处理需要评分的需求
            requirements_text = "\n".join([
                f"{req.id}: {req.text}"
                for req in needs_scoring
            ])
            
            # 使用提示词加载器加载并格式化提示词
            prompt = self.prompt_loader.format(
                "req_clarify",
                baseline_srs=baseline_srs,
                requirements_list_text=requirements_text
            )
            
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
                "model": Config.get_model_req_clarify(),
            }
            # 只有当 temperature 配置了值时才添加到参数中
            temperature = Config.get_temperature_req_clarify()
            if temperature is not None:
                base_api_params["temperature"] = temperature
            max_tokens = Config.get_max_tokens()
            if max_tokens is not None:
                base_api_params["max_tokens"] = max_tokens
            
            # 使用 extra_body 传递额外参数（用于兼容支持这些参数的其他API）
            base_api_params["extra_body"] = {
                "repetition_penalty": 1.2,
            }
            
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
            self.logger.debug(content)
            
            # 解析 TSV 格式输出（使用统一的评分定义）
            score_distribution = {score: 0 for score in VALID_SCORES}
            
            # 尝试提取 TSV 内容（可能在代码块中）
            tsv_content = content
            # 检查是否在代码块中
            if "```" in content:
                # 尝试提取 ```tsv 或 ``` 代码块中的内容
                tsv_match = re.search(r"```(?:tsv)?\s*\n(.*?)\n```", content, re.DOTALL)
                if tsv_match:
                    tsv_content = tsv_match.group(1)
                else:
                    # 如果没有找到代码块，尝试提取第一个 ``` 到最后一个 ``` 之间的内容
                    parts = content.split("```")
                    if len(parts) >= 3:
                        tsv_content = (parts[1] or "") if (parts[1] and len(parts[1].strip()) > 0) else (parts[2] if len(parts) > 2 and parts[2] else "")
            
            # 清理TSV内容：移除前导空行，确保第一行是表头
            lines = tsv_content.split('\n')
            cleaned_lines = []
            found_header = False
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    # 如果还没找到表头，跳过空行
                    if not found_header:
                        continue
                    # 如果已经找到表头，跳过空行（DictReader会自动处理）
                else:
                    # 检查是否是表头行
                    if not found_header and ('Requirement ID' in stripped or '需求ID' in stripped):
                        found_header = True
                        cleaned_lines.append(line)
                    elif found_header:
                        cleaned_lines.append(line)
            
            if cleaned_lines:
                tsv_content = '\n'.join(cleaned_lines)
            
            # 使用 csv.DictReader 解析 TSV
            try:
                reader = csv.DictReader(io.StringIO(tsv_content), delimiter='\t')
                
                for row in reader:
                    # 支持英文和中文表头
                    req_id = (row.get("Requirement ID") or row.get("需求ID") or "").strip()
                    if not req_id or not req_id.startswith("REQ-"):
                        continue
                    
                    # 获取理由（新格式：Reason）
                    reason = (row.get("Reason") or row.get("理由") or "").strip()[:30]
                    
                    # 解析分数（支持新格式和旧格式）
                    score_str = (row.get("Score") or row.get("评分") or "").strip()
                    score_val = None
                    if score_str:
                        # 移除可能的 + 号并转换为整数
                        score_str_clean = score_str.replace("+", "").strip()
                        try:
                            score_val = int(score_str_clean)
                        except ValueError:
                            self.logger.warning(f"需求 {req_id} 的分数格式无效: {score_str}")
                            score_val = 0
                    else:
                        score_val = 0
                    
                    # 验证并限制分数在有效范围内 (-2 到 +2)
                    if score_val > 2:
                        self.logger.warning(f"需求 {req_id} 的分数 {score_val} 超出上限，限制为 2")
                        score_val = 2
                    elif score_val < -2:
                        self.logger.warning(f"需求 {req_id} 的分数 {score_val} 超出下限，限制为 -2")
                        score_val = -2
                    
                    # 直接使用字典键更新，不需要get方法（因为已经初始化了所有键）
                    score_distribution[score_val] = score_distribution[score_val] + 1
                    
                    results.append(ClarificationResult(
                        req_id=req_id,
                        score=score_val,
                        reason=reason,
                        evidence=None  # 证据已合并到reason中
                    ))
                    
            except Exception as e:
                self.logger.error(f"解析 TSV 格式时出错: {e}")
                self.logger.debug("TSV 内容:")
                self.logger.debug(tsv_content)
                raise
            
            # 记录评分结果统计（使用统一的评分定义）
            self.logger.info("评分结果统计:")
            for score in sorted(VALID_SCORES, reverse=True):
                count = score_distribution[score]
                meaning = SCORE_MEANINGS[score]
                self.logger.info(f"  {format_score_for_log(score)}: {count}")
            
            negative_count = score_distribution[-1] + score_distribution[-2]
            if negative_count > 0:
                self.logger.info(f"负分需求数量: {negative_count}（将在下一轮迭代中改进）")
            
            return results
        
        except Exception as e:
            self.logger.error(f"澄清过程中发生错误: {e}", exc_info=True)
            raise
        
        finally:
            self.timer.stop()
