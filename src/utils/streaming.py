"""流式响应工具模块：统一处理流式响应和自动续接"""
import sys
from typing import Callable, List, Tuple
from openai import OpenAI

from ..config import Config
from .logger import get_logger
from .token_counter import calculate_adjusted_max_tokens, count_tokens

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
    continuation_prompt: str = None  # 已废弃，不再使用
) -> str:
    """统一的流式响应和续接处理
    
    始终使用流式响应，并在检测到 max_tokens 截断时自动续接。
    参考 srs-eval 的实现，使用对话前缀续写方式，不需要额外的提示词。
    
    Args:
        client: OpenAI客户端实例
        base_api_params: API调用基础参数（不包含 messages 和 stream）
        messages: 消息列表（会被修改以支持续接）
        task_name: 任务名称（用于日志）
        continuation_prompt: 已废弃，不再使用（保留参数以保持兼容性）
    
    Returns:
        完整的内容字符串
    """
    import copy
    
    content_parts = []
    auto_continue_attempts = 0
    max_auto_continue = Config.MAX_CONTINUATIONS
    
    # 保存原始消息列表的副本，用于续接
    base_messages = copy.deepcopy(messages)
    
    # 获取最大上下文长度和配置的 max_tokens
    max_context_length = Config.get_max_context_length()
    configured_max_tokens = base_api_params.get("max_tokens")
    
    # 记录配置信息（用于调试）
    logger.info(
        f"{task_name} 上下文配置 - MAX_CONTEXT_LENGTH: {max_context_length}, "
        f"配置的MAX_TOKENS: {configured_max_tokens}"
    )
    
    while True:
        api_params = dict(base_api_params)
        api_params["messages"] = messages
        api_params["stream"] = True
        
        # 在请求前计算输入 token 并调整 MAX_TOKENS
        if max_context_length is not None:
            # 先计算输入 token 数量（用于日志）
            input_tokens = count_tokens(messages)
            
            adjusted_max_tokens = calculate_adjusted_max_tokens(
                messages=messages,
                max_context_length=max_context_length,
                configured_max_tokens=configured_max_tokens
            )
            
            if adjusted_max_tokens is not None:
                api_params["max_tokens"] = adjusted_max_tokens
                # 记录 token 计算信息
                if input_tokens is not None:
                    logger.info(
                        f"{task_name} Token计算 - 输入: {input_tokens}, "
                        f"最大上下文: {max_context_length}, "
                        f"调整后MAX_TOKENS: {adjusted_max_tokens}, "
                        f"总计: {input_tokens + adjusted_max_tokens}"
                    )
                else:
                    logger.warning(
                        f"{task_name} 无法计算输入token，使用调整后的MAX_TOKENS: {adjusted_max_tokens}"
                    )
            elif "max_tokens" in api_params:
                # 如果调整后为 None（输入已超过最大上下文长度），移除 max_tokens 参数
                del api_params["max_tokens"]
                logger.warning(
                    f"{task_name} 输入token数量 ({input_tokens if input_tokens is not None else '未知'}) "
                    f"已超过最大上下文长度 ({max_context_length})，移除MAX_TOKENS限制"
                )
        else:
            # 如果没有配置最大上下文长度，记录警告
            if configured_max_tokens is not None:
                logger.debug(
                    f"{task_name} 未配置MAX_CONTEXT_LENGTH，使用配置的MAX_TOKENS: {configured_max_tokens}"
                )
        
        try:
            content, finish_reason = request_stream_completion(client, api_params)
        except Exception as e:
            logger.error(f"{task_name} 流式生成过程中出错: {e}")
            raise
        
        if content:
            content_parts.append(content)
            # 记录接续后新增的内容（用于调试）
            if auto_continue_attempts > 0:
                logger.debug(f"接续后新增内容（长度: {len(content)}字符）:")
                logger.debug("=" * 80)
                logger.debug(content[:500] + ("..." if len(content) > 500 else ""))
                logger.debug("=" * 80)
        
        if finish_reason != "length":
            break
        
        # 流式响应的续接逻辑
        auto_continue_attempts += 1
        if auto_continue_attempts >= max_auto_continue:
            logger.warning(f"{task_name} 检测到连续截断且达到自动续接次数上限（{max_auto_continue}），停止继续请求。")
            break
        
        logger.info(f"{task_name} 检测到输出因达到最大token限制被截断，自动续接（{auto_continue_attempts}/{max_auto_continue}）...")
        
        # 记录接续前的内容（最后500字符，用于调试）
        combined_text = "".join(content_parts)
        preview_length = 500
        before_text = combined_text[-preview_length:] if len(combined_text) > preview_length else combined_text
        logger.debug(f"接续前内容（最后{len(before_text)}字符，总长度{len(combined_text)}字符）:")
        logger.debug("=" * 80)
        logger.debug(before_text)
        logger.debug("=" * 80)
        
        # 使用对话前缀续写方式：将已生成的内容作为 assistant 消息
        # 参考 srs-eval 的实现，不需要额外的提示词
        # 注意：prefix 和 partial 可能是某些 API 客户端的扩展参数，标准 OpenAI API 会忽略它们
        continuation_messages = copy.deepcopy(base_messages)
        
        # 如果最后一个消息是 assistant 消息，更新它；否则追加新的
        if continuation_messages and continuation_messages[-1].get("role") == "assistant":
            continuation_messages[-1] = {
                "role": "assistant",
                "content": combined_text,
                "prefix": True,  # 某些 API 客户端可能支持此参数，表示这是前缀内容
                "partial": True  # 某些 API 客户端可能支持此参数，表示这是部分内容
            }
        else:
            continuation_messages.append({
                "role": "assistant",
                "content": combined_text,
                "prefix": True,
                "partial": True
            })
        
        # 更新 messages 用于下一次请求
        messages = continuation_messages
        
        # 记录合并后的内容（最后500字符，用于验证接续是否连贯）
        combined_text_after = "".join(content_parts)
        after_text = combined_text_after[-preview_length:] if len(combined_text_after) > preview_length else combined_text_after
        logger.debug(f"接续后合并内容（最后{len(after_text)}字符，总长度{len(combined_text_after)}字符）:")
        logger.debug("=" * 80)
        logger.debug(after_text)
        logger.debug("=" * 80)
    
    final_content = "".join(content_parts)
    logger.info(f"{task_name} 完成，总长度: {len(final_content)} 字符，接续次数: {auto_continue_attempts}")
    return final_content

