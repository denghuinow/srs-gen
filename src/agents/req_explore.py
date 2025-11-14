"""需求挖掘智能体 (FR-002)"""
from typing import List, Optional
from openai import OpenAI
from ..config import Config
from ..models.requirement import Requirement, RequirementList
from ..utils.timer import TimerManager
from ..utils.forbidden_list import ForbiddenList
from ..utils.logger import get_logger


class ReqExploreAgent:
    """需求挖掘智能体：采用裂变式挖掘，迭代次数=树的深度"""
    
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
        ablation_mode: str = "default"
    ) -> RequirementList:
        """裂变式需求挖掘"""
        self.timer.start()
        
        try:
            self.logger.info(f"开始裂变式挖掘（深度 {iteration}）")
            
            # no-explore-clarify 模式：直接返回空列表
            if ablation_mode == "no-explore-clarify":
                self.logger.info("no-explore-clarify 模式，跳过挖掘")
                return RequirementList()
            
            # 深度1（iteration=0）：从原始输入提取种子并裂变
            if iteration == 0:
                seeds = self.extract_seeds(raw_input)
                self.logger.info(f"提取到 {len(seeds)} 个需求种子")
                
                # 对每个种子进行第一层裂变
                new_requirements = RequirementList()
                next_id = "REQ-001"
                
                for seed_text in seeds:
                    seed_req = Requirement(
                        id=next_id,
                        text=seed_text,
                        iteration=0,
                        parent_id=None
                    )
                    
                    # 先添加种子本身
                    if not forbidden_list.is_forbidden(seed_req):
                        new_requirements.add(seed_req)
                        next_id = new_requirements.get_next_id()
                    
                    # 对种子进行裂变（子需求的 iteration 应该是 1）
                    fissioned = self.fission_from_seed(
                        raw_input=raw_input,
                        seed=seed_req,
                        existing_requirements=new_requirements,
                        forbidden_list=forbidden_list,
                        iteration=1  # 子需求是第一层裂变的结果，iteration=1
                    )
                    
                    # 添加裂变出的子需求
                    for child_req in fissioned:
                        if not forbidden_list.is_forbidden(child_req):
                            new_requirements.add(child_req)
                            next_id = new_requirements.get_next_id()
                
                return new_requirements
            
            # 深度2+（iteration>0）：对上一层的叶子节点进行裂变
            else:
                return self.fission_explore(
                    raw_input=raw_input,
                    existing_requirements=existing_requirements,
                    forbidden_list=forbidden_list,
                    iteration=iteration,
                    ablation_mode=ablation_mode
                )
        
        except Exception as e:
            self.logger.error(f"裂变挖掘过程中发生错误: {e}", exc_info=True)
            raise
        
        finally:
            self.timer.stop()
    
    def extract_seeds(self, raw_input: str) -> List[str]:
        """从原始输入中提取需求种子（深度0 → 深度1）"""
        self.logger.info("开始提取需求种子")
        
        system_message = "你是一个专业的需求分析师，擅长从自然语言需求中提取核心功能点。"
        prompt = f"""请从以下原始需求中提取3-10个核心需求种子（主要功能点）。

要求：
1. 不过度过滤，保留上下文和关联信息
2. 每个种子应该是一个独立的功能点
3. 保留疑问句和主观表述中的有用信息（转换为功能需求）
4. 不要过度简化，保持需求的完整性

原始需求：
{raw_input}

请直接输出需求种子列表，每行一个种子，不要添加编号或其他格式。"""
        
        response = self.client.chat.completions.create(
            model=Config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        
        content = response.choices[0].message.content
        if not content:
            self.logger.warning("种子提取响应为空")
            return []
        
        # 解析输出
        seeds = [
            line.strip()
            for line in content.split("\n")
            if line.strip() and not line.strip().startswith("#")
        ]
        
        self.logger.info(f"提取完成，获得 {len(seeds)} 个种子")
        return seeds
    
    def fission_explore(
        self,
        raw_input: str,
        existing_requirements: RequirementList,
        forbidden_list: ForbiddenList,
        iteration: int,
        ablation_mode: str = "default"
    ) -> RequirementList:
        """递归裂变挖掘（深度2+）"""
        self.logger.info(f"开始递归裂变（深度 {iteration}）")
        
        # 获取上一层的叶子节点（可以继续裂变的需求）
        # iteration=1 时，查找 iteration=1 的叶子节点（第一层裂变的子需求）
        # iteration=2 时，查找 iteration=2 的叶子节点（第二层裂变的子需求）
        # 所以应该查找 iteration-1 层的叶子节点
        prev_iteration = iteration - 1
        leaf_reqs = existing_requirements.get_leaf_requirements(prev_iteration)
        
        # 根据评分筛选可以裂变的需求
        if ablation_mode == "no-clarify":
            # no-clarify 模式：所有需求都可以裂变（默认评分0）
            seeds_for_fission = leaf_reqs
        else:
            # default 模式：只对评分≥1的需求进行裂变
            seeds_for_fission = [
                req for req in leaf_reqs
                if req.score is not None and req.score >= 1
            ]
            
            # 需要改进的需求（评分<1）：先改进，不裂变
            needs_improvement = [
                req for req in leaf_reqs
                if req.score is not None and req.score < 1
            ]
            
            if needs_improvement:
                self.logger.info(f"发现 {len(needs_improvement)} 个需要改进的需求，将先改进而非裂变")
        
        if not seeds_for_fission:
            self.logger.info("没有可裂变的需求种子")
            return existing_requirements
        
        self.logger.info(f"找到 {len(seeds_for_fission)} 个可裂变的需求种子")
        
        # 对每个种子进行裂变
        new_requirements = RequirementList()
        new_requirements.requirements = existing_requirements.requirements.copy()
        
        for seed in seeds_for_fission:
            # 对种子进行裂变
            fissioned = self.fission_from_seed(
                raw_input=raw_input,
                seed=seed,
                existing_requirements=new_requirements,
                forbidden_list=forbidden_list,
                iteration=iteration
            )
            
            # 添加裂变出的子需求
            for child_req in fissioned:
                if not forbidden_list.is_forbidden(child_req):
                    new_requirements.add(child_req)
        
        # 改进评分<1的需求（如果有）
        if ablation_mode != "no-clarify" and needs_improvement:
            improved = self.improve_requirements(
                raw_input=raw_input,
                requirements_to_improve=needs_improvement,
                existing_requirements=new_requirements,
                forbidden_list=forbidden_list,
                iteration=iteration
            )
            
            # 更新改进后的需求
            for improved_req in improved:
                # 移除旧需求，添加改进后的需求
                new_requirements.requirements = [
                    req for req in new_requirements.requirements
                    if req.id != improved_req.id
                ]
                new_requirements.add(improved_req)
        
        return new_requirements
    
    def fission_from_seed(
        self,
        raw_input: str,
        seed: Requirement,
        existing_requirements: RequirementList,
        forbidden_list: ForbiddenList,
        iteration: int
    ) -> List[Requirement]:
        """从单个种子裂变出多个子需求"""
        self.logger.debug(f"从种子 {seed.id} 进行裂变")
        
        # 获取祖先需求（用于上下文）
        ancestors = existing_requirements.get_ancestors(seed.id)
        ancestor_context = ""
        if ancestors:
            ancestor_context = "\n**祖先需求（上下文）：**\n"
            for ancestor in ancestors:
                ancestor_context += f"- {ancestor.id}: {ancestor.text[:200]}...\n"
        
        # 获取父需求信息
        parent_context = f"\n**父需求（当前种子）：**\n"
        parent_context += f"- {seed.id}: {seed.text}\n"
        if seed.score is not None:
            parent_context += f"  评分: {seed.score}\n"
        
        # 获取现有需求信息（用于避免重复）
        existing_ids = {req.id for req in existing_requirements.requirements}
        next_id = existing_requirements.get_next_id()
        
        # 构建提示词
        system_message = "你是一个专业的需求分析师，擅长从需求种子中深度挖掘相关需求。"
        prompt = f"""基于以下原始需求和父需求，进行深度裂变挖掘。

**原始用户需求（全局上下文）：**
{raw_input}

{ancestor_context}
{parent_context}

**任务：**
从父需求中裂变出3-8个相关子需求，包括：
1. 正常路径需求
2. 异常路径需求
3. 权限控制需求
4. 数据验证需求
5. 边界条件需求
6. 子功能需求

**重要说明：**
- 当前最大需求ID为：{existing_requirements.requirements[-1].id if existing_requirements.requirements else "REQ-000"}
- 新需求必须从 {next_id} 开始，不得重复使用现有ID
- 每个子需求的 parent_id 应为 {seed.id}
- 每个子需求的 iteration 应为 {iteration}

**要求：**
1. 使用业务语言表述
2. 每个需求条目必须包含详细的功能规格说明，包括：
   - 功能描述：清晰说明该需求要实现的功能
   - 使用场景：描述在什么情况下使用该功能
   - 用户交互流程：说明用户如何操作，系统如何响应
   - 前置条件：执行该功能前需要满足的条件
   - 后置条件：执行该功能后系统应达到的状态
   - 输入输出：说明需要输入的数据和系统输出的结果
3. 输出格式：每个需求以 "REQ-XXX:" 开头，后跟详细描述（可以跨多行），使用Markdown格式组织内容
4. 每个需求之间用 "---" 分隔符明确分隔

请输出裂变出的子需求列表。"""
        
        response = self.client.chat.completions.create(
            model=Config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        
        content = response.choices[0].message.content
        if not content:
            self.logger.warning(f"种子 {seed.id} 裂变响应为空")
            return []
        
        # 解析输出
        child_requirements = []
        lines = content.split("\n")
        i = 0
        current_req_id = None
        current_req_text_lines = []
        
        while i < len(lines):
            line = lines[i].strip()
            
            # 检查是否是需求分隔符 "---"
            if line == "---" or line.startswith("---"):
                if current_req_id and current_req_text_lines:
                    req_text = "\n".join(current_req_text_lines).strip()
                    if req_text:
                        req = Requirement(
                            id=current_req_id,
                            text=req_text,
                            iteration=iteration,
                            parent_id=seed.id
                        )
                        child_requirements.append(req)
                    
                    current_req_id = None
                    current_req_text_lines = []
                i += 1
                continue
            
            # 跳过空行
            if not line:
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
                
                if req_id.startswith("REQ-"):
                    # 保存之前的需求
                    if current_req_id and current_req_text_lines:
                        req_text = "\n".join(current_req_text_lines).strip()
                        if req_text:
                            req = Requirement(
                                id=current_req_id,
                                text=req_text,
                                iteration=iteration,
                                parent_id=seed.id
                            )
                            child_requirements.append(req)
                    
                    # 开始新的需求
                    current_req_id = req_id
                    current_req_text_lines = []
                    if len(parts) > 1 and parts[1].strip():
                        current_req_text_lines.append(parts[1].strip())
                else:
                    if current_req_id:
                        current_req_text_lines.append(line)
            
            elif current_req_id:
                current_req_text_lines.append(line)
            
            i += 1
        
        # 处理最后一个需求
        if current_req_id and current_req_text_lines:
            req_text = "\n".join(current_req_text_lines).strip()
            if req_text:
                req = Requirement(
                    id=current_req_id,
                    text=req_text,
                    iteration=iteration,
                    parent_id=seed.id
                )
                child_requirements.append(req)
        
        self.logger.debug(f"从种子 {seed.id} 裂变出 {len(child_requirements)} 个子需求")
        return child_requirements
    
    def improve_requirements(
        self,
        raw_input: str,
        requirements_to_improve: List[Requirement],
        existing_requirements: RequirementList,
        forbidden_list: ForbiddenList,
        iteration: int
    ) -> List[Requirement]:
        """改进评分<1的需求"""
        if not requirements_to_improve:
            return []
        
        self.logger.info(f"开始改进 {len(requirements_to_improve)} 个需求")
        
        improvement_ids = [req.id for req in requirements_to_improve]
        improvement_context = "\n".join([
            f"- {req.id}: {req.text[:200]}... (评分: {req.score})"
            for req in requirements_to_improve
        ])
        
        system_message = "你是一个专业的需求分析师，擅长改进和优化需求。"
        prompt = f"""基于以下原始需求和需要改进的需求，重新生成改进版本。

**原始用户需求（全局上下文）：**
{raw_input}

**需要改进的需求（评分<1）：**
{improvement_context}

**要求：**
1. 分析为什么评分低（可能与用户期望不一致、描述不清晰、缺少关键细节等）
2. 重新设计需求，使其更符合用户期望
3. 使用相同的需求ID重新生成
4. 保持原有的 parent_id 和 iteration
5. 每个需求条目必须包含详细的功能规格说明

**输出格式：**
每个需求以 "REQ-XXX:" 开头，后跟详细描述，使用 "---" 分隔。

请输出改进后的需求列表。"""
        
        response = self.client.chat.completions.create(
            model=Config.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        
        content = response.choices[0].message.content
        if not content:
            self.logger.warning("需求改进响应为空")
            return requirements_to_improve  # 返回原需求
        
        # 解析输出（类似 fission_from_seed 的解析逻辑）
        improved_requirements = []
        lines = content.split("\n")
        i = 0
        current_req_id = None
        current_req_text_lines = []
        
        while i < len(lines):
            line = lines[i].strip()
            
            if line == "---" or line.startswith("---"):
                if current_req_id and current_req_text_lines:
                    req_text = "\n".join(current_req_text_lines).strip()
                    if req_text:
                        # 查找原需求以保持 parent_id 和 iteration
                        original_req = next(
                            (req for req in requirements_to_improve if req.id == current_req_id),
                            None
                        )
                        if original_req:
                            req = Requirement(
                                id=current_req_id,
                                text=req_text,
                                iteration=original_req.iteration,
                                parent_id=original_req.parent_id
                            )
                            improved_requirements.append(req)
                    
                    current_req_id = None
                    current_req_text_lines = []
                i += 1
                continue
            
            if not line:
                if current_req_id:
                    current_req_text_lines.append("")
                i += 1
                continue
            
            if line.startswith("#"):
                i += 1
                continue
            
            if ":" in line:
                parts = line.split(":", 1)
                req_id = parts[0].strip()
                
                if req_id.startswith("REQ-"):
                    if current_req_id and current_req_text_lines:
                        req_text = "\n".join(current_req_text_lines).strip()
                        if req_text:
                            original_req = next(
                                (req for req in requirements_to_improve if req.id == current_req_id),
                                None
                            )
                            if original_req:
                                req = Requirement(
                                    id=current_req_id,
                                    text=req_text,
                                    iteration=original_req.iteration,
                                    parent_id=original_req.parent_id
                                )
                                improved_requirements.append(req)
                    
                    current_req_id = req_id
                    current_req_text_lines = []
                    if len(parts) > 1 and parts[1].strip():
                        current_req_text_lines.append(parts[1].strip())
                else:
                    if current_req_id:
                        current_req_text_lines.append(line)
            
            elif current_req_id:
                current_req_text_lines.append(line)
            
            i += 1
        
        if current_req_id and current_req_text_lines:
            req_text = "\n".join(current_req_text_lines).strip()
            if req_text:
                original_req = next(
                    (req for req in requirements_to_improve if req.id == current_req_id),
                    None
                )
                if original_req:
                    req = Requirement(
                        id=current_req_id,
                        text=req_text,
                        iteration=original_req.iteration,
                        parent_id=original_req.parent_id
                    )
                    improved_requirements.append(req)
        
        self.logger.info(f"改进完成，生成 {len(improved_requirements)} 个改进后的需求")
        return improved_requirements
