"""流式响应工具模块：统一处理流式响应和自动续接"""
import sys
from typing import Callable, List, Tuple
from openai import OpenAI

from ..config import Config
from .logger import get_logger

logger = get_logger("Streaming")


def request_stream_completion(client: OpenAI, api_params: dict) -> Tuple[str, str]:
    """处理流式补全请求
    
    Args:
        client: OpenAI客户端实例
        api_params: API调用参数（必须包含 stream=True）
    
    Returns:
        (内容, finish_reason)
    """
    content_parts = []
    finish_reason = "stop"
    stream_response = client.chat.completions.create(**api_params)
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


def stream_with_continuation(
    client: OpenAI,
    base_api_params: dict,
    messages: List[dict],
    task_name: str = "任务",
    continuation_prompt: str = "请继续完成上文未完的内容，保持相同的格式并直接衔接。"
) -> str:
    """统一的流式响应和续接处理
    
    始终使用流式响应，并在检测到 max_tokens 截断时自动续接。
    
    Args:
        client: OpenAI客户端实例
        base_api_params: API调用基础参数（不包含 messages 和 stream）
        messages: 消息列表（会被修改以支持续接）
        task_name: 任务名称（用于日志）
        continuation_prompt: 续接提示词
    
    Returns:
        完整的内容字符串
    """
    content_parts = []
    auto_continue_attempts = 0
    max_auto_continue = Config.MAX_CONTINUATIONS
    
    while True:
        api_params = dict(base_api_params)
        api_params["messages"] = messages
        api_params["stream"] = True
        
        try:
            content, finish_reason = request_stream_completion(client, api_params)
        except Exception as e:
            logger.error(f"{task_name} 流式生成过程中出错: {e}")
            raise
        
        if content:
            content_parts.append(content)
        
        if finish_reason != "length":
            break
        
        # 流式响应的续接逻辑
        auto_continue_attempts += 1
        if auto_continue_attempts >= max_auto_continue:
            logger.warning(f"{task_name} 检测到连续截断且达到自动续接次数上限（{max_auto_continue}），停止继续请求。")
            break
        
        logger.info(f"{task_name} 检测到输出因达到最大token限制被截断，自动续接（{auto_continue_attempts}/{max_auto_continue}）...")
        if content:
            messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": continuation_prompt})
    
    return "".join(content_parts)

