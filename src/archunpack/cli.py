import argparse
import sys
from pathlib import Path
from .config import Config
from .logger import AppLogger
from .password_mgr import PasswordManager
from .scanner import Scanner
from .extractor import Extractor
from .task_queue import TaskQueue
from .types import ArchiveTask, Result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="archunpack: Multi-threaded recursive archive batch extraction utility with password trial."
    )
    parser.add_argument(
        "source",
        type=str,
        help="Source directory containing archives or path to a single archive file.",
    )
    parser.add_argument(
        "output",
        type=str,
        help="Output destination directory.",
    )
    parser.add_argument(
        "-p",
        "--password-file",
        type=str,
        help="Path to the password dictionary file (.txt).",
    )
    parser.add_argument(
        "-d",
        "--max-depth",
        type=int,
        default=5,
        help="Maximum recursion depth for nested archives (default: 5).",
    )
    parser.add_argument(
        "--no-delete",
        action="store_true",
        help="Do NOT delete intermediate decrypted nested archives.",
    )
    parser.add_argument(
        "--delete-source",
        action="store_true",
        help="Delete the original source archives after successful extraction.",
    )
    parser.add_argument(
        "--overwrite-mode",
        choices=["skip", "overwrite", "rename"],
        default="skip",
        help="Behavior when output directory already exists (default: skip).",
    )
    parser.add_argument(
        "-j",
        "--threads",
        type=int,
        default=0,
        help="Maximum number of parallel workers. 0 means CPU core count (default: 0).",
    )
    parser.add_argument(
        "--scan-only",
        action="store_true",
        help="Only scan the source directory and show the archive analysis summary without extracting.",
    )
    parser.add_argument(
        "--failed-csv",
        type=str,
        help="Path to export a list of failed and error tasks as a CSV file.",
    )
    return parser.parse_args()


def run_cli() -> int:
    args = parse_args()

    # 1. 构造 Config
    config = Config.from_args(
        source_dir=args.source,
        output_dir=args.output,
        password_file=args.password_file,
        max_depth=args.max_depth,
        delete_intermediate=not args.no_delete,
        delete_source=args.delete_source,
        overwrite_mode=args.overwrite_mode,
        max_parallel=args.threads,
    )

    # 2. 构造并启动 Logger 和 PasswordManager
    logger = AppLogger(config)
    log_setup = logger.setup()
    if log_setup.is_fail():
        print(f"ERROR setting up logging: {log_setup.error}", file=sys.stderr)
        return 1

    password_mgr = PasswordManager(config)
    if config.password_file:
        logger.info(f"Loaded {len(password_mgr)} passwords from {config.password_file}")

    source_path = Path(args.source)
    if not source_path.exists():
        logger.error(f"Source path does not exist: {source_path}")
        return 1

    # 3. 扫描文件
    logger.info(f"Scanning source directory: {source_path}")
    scanner = Scanner(config)
    scan_res = scanner.scan(source_path)
    if scan_res.is_fail():
        logger.error(f"Scanning failed: {scan_res.error}")
        return 1

    summary = scan_res.unwrap()
    logger.info(f"Scan complete: Found {len(summary.tasks)} archive(s) (Total size: {summary.total_size_bytes} bytes)")

    # 打印扫描概述表
    print("\n" + "=" * 60)
    print("                      SCAN SUMMARY")
    print("=" * 60)
    print(f"Root path:       {summary.root_dir}")
    print(f"Total files:     {summary.total_files}")
    print(f"Total archives:  {len(summary.tasks)}")
    print(f"Total size:      {summary.total_size_bytes} bytes")
    print(f"Ignored files:   {summary.ignored_count}")
    print("-" * 60)
    print("Format Distribution:")
    for fmt, count in summary.type_distribution.items():
        print(f"  - {fmt}: {count}")
    print("=" * 60)

    if args.scan_only:
        print("\nScan-only mode active. Extraction skipped.")
        logger.close()
        return 0

    if not summary.tasks:
        logger.info("No archives found to extract.")
        logger.close()
        return 0

    # 4. 执行解压
    logger.info("Starting batch extraction process...")
    extractor = Extractor(config, password_mgr, logger)
    queue = TaskQueue(config, extractor.extract)
    extractor.is_cancelled = queue._force_stop_event.is_set

    # 注册事件回调，实时在控制台打印进度
    def handle_task_start(task: ArchiveTask) -> None:
        logger.info(f"[Queue] Task started: {task.file_paths[0].name} (depth={task.depth})")

    def handle_task_complete(task: ArchiveTask, result: Result[ArchiveTask]) -> None:
        status_name = task.status.value.upper()
        if result.is_ok():
            logger.info(f"[Queue] Task finished successfully: {task.file_paths[0].name} (status={status_name})")
        else:
            logger.warning(f"[Queue] Task failed/error: {task.file_paths[0].name} (status={status_name}) - {result.error}")

    queue.on_task_start = handle_task_start
    queue.on_task_complete = handle_task_complete

    # 任务装载
    for task in summary.tasks:
        queue.add_task(task)

    # 启动多线程分发
    queue.start()

    # 阻塞等待完成
    try:
        queue.join()
    except KeyboardInterrupt:
        logger.warning("KeyboardInterrupt received. Terminating extraction queue...")
        queue.force_stop()
        queue.join()

    # 5. 后置处理与报告
    # 保存密码本热点文件 (.hot)
    if config.password_file and len(password_mgr) > 0:
        save_res = password_mgr.save_hot_passwords()
        if save_res.is_ok():
            logger.info(f"Saved optimized hot passwords to: {save_res.unwrap()}")

    # 导出失败任务 CSV
    if args.failed_csv:
        csv_path = Path(args.failed_csv)
        export_res = logger.export_failed_tasks(csv_path)
        if export_res.is_ok():
            logger.info(f"Exported failed tasks list to CSV: {export_res.unwrap()}")

    # 输出最终运行汇总报告
    run_sum = logger.get_run_summary()
    print("\n" + "=" * 60)
    print("                    EXTRACTION REPORT")
    print("=" * 60)
    print(f"Total tasks processed: {run_sum.total_tasks}")
    print(f"Successfully extracted: {run_sum.success_count}")
    print(f"Failed decryptions:     {run_sum.failed_count}")
    print(f"Errors occurred:        {run_sum.error_count}")
    print(f"Skipped tasks:          {run_sum.skipped_count}")
    print(f"Total size extracted:   {run_sum.total_extracted_bytes} bytes")
    print(f"Total time elapsed:     {run_sum.total_duration_seconds:.2f} seconds")
    print("=" * 60)

    # 释放 logger 资源，确保句柄被正确关闭
    logger.close()

    if run_sum.failed_count > 0 or run_sum.error_count > 0:
        return 1
    return 0


def main() -> None:
    sys.exit(run_cli())


if __name__ == "__main__":
    main()
