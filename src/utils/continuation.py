"""续接工具模块：处理因max_tokens导致输出截断时的自动续接"""
import copy
from typing import Optional, Tuple
from openai import OpenAI

from ..config import Config
from .logger import get_logger

logger = get_logger("Continuation")


def continue_on_truncation(
    client: OpenAI,
    api_params: dict,
    accumulated_text: str,
    finish_reason: Optional[str],
    task_name: str = "任务",
) -> Tuple[str, Optional[str]]:
    """
    当模型因为max_tokens截断时自动发送接续请求
    
    使用对话前缀续写方式：将已生成的内容作为 assistant 消息，设置 prefix: True 和 partial: True，
    让模型从该前缀继续生成，避免重复输出表头和上一行。

    Args:
        client: OpenAI客户端实例
        api_params: 首次请求的参数（用于构造后续messages）
        accumulated_text: 当前已生成的文本
        finish_reason: 首次响应的finish_reason
        task_name: 日志中展示的任务名称

    Returns:
        (完整文本, 最终finish_reason)
    """
    if finish_reason != "length":
        return accumulated_text, finish_reason
    
    max_continuations = Config.MAX_CONTINUATIONS
    if max_continuations <= 0:
        logger.warning(f"{task_name} 输出因max_tokens被截断，但未配置接续次数（MAX_CONTINUATIONS={max_continuations}），将直接返回当前结果")
        return accumulated_text, finish_reason
    
    base_messages = api_params.get("messages")
    if not base_messages:
        logger.warning(f"{task_name} 输出被截断，但缺少原始消息上下文，无法自动接续")
        return accumulated_text, finish_reason

    combined_text = accumulated_text
    total_attempts = max_continuations
    attempt = 0

    while finish_reason == "length" and attempt < total_attempts:
        attempt += 1
        logger.info(f"{task_name} 响应达到 max_tokens，自动发送第 {attempt}/{total_attempts} 次接续请求...")
        
        # 使用对话前缀续写：更新最后一个 assistant 消息，而不是追加新消息
        continuation_messages = copy.deepcopy(base_messages)
        # 如果最后一个消息是 assistant 消息，更新它；否则追加新的
        if continuation_messages and continuation_messages[-1].get("role") == "assistant":
            continuation_messages[-1] = {
                "role": "assistant",
                "content": combined_text,
                "prefix": True,
                "partial": True
            }
        else:
            continuation_messages.append({
                "role": "assistant",
                "content": combined_text,
                "prefix": True,
                "partial": True
            })

        continuation_params = {
            k: v for k, v in api_params.items() if k != "messages"
        }
        continuation_params["messages"] = continuation_messages

        try:
            response = client.chat.completions.create(**continuation_params)
        except Exception as e:
            logger.error(f"{task_name} 接续请求 #{attempt} 失败: {e}", exc_info=True)
            break

        if not response or not response.choices:
            logger.warning(f"{task_name} 接续请求返回无效响应，停止继续尝试")
            break

        if hasattr(response, "usage") and response.usage:
            usage = response.usage
            logger.debug(
                f"{task_name} 接续 Token使用 - prompt_tokens: {usage.prompt_tokens}, "
                f"completion_tokens: {usage.completion_tokens}, "
                f"total_tokens: {usage.total_tokens}"
            )

        extra_text = response.choices[0].message.content or ""
        if not extra_text:
            logger.warning(f"{task_name} 接续响应内容为空，停止继续尝试")
            break

        combined_text += extra_text
        finish_reason = response.choices[0].finish_reason

    if finish_reason == "length":
        logger.warning(
            f"{task_name} 在尝试 {total_attempts} 次后仍被max_tokens截断，输出可能不完整"
        )

    return combined_text, finish_reason

