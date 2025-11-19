"""需求挖掘智能体 (FR-002)"""

from openai import OpenAI
from ..config import Config
from ..models.requirement import Requirement, RequirementList
from ..utils.timer import TimerManager
from ..utils.forbidden_list import ForbiddenList
from ..utils.logger import get_logger
from ..utils.streaming import stream_with_continuation


class ReqExploreAgent:
    """需求挖掘智能体：补充缺口，形成全局需求清单"""

    def __init__(self, client: OpenAI, timer_manager: TimerManager):
        self.client = client
        self.timer = timer_manager.get_timer("ReqExplore")
        self.logger = get_logger("ReqExplore")

    def explore(
        self,
        raw_input: str,
        existing_requirements: RequirementList,
        forbidden_list: ForbiddenList,
        iteration: int,
        baseline_requirement_structure: str = "",
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

            if forbidden_list.forbidden_ids:
                self.logger.info(f"禁用需求ID数量: {len(forbidden_list.forbidden_ids)}")
                self.logger.debug(f"禁用需求ID列表: {forbidden_list.forbidden_ids}")

            # 获取当前最大需求ID和下一个可用ID
            next_id = existing_requirements.get_next_id()
            max_id = (
                existing_requirements.requirements[-1].id
                if existing_requirements.requirements
                else "REQ-000"
            )

            # 统计需要改进的需求（评分<=0）
            needs_improvement = [
                req_info for req_info in existing_for_explore if req_info["score"] is not None and req_info["score"] <= 0
            ]

            # 使用配置的固定值作为新需求数量
            new_req_count = Config.NEW_REQUIREMENTS_PER_ITERATION

            self.logger.info(
                f"需要生成新需求数量: {new_req_count} (配置值: NEW_REQUIREMENTS_PER_ITERATION={Config.NEW_REQUIREMENTS_PER_ITERATION})"
            )

            # 构建完整需求清单（包含id、评分、需求细节）
            requirements_list = ""
            if existing_for_explore:
                for req_info in existing_for_explore:
                    req_text = req_info.get("text", "")
                    requirements_list += (
                        f"- {req_info['id']}: 评分 {req_info['score']}\n{req_text}\n"
                    )

            prompt = f"""你是一个专业的软件工程需求分析师，擅长挖掘和补充系统需求。
基于以下信息完成两个任务：
1. **改进现有需求**：对于评分<=0的需求，必须重新生成改进版本，使用相同的ID
2. **补充新需求**：基于用户原始需求自由挖掘和补充新需求，必须生成至少 {new_req_count} 个新需求

**用户原始需求：**
{raw_input}
{baseline_requirement_structure}

**完整需求清单：**
{requirements_list}

要求：
1. 使用自然流畅的业务语言表述，避免模板化格式
2. 对于评分<=0的现有需求，必须重新生成改进版本，保持使用原ID
3. 对于评分>0的现有需求，可以保持不变或轻微优化，保持使用原ID
4. 新需求必须从 {next_id} 开始，至少生成 {new_req_count} 个
5. 每个需求条目应使用自然语言详细描述，包含功能、场景、操作流程、前置后置条件等信息，但不要使用结构化的分类标签（如"功能描述："、"使用场景："等），而是用流畅的段落形式表述
6. 输出格式：每个需求以 "REQ-XXX:" 开头（不要使用Markdown粗体标记**包裹需求ID），后跟自然流畅的详细描述（可以跨多行）
7. 每个需求之间用 "---" 分隔符明确分隔（在需求详细内容结束后，下一个REQ-XXX之前添加 "---"）

**重要：你只输出新增的需求（使用新ID）和你要改进的需求（使用原ID）**"""

            # 记录完整请求内容
            self.logger.debug("完整请求内容:")
            self.logger.debug(f"  User: {prompt}")

            # 始终使用流式响应
            self.logger.info("开始流式生成需求挖掘结果...")

            # 构建消息列表用于续接
            messages = [{"role": "user", "content": prompt}]

            # 构建API调用基础参数
            base_api_params = {
                "model": Config.OPENAI_MODEL,
                "temperature": 0.7,
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
                            req = Requirement(
                                id=current_req_id, text=req_text, iteration=iteration
                            )

                            # 检查是否被禁用
                            if not forbidden_list.is_forbidden(req):
                                success, is_update = new_requirements.update_or_add(req)
                                if success:
                                    if is_update:
                                        updated_ids.append(current_req_id)
                                    else:
                                        added_ids.append(current_req_id)
                            else:
                                self.logger.debug(
                                    f"需求 {current_req_id} 被禁用，已跳过"
                                )

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
                                req = Requirement(
                                    id=current_req_id,
                                    text=req_text,
                                    iteration=iteration,
                                )

                                # 检查是否被禁用
                                if not forbidden_list.is_forbidden(req):
                                    success, is_update = new_requirements.update_or_add(
                                        req
                                    )
                                    if success:
                                        if is_update:
                                            updated_ids.append(current_req_id)
                                        else:
                                            added_ids.append(current_req_id)
                                else:
                                    self.logger.debug(
                                        f"需求 {current_req_id} 被禁用，已跳过"
                                    )

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
                    req = Requirement(
                        id=current_req_id, text=req_text, iteration=iteration
                    )

                    # 检查是否被禁用
                    if not forbidden_list.is_forbidden(req):
                        success, is_update = new_requirements.update_or_add(req)
                        if success:
                            if is_update:
                                updated_ids.append(current_req_id)
                            else:
                                added_ids.append(current_req_id)
                    else:
                        self.logger.debug(f"需求 {current_req_id} 被禁用，已跳过")

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
