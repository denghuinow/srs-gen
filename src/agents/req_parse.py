"""需求解析智能体 (FR-001)"""

from openai import OpenAI
from ..config import Config
from ..utils.timer import TimerManager
from ..utils.logger import get_logger
from ..utils.streaming import stream_with_continuation
from ..utils.prompt_loader import PromptLoader
from ..utils.token_counter import count_text_tokens


class ReqParseAgent:
    """需求解析智能体：将自然语言需求解析为需求语义单元"""

    def __init__(self, client: OpenAI, timer_manager: TimerManager, prompt_version: str = None):
        self.client = client
        self.timer = timer_manager.get_timer("ReqParse")
        self.logger = get_logger("ReqParse")
        self.prompt_loader = PromptLoader(
            prompt_version=prompt_version or Config.PROMPT_VERSION
        )

    def parse(self, raw_input: str, input_type: str = "用户需求") -> str:
        """解析自然语言需求为需求语义单元（Markdown格式）
        
        Args:
            raw_input: 要解析的输入文本
            input_type: 输入类型标识，用于日志记录（默认："用户需求"）
        """
        self.timer.start()

        try:
            raw_input_tokens = count_text_tokens(raw_input)
            raw_input_token_str = f"{raw_input_tokens} tokens" if raw_input_tokens is not None else f"{len(raw_input)} 字符"
            self.logger.info(f"开始生成需求语义单元（{input_type}），输入长度: {raw_input_token_str}")
            self.logger.debug("输入文本:")
            self.logger.debug(raw_input)

            # 使用提示词加载器加载并格式化提示词
            # 注意：虽然方法参数名是 raw_input，但实际来源是命令行参数 --baseline-gend-srs
            # 因此提示词模板变量名使用 baseline_gend_srs 以保持与命令行参数名一致
            prompt = self.prompt_loader.format(
                "req_parse",
                baseline_gend_srs=raw_input
            )

            # 记录完整请求内容
            self.logger.debug("完整请求内容:")
            self.logger.debug(f"  User: {prompt}")

            # 始终使用流式响应
            self.logger.info("开始流式生成需求语义单元...")

            # 构建消息列表用于续接
            messages = [{"role": "user", "content": prompt}]

            # 构建API调用基础参数
            base_api_params = {
                "model": Config.get_model_req_parse(),
            }
            # 只有当 temperature 配置了值时才添加到参数中
            temperature = Config.get_temperature_req_parse()
            if temperature is not None:
                base_api_params["temperature"] = temperature
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
                task_name="需求语义单元解析",
            )

            # 记录完整响应内容
            if content:
                self.logger.debug("完整响应内容:")
                self.logger.debug(content)

                # 清理可能的代码块包裹
                requirement_semantic_unit = content.strip()
                if requirement_semantic_unit.startswith("```"):
                    # 移除代码块标记
                    lines = requirement_semantic_unit.split("\n")
                    # 移除第一行和最后一行（代码块标记）
                    if len(lines) > 2:
                        requirement_semantic_unit = "\n".join(lines[1:-1])
                    else:
                        requirement_semantic_unit = ""

                requirement_tokens = count_text_tokens(requirement_semantic_unit)
                requirement_token_str = f"{requirement_tokens} tokens" if requirement_tokens is not None else f"{len(requirement_semantic_unit)} 字符"
                self.logger.info(
                    f"需求语义单元生成完成，长度: {requirement_token_str}"
                )
                return requirement_semantic_unit
            else:
                self.logger.warning("API响应为空")
                return ""

        except Exception as e:
            self.logger.error(f"生成需求语义单元过程中发生错误: {e}", exc_info=True)
            raise

        finally:
            self.timer.stop()
