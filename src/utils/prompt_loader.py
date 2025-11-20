"""提示词加载工具"""
from pathlib import Path
from typing import Optional
from ..utils.logger import get_logger


class PromptLoader:
    """提示词加载器，支持版本管理"""
    
    def __init__(self, prompt_version: str = "v1", prompts_dir: Optional[Path] = None):
        """
        初始化提示词加载器
        
        Args:
            prompt_version: 提示词版本，默认为 "v1"
            prompts_dir: 提示词目录路径，如果为None则使用默认路径
        """
        self.prompt_version = prompt_version
        self.logger = get_logger("PromptLoader")
        
        if prompts_dir is None:
            # 默认路径：项目根目录下的 prompts 目录
            self.prompts_dir = Path(__file__).parent.parent.parent / "prompts"
        else:
            self.prompts_dir = Path(prompts_dir)
        
        if not self.prompts_dir.exists():
            raise FileNotFoundError(f"提示词目录不存在: {self.prompts_dir}")
    
    def load(self, agent_name: str, suffix: str = "") -> str:
        """
        加载指定agent的提示词
        
        Args:
            agent_name: agent名称，如 "req_explore", "req_clarify" 等
            suffix: 文件名后缀，如 "_continuation" 用于续接提示词
        
        Returns:
            提示词内容字符串
        """
        # 构建文件路径：prompts/{version}/{agent_name}{suffix}.md
        # 新结构：版本作为文件夹，文件名区分agent
        prompt_file = self.prompts_dir / self.prompt_version / f"{agent_name}{suffix}.md"
        
        if not prompt_file.exists():
            # 如果指定版本不存在，尝试使用v1作为默认版本
            if self.prompt_version != "v1":
                self.logger.warning(
                    f"提示词文件不存在: {prompt_file}，尝试使用 v1 版本"
                )
                prompt_file = self.prompts_dir / "v1" / f"{agent_name}{suffix}.md"
        
        if not prompt_file.exists():
            raise FileNotFoundError(
                f"提示词文件不存在: {prompt_file}，请检查提示词版本和文件路径"
            )
        
        try:
            with open(prompt_file, "r", encoding="utf-8") as f:
                content = f.read()
            self.logger.debug(f"成功加载提示词: {prompt_file}")
            return content
        except Exception as e:
            self.logger.error(f"加载提示词失败: {prompt_file}, 错误: {e}")
            raise
    
    def format(self, agent_name: str, **kwargs) -> str:
        """
        加载并格式化提示词（使用format方法）
        
        Args:
            agent_name: agent名称
            **kwargs: 格式化参数
        
        Returns:
            格式化后的提示词内容
        """
        template = self.load(agent_name)
        try:
            return template.format(**kwargs)
        except KeyError as e:
            self.logger.error(f"提示词格式化失败，缺少参数: {e}")
            raise
    
    def format_continuation(self, agent_name: str, **kwargs) -> str:
        """
        加载并格式化续接提示词（已废弃）
        
        注意：接续生成已改为使用对话前缀续写方式，不再需要单独的续接提示词。
        此方法保留仅为向后兼容，实际不会被调用。
        
        Args:
            agent_name: agent名称
            **kwargs: 格式化参数
        
        Returns:
            格式化后的续接提示词内容
        """
        import warnings
        warnings.warn(
            "format_continuation 已废弃，接续生成不再需要提示词，使用对话前缀续写方式",
            DeprecationWarning,
            stacklevel=2
        )
        template = self.load(agent_name, suffix="_continuation")
        try:
            return template.format(**kwargs) if kwargs else template
        except KeyError as e:
            self.logger.error(f"续接提示词格式化失败，缺少参数: {e}")
            raise

