#!/usr/bin/env python3
"""监听srs-gen输出目录，自动评估新生成的文档"""
import argparse
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Set
import json

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
except ImportError:
    print("错误：需要安装watchdog库")
    print("请运行: pip install watchdog 或 uv pip install watchdog")
    sys.exit(1)


class SRSFileHandler(FileSystemEventHandler):
    """处理SRS文件变化的事件处理器"""
    
    def __init__(
        self,
        srs_collection_dir: Path,
        baseline_dir: Path,
        eval_output_dir: Path,
        eval_script_path: Path,
        debounce_seconds: float = 5.0,
        skip_existing: bool = True,
        max_workers: int | None = None
    ):
        """
        初始化处理器
        
        Args:
            srs_collection_dir: 要监听的srs_collection目录
            baseline_dir: 基准文档目录
            eval_output_dir: 评估输出目录
            eval_script_path: srs-eval的main.py路径
            debounce_seconds: 防抖时间（秒），在文件变化后等待多久再评估
            skip_existing: 是否跳过已评估的文件
            max_workers: 评估时的最大并行线程数（None时使用srs-eval的默认值）
        """
        self.srs_collection_dir = srs_collection_dir
        self.baseline_dir = baseline_dir
        self.eval_output_dir = eval_output_dir
        self.eval_script_path = eval_script_path
        self.debounce_seconds = debounce_seconds
        self.skip_existing = skip_existing
        self.max_workers = max_workers
        
        # 记录已处理的文件（避免重复评估）
        self.processed_files: Set[Path] = set()
        
        # 记录已评估的文件（用于skip_existing）
        # 格式：{stage_name: {doc_name, ...}}
        self.evaluated_files: dict[str, Set[str]] = {}
        self._load_evaluated_files()
        
        # 待处理的文件队列（用于防抖）
        self.pending_files: dict[Path, float] = {}  # {file_path: timestamp}
        
        # 最后评估时间
        self.last_eval_time = 0.0
        
        print(f"监听目录: {srs_collection_dir}")
        print(f"基准目录: {baseline_dir}")
        print(f"评估输出目录: {eval_output_dir}")
        print(f"防抖时间: {debounce_seconds}秒")
        print(f"跳过已评估: {skip_existing}")
        if max_workers is not None:
            print(f"最大并行线程数: {max_workers}")
        print()
    
    def _load_evaluated_files(self):
        """加载已评估的文件列表（按阶段组织）"""
        if not self.skip_existing:
            return
        
        # 从评估输出目录中查找已评估的文件
        if self.eval_output_dir.exists():
            for stage_dir in self.eval_output_dir.iterdir():
                if not stage_dir.is_dir():
                    continue
                
                stage_name = stage_dir.name
                if stage_name not in self.evaluated_files:
                    self.evaluated_files[stage_name] = set()
                
                # 查找评估结果文件
                for json_file in stage_dir.glob("*_evaluation.json"):
                    # 从JSON文件名提取文档名
                    doc_name = json_file.stem.replace("_evaluation", "")
                    self.evaluated_files[stage_name].add(doc_name)
        
        total_count = sum(len(files) for files in self.evaluated_files.values())
        print(f"已加载 {len(self.evaluated_files)} 个阶段的评估记录，共 {total_count} 个已评估文件")
    
    def _is_srs_file(self, file_path: Path) -> bool:
        """判断是否是SRS文档文件"""
        return file_path.suffix in ['.md', '.markdown'] and file_path.is_file()
    
    def _should_evaluate(self, file_path: Path) -> bool:
        """判断是否应该评估该文件"""
        # 检查是否在srs_collection目录下
        try:
            file_path.relative_to(self.srs_collection_dir)
        except ValueError:
            return False
        
        # 检查是否是SRS文件
        if not self._is_srs_file(file_path):
            return False
        
        # 检查是否已处理过
        if file_path in self.processed_files:
            return False
        
        # 检查是否已评估过（如果启用skip_existing）
        # 需要按阶段来判断，因为不同阶段的同名文件需要分别评估
        if self.skip_existing:
            # 获取阶段名（父目录名）
            stage_name = file_path.parent.name
            doc_name = file_path.stem
            
            # 检查该阶段是否已评估过该文件
            if stage_name in self.evaluated_files and doc_name in self.evaluated_files[stage_name]:
                return False
        
        return True
    
    def on_created(self, event: FileSystemEvent):
        """文件创建事件"""
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        if self._should_evaluate(file_path):
            # 添加到待处理队列
            self.pending_files[file_path] = time.time()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 检测到新文件: {file_path.relative_to(self.srs_collection_dir)}")
    
    def on_modified(self, event: FileSystemEvent):
        """文件修改事件"""
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        if self._should_evaluate(file_path):
            # 更新待处理队列中的时间戳
            self.pending_files[file_path] = time.time()
    
    def process_pending_files(self):
        """处理待评估的文件（防抖后）"""
        current_time = time.time()
        
        # 找出需要处理的文件（防抖时间已过）
        files_to_eval = []
        for file_path, timestamp in list(self.pending_files.items()):
            if current_time - timestamp >= self.debounce_seconds:
                files_to_eval.append(file_path)
                del self.pending_files[file_path]
        
        if files_to_eval:
            # 标记为已处理
            for file_path in files_to_eval:
                self.processed_files.add(file_path)
            
            # 执行评估
            self._run_evaluation()
    
    def scan_existing_files(self):
        """扫描已存在的文件，找出未评估的文件"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 扫描已存在的文件...")
        found_count = 0
        total_count = 0
        skipped_count = 0
        
        # 递归扫描srs_collection目录下的所有.md和.markdown文件
        for file_path in self.srs_collection_dir.rglob("*.md"):
            total_count += 1
            if self._should_evaluate(file_path):
                self.pending_files[file_path] = time.time()
                found_count += 1
                if found_count <= 10:  # 只显示前10个
                    print(f"  发现未评估文件: {file_path.relative_to(self.srs_collection_dir)}")
            else:
                skipped_count += 1
        
        for file_path in self.srs_collection_dir.rglob("*.markdown"):
            total_count += 1
            if self._should_evaluate(file_path):
                self.pending_files[file_path] = time.time()
                found_count += 1
                if found_count <= 10:  # 只显示前10个
                    print(f"  发现未评估文件: {file_path.relative_to(self.srs_collection_dir)}")
            else:
                skipped_count += 1
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 扫描完成: 总计 {total_count} 个文件, 跳过 {skipped_count} 个, 发现 {found_count} 个未评估文件")
        if found_count > 10:
            print(f"  ... 还有 {found_count - 10} 个未评估文件未显示")
        
        if found_count > 0:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 将在防抖时间后开始评估")
        print()
    
    def _run_evaluation(self):
        """运行评估"""
        current_time = time.time()
        
        # 避免频繁评估（至少间隔10秒）
        if current_time - self.last_eval_time < 10.0:
            return
        
        self.last_eval_time = current_time
        
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 开始评估srs_collection目录...")
        print("-" * 60)
        
        # 构建评估命令
        cmd = [
            sys.executable,
            str(self.eval_script_path),
            "--srs-collection-dir",
            str(self.srs_collection_dir),
            "--baseline-dir",
            str(self.baseline_dir),
            "--output-dir",
            str(self.eval_output_dir),
            "--skip-existing"
        ]
        
        # 如果指定了max_workers，添加到命令中
        if self.max_workers is not None:
            cmd.extend(["--max-workers", str(self.max_workers)])
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8"
            )
            
            if result.returncode == 0:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✓ 评估完成")
                # 重新加载已评估的文件列表
                self._load_evaluated_files()
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ 评估失败:")
                if result.stderr:
                    print(result.stderr[:500])  # 只显示前500字符
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✗ 评估出错: {e}")
        
        print("-" * 60)
        print()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="监听srs-gen输出目录，自动评估新生成的文档"
    )
    
    parser.add_argument(
        "--srs-collection-dir",
        type=str,
        required=True,
        help="srs_collection目录路径（要监听的目录）"
    )
    
    parser.add_argument(
        "--baseline-dir",
        type=str,
        required=True,
        help="基准文档目录路径"
    )
    
    parser.add_argument(
        "--eval-output-dir",
        type=str,
        default="eval_output",
        help="评估输出目录（默认：eval_output）"
    )
    
    parser.add_argument(
        "--eval-script",
        type=str,
        default=None,
        help="srs-eval的main.py路径（默认：自动查找）"
    )
    
    parser.add_argument(
        "--debounce",
        type=float,
        default=5.0,
        help="防抖时间（秒），文件变化后等待多久再评估（默认：5.0）"
    )
    
    parser.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="不跳过已评估的文件（默认：跳过）"
    )
    
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="评估时的最大并行线程数（默认：使用srs-eval的默认值，通常为min(文档数, 10)）"
    )
    
    args = parser.parse_args()
    
    # 验证目录
    srs_collection_dir = Path(args.srs_collection_dir)
    if not srs_collection_dir.exists():
        print(f"错误：srs_collection目录不存在: {srs_collection_dir}")
        sys.exit(1)
    
    baseline_dir = Path(args.baseline_dir)
    if not baseline_dir.exists():
        print(f"错误：基准目录不存在: {baseline_dir}")
        sys.exit(1)
    
    eval_output_dir = Path(args.eval_output_dir)
    eval_output_dir.mkdir(parents=True, exist_ok=True)
    
    # 查找srs-eval的main.py
    if args.eval_script:
        eval_script_path = Path(args.eval_script)
    else:
        # 自动查找：假设srs-eval在srs-gen的兄弟目录
        current_dir = Path(__file__).parent
        eval_script_path = current_dir.parent / "srs-eval" / "main.py"
    
    if not eval_script_path.exists():
        print(f"错误：找不到srs-eval的main.py: {eval_script_path}")
        print("请使用 --eval-script 参数指定路径")
        sys.exit(1)
    
    # 创建事件处理器
    event_handler = SRSFileHandler(
        srs_collection_dir=srs_collection_dir,
        baseline_dir=baseline_dir,
        eval_output_dir=eval_output_dir,
        eval_script_path=eval_script_path,
        debounce_seconds=args.debounce,
        skip_existing=args.skip_existing,
        max_workers=args.max_workers
    )
    
    # 创建观察者
    observer = Observer()
    observer.schedule(event_handler, str(srs_collection_dir), recursive=True)
    
    print("=" * 60)
    print("开始监听...")
    print("=" * 60)
    print()
    
    # 启动监听
    observer.start()
    
    # 启动时先扫描一次已存在的文件
    event_handler.scan_existing_files()
    
    try:
        # 定期处理待评估的文件
        while True:
            time.sleep(1.0)  # 每秒检查一次
            event_handler.process_pending_files()
    except KeyboardInterrupt:
        print("\n停止监听...")
        observer.stop()
    
    observer.join()
    print("监听已停止")


if __name__ == "__main__":
    main()

