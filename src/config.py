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
