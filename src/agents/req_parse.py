"""需求解析智能体 (FR-001)"""

from openai import OpenAI
from ..config import Config
from ..utils.timer import TimerManager
from ..utils.logger import get_logger
from ..utils.streaming import stream_with_continuation


class ReqParseAgent:
    """需求解析智能体：将自然语言需求解析为需求语义单元"""

    def __init__(self, client: OpenAI, timer_manager: TimerManager):
        self.client = client
        self.timer = timer_manager.get_timer("ReqParse")
        self.logger = get_logger("ReqParse")

    def parse(self, raw_input: str, input_type: str = "用户需求") -> str:
        """解析自然语言需求为需求语义单元（Markdown格式）
        
        Args:
            raw_input: 要解析的输入文本
            input_type: 输入类型标识，用于日志记录（默认："用户需求"）
        """
        self.timer.start()

        try:
            self.logger.info(f"开始生成需求语义单元（{input_type}），输入长度: {len(raw_input)} 字符")
            self.logger.debug(
                f"输入文本摘要: {raw_input[:200]}..."
                if len(raw_input) > 200
                else f"输入文本: {raw_input}"
            )

            # 需求语义单元生成 Prompt（参考 index.html 的 defaultPrompt）
            requirement_semantic_unit_prompt_template = """{{CONTENT}}
请根据以上软件需求规格说明书（SRS）文档，识别并提取其中的核心内容：

1. 功能需求：列出所有明确的功能模块及其具体描述，包括输入输出参数、处理逻辑和性能指标
2. 非功能需求：提取所有性能要求、安全要求、可用性要求和可靠性指标，并量化具体数值
3. 约束条件：识别所有技术约束、业务约束和法规约束，包括具体的版本要求、兼容性标准和合规规范
4. 业务规则：提取所有业务逻辑规则、数据验证规则和流程控制规则，明确触发条件和执行结果

要求：
- 每个内容项需包含：类型、描述、优先级、关联关系和验证标准
- 对于模糊的需求描述，需基于行业最佳实践补充具体实现细节和量化指标
- 识别需求间的依赖关系，建立内容项间的关联映射
- 不要使用JSON格式输出结果
- 在输出中避免使用"语义单元"及相关表述
- 直接开始输出提取结果，不要使用"根据提供的软件需求规格说明书（SRS），以下是提取的核心内容，按照要求的结构化文本格式进行组织"等类似的开场白
- 不要使用固定的结构化输出格式，如"名称："、"类型："、"详细描述："等标签化的段落结构，而是采用自然流畅的段落描述方式"""

            # 替换占位符
            prompt = requirement_semantic_unit_prompt_template.replace(
                "{{CONTENT}}", raw_input
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
                "model": Config.OPENAI_MODEL,
                "temperature": 0.6,
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
                task_name="需求语义单元解析",
            )

            # 记录完整响应内容
            if content:
                self.logger.debug("完整响应内容:")
                for line in content.split("\n"):
                    self.logger.debug(f"  {line}")

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

                self.logger.info(
                    f"需求语义单元生成完成，长度: {len(requirement_semantic_unit)} 字符"
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
