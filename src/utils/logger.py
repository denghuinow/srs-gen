"""日志工具模块"""
import logging
import sys
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional
from logging.handlers import QueueHandler, QueueListener
from queue import Queue


class Logger:
    """日志管理器（线程安全版本）"""
    
    _logger: Optional[logging.Logger] = None
    _log_file_path: Optional[str] = None
    _queue: Optional[Queue] = None
    _listener: Optional[QueueListener] = None
    _lock = threading.Lock()
    
    @classmethod
    def get_logger(cls, name: str = "SRSGen") -> logging.Logger:
        """获取日志记录器（线程安全）"""
        with cls._lock:
            if cls._logger is None:
                cls._logger = logging.getLogger(name)
                cls._logger.setLevel(logging.DEBUG)
                
                # 避免重复添加处理器
                if cls._logger.handlers:
                    return cls._logger
                
                # 创建队列用于线程安全的日志处理
                if cls._queue is None:
                    cls._queue = Queue(-1)  # 无界队列
                
                # 创建格式器
                formatter = logging.Formatter(
                    '%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
                
                # 控制台处理器（INFO级别）
                console_handler = logging.StreamHandler(sys.stdout)
                console_handler.setLevel(logging.INFO)
                console_handler.setFormatter(formatter)
                
                # 文件处理器（如果已设置日志文件路径）
                handlers = [console_handler]
                if cls._log_file_path:
                    file_handler = logging.FileHandler(cls._log_file_path, encoding='utf-8')
                    file_handler.setLevel(logging.DEBUG)
                    file_handler.setFormatter(formatter)
                    handlers.append(file_handler)
                
                # 创建队列监听器，在单独的线程中处理日志
                if cls._listener is None:
                    cls._listener = QueueListener(cls._queue, *handlers, respect_handler_level=True)
                    cls._listener.start()
                
                # 使用QueueHandler包装logger
                queue_handler = QueueHandler(cls._queue)
                queue_handler.setLevel(logging.DEBUG)
                cls._logger.addHandler(queue_handler)
        
        return cls._logger
    
    @classmethod
    def set_log_file(cls, log_file_path: str) -> None:
        """设置日志文件路径"""
        with cls._lock:
            cls._log_file_path = log_file_path
            
            # 确保目录存在
            log_path = Path(log_file_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 如果logger已创建，需要重新创建listener以添加文件处理器
            if cls._logger and cls._listener:
                # 停止旧的listener
                cls._listener.stop()
                
                # 创建格式器
                formatter = logging.Formatter(
                    '%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
                
                # 控制台处理器
                console_handler = logging.StreamHandler(sys.stdout)
                console_handler.setLevel(logging.INFO)
                console_handler.setFormatter(formatter)
                
                # 文件处理器
                file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
                file_handler.setLevel(logging.DEBUG)
                file_handler.setFormatter(formatter)
                
                # 重新创建listener
                cls._listener = QueueListener(cls._queue, console_handler, file_handler, respect_handler_level=True)
                cls._listener.start()
            elif cls._logger and not cls._listener:
                # logger已创建但listener未创建，说明是第一次调用set_log_file
                # 这种情况不应该发生，但为了健壮性还是处理一下
                formatter = logging.Formatter(
                    '%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
                
                # 创建队列（如果还没有）
                if cls._queue is None:
                    cls._queue = Queue(-1)
                
                # 控制台处理器
                console_handler = logging.StreamHandler(sys.stdout)
                console_handler.setLevel(logging.INFO)
                console_handler.setFormatter(formatter)
                
                # 文件处理器
                file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
                file_handler.setLevel(logging.DEBUG)
                file_handler.setFormatter(formatter)
                
                # 创建listener
                cls._listener = QueueListener(cls._queue, console_handler, file_handler, respect_handler_level=True)
                cls._listener.start()
                
                # 如果logger还没有QueueHandler，添加一个
                if not any(isinstance(h, QueueHandler) for h in cls._logger.handlers):
                    queue_handler = QueueHandler(cls._queue)
                    queue_handler.setLevel(logging.DEBUG)
                    cls._logger.addHandler(queue_handler)
    
    @classmethod
    def shutdown(cls) -> None:
        """关闭日志系统，确保所有日志都被写入"""
        with cls._lock:
            if cls._listener:
                cls._listener.stop()
                cls._listener = None
            if cls._queue:
                # 等待队列中的所有日志被处理
                cls._queue.join()
                cls._queue = None
    
    @classmethod
    def create_log_filename(cls, output_dir: str, prefix: str = "srs_gen") -> str:
        """创建日志文件名"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filename = f"{prefix}_{timestamp}.log"
        return str(Path(output_dir) / log_filename)


def get_logger(name: str = "SRSGen") -> logging.Logger:
    """获取日志记录器的便捷函数"""
    return Logger.get_logger(name)

