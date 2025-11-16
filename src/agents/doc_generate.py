"""文档生成智能体 (FR-004)"""

import sys
from openai import OpenAI
from ..config import Config
from ..models.requirement import RequirementList
from ..models.srs_template import SRSTemplate
from ..utils.timer import TimerManager
from ..utils.logger import get_logger


class DocGenerateAgent:
    """文档生成智能体：基于清单生成SRS文档"""

    def __init__(self, client: OpenAI, timer_manager: TimerManager):
        self.client = client
        self.timer = timer_manager.get_timer("DocGenerate")
        self.template = SRSTemplate()
        self.logger = get_logger("DocGenerate")

    def generate(
        self,
        requirements: RequirementList,
        project_name: str = "项目",
        raw_input: str = "Not provided.",
        stream: bool = None,
        requirement_structure: str = "",
        ablation_mode: str = "default",
    ) -> str:
        """生成SRS文档
        
        Args:
            requirements: 需求清单
            project_name: 项目名称
            raw_input: 原始输入
            stream: 是否使用流式响应（默认从Config读取）
            requirement_structure: 需求结构（Markdown格式）
            ablation_mode: 消融模式
        
        Returns:
            生成的SRS文档内容
        """
        # 如果未指定stream参数，从配置中读取
        if stream is None:
            stream = Config.STREAM_RESPONSE
        
        self.timer.start()

        try:
            # 使用模板生成基础结构
            doc = self.template.generate(requirements.requirements, project_name)

            # 构建详细的需求清单文本
            # no-explore-clarify模式：直接使用ReqParse的响应（requirement_structure）
            if ablation_mode == "no-explore-clarify" and requirement_structure:
                self.logger.info("no-explore-clarify模式：直接使用ReqParse的响应作为requirements_text")
                requirements_text = requirement_structure
            else:
                requirements_text = "\n\n".join(
                    [f"**{req.id}**\n{req.text}" for req in requirements.requirements]
                )

            context = """
            No relevant examples found.
            """
            # IEEE 830标准的SRS文档风格
            style_profile = """
            Writing Style: Professional\nStructure: IEEE 830\nFormatting: Markdown
            """
            prompt = f"""You are an expert in creating Software Requirements Specification (SRS) documents. 
Generate a comprehensive SRS document based on the following information:

Project Summary: {raw_input}
Requirements: {requirements_text}
Style Profile: {style_profile}
Context Examples: {context}

Ensure the document follows professional SRS standards with proper sections, formatting, and technical accuracy. 
Use markdown formatting with appropriate headers, lists, and code blocks where necessary."""

            # 构建API调用参数
            api_params = {
                "model": Config.OPENAI_MODEL,
                "messages": [
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.0,
                "stream": stream,
            }
            
            # 记录完整请求内容
            self.logger.debug("完整请求内容:")
            self.logger.debug(f"  User: {prompt}")

            # 如果配置了MAX_TOKENS，则添加到参数中
            max_tokens = Config.get_max_tokens()
            if max_tokens is not None:
                api_params["max_tokens"] = max_tokens

            if stream:
                # 流式响应处理
                self.logger.info("开始流式生成SRS文档...")
                content_parts = []
                
                try:
                    stream_response = self.client.chat.completions.create(**api_params)
                    
                    # 实时输出流式内容
                    for chunk in stream_response:
                        if chunk.choices and chunk.choices[0].delta.content:
                            content = chunk.choices[0].delta.content
                            content_parts.append(content)
                            # 实时输出到控制台
                            sys.stdout.write(content)
                            sys.stdout.flush()
                    
                    # 输出换行
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    
                    generated_doc = "".join(content_parts)
                    if generated_doc:
                        self.logger.info(f"流式生成完成，文档长度: {len(generated_doc)} 字符")
                        # 记录完整响应内容
                        self.logger.debug("完整响应内容:")
                        for line in generated_doc.split("\n"):
                            self.logger.debug(f"  {line}")
                        return generated_doc
                except Exception as e:
                    self.logger.error(f"流式生成过程中出错: {e}")
                    # 如果流式失败，回退到非流式
                    self.logger.info("回退到非流式模式...")
                    api_params["stream"] = False
                    response = self.client.chat.completions.create(**api_params)
                    generated_doc = response.choices[0].message.content
                    if generated_doc:
                        # 记录完整响应内容
                        self.logger.debug("完整响应内容:")
                        for line in generated_doc.split("\n"):
                            self.logger.debug(f"  {line}")
                        return generated_doc
            else:
                # 非流式响应（原有逻辑）
                response = self.client.chat.completions.create(**api_params)
                generated_doc = response.choices[0].message.content
                if generated_doc:
                    # 记录完整响应内容
                    self.logger.debug("完整响应内容:")
                    for line in generated_doc.split("\n"):
                        self.logger.debug(f"  {line}")
                    return generated_doc

            return doc

        finally:
            self.timer.stop()
