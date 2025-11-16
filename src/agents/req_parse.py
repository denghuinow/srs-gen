"""需求解析智能体 (FR-001)"""
from openai import OpenAI
from ..config import Config
from ..utils.timer import TimerManager
from ..utils.logger import get_logger


class ReqParseAgent:
    """需求解析智能体：将自然语言需求解析为需求结构"""
    
    def __init__(self, client: OpenAI, timer_manager: TimerManager):
        self.client = client
        self.timer = timer_manager.get_timer("ReqParse")
        self.logger = get_logger("ReqParse")
    
    def parse(self, raw_input: str) -> str:
        """解析自然语言需求为需求结构（Markdown格式）"""
        self.timer.start()
        
        try:
            self.logger.info(f"开始生成需求结构，输入长度: {len(raw_input)} 字符")
            self.logger.debug(f"输入文本摘要: {raw_input[:200]}..." if len(raw_input) > 200 else f"输入文本: {raw_input}")
            
            # 需求结构生成 Prompt（参考 index.html 的 defaultPrompt）
            requirement_structure_prompt_template = """{{CONTENT}}
请按以下设定的需求结构架构师的身份对以上内容执行任务。

# Role: 需求结构架构师

## Profile
- description: 精通信息结构提取与层次关系分析，能够将复杂文本内容转化为清晰、分层的需求结构格式，便于阅读与理解。
- background: 拥有丰富的信息架构设计经验，熟悉多种内容结构优化方法，擅长运用Markdown及视觉元素增强内容表现力。
- personality: 细致严谨，逻辑清晰，注重条理性与用户体验，表达简洁明了。
- expertise: 信息架构设计、内容层次化、结构化表达、Markdown需求结构制作。
- target_audience: 内容编辑人员、文档撰写者、项目管理者、学习者及需要清晰信息结构的用户群体。

## Skills

1. 信息结构设计
   - 层级划分: 根据内容逻辑精准划分多层级结构
   - 关系梳理: 明确主次、分支及关联节点
   - 内容细化: 优化内容条目，细化分点展开
   - 逻辑优化: 保持结构简洁且易读

2. Markdown及可视化表达
   - 需求结构格式制作: 灵活使用#、##、###等级标题表达层次
   - 列表运用: 以条目列表形式呈现节点内容
   - 语言保持: 保持原文语言与用词
   - Emoji增强: 合理使用Emoji增强视觉导向与可读性

3. Rules

1. 基本原则：
   - 原文尊重：所有内容必须保留原文句子，杜绝改写或删减关键内容
   - 结构清晰：层级分明，结构简洁，避免内容堆叠不清晰
   - 语言一致：输出语言应与原文本主要语言保持一致
   - 可视增强：尽量融合Emoji，增强层次感和视觉舒适度


2. 行为准则：
   - 不添不减：不得添加任何解释、观点或额外信息
   - 句式优化：适度调整句式以提升表达通顺度和条理明晰
   - 内容拆分：长句或内容过多时合理拆分并保持逻辑完整
   - 专业严谨：坚持专业风格，避免模糊和歧义表述


3. 限制条件：
   - 不允许自创内容：不加入个人见解或未出现的信息
   - 禁止格式错误：排版清晰，禁止Markdown语法错误
   - 中心主题限制：中心主题字数限制10个字左右
   - 层级限制：最少3级，层级数可根据内容合理扩展无上限

## Workflows

- 目标: 将原始文本内容转化为清晰分层的需求结构Markdown格式，便于直接阅读和内容解析
- 步骤 1: 彻底阅读并理解原始内容，分析其内在逻辑和层级关系
- 步骤 2: 按照层级使用#标题标记，条目采用列表形式排列，确保不少于三级层级
- 步骤 3: 对长句进行分点拆解，调整句式增强表述清晰度，并合适插入Emoji提升视觉效果
- 步骤 4: 最终输出为纯Markdown格式，只输出 Markdown文本本体，不要使用代码块包裹。
- 预期结果: 输出符合规范的Markdown格式需求结构文本，层级明晰，内容完整，语言统一，无任何附加解释或内容

## Initialization
作为需求结构架构师，你必须遵守上述Rules，按照Workflows执行任务。"""
            
            # 替换占位符
            prompt = requirement_structure_prompt_template.replace("{{CONTENT}}", raw_input)
            
            system_message = "你是一个专业的需求分析师和需求结构架构师，擅长将自然语言需求转化为清晰的需求结构。"
            
            # 记录API调用参数
            api_params = {
                "model": Config.OPENAI_MODEL,
                "temperature": 0.6
            }
            self.logger.debug(f"API调用参数: {api_params}")
            
            # 记录完整请求内容
            self.logger.debug("完整请求内容:")
            self.logger.debug(f"  System: {system_message}")
            self.logger.debug(f"  User: {prompt[:500]}..." if len(prompt) > 500 else f"  User: {prompt}")
            
            response = self.client.chat.completions.create(
                model=Config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.6,
                max_tokens=2000
            )
            
            # 记录完整响应内容
            content = response.choices[0].message.content
            if content:
                self.logger.debug("完整响应内容（前500字符）:")
                preview = content[:500] + "..." if len(content) > 500 else content
                for line in preview.split("\n")[:20]:  # 只记录前20行
                    self.logger.debug(f"  {line}")
                
                # 记录Token使用情况（如果可用）
                if hasattr(response, 'usage') and response.usage:
                    usage = response.usage
                    self.logger.debug(f"Token使用情况: prompt_tokens={usage.prompt_tokens}, completion_tokens={usage.completion_tokens}, total_tokens={usage.total_tokens}")
                
                # 清理可能的代码块包裹
                requirement_structure = content.strip()
                if requirement_structure.startswith("```"):
                    # 移除代码块标记
                    lines = requirement_structure.split("\n")
                    # 移除第一行和最后一行（代码块标记）
                    if len(lines) > 2:
                        requirement_structure = "\n".join(lines[1:-1])
                    else:
                        requirement_structure = ""
                
                self.logger.info(f"需求结构生成完成，长度: {len(requirement_structure)} 字符")
                return requirement_structure
            else:
                self.logger.warning("API响应为空")
                return ""
        
        except Exception as e:
            self.logger.error(f"生成需求结构过程中发生错误: {e}", exc_info=True)
            raise
        
        finally:
            self.timer.stop()
