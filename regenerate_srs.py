#!/usr/bin/env python3
"""
基于10轮迭代的日志和文件，提取不同迭代轮次和模式的需求信息，
调用DocGenerateAgent生成对应的SRS文档
"""

import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from openai import OpenAI
from src.config import Config
from src.models.requirement import Requirement, RequirementList
from src.agents.doc_generate import DocGenerateAgent
from src.utils.timer import TimerManager
from src.utils.logger import Logger, get_logger
from src.utils.prompt_loader import PromptLoader


def find_latest_log(log_dir: Path) -> Optional[Path]:
    """查找最新的日志文件"""
    log_files = list(log_dir.glob("srs_gen_*.log"))
    if not log_files:
        return None
    return max(log_files, key=lambda p: p.stat().st_mtime)


def extract_requirements_from_log(
    log_file: Path, 
    target_iteration: int,
    min_score: int = 1
) -> Tuple[Dict[str, str], Dict[str, int]]:
    """
    从日志中提取指定迭代轮次后历史评分>=min_score的需求清单
    
    需求是从前面累积上来的，历史评分是从第1轮到第target_iteration轮的所有评分记录中，
    找出每个需求的最佳得分，筛选出历史得分>=min_score的需求。
    
    需求文本提取逻辑（与main.py逻辑一致）：
    - 从所有轮次的挖掘响应中收集需求文本和对应得分
    - 对于每个需求ID，选择对应历史最佳得分时的文本版本，而不是最新版本
    - 如果某个需求ID在迭代过程中分数下降，保留分数高的版本的文本
    
    Returns:
        (requirements_dict, scores_dict): 
        - requirements_dict: {req_id: req_text}  # 使用对应历史最佳得分时的文本版本
        - scores_dict: {req_id: best_score}  # 最佳得分（历史最高分）
    """
    with open(log_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 记录每个需求在所有迭代中的评分历史（用于找出最佳得分）
    all_scores = {}  # {req_id: [score1, score2, ...]}
    # 记录每个需求ID在每轮迭代中的得分（用于匹配最佳得分时的文本）
    req_scores_by_iteration = {}  # {req_id: {iteration: score, ...}}
    
    # 从第1轮到第target_iteration轮，提取所有评分记录
    for iteration in range(1, target_iteration + 1):
        # 查找该轮迭代的评分结果
        clarify_complete_pattern = rf'\[迭代 {iteration}\].*?需求澄清 完成'
        clarify_match = re.search(clarify_complete_pattern, content, re.DOTALL)
        
        if not clarify_match:
            continue
        
        # 查找下一轮迭代的开始位置，作为边界
        next_iteration_pattern = rf'\[迭代 {iteration + 1}\].*?挖掘前需求ID集合'
        next_iteration_match = re.search(next_iteration_pattern, content[clarify_match.end():], re.DOTALL)
        
        if next_iteration_match:
            score_section = content[clarify_match.end():clarify_match.end() + next_iteration_match.start()]
        else:
            # 最后一轮迭代，提取到文件末尾
            score_section = content[clarify_match.end():]
        
        # 提取评分（TSV格式）
        tsv_section_pattern = r'完整响应内容:.*?\nRequirement ID\tReason\tScore\n((?:REQ-\d+\t[^\n]+\t[+-]?[0-2]\n?)+)'
        tsv_match = re.search(tsv_section_pattern, score_section, re.DOTALL)
        
        if not tsv_match:
            # 如果没有找到"完整响应内容:"，直接查找TSV格式
            tsv_pattern = r'Requirement ID\tReason\tScore\n((?:REQ-\d+\t[^\n]+\t[+-]?[0-2]\n?)+)'
            tsv_match = re.search(tsv_pattern, score_section, re.DOTALL)
        
        if tsv_match:
            tsv_lines = tsv_match.group(1).strip().split('\n')
            for line in tsv_lines:
                if not line.strip():
                    continue
                parts = line.split('\t')
                if len(parts) >= 3:
                    req_id = parts[0].strip()
                    try:
                        score_str = parts[2].strip()
                        score = int(score_str)  # int()可以处理+1, +2格式
                        if req_id not in all_scores:
                            all_scores[req_id] = []
                        all_scores[req_id].append(score)
                        # 记录该轮迭代的得分
                        if req_id not in req_scores_by_iteration:
                            req_scores_by_iteration[req_id] = {}
                        req_scores_by_iteration[req_id][iteration] = score
                    except ValueError:
                        continue
        
        # 提取评分（分组格式）
        score_group_pattern = r'Score:\s*([12])\s*\([^)]+\)\s*\n((?:-\s*REQ-\d+\s*\n?)+)'
        score_groups = re.findall(score_group_pattern, score_section)
        
        for score_str, req_list in score_groups:
            try:
                score = int(score_str)
                req_ids = re.findall(r'REQ-\d+', req_list)
                for req_id in req_ids:
                    if req_id not in all_scores:
                        all_scores[req_id] = []
                    all_scores[req_id].append(score)
                    # 记录该轮迭代的得分
                    if req_id not in req_scores_by_iteration:
                        req_scores_by_iteration[req_id] = {}
                    req_scores_by_iteration[req_id][iteration] = score
            except ValueError:
                continue
    
    # 计算每个需求的最佳得分（历史最高分）
    best_scores = {}  # {req_id: best_score}
    best_score_iterations = {}  # {req_id: [iterations_with_best_score, ...]}  # 可能有多个轮次达到最佳得分
    for req_id, score_list in all_scores.items():
        best_score = max(score_list)
        if best_score >= min_score:
            best_scores[req_id] = best_score
            # 找出达到最佳得分的所有轮次
            if req_id in req_scores_by_iteration:
                best_score_iterations[req_id] = [
                    iter_num for iter_num, score in req_scores_by_iteration[req_id].items()
                    if score == best_score
                ]
    
    if not best_scores:
        return {}, {}
    
    # 从所有轮次的挖掘响应中收集需求文本和对应得分
    # 格式：{req_id: [(iteration, score, text), ...]}
    req_texts_by_iteration = {}  # {req_id: [(iteration, score, text), ...]}
    
    # 从第1轮到第target_iteration轮，提取挖掘响应中的需求文本
    for iteration in range(1, target_iteration + 1):
        # 查找该轮迭代的挖掘完成位置
        explore_complete_pattern = rf'\[迭代 {iteration}\].*?需求挖掘 完成'
        explore_match = re.search(explore_complete_pattern, content, re.DOTALL)
        
        if not explore_match:
            continue
        
        # 查找下一轮迭代的开始位置，作为边界
        next_iteration_pattern = rf'\[迭代 {iteration + 1}\].*?挖掘前需求ID集合'
        next_iteration_match = re.search(next_iteration_pattern, content[explore_match.end():], re.DOTALL)
        
        if next_iteration_match:
            explore_section = content[explore_match.end():explore_match.end() + next_iteration_match.start()]
        else:
            # 最后一轮迭代，提取到文件末尾
            explore_section = content[explore_match.end():]
        
        # 从挖掘阶段的完整响应内容中提取需求文本
        # 格式：REQ-001: 需求文本
        full_response_pattern = r'完整响应内容:.*?\n((?:REQ-\d+:[^\n]+(?:\n(?!REQ-\d+:)[^\n]+)*\n?)+)'
        full_response_match = re.search(full_response_pattern, explore_section, re.DOTALL)
        
        if full_response_match:
            req_list_text = full_response_match.group(1)
            req_text_pattern = r'REQ-(\d+):\s*([^\n]+(?:\n(?!REQ-\d+:)[^\n]+)*)'
            req_text_matches = re.findall(req_text_pattern, req_list_text)
            
            for req_num, req_text in req_text_matches:
                req_id = f"REQ-{int(req_num):03d}"
                if req_id in best_scores:  # 只处理历史得分>=min_score的需求
                    # 清理文本
                    lines = [line.strip() for line in req_text.split('\n') if line.strip()]
                    clean_text = ' '.join(lines)
                    
                    # 获取该需求在该轮迭代的得分（如果该轮有评分）
                    score = req_scores_by_iteration.get(req_id, {}).get(iteration)
                    if score is None:
                        # 如果该轮没有评分（可能是新增需求，还未评分），使用None
                        score = None
                    
                    # 记录该需求在该轮迭代的文本和得分
                    if req_id not in req_texts_by_iteration:
                        req_texts_by_iteration[req_id] = []
                    req_texts_by_iteration[req_id].append((iteration, score, clean_text))
    
    # 对于每个需求ID，选择对应历史最佳得分时的文本版本
    requirements = {}  # {req_id: req_text}
    
    for req_id in best_scores.keys():
        best_score = best_scores[req_id]
        
        # 找出该需求在哪些轮次达到了最佳得分
        best_iterations = best_score_iterations.get(req_id, [])
        
        if req_id in req_texts_by_iteration:
            # 从该需求的所有文本版本中选择
            candidates = []
            
            # 优先选择在达到最佳得分的轮次中的文本版本
            for iteration, score, text in req_texts_by_iteration[req_id]:
                if iteration in best_iterations:
                    candidates.append((iteration, score, text))
            
            if candidates:
                # 如果有多个候选，选择最接近target_iteration的版本（但必须是达到最佳得分的）
                candidates.sort(key=lambda x: x[0], reverse=True)  # 按迭代轮次降序排列
                requirements[req_id] = candidates[0][2]
            else:
                # 如果没有在达到最佳得分的轮次中找到文本，使用最新的版本
                # 这种情况应该很少见，但作为fallback
                all_texts = req_texts_by_iteration[req_id]
                all_texts.sort(key=lambda x: x[0], reverse=True)  # 按迭代轮次降序排列
                requirements[req_id] = all_texts[0][2]
        else:
            # 如果从挖掘响应中找不到，尝试从其他位置提取（作为fallback）
            # 这种情况应该很少见
            pass
    
    # 如果还有需求没有找到文本，尝试从其他位置提取（作为fallback）
    if len(requirements) < len(best_scores):
        # 从Requirements List中提取（作为补充）
        req_list_pattern = r'\[Requirements List\]:\s*\n((?:REQ-\d+:[^\n]+(?:\n(?!REQ-\d+:)[^\n]+)*\n?)+)'
        req_list_matches = list(re.finditer(req_list_pattern, content))
        
        for req_list_match in req_list_matches:
            req_list_text = req_list_match.group(1)
            req_text_pattern = r'REQ-(\d+):\s*([^\n]+(?:\n(?!REQ-\d+:)[^\n]+)*)'
            req_text_matches = re.findall(req_text_pattern, req_list_text)
            
            for req_num, req_text in req_text_matches:
                req_id = f"REQ-{int(req_num):03d}"
                if req_id in best_scores and req_id not in requirements:
                    lines = [line.strip() for line in req_text.split('\n') if line.strip()]
                    clean_text = ' '.join(lines)
                    requirements[req_id] = clean_text
    
    # 如果还有需求没有找到文本，尝试从整个日志中提取（作为最后的fallback）
    if len(requirements) < len(best_scores):
        req_text_pattern = r'REQ-(\d+):\s*([^\n]+(?:\n(?!REQ-\d+:)[^\n]+)*)'
        req_text_matches = re.findall(req_text_pattern, content)
        
        for req_num, req_text in req_text_matches:
            req_id = f"REQ-{int(req_num):03d}"
            if req_id in best_scores and req_id not in requirements:
                lines = [line.strip() for line in req_text.split('\n') if line.strip()]
                clean_text = ' '.join(lines)
                requirements[req_id] = clean_text
    
    # 返回筛选后的需求和最佳得分
    filtered_scores = {req_id: best_scores[req_id] for req_id in requirements.keys()}
    
    return requirements, filtered_scores


def extract_raw_input(output_dir: Path) -> str:
    """从输出目录提取原始输入"""
    # 查找input文件
    input_files = list(output_dir.glob("input_*"))
    if input_files:
        with open(input_files[0], 'r', encoding='utf-8') as f:
            return f.read()
    
    # 如果找不到，返回默认值
    return "Not provided."


def clean_log_format(text: str) -> str:
    """
    清理日志格式标记（时间戳和日志级别）
    
    日志格式示例：
    2025-11-23 16:06:56 [DEBUG] [Streaming] 实际内容
    
    清理后只保留实际内容
    """
    if not text:
        return text
    
    lines = text.split('\n')
    cleaned_lines = []
    
    # 日志格式的正则表达式：时间戳 [级别] [Streaming] 内容
    log_prefix_pattern = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[[^\]]+\](?: \[[^\]]+\])?\s*')
    
    for line in lines:
        # 移除日志格式前缀
        cleaned_line = log_prefix_pattern.sub('', line)
        cleaned_lines.append(cleaned_line)
    
    return '\n'.join(cleaned_lines).strip()


def extract_first_explore_requirements(log_file: Path) -> Dict[str, str]:
    """
    从日志中提取第一次挖掘后的需求清单（用于no-clarify模式）
    
    Returns:
        {req_id: req_text}
    """
    with open(log_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    requirements = {}
    
    # 查找第一次挖掘后的需求
    # 策略1：查找"需求挖掘 完成"之后，"完整响应内容:"之后的需求列表
    # 格式：REQ-001: 需求文本（可能包含日志格式标记）
    first_explore_pattern = r'需求挖掘 完成.*?完整响应内容:.*?\n(.*?)(?=\n\[迭代 1\]|挖掘完成|$)'
    first_explore_match = re.search(first_explore_pattern, content, re.DOTALL)
    
    if first_explore_match:
        req_list_text = first_explore_match.group(1)
        # 清理日志格式标记
        req_list_text = clean_log_format(req_list_text)
        # 提取需求（支持多行需求文本，需求之间用---分隔）
        req_text_pattern = r'REQ-(\d+):\s*([^\n]+(?:\n(?!REQ-\d+:|---)[^\n]+)*)'
        req_text_matches = re.findall(req_text_pattern, req_list_text)
        
        for req_num, req_text in req_text_matches:
            req_id = f"REQ-{int(req_num):03d}"
            # 清理文本（移除多余的空行和分隔符）
            lines = [line.strip() for line in req_text.split('\n') if line.strip() and not line.strip().startswith('---')]
            clean_text = ' '.join(lines)
            if clean_text:  # 确保不是空文本
                requirements[req_id] = clean_text
    else:
        # 策略2：查找"[迭代 1] 挖掘后需求ID集合"之后，到"[迭代 2]"之前的内容
        iter1_pattern = r'\[迭代 1\].*?挖掘后需求ID集合'
        iter1_match = re.search(iter1_pattern, content, re.DOTALL)
        if iter1_match:
            explore_section = content[iter1_match.end():]
            # 查找下一轮迭代之前的内容
            next_iter_pattern = r'\[迭代 2\].*?挖掘前需求ID集合'
            next_iter_match = re.search(next_iter_pattern, explore_section, re.DOTALL)
            if next_iter_match:
                explore_section = explore_section[:next_iter_match.start()]
            
            # 从这部分提取需求（查找"完整响应内容:"之后的内容）
            full_response_pattern = r'完整响应内容:.*?\n(.*?)(?=\n\[迭代|挖掘完成|$)'
            full_response_match = re.search(full_response_pattern, explore_section, re.DOTALL)
            if full_response_match:
                req_list_text = full_response_match.group(1)
                # 清理日志格式标记
                req_list_text = clean_log_format(req_list_text)
                # 提取需求
                req_text_pattern = r'REQ-(\d+):\s*([^\n]+(?:\n(?!REQ-\d+:|---)[^\n]+)*)'
                req_text_matches = re.findall(req_text_pattern, req_list_text)
                
                for req_num, req_text in req_text_matches:
                    req_id = f"REQ-{int(req_num):03d}"
                    # 清理文本（移除多余的空行和分隔符）
                    lines = [line.strip() for line in req_text.split('\n') if line.strip() and not line.strip().startswith('---')]
                    clean_text = ' '.join(lines)
                    if clean_text:  # 确保不是空文本
                        requirements[req_id] = clean_text
    
    return requirements


def extract_requirement_structure(log_file: Path) -> str:
    """从日志中提取ReqParse的响应（用于no-explore-clarify模式）"""
    with open(log_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    extracted_text = ""
    
    # 策略1：查找"基准需求语义单元生成完成"之前的ReqParse响应
    # 这是baseline_requirement_structure，通过ReqParseAgent解析baseline_gend_srs得到
    baseline_pattern = r'基准需求语义单元生成完成.*?\n(.*?)(?=基准需求语义单元生成完成|需求挖掘|$)'
    baseline_match = re.search(baseline_pattern, content, re.DOTALL)
    
    if baseline_match:
        # 在匹配区域之前查找ReqParse的完整响应内容
        before_baseline = content[:baseline_match.start()]
        reqparse_pattern = r'ReqParse.*?完整响应内容:.*?\n(.*?)(?=\n\[|基准需求语义单元生成完成|$)'
        reqparse_match = re.search(reqparse_pattern, before_baseline, re.DOTALL)
        if reqparse_match:
            extracted_text = reqparse_match.group(1).strip()
    
    # 策略2：查找"需求语义单元解析 完成"之后的响应（旧格式兼容）
    if not extracted_text:
        pattern = r'需求语义单元解析 完成.*?\n(.*?)(?=需求语义单元生成完成|$)'
        match = re.search(pattern, content, re.DOTALL)
        
        if match:
            # 进一步提取实际内容（可能在DEBUG日志中）
            text = match.group(1)
            # 查找完整响应内容
            debug_pattern = r'完整响应内容:.*?\n(.*?)(?=\n\[|$)'
            debug_match = re.search(debug_pattern, text, re.DOTALL)
            if debug_match:
                extracted_text = debug_match.group(1).strip()
            else:
                extracted_text = text.strip()
    
    # 策略3：直接查找ReqParse的响应（最后的fallback）
    if not extracted_text:
        reqparse_pattern = r'ReqParse.*?完整响应内容:.*?\n(.*?)(?=\n\[|$)'
        reqparse_match = re.search(reqparse_pattern, content, re.DOTALL)
        if reqparse_match:
            extracted_text = reqparse_match.group(1).strip()
    
    # 清理日志格式标记
    if extracted_text:
        extracted_text = clean_log_format(extracted_text)
    
    return extracted_text


def generate_srs_for_iteration(
    source_dir: Path,
    target_output_dir: Path,
    iteration: Optional[int],
    ablation_mode: str = "default",
    prompt_version: Optional[str] = None
) -> bool:
    """
    为指定迭代轮次和模式生成SRS文档
    
    Args:
        source_dir: 源目录（包含日志文件的原始目录）
        target_output_dir: 目标输出目录（保存生成的SRS和日志）
        iteration: 迭代轮次（None表示消融模式，不需要迭代次数）
        ablation_mode: 消融模式
        prompt_version: 提示词版本
    
    Returns:
        是否成功
    """
    logger = get_logger("RegenerateSRS")
    
    # 确保目标输出目录存在
    target_output_dir.mkdir(parents=True, exist_ok=True)
    
    # 查找最新日志（从源目录）
    log_file = find_latest_log(source_dir)
    if not log_file:
        logger.error(f"未找到日志文件: {source_dir}")
        return False
    
    logger.info(f"使用日志文件: {log_file}")
    
    # 提取原始输入（所有模式都需要）
    raw_input = extract_raw_input(source_dir)
    
    # 提取基准需求语义单元（ReqParse的响应，所有模式都尝试提取）
    baseline_requirement_structure = extract_requirement_structure(log_file)
    if baseline_requirement_structure:
        logger.info(f"提取到 baseline_requirement_structure（长度: {len(baseline_requirement_structure)} 字符）")
    else:
        logger.debug("未找到 baseline_requirement_structure，将使用空字符串")
    
    # 提取需求
    if ablation_mode == "no-explore-clarify":
        # no-explore-clarify模式：使用ReqParse的响应作为requirement_structure
        logger.info(f"模式: {ablation_mode}（使用ReqParse的响应）")
        requirement_structure = "Not provided."
        # 创建空的RequirementList（因为使用requirement_structure）
        requirements = RequirementList()
    elif ablation_mode == "no-clarify":
        # no-clarify模式：使用第一次挖掘后的需求（未经评分）
        logger.info(f"模式: {ablation_mode}（使用第一次挖掘后的需求）")
        requirements_dict = extract_first_explore_requirements(log_file)
        
        if not requirements_dict:
            logger.error("未找到第一次挖掘后的需求")
            return False
        
        # 创建RequirementList
        requirements = RequirementList()
        for req_id, req_text in requirements_dict.items():
            req = Requirement(
                id=req_id,
                text=req_text,
                score=0  # no-clarify模式默认0分
            )
            requirements.add(req)
        
        requirement_structure = ""
    else:
        # default模式：从指定迭代轮次后提取评分>=1的需求
        if iteration is None:
            logger.error("default模式需要指定迭代轮次")
            return False
        
        logger.info(f"模式: {ablation_mode}（提取第{iteration}轮迭代后评分>=1的需求）")
        requirements_dict, scores_dict = extract_requirements_from_log(
            log_file, iteration, min_score=1
        )
        
        if not requirements_dict:
            logger.error(f"未找到第{iteration}轮迭代后评分>=1的需求")
            return False
        
        # 创建RequirementList
        requirements = RequirementList()
        for req_id, req_text in requirements_dict.items():
            req = Requirement(
                id=req_id,
                text=req_text,
                score=scores_dict.get(req_id, 1)
            )
            requirements.add(req)
        
        requirement_structure = ""
    
    # 打印提取到的需求数量
    if ablation_mode == "no-explore-clarify":
        logger.info(f"提取到 requirement_structure（长度: {len(requirement_structure)} 字符）")
    else:
        logger.info(f"提取到 {len(requirements.requirements)} 个需求")
    
    # 提取项目名称（从源目录名）
    project_name = source_dir.name
    
    # 初始化配置
    try:
        Config.validate()
    except ValueError as e:
        logger.error(f"配置错误: {e}")
        return False
    
    # 设置提示词版本
    if prompt_version:
        Config.PROMPT_VERSION = prompt_version
    
    # 初始化DocGenerateAgent
    client = OpenAI(**Config.get_openai_client_kwargs())
    timer_manager = TimerManager()
    
    agent = DocGenerateAgent(
        client=client,
        timer_manager=timer_manager,
        prompt_version=prompt_version or Config.PROMPT_VERSION
    )
    
    # 生成SRS文档
    try:
        logger.info("开始生成SRS文档...")
        srs_document = agent.generate(
            requirements=requirements,
            project_name=project_name,
            raw_input=raw_input,
            requirement_structure=requirement_structure,
            ablation_mode=ablation_mode,
            baseline_requirement_structure=baseline_requirement_structure
        )
        
        # 保存SRS文档到聚合目录结构
        # 格式：srs_document_iter{N}/{doc_name}.md 或 srs_document_{mode}/{doc_name}.md
        doc_name = source_dir.name
        
        if iteration is not None:
            # default模式：srs_document_iter{N}/{doc_name}.md
            aggregate_dir = target_output_dir / f"srs_document_iter{iteration}"
        else:
            # 消融模式：srs_document_{mode}/{doc_name}.md
            aggregate_dir = target_output_dir / f"srs_document_{ablation_mode}"
        
        aggregate_dir.mkdir(parents=True, exist_ok=True)
        srs_path = aggregate_dir / f"{doc_name}.md"
        
        # 检查文件是否已存在，如果存在则跳过
        if srs_path.exists():
            logger.info(f"SRS文档已存在，跳过生成: {srs_path}")
            return True
        
        with open(srs_path, 'w', encoding='utf-8') as f:
            f.write(srs_document)
        
        logger.info(f"SRS文档已保存到: {srs_path}")
        return True
        
    except Exception as e:
        logger.error(f"生成SRS文档失败: {e}", exc_info=True)
        return False


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="基于10轮迭代的日志，生成不同配置的SRS文档"
    )
    
    parser.add_argument(
        "source_dirs",
        type=str,
        nargs="+",
        help="源目录路径（包含日志文件的原始目录），可以指定多个目录进行批量处理"
    )
    
    parser.add_argument(
        "--output-dir",
        type=str,
        required=True,
        help="目标输出目录路径（保存生成的SRS和日志，会按模式聚合）"
    )
    
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="并发处理的最大工作线程数（默认: 4）"
    )
    
    parser.add_argument(
        "--iterations",
        type=int,
        nargs="+",
        default=[2, 5, 7],
        help="要生成的迭代轮次（默认: 2 5 7）"
    )
    
    parser.add_argument(
        "--modes",
        type=str,
        nargs="+",
        choices=["no-clarify", "no-explore-clarify"],
        default=[],
        help="消融模式（可选: no-clarify, no-explore-clarify）。如果不指定，则使用default模式（指定迭代轮次即为default模式）"
    )
    
    parser.add_argument(
        "--prompt-version",
        type=str,
        default=None,
        help="提示词版本（默认: 使用配置中的版本）"
    )
    
    args = parser.parse_args()
    
    # 验证源目录，排除归集文件夹
    source_dirs = []
    for d in args.source_dirs:
        source_dir = Path(d)
        if not source_dir.exists():
            print(f"错误：源目录不存在: {source_dir}")
            sys.exit(1)
        # 排除归集文件夹（如 srs_collection）
        if source_dir.name == "srs_collection":
            print(f"跳过归集文件夹: {source_dir}")
            continue
        source_dirs.append(source_dir)
    
    if not source_dirs:
        print("错误：没有有效的源目录")
        sys.exit(1)
    
    target_output_dir = Path(args.output_dir)
    target_output_dir.mkdir(parents=True, exist_ok=True)
    
    # 初始化日志（保存到目标输出目录）
    log_file_path = target_output_dir / "regenerate_srs.log"
    Logger.set_log_file(str(log_file_path))
    logger = get_logger("Main")
    
    logger.info(f"开始批量生成SRS文档")
    logger.info(f"源目录数量: {len(source_dirs)}")
    logger.info(f"目标输出目录: {target_output_dir}")
    logger.info(f"迭代轮次: {args.iterations}")
    logger.info(f"并发工作线程数: {args.max_workers}")
    
    # 构建任务列表：每个源目录 × 每个模式/迭代
    tasks = []
    
    for source_dir in source_dirs:
        # 1. 为每个迭代轮次生成default模式的SRS
        for iteration in args.iterations:
            tasks.append((source_dir, "default", iteration))
        
        # 2. 为每个消融模式生成SRS（不需要迭代次数）
        for mode in args.modes:
            tasks.append((source_dir, mode, None))
    
    logger.info(f"总任务数: {len(tasks)}")
    logger.info(f"  迭代轮次: {args.iterations}")
    if args.modes:
        logger.info(f"  消融模式: {args.modes}")
    
    # 并发执行所有任务
    success_count = 0
    fail_count = 0
    skipped_count = 0
    
    def process_task(task):
        """处理单个任务"""
        source_dir, mode, iteration = task
        task_logger = get_logger("Task")
        
        # 检查文件是否已存在（提前检查，避免不必要的处理）
        doc_name = source_dir.name
        if iteration is not None:
            aggregate_dir = target_output_dir / f"srs_document_iter{iteration}"
        else:
            aggregate_dir = target_output_dir / f"srs_document_{mode}"
        srs_path = aggregate_dir / f"{doc_name}.md"
        
        if srs_path.exists():
            task_logger.info(f"[跳过] {doc_name} - {mode}{f' iter{iteration}' if iteration else ''} (文件已存在)")
            return True, doc_name, mode, iteration, True  # 最后一个参数表示是否跳过
        
        task_logger.info(f"\n{'='*80}")
        if iteration is not None:
            task_logger.info(f"处理: {doc_name} - 迭代{iteration}, 模式{mode}")
        else:
            task_logger.info(f"处理: {doc_name} - 模式{mode}")
        task_logger.info(f"{'='*80}")
        
        try:
            result = generate_srs_for_iteration(
                source_dir, target_output_dir, iteration, mode, args.prompt_version
            )
            return result, doc_name, mode, iteration, False
        except Exception as e:
            task_logger.error(f"任务执行失败: {e}", exc_info=True)
            return False, doc_name, mode, iteration, False
    
    # 使用线程池并发处理
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        future_to_task = {executor.submit(process_task, task): task for task in tasks}
        
        completed = 0
        for future in as_completed(future_to_task):
            completed += 1
            try:
                result, doc_name, mode, iteration, is_skipped = future.result()
                if result:
                    success_count += 1
                    if is_skipped:
                        skipped_count += 1
                        logger.info(f"[{completed}/{len(tasks)}] ⊘ {doc_name} - {mode}{f' iter{iteration}' if iteration else ''} (已跳过)")
                    else:
                        logger.info(f"[{completed}/{len(tasks)}] ✓ {doc_name} - {mode}{f' iter{iteration}' if iteration else ''}")
                else:
                    fail_count += 1
                    logger.error(f"[{completed}/{len(tasks)}] ✗ {doc_name} - {mode}{f' iter{iteration}' if iteration else ''}")
            except Exception as e:
                fail_count += 1
                task = future_to_task[future]
                source_dir, mode, iteration = task
                logger.error(f"[{completed}/{len(tasks)}] ✗ 任务执行异常: {e}", exc_info=True)
    
    logger.info(f"\n{'='*80}")
    logger.info(f"完成！成功: {success_count}, 跳过: {skipped_count}, 失败: {fail_count}")
    if skipped_count > 0:
        logger.info(f"提示：已跳过 {skipped_count} 个已存在的文件，如需重新生成请先删除对应文件")
    logger.info(f"{'='*80}")


if __name__ == "__main__":
    main()

