"""流式响应工具模块：统一处理流式响应和自动续接"""
import sys
import time
from typing import Callable, List, Tuple
from openai import OpenAI, APIError, APITimeoutError, InternalServerError

from ..config import Config
from .logger import get_logger
from .token_counter import calculate_adjusted_max_tokens, count_tokens, count_text_tokens

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
            usage_data = None
            
            # 记录请求开始时间
            start_time = time.time()
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
                    # 检查是否有 usage 信息（通常在最后一个 chunk 中）
                    if hasattr(chunk, 'usage') and chunk.usage:
                        usage_data = chunk.usage
            except Exception as stream_error:
                # 流式响应处理过程中的错误也需要重试
                # 如果已经收集到部分内容，记录日志但不保留（因为流可能不完整）
                if content_parts:
                    collected_text = ''.join(content_parts)
                    collected_tokens = count_text_tokens(collected_text)
                    token_str = f"{collected_tokens} tokens" if collected_tokens is not None else f"{len(collected_text)} 字符"
                    logger.warning(f"流式响应处理中断，已收集 {token_str}，将重试...")
                # 重新抛出异常以便外层重试逻辑处理
                raise stream_error
            
            sys.stdout.write("\n")
            sys.stdout.flush()
            
            # 计算耗时和 token/s
            elapsed_time = time.time() - start_time
            final_content = "".join(content_parts)
            
            # 获取生成的 token 数量
            completion_tokens = None
            if usage_data and hasattr(usage_data, 'completion_tokens'):
                completion_tokens = usage_data.completion_tokens
            else:
                # 如果没有 usage 信息，通过 tokenizer 计算
                completion_tokens = count_text_tokens(final_content)
            
            # 计算并记录 token/s
            if completion_tokens is not None and elapsed_time > 0:
                tokens_per_second = completion_tokens / elapsed_time
                logger.info(f"API生成速度: {tokens_per_second:.2f} token/s (生成 {completion_tokens} tokens, 耗时 {elapsed_time:.2f}秒)")
            elif completion_tokens is not None:
                logger.info(f"API生成完成: {completion_tokens} tokens (耗时 {elapsed_time:.2f}秒)")
            
            # 记录完整的 token 使用情况（如果有）
            if usage_data:
                prompt_tokens = getattr(usage_data, 'prompt_tokens', None)
                total_tokens = getattr(usage_data, 'total_tokens', None)
                if prompt_tokens is not None or total_tokens is not None:
                    token_info = []
                    if prompt_tokens is not None:
                        token_info.append(f"prompt_tokens: {prompt_tokens}")
                    if completion_tokens is not None:
                        token_info.append(f"completion_tokens: {completion_tokens}")
                    if total_tokens is not None:
                        token_info.append(f"total_tokens: {total_tokens}")
                    logger.info(f"Token使用 - {', '.join(token_info)}")
            
            if attempt > 0:
                logger.info(f"重试成功（第 {attempt + 1} 次尝试）")
            
            return final_content, finish_reason
            
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
            is_max_tokens_error = False
            parsed_input_tokens = None
            parsed_max_context = None
            parsed_requested_max_tokens = None
            
            if error_body:
                try:
                    import json
                    import re
                    if isinstance(error_body, str):
                        error_dict = json.loads(error_body)
                    else:
                        error_dict = error_body
                    if isinstance(error_dict, dict) and 'error' in error_dict:
                        error_detail = error_dict['error']
                        if isinstance(error_detail, dict):
                            error_message = f"{error_message} - {json.dumps(error_detail, ensure_ascii=False)}"
                            # 检查是否是max_tokens相关的错误
                            error_msg = str(error_detail.get('message', ''))
                            error_msg_lower = error_msg.lower()
                            if 'max_tokens' in error_msg_lower or 'max_completion_tokens' in error_msg_lower:
                                is_max_tokens_error = True
                                
                                # 从错误信息中解析实际值
                                # 示例: "'max_tokens' or 'max_completion_tokens' is too large: 4387. This model's maximum context length is 131072 tokens and your request has 129968 input tokens"
                                # 提取请求的max_tokens
                                max_tokens_match = re.search(r'(?:max_tokens|max_completion_tokens).*?is too large:\s*(\d+)', error_msg, re.IGNORECASE)
                                if max_tokens_match:
                                    parsed_requested_max_tokens = int(max_tokens_match.group(1))
                                
                                # 提取最大上下文长度
                                context_match = re.search(r'maximum context length is (\d+)', error_msg, re.IGNORECASE)
                                if context_match:
                                    parsed_max_context = int(context_match.group(1))
                                
                                # 提取实际输入token
                                input_match = re.search(r'your request has (\d+) input tokens', error_msg, re.IGNORECASE)
                                if input_match:
                                    parsed_input_tokens = int(input_match.group(1))
                                
                                if parsed_input_tokens and parsed_max_context:
                                    logger.info(
                                        f"从API错误信息中解析出：输入token={parsed_input_tokens}, "
                                        f"最大上下文={parsed_max_context}, "
                                        f"请求的max_tokens={parsed_requested_max_tokens}"
                                    )
                        else:
                            error_message = f"{error_message} - {error_detail}"
                except Exception as parse_error:
                    logger.debug(f"解析错误信息失败: {parse_error}")
                    pass  # 如果解析失败，使用原始错误信息
            
            # 5xx错误可以重试
            if status_code and 500 <= status_code < 600:
                logger.warning(f"API调用失败（服务器错误 {status_code}）: {error_message}")
                if attempt < max_retries:
                    continue
                else:
                    logger.error(f"所有 {max_retries + 1} 次尝试均失败")
                    raise Exception(f"API调用失败（服务器错误 {status_code}）: {error_message}")
            # max_tokens相关的400错误可以自动修复并重试
            elif is_max_tokens_error and status_code == 400:
                error_prefix = f"Error code: {status_code}" if status_code else "客户端错误"
                logger.warning(f"API调用失败（max_tokens错误，将自动修复）: {error_message}")
                
                # 如果成功解析出值，使用解析出的值重新计算max_tokens
                if parsed_input_tokens is not None and parsed_max_context is not None:
                    # 计算可用的输出token（预留安全边距）
                    available_tokens = parsed_max_context - parsed_input_tokens
                    safety_margin = 200  # 安全边距
                    safe_max_tokens = max(100, available_tokens - safety_margin)
                    
                    if safe_max_tokens > 0:
                        logger.info(
                            f"使用API返回的实际值重新计算max_tokens: "
                            f"输入={parsed_input_tokens}, 最大上下文={parsed_max_context}, "
                            f"可用={available_tokens}, 安全max_tokens={safe_max_tokens}"
                        )
                        # 更新api_params中的max_tokens并重试
                        api_params["max_tokens"] = safe_max_tokens
                        # 继续重试循环
                        if attempt < max_retries:
                            continue
                        else:
                            # 如果已经是最后一次尝试，抛出异常让外层处理
                            raise Exception(
                                f"API调用失败（max_tokens错误，已使用API返回的实际值修复，可自动修复）: "
                                f"{error_prefix} - 输入token={parsed_input_tokens}, "
                                f"最大上下文={parsed_max_context}, 修复后max_tokens={safe_max_tokens}"
                            )
                    else:
                        logger.error(
                            f"无法修复：输入token ({parsed_input_tokens}) 已超过或接近最大上下文长度 ({parsed_max_context})"
                        )
                        raise Exception(
                            f"输入token数量 ({parsed_input_tokens}) 已超过或接近最大上下文长度 ({parsed_max_context})，"
                            f"无法生成输出。请减少输入内容或增加最大上下文长度。"
                        )
                else:
                    # 如果无法解析，标记为可修复的错误，让外层处理
                    raise Exception(f"API调用失败（max_tokens错误，可自动修复）: {error_prefix} - {error_message}")
            else:
                # 其他客户端错误（4xx）不重试，直接抛出
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
            error_str = str(e)
            # 检查是否是max_tokens相关的错误，如果是，尝试自动修复
            if "max_tokens错误，可自动修复" in error_str or ("max_tokens" in error_str.lower() and "400" in error_str):
                logger.warning(f"{task_name} 检测到max_tokens错误，尝试自动修复...")
                
                # 尝试从错误信息中提取API返回的实际值
                import re
                parsed_input_tokens = None
                parsed_max_context = None
                parsed_requested_max_tokens = None
                
                # 从错误信息中解析
                # 示例: "输入token=129968, 最大上下文=131072, 修复后max_tokens=1104"
                input_match = re.search(r'输入token[=:](\d+)', error_str)
                if input_match:
                    parsed_input_tokens = int(input_match.group(1))
                
                context_match = re.search(r'最大上下文[=:](\d+)', error_str)
                if context_match:
                    parsed_max_context = int(context_match.group(1))
                
                max_tokens_match = re.search(r'修复后max_tokens[=:](\d+)', error_str)
                if max_tokens_match:
                    parsed_requested_max_tokens = int(max_tokens_match.group(1))
                
                # 如果从错误信息中解析出了值，直接使用
                if parsed_input_tokens is not None and parsed_max_context is not None:
                    available_tokens = parsed_max_context - parsed_input_tokens
                    safety_margin = 200
                    safe_max_tokens = max(100, available_tokens - safety_margin)
                    
                    if safe_max_tokens > 0:
                        logger.info(
                            f"{task_name} 使用API返回的实际值自动修复max_tokens - "
                            f"输入: {parsed_input_tokens}, 最大上下文: {parsed_max_context}, "
                            f"可用: {available_tokens}, 安全max_tokens: {safe_max_tokens}"
                        )
                        api_params["max_tokens"] = safe_max_tokens
                        try:
                            content, finish_reason = request_stream_completion(client, api_params)
                            logger.info(f"{task_name} 自动修复成功，继续生成...")
                        except Exception as retry_e:
                            logger.error(f"{task_name} 自动修复后仍然失败: {retry_e}")
                            raise
                    else:
                        logger.error(
                            f"{task_name} 无法自动修复：输入token ({parsed_input_tokens}) "
                            f"已超过最大上下文长度 ({parsed_max_context})"
                        )
                        raise Exception(
                            f"输入token数量 ({parsed_input_tokens}) 已超过最大上下文长度 ({parsed_max_context})，"
                            f"无法生成输出。请减少输入内容或增加最大上下文长度。"
                        )
                # 如果没有解析出值，使用本地计算
                elif max_context_length is not None:
                    input_tokens = count_tokens(messages)
                    if input_tokens is not None:
                        # 使用更保守的计算：可用token减去更大的安全边距
                        available_tokens = max_context_length - input_tokens
                        safety_margin = 500  # 增加安全边距
                        safe_max_tokens = max(100, available_tokens - safety_margin)  # 至少保留100 tokens
                        
                        if safe_max_tokens > 0:
                            logger.info(
                                f"{task_name} 自动修复max_tokens - 输入: {input_tokens}, "
                                f"可用: {available_tokens}, 安全max_tokens: {safe_max_tokens}"
                            )
                            # 更新api_params并重试一次
                            api_params["max_tokens"] = safe_max_tokens
                            try:
                                content, finish_reason = request_stream_completion(client, api_params)
                                logger.info(f"{task_name} 自动修复成功，继续生成...")
                            except Exception as retry_e:
                                logger.error(f"{task_name} 自动修复后仍然失败: {retry_e}")
                                raise
                        else:
                            logger.error(
                                f"{task_name} 无法自动修复：输入token ({input_tokens}) 已超过最大上下文长度 ({max_context_length})"
                            )
                            raise Exception(
                                f"输入token数量 ({input_tokens}) 已超过最大上下文长度 ({max_context_length})，"
                                f"无法生成输出。请减少输入内容或增加最大上下文长度。"
                            )
                    else:
                        logger.error(f"{task_name} 无法计算输入token，无法自动修复")
                        raise
                else:
                    logger.error(f"{task_name} 未配置MAX_CONTEXT_LENGTH，无法自动修复")
                    raise
            else:
                logger.error(f"{task_name} 流式生成过程中出错: {e}")
                raise
        
        if content:
            content_parts.append(content)
            # 记录接续后新增的内容（用于调试）
            if auto_continue_attempts > 0:
                content_tokens = count_text_tokens(content)
                content_token_str = f"{content_tokens} tokens" if content_tokens is not None else f"{len(content)} 字符"
                logger.debug(f"接续后新增内容（长度: {content_token_str}）:")
                logger.debug("=" * 80)
                logger.debug(content)
                logger.debug("=" * 80)
                
                # 记录接续后合并的内容（最后500字符，用于验证接续是否连贯）
                combined_text_after = "".join(content_parts)
                preview_length = 500
                after_text = combined_text_after[-preview_length:] if len(combined_text_after) > preview_length else combined_text_after
                after_text_tokens = count_text_tokens(after_text)
                combined_tokens = count_text_tokens(combined_text_after)
                after_token_str = f"{after_text_tokens} tokens" if after_text_tokens is not None else f"{len(after_text)} 字符"
                combined_token_str = f"{combined_tokens} tokens" if combined_tokens is not None else f"{len(combined_text_after)} 字符"
                logger.debug(f"接续后合并内容（最后{after_token_str}，总长度{combined_token_str}）:")
                logger.debug("=" * 80)
                logger.debug(after_text)
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
        before_text_tokens = count_text_tokens(before_text)
        combined_tokens = count_text_tokens(combined_text)
        before_token_str = f"{before_text_tokens} tokens" if before_text_tokens is not None else f"{len(before_text)} 字符"
        combined_token_str = f"{combined_tokens} tokens" if combined_tokens is not None else f"{len(combined_text)} 字符"
        logger.debug(f"接续前内容（最后{before_token_str}，总长度{combined_token_str}）:")
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
    
    final_content = "".join(content_parts)
    final_tokens = count_text_tokens(final_content)
    final_token_str = f"{final_tokens} tokens" if final_tokens is not None else f"{len(final_content)} 字符"
    logger.info(f"{task_name} 完成，总长度: {final_token_str}，接续次数: {auto_continue_attempts}")
    return final_content

