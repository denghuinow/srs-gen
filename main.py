"""多智能体SRS智能编制系统主入口"""
import argparse
import shutil
import sys
import time
from pathlib import Path
from src.workflow.orchestrator import WorkflowOrchestrator
from src.config import Config, AblationMode
from src.utils.logger import Logger, get_logger
from src.models.requirement import RequirementList


def load_file(file_path: str) -> str:
    """加载文件内容"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"错误：文件不存在 {file_path}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"错误：读取文件失败 {file_path}: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="多智能体SRS智能编制系统",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "input",
        type=str,
        help="需求输入（文本或文件路径）"
    )
    
    parser.add_argument(
        "--baseline-srs",
        type=str,
        default="",
        help="基准SRS文件路径（可选）"
    )
    
    parser.add_argument(
        "--baseline-gend-srs",
        type=str,
        default="",
        help="基准生成的SRS文件路径（可选），将被解析成需求语义单元作为需求参考"
    )
    
    parser.add_argument(
        "--ablation-mode",
        type=str,
        choices=["default", "no-clarify", "no-explore-clarify"],
        default="default",
        help="消融模式：default（完整流程）、no-clarify（跳过澄清）、no-explore-clarify（跳过挖掘和澄清）"
    )
    
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="输出目录路径（默认：output）"
    )
    
    parser.add_argument(
        "--max-new-requirements-per-iteration",
        type=int,
        default=None,
        help="每轮迭代需改进需求+新增需求的总数（默认：从环境变量NEW_REQUIREMENTS_PER_ITERATION或配置中读取，默认值为10）"
    )
    
    parser.add_argument(
        "--prompt-version",
        type=str,
        default=None,
        help="提示词版本（默认：从环境变量PROMPT_VERSION或配置中读取，默认值为v1）"
    )
    
    parser.add_argument(
        "--gen",
        nargs="+",
        required=True,
        help="指定需要生成的版本：no-explore-clarify、no-clarify、数字（迭代次数）。必须至少指定一个数字版本。例如：--gen no-explore-clarify no-clarify 2 4 6"
    )
    
    args = parser.parse_args()
    
    # 解析--gen参数
    gen_versions = set()
    numbers = []
    for item in args.gen:
        if item == "no-explore-clarify" or item == "no-clarify":
            gen_versions.add(item)
        else:
            try:
                num = int(item)
                numbers.append(num)
                gen_versions.add(num)
            except ValueError:
                print(f"错误：无效的--gen参数值 '{item}'。必须是 'no-explore-clarify'、'no-clarify' 或数字", file=sys.stderr)
                sys.exit(1)
    
    # 必须至少指定一个数字版本
    if not numbers:
        print("错误：必须至少指定一个数字版本（迭代次数）", file=sys.stderr)
        sys.exit(1)
    
    max_iterations = max(numbers)
    
    # 加载输入
    if Path(args.input).exists():
        raw_input = load_file(args.input)
    else:
        raw_input = args.input
    
    # 加载基准SRS
    baseline_srs = ""
    if args.baseline_srs:
        baseline_srs = load_file(args.baseline_srs)
    
    # 加载基准生成的SRS
    baseline_gend_srs = ""
    if args.baseline_gend_srs:
        baseline_gend_srs = load_file(args.baseline_gend_srs)
    
    # 设置提示词版本（如果通过参数指定）
    if args.prompt_version:
        Config.PROMPT_VERSION = args.prompt_version
    
    # 验证配置
    try:
        Config.validate()
    except ValueError as e:
        print(f"配置错误：{e}", file=sys.stderr)
        print("提示：请设置OPENAI_API_KEY环境变量", file=sys.stderr)
        sys.exit(1)
    
    # 创建输出目录
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 初始化日志系统
    log_file_path = Logger.create_log_filename(str(output_dir))
    Logger.set_log_file(log_file_path)
    logger = get_logger("Main")
    
    # 运行工作流
    # 对版本进行排序（字符串在前，数字在后）
    def sort_gen_versions(versions):
        strings = sorted([v for v in versions if isinstance(v, str)])
        numbers = sorted([v for v in versions if isinstance(v, int)])
        return strings + numbers
    
    sorted_versions = sort_gen_versions(gen_versions)
    logger.info(f"开始运行SRS编制系统（模式：{args.ablation_mode}，版本：{sorted_versions}，最大迭代：{max_iterations}）")
    
    # srs_collection目录在output_dir的父目录下
    srs_collection_dir = output_dir.parent / "srs_collection"
    srs_collection_dir.mkdir(parents=True, exist_ok=True)
    
    # 从输入文件路径提取任务名
    input_path = Path(args.input)
    if input_path.exists():
        task_name = input_path.stem
    else:
        # 如果输入是文本，使用output_dir的名称作为任务名
        task_name = output_dir.name
    
    # 运行工作流
    orchestrator = WorkflowOrchestrator(
        ablation_mode=args.ablation_mode,  # type: ignore
        prompt_version=args.prompt_version
    )
    
    try:
        result = orchestrator.run(
            raw_input=raw_input,
            max_iterations=max_iterations,
            baseline_srs=baseline_srs,
            baseline_gend_srs=baseline_gend_srs,
            ablation_mode=args.ablation_mode,  # type: ignore
            max_new_requirements_per_iteration=args.max_new_requirements_per_iteration,
            output_dir_base=str(srs_collection_dir),
            task_name=task_name,
            gen_versions=gen_versions
        )
    except Exception as e:
        logger.error(f"工作流执行失败：{e}", exc_info=True)
        raise
    
    try:
        
        # 保存对比报告
        report_path = output_dir / "comparison_report.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(result["comparison_report"])
        
        # 复制输入文档到输出目录
        input_path = Path(args.input)
        if input_path.exists():
            input_suffix = input_path.suffix
            input_stem = input_path.stem
            input_dest = output_dir / f"input_{input_stem}{input_suffix}"
            shutil.copy2(input_path, input_dest)
        else:
            input_dest = output_dir / "input.txt"
            with open(input_dest, "w", encoding="utf-8") as f:
                f.write(raw_input)
        
        # 复制基准文档到输出目录
        if args.baseline_srs:
            baseline_path = Path(args.baseline_srs)
            if baseline_path.exists():
                baseline_suffix = baseline_path.suffix
                baseline_stem = baseline_path.stem
                baseline_dest = output_dir / f"baseline_srs_{baseline_stem}{baseline_suffix}"
                shutil.copy2(baseline_path, baseline_dest)
            else:
                logger.warning(f"基准文档文件不存在：{baseline_path}")
        
        # 复制基准生成的SRS文档到输出目录
        if args.baseline_gend_srs:
            baseline_gend_path = Path(args.baseline_gend_srs)
            if baseline_gend_path.exists():
                baseline_gend_suffix = baseline_gend_path.suffix
                baseline_gend_stem = baseline_gend_path.stem
                baseline_gend_dest = output_dir / f"baseline_gend_srs_{baseline_gend_stem}{baseline_gend_suffix}"
                shutil.copy2(baseline_gend_path, baseline_gend_dest)
            else:
                logger.warning(f"基准生成的SRS文档文件不存在：{baseline_gend_path}")
        
        # 输出统计信息
        logger.info(f"执行完成：总耗时 {result['total_time']:.2f}秒，最终需求数 {len(result['requirements'].requirements)}")
        
        # 输出版本生成结果（仅显示失败）
        if result.get("version_generation_results"):
            failed_versions = [name for name, r in result["version_generation_results"].items() if not r.get("success")]
            if failed_versions:
                logger.warning(f"版本生成失败：{failed_versions}")
        print(f"\n执行完成！所有文件已保存到：{output_dir.absolute()}")
        
    except Exception as e:
        logger.error(f"执行失败：{e}", exc_info=True)
        print(f"执行失败：{e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()