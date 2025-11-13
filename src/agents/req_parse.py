"""需求解析智能体 (FR-001)"""
from typing import List
from openai import OpenAI
from ..config import Config
from ..utils.timer import TimerManager
from ..utils.logger import get_logger


class ReqParseAgent:
    """需求解析智能体：将自然语言需求解析为去重的原子需求列表"""
    
    def __init__(self, client: OpenAI, timer_manager: TimerManager):
        self.client = client
        self.timer = timer_manager.get_timer("ReqParse")
        self.logger = get_logger("ReqParse")
    
    def parse(self, raw_input: str) -> List[str]:
        """解析自然语言需求为原子需求列表"""
        self.timer.start()
        
        try:
            self.logger.info(f"开始解析需求，输入长度: {len(raw_input)} 字符")
            self.logger.debug(f"输入文本摘要: {raw_input[:200]}..." if len(raw_input) > 200 else f"输入文本: {raw_input}")
            
            system_message = "你是一个专业的需求分析师，擅长将自然语言需求解析为清晰的原子需求。"
            prompt = f"""请将以下需求文本解析为去重的原子需求列表。

要求：
1. 仅保留可执行、可验证的独立句
2. 剔除疑问句和主观表述
3. 每个需求应该是独立的、可验证的
4. 去除重复需求

需求文本：
{raw_input}

请直接输出需求列表，每行一个需求，不要添加编号或其他格式。"""
            
            # 记录API调用参数
            api_params = {
                "model": Config.OPENAI_MODEL,
                "temperature": 0.0
            }
            self.logger.debug(f"API调用参数: {api_params}")
            
            # 记录完整请求内容
            self.logger.debug("完整请求内容:")
            self.logger.debug(f"  System: {system_message}")
            self.logger.debug(f"  User: {prompt}")
            
            response = self.client.chat.completions.create(
                model=Config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0
            )
            
            # 记录完整响应内容
            content = response.choices[0].message.content
            if content:
                self.logger.debug("完整响应内容:")
                for line in content.split("\n"):
                    self.logger.debug(f"  {line}")
                
                # 记录Token使用情况（如果可用）
                if hasattr(response, 'usage') and response.usage:
                    usage = response.usage
                    self.logger.debug(f"Token使用情况: prompt_tokens={usage.prompt_tokens}, completion_tokens={usage.completion_tokens}, total_tokens={usage.total_tokens}")
            else:
                self.logger.warning("API响应为空")
                return []
            
            # 解析输出，每行一个需求
            requirements = [
                line.strip()
                for line in content.split("\n")
                if line.strip() and not line.strip().startswith("#")
            ]
            
            original_count = len(requirements)
            
            # 去重
            seen = set()
            unique_requirements = []
            for req in requirements:
                if req.lower() not in seen:
                    seen.add(req.lower())
                    unique_requirements.append(req)
            
            self.logger.info(f"解析完成，原始需求数: {original_count}, 去重后: {len(unique_requirements)}")
            if unique_requirements:
                self.logger.debug(f"解析出的需求列表: {unique_requirements}")
            
            return unique_requirements
        
        except Exception as e:
            self.logger.error(f"解析过程中发生错误: {e}", exc_info=True)
            raise
        
        finally:
            self.timer.stop()
