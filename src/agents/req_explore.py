"""需求挖掘智能体 (FR-002)"""

from typing import Optional
from openai import OpenAI
from ..config import Config
from ..models.requirement import Requirement, RequirementList
from ..utils.timer import TimerManager
from ..utils.logger import get_logger
from ..utils.streaming import stream_with_continuation
from ..utils.prompt_loader import PromptLoader


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
    ) -> RequirementList:
        """挖掘补充需求"""
        self.timer.start()

        try:
            self.logger.info(f"开始挖掘需求（迭代 {iteration}）")
            self.logger.info(f"用户原始需求长度: {len(raw_input)} 字符")
            self.logger.debug(
                f"用户原始需求预览: {raw_input[:300]}..."
                if len(raw_input) > 300
                else f"用户原始需求: {raw_input}"
            )
            
            if baseline_requirement_structure:
                self.logger.info(f"基准需求语义单元长度: {len(baseline_requirement_structure)} 字符")
                self.logger.debug(
                    f"基准需求语义单元预览: {baseline_requirement_structure[:300]}..."
                    if len(baseline_requirement_structure) > 300
                    else f"基准需求语义单元: {baseline_requirement_structure}"
                )

            # 获取用于探索的现有需求（包含id、score和text，不包含reason - FR-013）
            existing_for_explore = existing_requirements.get_for_explore()

            existing_ids_before = set(
                req.id for req in existing_requirements.requirements
            )
            self.logger.info(f"现有需求数量: {len(existing_requirements.requirements)}")
            if existing_for_explore:
                self.logger.debug("现有需求及其评分:")
                for req_info in existing_for_explore:
                    req_text_preview = (
                        req_info.get("text", "")[:100] + "..."
                        if len(req_info.get("text", "")) > 100
                        else req_info.get("text", "")
                    )
                    self.logger.debug(
                        f"  {req_info['id']}: 评分 {req_info['score']} | 内容预览: {req_text_preview}"
                    )

            # 获取下一个可用ID
            next_id = existing_requirements.get_next_id()

            # 使用参数指定的值，如果未指定则使用配置的默认值
            new_req_count = max_new_requirements_per_iteration if max_new_requirements_per_iteration is not None else Config.NEW_REQUIREMENTS_PER_ITERATION

            self.logger.info(
                f"需要生成新需求数量: {new_req_count} (来源: {'参数指定' if max_new_requirements_per_iteration is not None else f'配置值 NEW_REQUIREMENTS_PER_ITERATION={Config.NEW_REQUIREMENTS_PER_ITERATION}'})"
            )

            # 构建完整需求清单（包含id、评分、需求细节）
            requirements_list = ""
            if existing_for_explore:
                for req_info in existing_for_explore:
                    req_text = req_info.get("text", "")
                    requirements_list += (
                        f"- {req_info['id']}: 评分 {req_info['score']}\n{req_text}\n"
                    )

            # 使用提示词加载器加载并格式化提示词
            prompt = self.prompt_loader.format(
                "req_explore",
                max_new_requirements_count=new_req_count,
                raw_input=raw_input,
                baseline_requirement_structure=baseline_requirement_structure,
                existing_requirements_list=requirements_list,
                next_requirement_id=next_id
            )

            # 记录完整请求内容
            self.logger.debug("完整请求内容:")
            self.logger.debug(f"  User: {prompt}")

            # 始终使用流式响应
            self.logger.info("开始流式生成需求挖掘结果...")

            # 构建消息列表用于续接
            messages = [{"role": "user", "content": prompt}]

            # 构建API调用基础参数
            base_api_params = {
                "model": Config.get_model_req_explore(),
                "temperature": Config.get_temperature_req_explore(),
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
                task_name="需求挖掘",
            )

            # 记录完整响应内容
            if not content:
                self.logger.warning("API响应为空，返回现有需求")
                return existing_requirements

            self.logger.debug("完整响应内容:")
            for line in content.split("\n"):
                self.logger.debug(f"  {line}")

            # 解析输出（支持多行需求描述）
            new_requirements = RequirementList()
            new_requirements.requirements = existing_requirements.requirements.copy()

            added_ids = []
            updated_ids = []
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

            return new_requirements

        except Exception as e:
            self.logger.error(f"挖掘过程中发生错误: {e}", exc_info=True)
            raise

        finally:
            self.timer.stop()
