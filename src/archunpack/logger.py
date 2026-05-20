import csv
import logging
import time
from pathlib import Path
from typing import Callable
from .config import Config
from .types import Result, ArchiveTask, RunSummary, TaskStatus


class AppLogger:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.log_dir = config.log_dir
        self.log_file = self.log_dir / "archunpack.log"
        self.callbacks: list[Callable[[str, str], None]] = []

        self.success_tasks: list[ArchiveTask] = []
        self.failed_tasks: list[ArchiveTask] = []
        self.error_tasks: list[ArchiveTask] = []
        self.skipped_tasks: list[ArchiveTask] = []
        self.attempt_counts: dict[str, int] = {}
        self.start_time = time.time()

    def setup(self) -> Result[bool]:
        """创建 log 目录，配置 file_handler 和 console_handler"""
        try:
            self.config.ensure_dirs()
            logger = logging.getLogger("archunpack")
            logger.setLevel(self.config.log_level)

            if not logger.handlers:
                ch = logging.StreamHandler()
                ch.setLevel(self.config.log_level)

                fh = logging.FileHandler(self.log_file, encoding="utf-8")
                fh.setLevel(self.config.log_level)

                formatter = logging.Formatter(
                    "[%(asctime)s] [%(levelname)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
                ch.setFormatter(formatter)
                fh.setFormatter(formatter)

                logger.addHandler(ch)
                logger.addHandler(fh)

            return Result.ok(True)
        except Exception as e:
            return Result.fail(f"Failed to set up logging: {e}", "IO_ERROR")

    def _log_and_callback(self, level: int, msg: str) -> None:
        logger = logging.getLogger("archunpack")
        logger.log(level, msg)

        level_name = logging.getLevelName(level)
        for cb in self.callbacks:
            try:
                cb(level_name, msg)
            except Exception:
                pass

    def debug(self, msg: str) -> None:
        self._log_and_callback(logging.DEBUG, msg)

    def info(self, msg: str) -> None:
        self._log_and_callback(logging.INFO, msg)

    def warning(self, msg: str) -> None:
        self._log_and_callback(logging.WARNING, msg)

    def error(self, msg: str) -> None:
        self._log_and_callback(logging.ERROR, msg)

    # 业务日志
    def log_task_start(self, task: ArchiveTask) -> None:
        self.info(f"Task started: {task.file_paths[0].name} (depth={task.depth})")

    def log_task_done(self, task: ArchiveTask, duration_ms: int) -> None:
        self.success_tasks.append(task)
        self.info(
            f"Task finished: {task.file_paths[0].name} in {duration_ms}ms"
            + (f" with pwd '{self.sanitize(task.password, task.password)}'" if task.password else "")
        )

    def log_task_fail(self, task: ArchiveTask, reason: str) -> None:
        if task.status == TaskStatus.ERROR:
            self.error_tasks.append(task)
            self.error(f"Task error: {task.file_paths[0].name} - Reason: {reason}")
        else:
            self.failed_tasks.append(task)
            self.warning(f"Task failed: {task.file_paths[0].name} - Reason: {reason}")

    def log_password_attempt(self, task: ArchiveTask, pwd_idx: int, success: bool) -> None:
        self.attempt_counts[task.task_id] = self.attempt_counts.get(task.task_id, 0) + 1
        status = "SUCCESS" if success else "FAILED"
        self.debug(
            f"Password attempt #{pwd_idx} for {task.file_paths[0].name}: {status}"
        )

    def log_type_mismatch(self, path: Path, declared: str, real: str) -> None:
        self.warning(
            f"Type mismatch detected for {path.name}: "
            f"Declared extension: {declared}, Identified real signature: {real}"
        )

    def log_nested_found(self, parent: ArchiveTask, count: int) -> None:
        self.info(
            f"Discovered {count} nested archive(s) inside {parent.file_paths[0].name}"
        )

    # GUI 回调
    def add_callback(self, cb: Callable[[str, str], None]) -> None:
        self.callbacks.append(cb)

    # 导入导出
    def export_failed_tasks(self, output_path: Path) -> Result[Path]:
        """将失败任务导出为 CSV"""
        try:
            # Ensure folder exists
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "task_id",
                        "file_path",
                        "real_type",
                        "reason",
                        "attempted_passwords_count",
                    ]
                )
                # Combine both failed and error tasks
                all_failed = self.failed_tasks + self.error_tasks
                for t in all_failed:
                    f_path = str(t.file_paths[0]) if t.file_paths else ""
                    attempts = self.attempt_counts.get(t.task_id, 0)
                    writer.writerow(
                        [
                            t.task_id,
                            f_path,
                            t.real_type,
                            t.status_message,
                            attempts,
                        ]
                    )
            return Result.ok(output_path)
        except Exception as e:
            return Result.fail(f"Failed to export failed tasks: {e}", "IO_ERROR")

    def load_failed_tasks(self, csv_path: Path) -> Result[list[ArchiveTask]]:
        """从 CSV 恢复失败任务列表"""
        try:
            if not csv_path.exists():
                return Result.fail(
                    f"CSV path {csv_path} does not exist", "FILE_NOT_FOUND"
                )

            tasks: list[ArchiveTask] = []
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                if not header:
                    return Result.ok([])

                for row in reader:
                    if len(row) >= 4:
                        task_id, file_path, real_type, reason = row[:4]
                        
                        # Reconstruct file_paths
                        paths = [Path(file_path)] if file_path else []
                        
                        task = ArchiveTask(
                            task_id=task_id,
                            file_paths=paths,
                            real_type=real_type,
                            status=TaskStatus.FAILED,
                            status_message=reason,
                        )
                        tasks.append(task)
                        
                        # Attempt count mapping
                        if len(row) >= 5:
                            try:
                                self.attempt_counts[task_id] = int(row[4])
                            except ValueError:
                                self.attempt_counts[task_id] = 0

            return Result.ok(tasks)
        except Exception as e:
            return Result.fail(f"Failed to load failed tasks: {e}", "IO_ERROR")

    # 汇总
    def get_run_summary(self) -> RunSummary:
        duration = time.time() - self.start_time
        total_extracted = sum(t.total_size_bytes for t in self.success_tasks)

        return RunSummary(
            total_tasks=len(self.success_tasks)
            + len(self.failed_tasks)
            + len(self.error_tasks)
            + len(self.skipped_tasks),
            success_count=len(self.success_tasks),
            failed_count=len(self.failed_tasks),
            error_count=len(self.error_tasks),
            skipped_count=len(self.skipped_tasks),
            total_duration_seconds=duration,
            total_extracted_bytes=total_extracted,
            failed_tasks=self.failed_tasks,
            error_tasks=self.error_tasks,
        )

    def close(self) -> None:
        logger = logging.getLogger("archunpack")
        handlers = list(logger.handlers)
        for handler in handlers:
            handler.close()
            logger.removeHandler(handler)

    # 脱敏
    @staticmethod
    def sanitize(message: str, password: str | None) -> str:
        """将明文密码替换为 ***"""
        if not password:
            return message
        return message.replace(password, "***")
