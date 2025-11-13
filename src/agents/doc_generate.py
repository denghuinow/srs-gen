"""文档生成智能体 (FR-004)"""
from openai import OpenAI
from ..config import Config
from ..models.requirement import RequirementList
from ..models.srs_template import SRSTemplate
from ..utils.timer import TimerManager


class DocGenerateAgent:
    """文档生成智能体：基于清单生成SRS文档"""
    
    def __init__(self, client: OpenAI, timer_manager: TimerManager):
        self.client = client
        self.timer = timer_manager.get_timer("DocGenerate")
        self.template = SRSTemplate()
    
    def generate(self, requirements: RequirementList, project_name: str = "项目") -> str:
        """生成SRS文档"""
        self.timer.start()
        
        try:
            # 使用模板生成基础结构
            doc = self.template.generate(requirements.requirements, project_name)
            
            # 构建详细的需求清单文本
            requirements_text = "\n\n".join([
                f"**{req.id}**\n{req.text}"
                for req in requirements.requirements
            ])
            
            prompt = f"""基于以下需求清单，生成完整的IEEE 830标准SRS文档。

需求清单：
{requirements_text}

要求：
1. 严格按照IEEE 830标准格式
2. 仅基于提供的需求清单内容，不引入外部知识或实现细节
3. 需求清单中已经包含了详细的功能规格说明（功能描述、使用场景、用户交互流程、前置/后置条件、输入输出），请充分利用这些详细信息
4. 将相关需求组织到功能模块中（如案件管理、消息交互、检索查询、权限管理、任务管理、数据管理、文件管理等）
5. 每个功能模块先给出概述，再列出详细需求
6. 每个需求条目应保持原有的详细描述，不要简化为简短文本
7. 确保文档结构完整、逻辑清晰
8. 输出Markdown格式

请生成完整的SRS文档。"""
            
            # 构建API调用参数
            api_params = {
                "model": Config.OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": "你是一个专业的文档编写专家，擅长编写符合IEEE 830标准的SRS文档。"},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.0
            }
            
            # 如果配置了MAX_TOKENS，则添加到参数中
            max_tokens = Config.get_max_tokens()
            if max_tokens is not None:
                api_params["max_tokens"] = max_tokens
            
            response = self.client.chat.completions.create(**api_params)
            
            generated_doc = response.choices[0].message.content
            if generated_doc:
                return generated_doc
            
            return doc
        
        finally:
            self.timer.stop()
