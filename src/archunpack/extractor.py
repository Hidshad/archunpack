import shutil
import time
from pathlib import Path
from typing import Callable
from .config import Config
from .types import ArchiveTask, Result, TaskStatus
from .password_mgr import PasswordManager
from .logger import AppLogger
from .engines.factory import create_engine
from .file_utils import detect_encryption, ensure_output_path, safe_delete
from .scanner import Scanner


class Extractor:
    def __init__(
        self,
        config: Config,
        password_mgr: PasswordManager,
        logger: AppLogger,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self.config = config
        self.password_mgr = password_mgr
        self.logger = logger
        self.is_cancelled = is_cancelled

    def extract(self, task: ArchiveTask) -> Result[ArchiveTask]:
        """
        执行解压流程：
        1. 检查输入文件是否存在。
        2. 确定输出目录镜像结构，处理 overwrite_mode (skip, overwrite, rename)。
        3. 检测加密状态，执行密码破解循环或直接解压。
        4. 记录日志与命中密码。
        5. 如果解压成功，扫描嵌套压缩包。
        6. 处理 depth > 0 时的中间压缩包删除。
        """
        task.status = TaskStatus.EXTRACTING
        self.logger.log_task_start(task)
        start_time = time.time()

        if not task.file_paths:
            msg = "No file paths specified in task"
            task.status = TaskStatus.ERROR
            task.status_message = msg
            self.logger.log_task_fail(task, msg)
            return Result.fail(msg, "IO_ERROR")

        # 检查所有分卷文件是否存在
        for path in task.file_paths:
            if not path.exists():
                msg = f"Archive file does not exist: {path}"
                task.status = TaskStatus.ERROR
                task.status_message = msg
                self.logger.log_task_fail(task, msg)
                return Result.fail(msg, "IO_ERROR")

        # 确定输出路径镜像结构
        # depth == 0 时以 source_dir 为源基准；depth > 0 时嵌套在 output_dir 下，以 output_dir 为源基准
        source_root = self.config.source_dir if task.depth == 0 else self.config.output_dir
        if not source_root:
            source_root = task.file_paths[0].parent

        output_root = self.config.output_dir if self.config.output_dir else Path(".")
        output_dir = ensure_output_path(task.file_paths[0], source_root, output_root)

        # 处理覆盖模式
        if output_dir.exists() and any(output_dir.iterdir()):
            if self.config.overwrite_mode == "skip":
                task.status = TaskStatus.SKIPPED
                task.status_message = "Output directory already exists, skipping."
                self.logger.skipped_tasks.append(task)
                self.logger.info(f"Task skipped: {task.file_paths[0].name}")
                task.finished_at = time.time()
                return Result.ok(task)
            elif self.config.overwrite_mode == "overwrite":
                # 删除已有文件夹
                del_res = safe_delete(output_dir, output_root)
                if del_res.is_fail():
                    msg = f"Failed to overwrite output directory: {del_res.error}"
                    task.status = TaskStatus.ERROR
                    task.status_message = msg
                    self.logger.log_task_fail(task, msg)
                    return Result.fail(msg, "IO_ERROR")
            elif self.config.overwrite_mode == "rename":
                # 重命名输出文件夹，如 output_dir_1
                counter = 1
                base_name = output_dir.name
                while True:
                    candidate = output_dir.parent / f"{base_name}_{counter}"
                    if not candidate.exists() or not any(candidate.iterdir()):
                        output_dir = candidate
                        break
                    counter += 1

        # 确定加密状态
        if task.is_encrypted is None:
            enc_res = detect_encryption(task.file_paths[0], task.real_type)
            if enc_res.is_ok():
                task.is_encrypted = enc_res.unwrap()
            else:
                # 无法检测时，保守假设未加密，如果解压失败再试密码？
                # 这里默认置为 False，如果后面引擎报密码错误，再判定
                task.is_encrypted = False

        # 为防止解压残缺文件污染目标文件夹，先解压到临时目录
        tmp_dir = output_dir.with_name(output_dir.name + "_tmp")

        success = False
        pwd_used = None
        engine_res = None

        # 加密时，尝试密码列表
        if task.is_encrypted:
            task.status = TaskStatus.TRYING_PWD
            passwords = self.password_mgr.get_ordered_passwords()
            if not passwords:
                # 如果没有密码可用，尝试使用 None (无密码) 以防魔数判断失误，或者直接报错
                passwords = [None]  # type: ignore

            for idx, pwd in enumerate(passwords):
                if self.is_cancelled and self.is_cancelled():
                    msg = "Task cancelled by user"
                    task.status = TaskStatus.SKIPPED
                    task.status_message = msg
                    self.logger.log_task_fail(task, msg)
                    safe_delete(tmp_dir, output_root)
                    return Result.fail(msg, "CANCELLED")

                engine_res = create_engine(task.real_type)
                if engine_res.is_fail():
                    msg = f"Failed to create engine: {engine_res.error}"
                    task.status = TaskStatus.ERROR
                    task.status_message = msg
                    self.logger.log_task_fail(task, msg)
                    safe_delete(tmp_dir, output_root)
                    return Result.fail(msg, "ENGINE_UNAVAILABLE")

                engine = engine_res.unwrap()
                ext_res = engine.extract(
                    task.file_paths,
                    tmp_dir,
                    pwd,
                    self.config.overwrite_mode,
                )

                if ext_res.is_ok():
                    success = True
                    pwd_used = pwd
                    self.logger.log_password_attempt(task, idx + 1, success=True)
                    if pwd:
                        self.password_mgr.record_hit(pwd)
                    break
                else:
                    self.logger.log_password_attempt(task, idx + 1, success=False)
                    # 密码错误继续，清理临时目录以备下一次尝试
                    last_error = ext_res.error or "Decompression failed"
                    safe_delete(tmp_dir, output_root)
        else:
            if self.is_cancelled and self.is_cancelled():
                msg = "Task cancelled by user"
                task.status = TaskStatus.SKIPPED
                task.status_message = msg
                self.logger.log_task_fail(task, msg)
                return Result.fail(msg, "CANCELLED")

            # 未加密，直接解压
            engine_res = create_engine(task.real_type)
            if engine_res.is_fail():
                msg = f"Failed to create engine: {engine_res.error}"
                task.status = TaskStatus.ERROR
                task.status_message = msg
                self.logger.log_task_fail(task, msg)
                safe_delete(tmp_dir, output_root)
                return Result.fail(msg, "ENGINE_UNAVAILABLE")

            engine = engine_res.unwrap()
            ext_res = engine.extract(
                task.file_paths,
                tmp_dir,
                None,
                self.config.overwrite_mode,
            )
            if ext_res.is_ok():
                success = True
            else:
                last_error = ext_res.error or "Decompression failed"
                safe_delete(tmp_dir, output_root)

        if success:
            try:
                # 成功后重命名为最终目录
                shutil.move(str(tmp_dir), str(output_dir))
            except Exception as e:
                safe_delete(tmp_dir, output_root)
                msg = f"Failed to rename temp directory: {e}"
                task.status = TaskStatus.ERROR
                task.status_message = msg
                self.logger.log_task_fail(task, msg)
                return Result.fail(msg, "IO_ERROR")
            # 记录解压成功
            duration_ms = int((time.time() - start_time) * 1000)
            task.status = TaskStatus.DONE
            task.password = pwd_used
            task.output_path = output_dir
            task.finished_at = time.time()
            self.logger.log_task_done(task, duration_ms)

            # 递归搜索嵌套压缩包
            if task.depth < self.config.max_depth:
                scanner = Scanner(self.config)
                scan_res = scanner.scan(output_dir)
                if scan_res.is_ok():
                    nested_summary = scan_res.unwrap()
                    if nested_summary.tasks:
                        for child in nested_summary.tasks:
                            child.depth = task.depth + 1
                            child.parent_task_id = task.task_id
                            task.inner_archives.append(child)
                        self.logger.log_nested_found(task, len(nested_summary.tasks))

            # 中间压缩包删除 (depth > 0)
            if self.config.delete_intermediate and task.depth > 0:
                for path in task.file_paths:
                    safe_delete(path, output_root)

            # 原始压缩包删除 (depth == 0)
            if self.config.delete_source and task.depth == 0:
                for path in task.file_paths:
                    # 限制仅删除 source_dir 内的文件以防误删
                    safe_delete(path, self.config.source_dir)

            return Result.ok(task)
        else:
            # 解压失败
            task.status = TaskStatus.FAILED
            task.status_message = last_error
            task.finished_at = time.time()
            self.logger.log_task_fail(task, last_error)
            return Result.fail(last_error, "PASSWORD_FAIL" if task.is_encrypted else "EXTRACT_ERROR")
