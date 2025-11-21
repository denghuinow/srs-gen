"""流式响应工具模块：统一处理流式响应和自动续接"""
import sys
import time
from typing import Callable, List, Tuple
from openai import OpenAI, APIError, APITimeoutError, InternalServerError

from ..config import Config
from .logger import get_logger
from .token_counter import calculate_adjusted_max_tokens, count_tokens

logger = get_logger("Streaming")


def request_stream_completion(client: OpenAI, api_params: dict) -> Tuple[str, str]:
    """处理流式补全请求（带重试机制）
    
    Args:
        client: OpenAI客户端实例
        api_params: API调用参数（必须包含 stream=True）
    
    Returns:
        (内容, finish_reason)
    
    Raises:
        Exception: 所有重试都失败后抛出异常
    """
    max_retries = Config.MAX_RETRIES
    retry_delay = Config.RETRY_DELAY
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            if attempt > 0:
                # 指数退避：延迟时间 = 初始延迟 * 2^(attempt-1)
                delay = retry_delay * (2 ** (attempt - 1))
                logger.warning(f"第 {attempt + 1}/{max_retries + 1} 次尝试，等待 {delay:.1f} 秒后重试...")
                time.sleep(delay)
            
            content_parts = []
            finish_reason = "stop"
            stream_response = client.chat.completions.create(**api_params)
            
            try:
                for chunk in stream_response:
                    if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        content_parts.append(content)
                        sys.stdout.write(content)
                        sys.stdout.flush()
                    if chunk.choices and chunk.choices[0].finish_reason:
                        finish_reason = chunk.choices[0].finish_reason
            except Exception as stream_error:
                # 流式响应处理过程中的错误也需要重试
                # 如果已经收集到部分内容，记录日志但不保留（因为流可能不完整）
                if content_parts:
                    logger.warning(f"流式响应处理中断，已收集 {len(''.join(content_parts))} 字符，将重试...")
                # 重新抛出异常以便外层重试逻辑处理
                raise stream_error
            
            sys.stdout.write("\n")
            sys.stdout.flush()
            
            if attempt > 0:
                logger.info(f"重试成功（第 {attempt + 1} 次尝试）")
            
            return "".join(content_parts), finish_reason
            
        except (InternalServerError, APITimeoutError) as e:
            # 对于500错误和超时错误，进行重试
            last_exception = e
            error_type = "服务器内部错误" if isinstance(e, InternalServerError) else "请求超时"
            logger.warning(f"API调用失败（{error_type}）: {e}")
            if attempt < max_retries:
                continue
            else:
                logger.error(f"所有 {max_retries + 1} 次尝试均失败")
                raise Exception(f"API调用失败（{error_type}）: {e}")
                
        except APIError as e:
            # 对于其他API错误，根据状态码决定是否重试
            last_exception = e
            status_code = getattr(e, 'status_code', None)
            # 提取详细的错误信息
            error_message = str(e)
            error_body = getattr(e, 'body', None)
            if error_body:
                try:
                    import json
                    if isinstance(error_body, str):
                        error_dict = json.loads(error_body)
                    else:
                        error_dict = error_body
                    if isinstance(error_dict, dict) and 'error' in error_dict:
                        error_detail = error_dict['error']
                        if isinstance(error_detail, dict):
                            error_message = f"{error_message} - {json.dumps(error_detail, ensure_ascii=False)}"
                        else:
                            error_message = f"{error_message} - {error_detail}"
                except Exception:
                    pass  # 如果解析失败，使用原始错误信息
            
            # 5xx错误可以重试，4xx错误（客户端错误）不重试
            if status_code and 500 <= status_code < 600:
                logger.warning(f"API调用失败（服务器错误 {status_code}）: {error_message}")
                if attempt < max_retries:
                    continue
                else:
                    logger.error(f"所有 {max_retries + 1} 次尝试均失败")
                    raise Exception(f"API调用失败（服务器错误 {status_code}）: {error_message}")
            else:
                # 客户端错误（4xx）不重试，直接抛出
                error_prefix = f"Error code: {status_code}" if status_code else "客户端错误"
                logger.error(f"API调用失败（{error_prefix}）: {error_message}")
                raise Exception(f"API调用失败: {error_prefix} - {error_message}")
                
        except Exception as e:
            # 其他异常（网络错误等）也进行重试
            last_exception = e
            logger.warning(f"API调用失败（未知错误）: {e}")
            if attempt < max_retries:
                continue
            else:
                logger.error(f"所有 {max_retries + 1} 次尝试均失败")
                raise Exception(f"API调用失败: {e}")
    
    # 如果所有重试都失败，抛出最后一个异常
    if last_exception:
        raise Exception(f"API调用失败: {last_exception}")
    
    # 理论上不会到达这里，但为了类型检查
    raise Exception("API调用失败: 未知错误")


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

