"""配置管理"""
import os
from pathlib import Path
from typing import Literal, Optional
from dotenv import load_dotenv

# 加载.env文件
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    # 如果项目根目录没有.env，尝试加载当前目录的.env
    load_dotenv()


AblationMode = Literal["default", "no-clarify", "no-explore-clarify"]


class Config:
    """系统配置"""
    
    # OpenAI API配置
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: Optional[str] = os.getenv("OPENAI_BASE_URL", None)
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    STREAM_RESPONSE: bool = os.getenv("STREAM_RESPONSE", "true").lower() in ("true", "1", "yes")
    
    # 迭代配置
    MAX_ITERATIONS: int = int(os.getenv("MAX_ITERATIONS", "5"))
    CONVERGENCE_THRESHOLD: int = 0  # 收敛阈值：无负分条目
    NEW_REQUIREMENTS_PER_ITERATION: int = int(os.getenv("NEW_REQUIREMENTS_PER_ITERATION", "10"))  # 每次迭代增加的新需求数量

    # 消融模式
    ABLATION_MODE: AblationMode = os.getenv("ABLATION_MODE", "default")  # type: ignore
    
    # 续接配置
    MAX_CONTINUATIONS: int = int(os.getenv("MAX_CONTINUATIONS", "2"))  # 当因max_tokens导致输出被截断时自动请求接续的次数上限
    
    # API重试配置
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "5"))  # API调用最大重试次数
    RETRY_DELAY: float = float(os.getenv("RETRY_DELAY", "8.0"))  # 重试延迟初始值（秒），使用指数退避
    
    # 提示词版本配置
    PROMPT_VERSION: str = os.getenv("PROMPT_VERSION", "v1")  # 提示词版本，默认为v1
    
    # 最大上下文长度配置
    @classmethod
    def get_max_context_length(cls) -> Optional[int]:
        """获取最大上下文长度配置值"""
        max_context_length_str = os.getenv("MAX_CONTEXT_LENGTH")
        if max_context_length_str:
            try:
                return int(max_context_length_str)
            except ValueError:
                return None
        return None
    
    @classmethod
    def get_max_tokens(cls) -> Optional[int]:
        """获取MAX_TOKENS配置值"""
        max_tokens_str = os.getenv("MAX_TOKENS")
        if max_tokens_str:
            try:
                return int(max_tokens_str)
            except ValueError:
                return None
        return None
    
    @classmethod
    def get_temperature_req_parse(cls) -> float:
        """获取需求解析智能体的温度参数"""
        temp_str = os.getenv("TEMPERATURE_REQ_PARSE")
        if temp_str:
            try:
                return float(temp_str)
            except ValueError:
                pass
        return 0.6  # 默认值
    
    @classmethod
    def get_temperature_req_explore(cls) -> float:
        """获取需求挖掘智能体的温度参数"""
        temp_str = os.getenv("TEMPERATURE_REQ_EXPLORE")
        if temp_str:
            try:
                return float(temp_str)
            except ValueError:
                pass
        return 0.7  # 默认值
    
    @classmethod
    def get_temperature_req_clarify(cls) -> float:
        """获取需求澄清智能体的温度参数"""
        temp_str = os.getenv("TEMPERATURE_REQ_CLARIFY")
        if temp_str:
            try:
                return float(temp_str)
            except ValueError:
                pass
        return 0.0  # 默认值
    
    @classmethod
    def get_temperature_doc_generate(cls) -> float:
        """获取文档生成智能体的温度参数"""
        temp_str = os.getenv("TEMPERATURE_DOC_GENERATE")
        if temp_str:
            try:
                return float(temp_str)
            except ValueError:
                pass
        return 0.0  # 默认值
    
    @classmethod
    def get_model_req_parse(cls) -> str:
        """获取需求解析智能体的模型配置"""
        model_str = os.getenv("MODEL_REQ_PARSE")
        if model_str:
            return model_str
        return cls.OPENAI_MODEL  # 默认使用全局模型
    
    @classmethod
    def get_model_req_explore(cls) -> str:
        """获取需求挖掘智能体的模型配置"""
        model_str = os.getenv("MODEL_REQ_EXPLORE")
        if model_str:
            return model_str
        return cls.OPENAI_MODEL  # 默认使用全局模型
    
    @classmethod
    def get_model_req_clarify(cls) -> str:
        """获取需求澄清智能体的模型配置"""
        model_str = os.getenv("MODEL_REQ_CLARIFY")
        if model_str:
            return model_str
        return cls.OPENAI_MODEL  # 默认使用全局模型
    
    @classmethod
    def get_model_doc_generate(cls) -> str:
        """获取文档生成智能体的模型配置"""
        model_str = os.getenv("MODEL_DOC_GENERATE")
        if model_str:
            return model_str
        return cls.OPENAI_MODEL  # 默认使用全局模型
    
    @classmethod
    def validate(cls) -> None:
        """验证配置"""
        if not cls.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY环境变量未设置")
    
    @classmethod
    def get_openai_client_kwargs(cls) -> dict:
        """获取OpenAI客户端初始化参数"""
        kwargs = {"api_key": cls.OPENAI_API_KEY}
        if cls.OPENAI_BASE_URL:
            kwargs["base_url"] = cls.OPENAI_BASE_URL
        return kwargs
