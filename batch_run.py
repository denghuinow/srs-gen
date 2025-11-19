#!/usr/bin/env python3
"""批量执行main.py的脚本"""
import argparse
import subprocess
import sys
import shutil
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Tuple, Optional
import time
from datetime import datetime
import re


def find_matching_baseline(input_file: Path, baseline_dir: Path) -> Optional[Path]:
    """根据输入文件名查找匹配的基准文档"""
    input_stem = input_file.stem  # 不含扩展名的文件名
    
    # 尝试多种匹配方式
    # 1. 完全匹配文件名（忽略扩展名）
    for ext in ['.md', '.txt', '.markdown']:
        baseline_path = baseline_dir / f"{input_stem}{ext}"
        if baseline_path.exists():
            return baseline_path
    
    # 2. 尝试在基准目录中查找包含输入文件名的文件
    for baseline_file in baseline_dir.glob("*"):
        if baseline_file.is_file():
            baseline_stem = baseline_file.stem
            # 如果基准文件名包含输入文件名，或者输入文件名包含基准文件名
            if input_stem in baseline_stem or baseline_stem in input_stem:
                return baseline_file
    
    return None


def is_retryable_error(error_msg: str) -> bool:
    """判断错误是否可重试（网络错误、超时等临时性错误）"""
    retryable_patterns = [
        r"Connection reset by peer",
        r"Connection refused",
        r"Connection aborted",
        r"Connection timeout",
        r"Timeout",
        r"timeout",
        r"Network is unreachable",
        r"No route to host",
        r"Temporary failure",
        r"Service temporarily unavailable",
        r"Too many requests",
        r"Rate limit",
        r"429",  # HTTP 429 Too Many Requests
        r"502",  # HTTP 502 Bad Gateway
        r"503",  # HTTP 503 Service Unavailable
        r"504",  # HTTP 504 Gateway Timeout
    ]
    
    error_text = error_msg.lower()
    for pattern in retryable_patterns:
        if re.search(pattern, error_text, re.IGNORECASE):
            return True
    return False


def run_single_task(
    input_file: Path,
    baseline_file: Optional[Path],
    baseline_gend_file: Optional[Path],
    output_base_dir: Path,
    ablation_mode: str,
    max_iterations: Optional[int],
    extra_args: List[str],
    max_retries: int = 3,
    retry_delay: float = 5.0
) -> Tuple[str, bool, str]:
    """执行单个任务，带重试机制"""
    task_name = input_file.stem
    output_dir = output_base_dir / task_name
    
    # 构建命令
    cmd = [
        sys.executable,
        str(Path(__file__).parent / "main.py"),
        str(input_file),
        "--output-dir",
        str(output_dir),
        "--ablation-mode",
        ablation_mode,
    ]
    
    if baseline_file:
        cmd.extend(["--baseline-srs", str(baseline_file)])
    
    if baseline_gend_file:
        cmd.extend(["--baseline-gend-srs", str(baseline_gend_file)])
    
    if max_iterations:
        cmd.extend(["--max-iterations", str(max_iterations)])
    
    cmd.extend(extra_args)
    
    # 执行命令，带重试
    start_time = time.time()
    last_error = None
    
    for attempt in range(max_retries + 1):  # 0到max_retries，共max_retries+1次尝试
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True
            )
            elapsed_time = time.time() - start_time
            if attempt > 0:
                return (task_name, True, f"成功 (耗时: {elapsed_time:.2f}秒, 重试: {attempt}次)")
            return (task_name, True, f"成功 (耗时: {elapsed_time:.2f}秒)")
        except subprocess.CalledProcessError as e:
            elapsed_time = time.time() - start_time
            # 优先使用 stderr，如果没有则使用 stdout，最后使用异常消息
            error_msg = e.stderr if e.stderr else (e.stdout if e.stdout else str(e))
            last_error = error_msg
            
            # 判断是否可重试
            if attempt < max_retries and is_retryable_error(error_msg):
                # 等待后重试
                time.sleep(retry_delay)
                continue
            else:
                # 不可重试或已达到最大重试次数
                if attempt > 0:
                    return (task_name, False, f"失败 (耗时: {elapsed_time:.2f}秒, 重试: {attempt}次): {error_msg[:200]}")
                return (task_name, False, f"失败 (耗时: {elapsed_time:.2f}秒): {error_msg[:200]}")
    
    # 如果所有重试都失败
    elapsed_time = time.time() - start_time
    error_msg = last_error[:200] if last_error else "未知错误"
    return (task_name, False, f"失败 (耗时: {elapsed_time:.2f}秒, 重试: {max_retries}次): {error_msg}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="批量执行SRS编制系统",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--input-dir",
        type=str,
        required=True,
        help="输入文档目录路径"
    )
    
    parser.add_argument(
        "--baseline-dir",
        type=str,
        default="",
        help="基准文档目录路径（可选，如果不指定则不会使用基准文档）"
    )
    
    parser.add_argument(
        "--baseline-gend-dir",
        type=str,
        default="",
        help="基准生成的SRS文档目录路径（可选，如果不指定则不会使用基准生成的SRS文档）"
    )
    
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="输出目录路径（默认：output）"
    )
    
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        help="并行度（同时执行的任务数，默认：1）"
    )
    
    parser.add_argument(
        "--ablation-mode",
        type=str,
        choices=["default", "no-clarify", "no-explore-clarify"],
        default="default",
        help="消融模式（默认：default）"
    )
    
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="最大迭代次数（可选）"
    )
    
    parser.add_argument(
        "--file-extensions",
        type=str,
        nargs="+",
        default=[".txt", ".md", ".markdown"],
        help="要处理的文件扩展名（默认：.txt .md .markdown）"
    )
    
    parser.add_argument(
        "--files",
        type=str,
        nargs="+",
        default=None,
        help="指定要处理的文件列表（文件名，可以包含或不包含扩展名）。如果指定，则只处理这些文件"
    )
    
    parser.add_argument(
        "--extra-args",
        type=str,
        nargs=argparse.REMAINDER,
        help="传递给main.py的额外参数"
    )
    
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="失败时的最大重试次数（默认：3）"
    )
    
    parser.add_argument(
        "--retry-delay",
        type=float,
        default=5.0,
        help="重试前的等待时间（秒，默认：5.0）"
    )
    
    args = parser.parse_args()
    
    # 验证输入目录
    input_dir = Path(args.input_dir)
    if not input_dir.exists() or not input_dir.is_dir():
        print(f"错误：输入目录不存在或不是目录：{input_dir}", file=sys.stderr)
        sys.exit(1)
    
    # 验证基准目录（如果指定）
    baseline_dir = None
    if args.baseline_dir:
        baseline_dir = Path(args.baseline_dir)
        if not baseline_dir.exists() or not baseline_dir.is_dir():
            print(f"错误：基准目录不存在或不是目录：{baseline_dir}", file=sys.stderr)
            sys.exit(1)
    
    # 验证基准生成的SRS目录（如果指定）
    baseline_gend_dir = None
    if args.baseline_gend_dir:
        baseline_gend_dir = Path(args.baseline_gend_dir)
        if not baseline_gend_dir.exists() or not baseline_gend_dir.is_dir():
            print(f"错误：基准生成的SRS目录不存在或不是目录：{baseline_gend_dir}", file=sys.stderr)
            sys.exit(1)
    
    # 创建输出目录
    output_base_dir = Path(args.output_dir)
    output_base_dir.mkdir(parents=True, exist_ok=True)
    
    # 查找所有输入文件
    input_files = []
    if args.files:
        # 如果指定了文件列表，只处理这些文件
        for file_name in args.files:
            # 尝试直接匹配文件名
            file_path = input_dir / file_name
            if file_path.exists() and file_path.is_file():
                input_files.append(file_path)
            else:
                # 尝试匹配文件名（不包含扩展名）
                file_stem = Path(file_name).stem
                for ext in args.file_extensions:
                    candidate = input_dir / f"{file_stem}{ext}"
                    if candidate.exists() and candidate.is_file():
                        input_files.append(candidate)
                        break
                else:
                    # 如果还是找不到，尝试模糊匹配
                    found = False
                    for ext in args.file_extensions:
                        for existing_file in input_dir.glob(f"*{ext}"):
                            if file_stem in existing_file.stem or existing_file.stem in file_stem:
                                input_files.append(existing_file)
                                found = True
                                break
                        if found:
                            break
                    if not found:
                        print(f"警告：未找到文件：{file_name}", file=sys.stderr)
    else:
        # 处理所有匹配扩展名的文件
        for ext in args.file_extensions:
            input_files.extend(input_dir.glob(f"*{ext}"))
    
    if not input_files:
        if args.files:
            print(f"错误：未找到任何指定的文件", file=sys.stderr)
        else:
            print(f"警告：在 {input_dir} 中未找到任何输入文件（扩展名：{args.file_extensions}）", file=sys.stderr)
        sys.exit(1)
    
    # 去重并排序
    input_files = sorted(set(input_files))
    
    print(f"找到 {len(input_files)} 个输入文件")
    print(f"输出目录：{output_base_dir.absolute()}")
    print(f"并行度：{args.parallel}")
    print(f"消融模式：{args.ablation_mode}")
    print(f"最大重试次数：{args.max_retries}")
    print(f"重试延迟：{args.retry_delay}秒")
    if baseline_dir:
        print(f"基准目录：{baseline_dir.absolute()}")
    if baseline_gend_dir:
        print(f"基准生成的SRS目录：{baseline_gend_dir.absolute()}")
    print()
    
    # 准备任务列表
    tasks = []
    for input_file in input_files:
        baseline_file = None
        if baseline_dir:
            baseline_file = find_matching_baseline(input_file, baseline_dir)
            if not baseline_file:
                print(f"警告：未找到 {input_file.name} 的匹配基准文档", file=sys.stderr)
        
        baseline_gend_file = None
        if baseline_gend_dir:
            baseline_gend_file = find_matching_baseline(input_file, baseline_gend_dir)
            if not baseline_gend_file:
                print(f"警告：未找到 {input_file.name} 的匹配基准生成的SRS文档", file=sys.stderr)
        
        tasks.append((input_file, baseline_file, baseline_gend_file))
    
    # 执行任务
    start_time = time.time()
    results = []  # 每个元素是 (task_name, success, msg, input_file)
    
    if args.parallel == 1:
        # 串行执行
        print("串行执行模式...")
        for input_file, baseline_file, baseline_gend_file in tasks:
            task_name = input_file.stem
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始处理：{task_name}")
            result = run_single_task(
                input_file,
                baseline_file,
                baseline_gend_file,
                output_base_dir,
                args.ablation_mode,
                args.max_iterations,
                args.extra_args or [],
                args.max_retries,
                args.retry_delay
            )
            # 添加输入文件信息到结果
            results.append((result[0], result[1], result[2], input_file))
            status = "✓" if result[1] else "✗"
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {status} {result[0]}: {result[2]}")
    else:
        # 并行执行
        print(f"并行执行模式（并行度：{args.parallel}）...")
        with ProcessPoolExecutor(max_workers=args.parallel) as executor:
            # 提交所有任务
            future_to_task = {}
            for input_file, baseline_file, baseline_gend_file in tasks:
                task_name = input_file.stem
                future = executor.submit(
                    run_single_task,
                    input_file,
                    baseline_file,
                    baseline_gend_file,
                    output_base_dir,
                    args.ablation_mode,
                    args.max_iterations,
                    args.extra_args or [],
                    args.max_retries,
                    args.retry_delay
                )
                future_to_task[future] = (task_name, baseline_file, baseline_gend_file, input_file)
            
            # 处理完成的任务
            completed = 0
            for future in as_completed(future_to_task):
                completed += 1
                result = future.result()
                task_name, baseline_file, baseline_gend_file, input_file = future_to_task[future]
                # 添加输入文件信息到结果
                results.append((result[0], result[1], result[2], input_file))
                status = "✓" if result[1] else "✗"
                baseline_info = f" (基准: {baseline_file.name})" if baseline_file else ""
                baseline_gend_info = f" (基准生成: {baseline_gend_file.name})" if baseline_gend_file else ""
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [{completed}/{len(tasks)}] {status} {result[0]}: {result[2]}{baseline_info}{baseline_gend_info}")
    
    # 输出统计信息
    total_time = time.time() - start_time
    success_count = sum(1 for _, success, _, _ in results if success)
    fail_count = len(results) - success_count
    
    print()
    print("=" * 60)
    print("执行统计")
    print("=" * 60)
    print(f"总任务数：{len(results)}")
    print(f"成功：{success_count}")
    print(f"失败：{fail_count}")
    print(f"总耗时：{total_time:.2f}秒")
    print(f"平均耗时：{total_time/len(results):.2f}秒/任务")
    print()
    
    # 输出失败的任务
    if fail_count > 0:
        print("失败的任务：")
        for task_name, success, msg, _ in results:
            if not success:
                print(f"  - {task_name}: {msg}")
        print()
    
    # 输出结果摘要文件
    summary_file = output_base_dir / f"batch_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(summary_file, "w", encoding="utf-8") as f:
        f.write("批量执行摘要\n")
        f.write("=" * 60 + "\n")
        f.write(f"执行时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"输入目录：{input_dir.absolute()}\n")
        if baseline_dir:
            f.write(f"基准目录：{baseline_dir.absolute()}\n")
        if baseline_gend_dir:
            f.write(f"基准生成的SRS目录：{baseline_gend_dir.absolute()}\n")
        f.write(f"输出目录：{output_base_dir.absolute()}\n")
        f.write(f"并行度：{args.parallel}\n")
        f.write(f"消融模式：{args.ablation_mode}\n")
        f.write(f"最大重试次数：{args.max_retries}\n")
        f.write(f"重试延迟：{args.retry_delay}秒\n")
        f.write(f"总任务数：{len(results)}\n")
        f.write(f"成功：{success_count}\n")
        f.write(f"失败：{fail_count}\n")
        f.write(f"总耗时：{total_time:.2f}秒\n")
        f.write("\n详细结果：\n")
        for task_name, success, msg, _ in results:
            status = "成功" if success else "失败"
            f.write(f"{status}: {task_name} - {msg}\n")
    
    print(f"摘要已保存到：{summary_file}")
    
    # 收集所有成功生成的SRS文档到统一文件夹
    if success_count > 0:
        srs_collection_dir = output_base_dir / "srs_collection"
        srs_collection_dir.mkdir(exist_ok=True)
        
        collected_count = 0
        for task_name, success, _, input_file in results:
            if success:
                task_output_dir = output_base_dir / task_name
                srs_file = task_output_dir / "srs_document.md"
                
                if srs_file.exists():
                    # 使用输入文档的原始文件名（扩展名改为.md）
                    input_stem = input_file.stem
                    dest_file = srs_collection_dir / f"{input_stem}.md"
                    shutil.copy2(srs_file, dest_file)
                    collected_count += 1
        
        if collected_count > 0:
            print(f"\n已收集 {collected_count} 个SRS文档到：{srs_collection_dir.absolute()}")
        else:
            print("\n警告：未找到任何SRS文档文件")
    
    # 如果有失败的任务，返回非零退出码
    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

