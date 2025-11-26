"""多智能体SRS智能编制系统主入口"""
import argparse
import shutil
import sys
from pathlib import Path
from src.workflow.orchestrator import WorkflowOrchestrator
from src.config import Config, AblationMode
from src.utils.logger import Logger, get_logger


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
        "--max-iterations",
        type=int,
        default=None,
        help="最大迭代次数（默认：从环境变量MAX_ITERATIONS或配置中读取，默认值为5）"
    )
    
    parser.add_argument(
        "--max-new-requirements-per-iteration",
        type=int,
        default=None,
        help="每轮迭代新增需求数量（默认：从环境变量NEW_REQUIREMENTS_PER_ITERATION或配置中读取，默认值为10）"
    )
    
    parser.add_argument(
        "--prompt-version",
        type=str,
        default=None,
        help="提示词版本（默认：从环境变量PROMPT_VERSION或配置中读取，默认值为v1）"
    )
    
    parser.add_argument(
        "--enable-parallel-generation",
        action="store_true",
        default=False,
        help="启用并行生成功能：在运行过程中自动生成no-explore-clarify、no-clarify和所有迭代版本的SRS文档"
    )
    
    args = parser.parse_args()
    
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
    logger.info(f"开始运行SRS编制系统（模式：{args.ablation_mode}）...")
    logger.info(f"输出目录：{output_dir.absolute()}")
    logger.info(f"日志文件：{log_file_path}")
    if args.prompt_version:
        logger.info(f"提示词版本：{args.prompt_version}")
    if args.enable_parallel_generation:
        logger.info("并行生成功能已启用：将自动生成所有版本（no-explore-clarify、no-clarify、iter1-N）")
    
    orchestrator = WorkflowOrchestrator(
        ablation_mode=args.ablation_mode,  # type: ignore
        prompt_version=args.prompt_version
    )
    
    try:
        # 主输出目录就是output_dir（不创建子目录）
        main_output_dir = output_dir
        
        # 如果启用并行生成，需要确定srs_collection目录和任务名
        srs_collection_dir = None
        task_name = None
        if args.enable_parallel_generation:
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
        
        result = orchestrator.run(
            raw_input=raw_input,
            baseline_srs=baseline_srs,
            baseline_gend_srs=baseline_gend_srs,
            ablation_mode=args.ablation_mode,  # type: ignore
            max_iterations=args.max_iterations,
            max_new_requirements_per_iteration=args.max_new_requirements_per_iteration,
            output_dir_base=str(srs_collection_dir) if args.enable_parallel_generation else None,
            task_name=task_name if args.enable_parallel_generation else None,
            enable_parallel_generation=args.enable_parallel_generation
        )
        
        # 保存SRS文档（主流程的最终版本）
        srs_path = main_output_dir / "srs_document.md"
        with open(srs_path, "w", encoding="utf-8") as f:
            f.write(result["srs_document"])
        logger.info(f"主流程SRS文档已保存到：{srs_path}")
        
        # 保存对比报告（保存到主输出目录）
        report_path = main_output_dir / "comparison_report.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(result["comparison_report"])
        logger.info(f"对比报告已保存到：{report_path}")
        
        # 复制输入文档到主输出目录
        input_path = Path(args.input)
        if input_path.exists():
            # 如果是文件，使用规范命名：input_<原文件名>
            input_suffix = input_path.suffix
            input_stem = input_path.stem
            input_dest = main_output_dir / f"input_{input_stem}{input_suffix}"
            shutil.copy2(input_path, input_dest)
            logger.info(f"输入文档已复制到：{input_dest}")
        else:
            # 如果是文本内容，保存为文件
            input_dest = main_output_dir / "input.txt"
            with open(input_dest, "w", encoding="utf-8") as f:
                f.write(raw_input)
            logger.info(f"输入内容已保存到：{input_dest}")
        
        # 复制基准文档到主输出目录
        if args.baseline_srs:
            baseline_path = Path(args.baseline_srs)
            if baseline_path.exists():
                # 使用规范命名：baseline_srs_<原文件名> 或 baseline_srs.md
                baseline_suffix = baseline_path.suffix
                baseline_stem = baseline_path.stem
                baseline_dest = main_output_dir / f"baseline_srs_{baseline_stem}{baseline_suffix}"
                shutil.copy2(baseline_path, baseline_dest)
                logger.info(f"基准文档已复制到：{baseline_dest}")
            else:
                logger.warning(f"基准文档文件不存在：{baseline_path}")
        
        # 复制基准生成的SRS文档到主输出目录
        if args.baseline_gend_srs:
            baseline_gend_path = Path(args.baseline_gend_srs)
            if baseline_gend_path.exists():
                baseline_gend_suffix = baseline_gend_path.suffix
                baseline_gend_stem = baseline_gend_path.stem
                baseline_gend_dest = main_output_dir / f"baseline_gend_srs_{baseline_gend_stem}{baseline_gend_suffix}"
                shutil.copy2(baseline_gend_path, baseline_gend_dest)
                logger.info(f"基准生成的SRS文档已复制到：{baseline_gend_dest}")
            else:
                logger.warning(f"基准生成的SRS文档文件不存在：{baseline_gend_path}")
        
        # 输出统计信息
        logger.info("\n=== 执行统计 ===")
        logger.info(f"总耗时：{result['total_time']:.2f}秒")
        logger.info(f"最终需求数：{len(result['requirements'].requirements)}")
        logger.info("\n各代理耗时：")
        for agent, time_cost in result["timer_summary"].items():
            logger.info(f"  {agent}: {time_cost:.2f}秒")
        
        # 输出并行生成结果
        if args.enable_parallel_generation and result.get("parallel_generation_results"):
            logger.info("\n=== 并行生成结果 ===")
            for version_name, gen_result in result["parallel_generation_results"].items():
                if gen_result.get("success"):
                    logger.info(f"✓ {version_name}: {gen_result.get('path')}")
                else:
                    logger.error(f"✗ {version_name}: {gen_result.get('error')}")
        
        logger.info("\n执行完成！")
        if args.enable_parallel_generation:
            print(f"\n执行完成！所有文件已保存到：{output_dir.absolute()}")
            print(f"主流程文档：{main_output_dir.absolute()}")
        else:
            print(f"\n执行完成！所有文件已保存到：{output_dir.absolute()}")
        
    except Exception as e:
        logger.error(f"执行失败：{e}", exc_info=True)
        print(f"执行失败：{e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()