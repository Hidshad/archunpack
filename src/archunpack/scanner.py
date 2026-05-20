from pathlib import Path
from .config import Config
from .types import Result, ScanSummary, ArchiveTask


class Scanner:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.last_summary: ScanSummary | None = None

    def scan(self, root_dir: Path) -> Result[ScanSummary]:
        """
        1. 调用 file_utils.find_archive_files(root_dir, config) 收集文件
        2. 逐文件调用 file_utils.identify_type() 魔数识别
           - 识别失败 → 回退 file_utils.detect_archive_type_from_path()
           - 仍失败 → 跳过并记录到 ignored_files
        3. 调用 file_utils.group_split_volumes() 合并分卷
        4. 每个组构建一个 ArchiveTask:
           - task_id 自动生成
           - file_paths = 组内文件列表
           - real_type = normalize_type(识别结果)
           - depth = 0, parent_task_id = None
           - status = PENDING
           - total_size_bytes = sum(组内各文件大小)
        5. 组装 ScanSummary 返回
        """
        if not root_dir.exists():
            return Result.fail(
                f"Scan root directory does not exist: {root_dir}", "IO_ERROR"
            )

        self.last_summary = ScanSummary(root_dir=root_dir)

        # Lazy imports to prevent circular references
        from .file_utils import (
            find_archive_files,
            identify_type,
            detect_archive_type_from_path,
            group_split_volumes,
            normalize_type,
        )

        files = find_archive_files(root_dir, self.config)
        self.last_summary.total_files = len(files)

        identified_types: dict[str, str] = {}
        for f in files:
            res = identify_type(f)
            if res.is_ok():
                identified_types[str(f)] = res.unwrap()
            else:
                ext_type = detect_archive_type_from_path(f)
                if ext_type:
                    identified_types[str(f)] = ext_type
                else:
                    self.last_summary.ignored_count += 1
                    self.last_summary.ignored_files.append(str(f))

        valid_files = [f for f in files if str(f) in identified_types]

        grouped = group_split_volumes(valid_files)

        for _, file_paths in grouped.items():
            raw_type = identified_types[str(file_paths[0])]
            real_type = normalize_type(raw_type)

            group_size = 0
            for p in file_paths:
                try:
                    group_size += p.stat().st_size
                except Exception:
                    pass

            name_lower = file_paths[0].name.lower()
            if name_lower.endswith(".tar.gz"):
                declared_ext = ".tar.gz"
            elif name_lower.endswith(".tar.bz2"):
                declared_ext = ".tar.bz2"
            elif name_lower.endswith(".tar.xz"):
                declared_ext = ".tar.xz"
            else:
                declared_ext = file_paths[0].suffix

            task = ArchiveTask(
                file_paths=file_paths,
                real_type=real_type,
                declared_ext=declared_ext,
                total_size_bytes=group_size,
                depth=0,
                parent_task_id=None,
            )

            self.last_summary.tasks.append(task)
            self.last_summary.total_size_bytes += group_size
            self.last_summary.type_distribution[real_type] = (
                self.last_summary.type_distribution.get(real_type, 0) + 1
            )

        return Result.ok(self.last_summary)

    def get_last_summary(self) -> ScanSummary | None:
        return self.last_summary
