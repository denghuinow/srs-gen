"""需求挖掘智能体 (FR-002)"""

import re
from typing import Optional, Tuple, List
from openai import OpenAI
from ..config import Config
from ..models.requirement import Requirement, RequirementList, ClarificationResult
from ..utils.timer import TimerManager
from ..utils.logger import get_logger
from ..utils.streaming import stream_with_continuation
from ..utils.prompt_loader import PromptLoader
from ..utils.token_counter import count_text_tokens
from ..utils.score_definitions import (
    VALID_SCORES,
    format_score_for_message
)


class ReqExploreAgent:
    """需求挖掘智能体：补充缺口，形成全局需求清单"""

    def __init__(self, client: OpenAI, timer_manager: TimerManager, prompt_version: str = None):
        self.client = client
        self.timer = timer_manager.get_timer("ReqExplore")
        self.logger = get_logger("ReqExplore")
        self.prompt_loader = PromptLoader(
            prompt_version=prompt_version or Config.PROMPT_VERSION
        )

    def explore(
        self,
        raw_input: str,
        existing_requirements: RequirementList,
        iteration: int,
        baseline_requirement_structure: str = "",
        max_new_requirements_per_iteration: Optional[int] = None,
        messages: Optional[List[dict]] = None,
        clarification_results: Optional[List[ClarificationResult]] = None,
    ) -> Tuple[RequirementList, List[dict]]:
        """挖掘补充需求
        
        Args:
            raw_input: 用户原始需求
            existing_requirements: 现有需求清单
            iteration: 迭代轮次
            baseline_requirement_structure: 基准需求语义单元
            max_new_requirements_per_iteration: 每轮迭代需改进需求+新增需求的总数
            messages: 对话历史（如果为None则初始化新的对话）
            clarification_results: 上一轮的评分结果（如果提供则作为用户消息追加）
        
        Returns:
            (RequirementList, List[dict]): 新的需求清单和更新后的对话历史
        """
        self.timer.start()

        try:
            self.logger.info(f"开始挖掘需求（迭代 {iteration}）")
            
            existing_ids_before = set(
                req.id for req in existing_requirements.requirements
            )
            self.logger.info(f"现有需求数量: {len(existing_requirements.requirements)}")

            # 获取下一个可用ID
            next_id = existing_requirements.get_next_id()

            # 使用参数指定的值，如果未指定则使用配置的默认值
            # max_total_req_count 表示每轮迭代需改进需求+新增需求的总数
            max_total_req_count = max_new_requirements_per_iteration if max_new_requirements_per_iteration is not None else Config.NEW_REQUIREMENTS_PER_ITERATION

            self.logger.info(
                f"每轮迭代总数限制: {max_total_req_count} (来源: {'参数指定' if max_new_requirements_per_iteration is not None else f'配置值 NEW_REQUIREMENTS_PER_ITERATION={Config.NEW_REQUIREMENTS_PER_ITERATION}'})"
            )

            # 处理多轮对话逻辑
            if messages is None:
                # 第一次调用：初始化新的对话
                # 第一次调用时没有待改进需求，所以新增需求数 = 总数限制
                new_req_count = max_total_req_count
                self.logger.info("初始化新的对话（第一次调用）")
                self.logger.info(f"待改进需求数: 0, 新增需求数: {new_req_count}")
                # 使用提示词加载器加载并格式化提示词（不包含需求清单）
                prompt = self.prompt_loader.format(
                    "req_explore",
                    max_new_requirements_count=new_req_count,
                    raw_input=raw_input,
                    baseline_requirement_structure=baseline_requirement_structure,
                    next_requirement_id=next_id
                )
                messages = [{"role": "user", "content": prompt}]
                self.logger.debug("完整请求内容:")
                self.logger.debug(f"  User: {prompt}")
            else:
                # 后续调用：使用已有的对话历史
                self.logger.info(f"继续已有对话（对话历史包含 {len(messages)} 条消息）")
                # 如果提供了评分结果，格式化为用户消息并追加
                if clarification_results:
                    # 按分数分组
                    score_groups = {}
                    for result in clarification_results:
                        if result.score not in score_groups:
                            score_groups[result.score] = []
                        score_groups[result.score].append(result.req_id)
                    
                    # 计算待改进需求数（评分 <= 0）
                    needs_improvement_count = sum(
                        len(req_ids) 
                        for score, req_ids in score_groups.items() 
                        if score <= 0
                    )
                    
                    # 根据总数限制和待改进需求数，计算应该生成的新增需求数
                    # 新增需求数 = max(0, 总数限制 - 待改进需求数)
                    new_req_count = max(0, max_total_req_count - needs_improvement_count)
                    
                    self.logger.info(
                        f"待改进需求数: {needs_improvement_count}, "
                        f"总数限制: {max_total_req_count}, "
                        f"新增需求数: {new_req_count}"
                    )
                    
                    # 从提示词文件加载评分消息模板
                    try:
                        score_template = self.prompt_loader.load("score_message_template")
                        # 移除评分描述部分（如果有），只保留模板主体
                        parts = re.split(r'^---\s*$', score_template, flags=re.MULTILINE)
                        score_template = parts[0].strip() if parts else score_template
                    except FileNotFoundError:
                        self.logger.warning("评分消息模板文件不存在，使用默认格式")
                        score_template = None
                    
                    # 构建评分分组内容（只显示分数和需求ID，不显示描述）
                    # 格式：Score: X 后跟逗号分隔的需求ID列表
                    score_groups_lines = []
                    for score in sorted(VALID_SCORES, reverse=True):
                        req_ids = sorted(score_groups.get(score, []))
                        
                        # 只显示有需求的分数情况
                        if req_ids:
                            # 使用逗号分隔的需求ID列表
                            req_ids_str = ", ".join(req_ids)
                            score_groups_lines.append(f"Score: {score}")
                            score_groups_lines.append(req_ids_str)
                            score_groups_lines.append("")  # 添加空行分隔不同分数组
                    score_groups_text = "\n".join(score_groups_lines).strip()
                    
                    # 构建新增需求指令（动态部分）
                    if new_req_count > 0:
                        new_requirements_instruction = f"4. While improving existing requirements, you must generate at least {new_req_count} new requirements (starting from {next_id})"
                    else:
                        self.logger.info(
                            f"待改进需求数 ({needs_improvement_count}) >= 总数限制 ({max_total_req_count})，"
                            f"本次反馈不要求生成新需求，专注于改进现有需求"
                        )
                        new_requirements_instruction = ""
                    
                    # 使用模板填充数据
                    if score_template:
                        score_message = score_template.format(
                            score_groups=score_groups_text,
                            new_requirements_instruction=new_requirements_instruction
                        )
                    else:
                        # 回退到原来的硬编码方式
                        score_message_lines = []
                        score_message_lines.append("Requirement Scoring Results:")
                        score_message_lines.append("")
                        score_message_lines.append(score_groups_text)
                        score_message_lines.append("")
                        score_message_lines.append("Score Legend: 2=Fully compliant, keep unchanged; 1=Generally compliant, keep or polish; 0=Partial coverage, rewrite; -1/-2=Deviation/conflict, redesign and rewrite")
                        score_message_lines.append("Action Required: Score<=0 must rewrite with same ID; Score=1 can keep or optimize with same ID; Score=2 keep unchanged and do not output again")
                        score_message_lines.append("")
                        score_message_lines.append("Task Requirements:")
                        score_message_lines.append("1. For requirements with Score <= 0 (partial coverage, deviation, or conflict), you must regenerate improved versions using the same ID")
                        score_message_lines.append("2. For requirements with Score = 1 (generally compliant), you can keep them unchanged or make minor optimizations using the same ID")
                        score_message_lines.append("3. For requirements with Score = 2 (fully compliant), keep them unchanged and do not output them again")
                        if new_requirements_instruction:
                            score_message_lines.append(new_requirements_instruction)
                        score_message = "\n".join(score_message_lines).strip()
                    messages.append({"role": "user", "content": score_message})
                    self.logger.info(f"追加评分结果消息，包含 {len(clarification_results)} 个需求的评分")
                    self.logger.debug(f"评分消息内容:\n{score_message}")

            # 始终使用流式响应
            self.logger.info("开始流式生成需求挖掘结果...")

            # 构建API调用基础参数
            base_api_params = {
                "model": Config.get_model_req_explore(),
            }
            # 只有当 temperature 配置了值时才添加到参数中
            temperature = Config.get_temperature_req_explore()
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
                task_name="需求挖掘",
            )

            # 记录完整响应内容
            if not content:
                self.logger.warning("API响应为空，返回现有需求")
                return (existing_requirements, messages)
            
            # 将 assistant 的回复追加到对话历史中，以便下次迭代时使用
            messages.append({"role": "assistant", "content": content})

            self.logger.debug("完整响应内容:")
            self.logger.debug(content)

            # 解析输出（支持多行需求描述）
            new_requirements = RequirementList()
            new_requirements.requirements = existing_requirements.requirements.copy()

            added_ids = []
            updated_ids = []
            processed_ids_in_response = set()  # 用于检测响应中的重复ID
            lines = content.split("\n")
            i = 0
            current_req_id = None
            current_req_text_lines = []

            while i < len(lines):
                line = lines[i].strip()

                # 检查是否是需求分隔符 "---"
                if line == "---" or line.startswith("---"):
                    # 如果当前正在收集需求文本，分隔符表示需求结束
                    if current_req_id and current_req_text_lines:
                        # 检测响应中的重复ID（在本次响应中已经出现过的ID）
                        if current_req_id in processed_ids_in_response:
                            self.logger.warning(
                                f"检测到重复的需求ID（在模型响应中重复出现）: {current_req_id}，跳过处理以避免重复"
                            )
                            current_req_id = None
                            current_req_text_lines = []
                            i += 1
                            continue
                        
                        req_text = "\n".join(current_req_text_lines).strip()
                        if req_text:
                            # 检查原需求的score，如果score == 2则保留，否则设为None以便重新评分
                            original_score = None
                            for existing_req in existing_requirements.requirements:
                                if existing_req.id == current_req_id and existing_req.score == 2:
                                    original_score = 2
                                    break
                            
                            req = Requirement(
                                id=current_req_id, text=req_text, iteration=iteration, score=original_score
                            )

                            success, is_update = new_requirements.update_or_add(req)
                            if success:
                                if is_update:
                                    updated_ids.append(current_req_id)
                                else:
                                    added_ids.append(current_req_id)
                                # 记录已处理的需求ID
                                processed_ids_in_response.add(current_req_id)

                        current_req_id = None
                        current_req_text_lines = []
                    i += 1
                    continue

                # 跳过空行（但保留在需求文本中，因为详细内容可能包含空行）
                if not line:
                    # 空行添加到当前需求文本中（用于保持格式）
                    if current_req_id:
                        current_req_text_lines.append("")
                    i += 1
                    continue

                if line.startswith("#"):
                    i += 1
                    continue

                # 检查是否是新的需求ID行 "REQ-XXX:"
                if ":" in line:
                    parts = line.split(":", 1)
                    req_id = parts[0].strip()

                    # 去除Markdown格式标记（**、*、`等），确保能正确识别需求ID
                    req_id_clean = (
                        req_id.replace("**", "")
                        .replace("*", "")
                        .replace("`", "")
                        .strip()
                    )

                    # 验证ID格式（使用清理后的ID）
                    if req_id_clean.startswith("REQ-"):
                        # 使用清理后的ID作为需求ID
                        req_id = req_id_clean
                        
                        # 检测响应中的重复ID（在本次响应中已经出现过的ID）
                        if req_id in processed_ids_in_response:
                            self.logger.warning(
                                f"检测到重复的需求ID（在模型响应中重复出现）: {req_id}，跳过处理以避免重复"
                            )
                            # 跳过这个重复的需求，继续处理下一行
                            current_req_id = None
                            current_req_text_lines = []
                            i += 1
                            continue
                        
                        # 保存之前的需求（如果有）
                        if current_req_id and current_req_text_lines:
                            req_text = "\n".join(current_req_text_lines).strip()
                            if req_text:
                                # 检查原需求的score，如果score == 2则保留，否则设为None以便重新评分
                                original_score = None
                                for existing_req in existing_requirements.requirements:
                                    if existing_req.id == current_req_id and existing_req.score == 2:
                                        original_score = 2
                                        break
                                
                                req = Requirement(
                                    id=current_req_id,
                                    text=req_text,
                                    iteration=iteration,
                                    score=original_score
                                )

                                success, is_update = new_requirements.update_or_add(
                                    req
                                )
                                if success:
                                    if is_update:
                                        updated_ids.append(current_req_id)
                                    else:
                                        added_ids.append(current_req_id)

                        # 开始新的需求
                        current_req_id = req_id
                        current_req_text_lines = []
                        # 添加冒号后的内容（如果有）
                        if len(parts) > 1 and parts[1].strip():
                            current_req_text_lines.append(parts[1].strip())
                    else:
                        # 包含冒号但不是REQ-开头，继续添加到当前需求文本中
                        if current_req_id:
                            current_req_text_lines.append(line)

                # 如果当前正在收集需求文本，将行添加到文本中
                elif current_req_id:
                    current_req_text_lines.append(line)

                i += 1

            # 处理最后一个需求（如果存在）
            if current_req_id and current_req_text_lines:
                # 检测响应中的重复ID（在本次响应中已经出现过的ID）
                if current_req_id in processed_ids_in_response:
                    self.logger.warning(
                        f"检测到重复的需求ID（在模型响应中重复出现）: {current_req_id}，跳过处理以避免重复"
                    )
                else:
                    req_text = "\n".join(current_req_text_lines).strip()
                    if req_text:
                        # 检查原需求的score，如果score == 2则保留，否则设为None以便重新评分
                        original_score = None
                        for existing_req in existing_requirements.requirements:
                            if existing_req.id == current_req_id and existing_req.score == 2:
                                original_score = 2
                                break
                        
                        req = Requirement(
                            id=current_req_id, text=req_text, iteration=iteration, score=original_score
                        )

                        success, is_update = new_requirements.update_or_add(req)
                        if success:
                            if is_update:
                                updated_ids.append(current_req_id)
                            else:
                                added_ids.append(current_req_id)
                            # 记录已处理的需求ID
                            processed_ids_in_response.add(current_req_id)

            existing_ids_after = set(req.id for req in new_requirements.requirements)
            new_ids = existing_ids_after - existing_ids_before

            self.logger.info(
                f"挖掘完成，新增需求数量: {len(added_ids)}, 更新需求数量: {len(updated_ids)}"
            )
            if added_ids:
                self.logger.info(f"新增需求ID: {sorted(added_ids)}")
                req_id_range = (
                    f"{min(added_ids)} - {max(added_ids)}"
                    if len(added_ids) > 1
                    else added_ids[0]
                )
                self.logger.debug(f"新增需求ID范围: {req_id_range}")
            if updated_ids:
                self.logger.info(f"更新需求ID: {sorted(updated_ids)}")

            return (new_requirements, messages)

        except Exception as e:
            self.logger.error(f"挖掘过程中发生错误: {e}", exc_info=True)
            raise

        finally:
            self.timer.stop()
