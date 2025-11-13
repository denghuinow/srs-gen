"""需求挖掘智能体 (FR-002)"""
from typing import List, Dict
from openai import OpenAI
from ..config import Config
from ..models.requirement import Requirement, RequirementList
from ..utils.timer import TimerManager
from ..utils.forbidden_list import ForbiddenList
from ..utils.logger import get_logger


class ReqExploreAgent:
    """需求挖掘智能体：补充缺口，形成全局需求清单"""
    
    def __init__(self, client: OpenAI, timer_manager: TimerManager):
        self.client = client
        self.timer = timer_manager.get_timer("ReqExplore")
        self.logger = get_logger("ReqExplore")
    
    def explore(
        self,
        atomic_requirements: List[str],
        existing_requirements: RequirementList,
        forbidden_list: ForbiddenList,
        iteration: int
    ) -> RequirementList:
        """挖掘补充需求"""
        self.timer.start()
        
        try:
            self.logger.info(f"开始挖掘需求（迭代 {iteration}）")
            self.logger.info(f"原子需求数量: {len(atomic_requirements)}")
            self.logger.debug(f"原子需求列表: {atomic_requirements}")
            
            # 获取用于探索的现有需求（仅id和score，不包含reason - FR-013）
            existing_for_explore = existing_requirements.get_for_explore()
            
            existing_ids_before = set(req.id for req in existing_requirements.requirements)
            self.logger.info(f"现有需求数量: {len(existing_requirements.requirements)}")
            if existing_for_explore:
                self.logger.debug("现有需求及其评分:")
                for req_info in existing_for_explore:
                    self.logger.debug(f"  {req_info['id']}: 评分 {req_info['score']}")
            
            if forbidden_list.forbidden_ids:
                self.logger.info(f"禁用需求ID数量: {len(forbidden_list.forbidden_ids)}")
                self.logger.debug(f"禁用需求ID列表: {forbidden_list.forbidden_ids}")
            
            # 获取当前最大需求ID和下一个可用ID
            next_id = existing_requirements.get_next_id()
            max_id = existing_requirements.requirements[-1].id if existing_requirements.requirements else "REQ-000"
            
            # 统计需要改进的需求（评分<1）
            needs_improvement = [req_info for req_info in existing_for_explore if req_info['score'] < 1]
            
            # 构建提示词
            existing_context = ""
            if existing_for_explore:
                existing_context = "\n现有需求及其评分：\n"
                for req_info in existing_for_explore:
                    score_desc = ""
                    if req_info['score'] < 1:
                        score_desc = " ⚠️需要改进"
                    existing_context += f"- {req_info['id']}: 评分 {req_info['score']}{score_desc}\n"
            
            forbidden_context = ""
            if forbidden_list.forbidden_ids:
                forbidden_context = f"\n禁用需求ID（不得复用）：{', '.join(forbidden_list.forbidden_ids)}\n"
            
            improvement_context = ""
            if needs_improvement:
                improvement_ids = [req['id'] for req in needs_improvement]
                improvement_context = f"\n**需要改进的需求（评分<1）：**\n"
                improvement_context += f"以下需求评分低于1分，必须重新生成改进版本，使用相同的ID：{', '.join(improvement_ids)}\n"
                improvement_context += "请分析评分低的原因（评分是用户反馈），重新设计使其更符合用户期望。\n"
            
            system_message = "你是一个专业的需求分析师，擅长挖掘和补充系统需求，并能生成详细的功能规格说明。"
            prompt = f"""基于以下原子需求和现有需求评分，完成两个任务：
1. **改进现有需求**：对于评分<1的需求，必须重新生成改进版本，使用相同的ID
2. **补充新需求**：挖掘异常路径、权限控制、数据完整性等隐含需求，补充缺口

原子需求：
{chr(10).join(f"- {req}" for req in atomic_requirements)}
{existing_context}
{improvement_context}
{forbidden_context}

**重要说明：**
- 当前最大需求ID为：{max_id}
- 新需求必须从 {next_id} 开始，不得重复使用现有ID（REQ-001 到 {max_id}）
- **对于评分<1的现有需求，必须重新生成改进版本，使用相同的ID**
- 对于评分≥1的现有需求，可以保持不变或轻微优化，使用相同的ID
- 只生成新需求时，必须使用新的ID（从 {next_id} 开始）

要求：
1. 使用业务语言表述
2. **重点关注改进评分<1的需求**：
   - 分析为什么评分低（评分是用户反馈，可能与用户期望不一致、描述不清晰、缺少关键细节等）
   - 重新设计需求，使其更符合用户期望
   - 使用相同的需求ID重新生成
3. 补充异常处理、权限控制、数据验证等隐含需求
4. 避免生成与禁用清单相似的需求
5. 每个需求条目必须包含详细的功能规格说明，包括：
   - 功能描述：清晰说明该需求要实现的功能
   - 使用场景：描述在什么情况下使用该功能
   - 用户交互流程：说明用户如何操作，系统如何响应
   - 前置条件：执行该功能前需要满足的条件
   - 后置条件：执行该功能后系统应达到的状态
   - 输入输出：说明需要输入的数据和系统输出的结果
6. 输出格式：每个需求以 "REQ-XXX:" 开头，后跟详细描述（可以跨多行），使用Markdown格式组织内容
7. 每个需求之间用 "---" 分隔符明确分隔（在需求详细内容结束后，下一个REQ-XXX之前添加 "---"）

请输出完整的需求清单，包括：
- **改进后的现有需求**（评分<1的必须改进，使用原ID；评分≥1的可保持不变或优化，使用原ID）
- **新增的补充需求**（使用新ID，从 {next_id} 开始）
每个需求都要包含上述详细说明。"""
            
            # 记录API调用参数
            api_params = {
                "model": Config.OPENAI_MODEL,
                "temperature": 0.7
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
                temperature=0.7
            )
            
            # 记录完整响应内容
            content = response.choices[0].message.content
            if not content:
                self.logger.warning("API响应为空，返回现有需求")
                return existing_requirements
            
            self.logger.debug("完整响应内容:")
            for line in content.split("\n"):
                self.logger.debug(f"  {line}")
            
            # 记录Token使用情况（如果可用）
            if hasattr(response, 'usage') and response.usage:
                usage = response.usage
                self.logger.debug(f"Token使用情况: prompt_tokens={usage.prompt_tokens}, completion_tokens={usage.completion_tokens}, total_tokens={usage.total_tokens}")
            
            # 解析输出（支持多行需求描述）
            new_requirements = RequirementList()
            new_requirements.requirements = existing_requirements.requirements.copy()
            
            added_ids = []
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
                                id=current_req_id,
                                text=req_text,
                                iteration=iteration
                            )
                            
                            # 检查是否被禁用
                            if not forbidden_list.is_forbidden(req):
                                if new_requirements.add(req):
                                    added_ids.append(current_req_id)
                            else:
                                self.logger.debug(f"需求 {current_req_id} 被禁用，已跳过")
                        
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
                    
                    # 验证ID格式
                    if req_id.startswith("REQ-"):
                        # 保存之前的需求（如果有）
                        if current_req_id and current_req_text_lines:
                            req_text = "\n".join(current_req_text_lines).strip()
                            if req_text:
                                req = Requirement(
                                    id=current_req_id,
                                    text=req_text,
                                    iteration=iteration
                                )
                                
                                # 检查是否被禁用
                                if not forbidden_list.is_forbidden(req):
                                    if new_requirements.add(req):
                                        added_ids.append(current_req_id)
                                else:
                                    self.logger.debug(f"需求 {current_req_id} 被禁用，已跳过")
                        
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
                        id=current_req_id,
                        text=req_text,
                        iteration=iteration
                    )
                    
                    # 检查是否被禁用
                    if not forbidden_list.is_forbidden(req):
                        if new_requirements.add(req):
                            added_ids.append(current_req_id)
                    else:
                        self.logger.debug(f"需求 {current_req_id} 被禁用，已跳过")
            
            existing_ids_after = set(req.id for req in new_requirements.requirements)
            new_ids = existing_ids_after - existing_ids_before
            
            self.logger.info(f"挖掘完成，新增需求数量: {len(new_ids)}")
            if new_ids:
                self.logger.info(f"新增需求ID: {sorted(new_ids)}")
                req_id_range = f"{min(new_ids)} - {max(new_ids)}" if len(new_ids) > 1 else list(new_ids)[0]
                self.logger.debug(f"需求ID范围: {req_id_range}")
            
            return new_requirements
        
        except Exception as e:
            self.logger.error(f"挖掘过程中发生错误: {e}", exc_info=True)
            raise
        
        finally:
            self.timer.stop()
    
    def map_atomic_to_requirements(
        self,
        atomic_requirements: List[str],
        iteration: int = 0
    ) -> RequirementList:
        """将原子需求直接映射为REQ-xxx条目（用于no-explore-clarify模式）"""
        self.logger.info(f"使用 no-explore-clarify 模式，直接映射原子需求（迭代 {iteration}）")
        self.logger.debug(f"原子需求数量: {len(atomic_requirements)}")
        
        requirements = RequirementList()
        
        for i, atomic_req in enumerate(atomic_requirements, 1):
            req_id = f"REQ-{i:03d}"
            req = Requirement(
                id=req_id,
                text=atomic_req,
                score=0,  # 默认0分
                iteration=iteration
            )
            if not requirements.add(req):
                self.logger.warning(f"需求 {req_id} 在映射时重复，已跳过")
        
        self.logger.info(f"映射完成，生成需求数量: {len(requirements.requirements)}")
        if requirements.requirements:
            req_ids = [req.id for req in requirements.requirements]
            self.logger.debug(f"生成的需求ID: {req_ids}")
        
        return requirements
