"""文档生成智能体 (FR-004)"""

import sys
from typing import Tuple
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
        current_stream = stream
        
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

            messages = [
                {"role": "user", "content": prompt},
            ]

            # 记录完整请求内容
            self.logger.debug("完整请求内容:")
            self.logger.debug(f"  User: {prompt}")

            # 构建API调用基础参数
            base_api_params = {
                "model": Config.OPENAI_MODEL,
                "temperature": 0.0,
            }

            # 如果配置了MAX_TOKENS，则添加到参数中
            max_tokens = Config.get_max_tokens()
            if max_tokens is not None:
                base_api_params["max_tokens"] = max_tokens

            if current_stream:
                self.logger.info("开始流式生成SRS文档...")

            generated_parts = []
            continue_instruction = "请继续完成上文未完的内容，保持相同的章节结构并直接衔接。"
            auto_continue_attempts = 0
            max_auto_continue = 5

            while True:
                api_params = dict(base_api_params)
                api_params["messages"] = messages
                api_params["stream"] = current_stream

                try:
                    content, finish_reason = self._request_completion(api_params, current_stream)
                except Exception as e:
                    if current_stream:
                        self.logger.error(f"流式生成过程中出错: {e}")
                        current_stream = False
                        self.logger.info("回退到非流式模式...")
                        continue
                    raise

                if content:
                    generated_parts.append(content)

                if finish_reason != "length":
                    break

                auto_continue_attempts += 1
                if auto_continue_attempts >= max_auto_continue:
                    self.logger.warning("检测到连续截断且达到自动续接次数上限，停止继续请求。")
                    break

                self.logger.info("检测到输出因达到最大token限制被截断，自动续接...")
                if content:
                    messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": continue_instruction})

            generated_doc = "".join(generated_parts)
            if generated_doc:
                self.logger.info(f"文档生成完成，长度: {len(generated_doc)} 字符")
                self.logger.debug("完整响应内容:")
                for line in generated_doc.split("\n"):
                    self.logger.debug(f"  {line}")
                return generated_doc

            return doc

        finally:
            self.timer.stop()

    def _request_completion(self, api_params: dict, stream: bool) -> Tuple[str, str]:
        """根据stream参数请求补全，并返回内容与结束原因"""
        if stream:
            return self._request_stream_completion(api_params)
        return self._request_non_stream_completion(api_params)

    def _request_stream_completion(self, api_params: dict) -> Tuple[str, str]:
        """处理流式补全请求"""
        content_parts = []
        finish_reason = "stop"
        stream_response = self.client.chat.completions.create(**api_params)
        for chunk in stream_response:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                content_parts.append(content)
                sys.stdout.write(content)
                sys.stdout.flush()
            if chunk.choices and chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

        sys.stdout.write("\n")
        sys.stdout.flush()

        return "".join(content_parts), finish_reason

    def _request_non_stream_completion(self, api_params: dict) -> Tuple[str, str]:
        """处理非流式补全请求"""
        response = self.client.chat.completions.create(**api_params)
        content = response.choices[0].message.content if response.choices else ""
        finish_reason = response.choices[0].finish_reason if response.choices else "stop"
        return content or "", finish_reason or "stop"
