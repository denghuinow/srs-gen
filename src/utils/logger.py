"""日志工具模块"""
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional


class Logger:
    """日志管理器"""
    
    _logger: Optional[logging.Logger] = None
    _log_file_path: Optional[str] = None
    
    @classmethod
    def get_logger(cls, name: str = "SRSGen") -> logging.Logger:
        """获取日志记录器"""
        if cls._logger is None:
            cls._logger = logging.getLogger(name)
            cls._logger.setLevel(logging.DEBUG)
            
            # 避免重复添加处理器
            if cls._logger.handlers:
                return cls._logger
            
            # 创建格式器
            formatter = logging.Formatter(
                '%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            
            # 控制台处理器（INFO级别）
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            cls._logger.addHandler(console_handler)
            
            # 文件处理器（如果已设置日志文件路径）
            if cls._log_file_path:
                cls._add_file_handler(cls._log_file_path, formatter)
        
        return cls._logger
    
    @classmethod
    def set_log_file(cls, log_file_path: str) -> None:
        """设置日志文件路径"""
        cls._log_file_path = log_file_path
        
        # 确保目录存在
        log_path = Path(log_file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 如果logger已创建，添加文件处理器
        if cls._logger:
            formatter = logging.Formatter(
                '%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            cls._add_file_handler(log_file_path, formatter)
    
    @classmethod
    def _add_file_handler(cls, log_file_path: str, formatter: logging.Formatter) -> None:
        """添加文件处理器"""
        file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)  # 文件记录所有级别
        file_handler.setFormatter(formatter)
        cls._logger.addHandler(file_handler)
    
    @classmethod
    def create_log_filename(cls, output_dir: str, prefix: str = "srs_gen") -> str:
        """创建日志文件名"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"{prefix}_{timestamp}.log"
        return str(Path(output_dir) / log_filename)


def get_logger(name: str = "SRSGen") -> logging.Logger:
    """获取日志记录器的便捷函数"""
    return Logger.get_logger(name)

