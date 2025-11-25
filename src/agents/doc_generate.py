"""文档生成智能体 (FR-004)"""

from openai import OpenAI
from ..config import Config
from ..models.requirement import RequirementList
from ..utils.timer import TimerManager
from ..utils.logger import get_logger
from ..utils.streaming import stream_with_continuation
from ..utils.prompt_loader import PromptLoader
from ..utils.token_counter import count_text_tokens


class DocGenerateAgent:
    """文档生成智能体：基于清单生成SRS文档"""

    def __init__(self, client: OpenAI, timer_manager: TimerManager, prompt_version: str = None):
        self.client = client
        self.timer = timer_manager.get_timer("DocGenerate")
        self.logger = get_logger("DocGenerate")
        self.prompt_loader = PromptLoader(
            prompt_version=prompt_version or Config.PROMPT_VERSION
        )

    def generate(
        self,
        requirements: RequirementList,
        project_name: str = "项目",
        raw_input: str = "Not provided.",
        stream: bool = None,
        requirement_structure: str = "",
        ablation_mode: str = "default",
        baseline_requirement_structure: str = "",
    ) -> str:
        """生成SRS文档
        
        Args:
            requirements: 需求清单
            project_name: 项目名称
            raw_input: 原始输入
            stream: 已废弃，始终使用流式响应
            requirement_structure: 需求结构（Markdown格式）
            ablation_mode: 消融模式
            baseline_requirement_structure: 基准需求语义单元（通过ReqParse解析baseline_gend_srs得到）
        
        Returns:
            生成的SRS文档内容
        """
        self.timer.start()

        try:
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
            # 使用提示词加载器加载并格式化提示词
            prompt = self.prompt_loader.format(
                "doc_generate",
                raw_input=raw_input,
                requirements_text=requirements_text,
                style_profile=style_profile,
                context_examples=baseline_requirement_structure if baseline_requirement_structure else context,
            )

            messages = [
                {"role": "user", "content": prompt},
            ]

            # 记录完整请求内容
            self.logger.debug("完整请求内容:")
            self.logger.debug(f"  User: {prompt}")

            # 始终使用流式响应
            self.logger.info("开始流式生成SRS文档...")

            # 构建API调用基础参数
            base_api_params = {
                "model": Config.get_model_doc_generate(),
            }
            # 只有当 temperature 配置了值时才添加到参数中
            temperature = Config.get_temperature_doc_generate()
            if temperature is not None:
                base_api_params["temperature"] = temperature

            # 如果配置了MAX_TOKENS，则添加到参数中
            max_tokens = Config.get_max_tokens()
            if max_tokens is not None:
                base_api_params["max_tokens"] = max_tokens

            # 使用统一的流式响应和续接处理
            # 接续生成不需要提示词，使用对话前缀续写方式
            generated_doc = stream_with_continuation(
                client=self.client,
                base_api_params=base_api_params,
                messages=messages,
                task_name="文档生成"
            )
            if generated_doc:
                doc_tokens = count_text_tokens(generated_doc)
                doc_token_str = f"{doc_tokens} tokens" if doc_tokens is not None else f"{len(generated_doc)} 字符"
                self.logger.info(f"文档生成完成，长度: {doc_token_str}")
                self.logger.debug("完整响应内容:")
                self.logger.debug(generated_doc)
                return generated_doc
            else:
                self.logger.error("LLM返回空内容，无法生成SRS文档")
                raise ValueError("LLM返回空内容，无法生成SRS文档")

        finally:
            self.timer.stop()
