import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Generic, TypeVar
from uuid import uuid4

T = TypeVar("T")


class TaskStatus(Enum):
    PENDING = "pending"
    SCANNING = "scanning"
    TRYING_PWD = "trying_pwd"
    EXTRACTING = "extracting"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"
    ERROR = "error"


@dataclass
class Result(Generic[T]):
    success: bool
    data: T | None = None
    error: str | None = None
    error_code: str | None = None  # "PASSWORD_FAIL" | "ENGINE_UNAVAILABLE" | "IO_ERROR" ...

    @staticmethod
    def ok(data: T) -> "Result[T]":
        return Result(success=True, data=data)

    @staticmethod
    def fail(error: str, code: str = "UNKNOWN") -> "Result[T]":
        return Result(success=False, data=None, error=error, error_code=code)

    def is_ok(self) -> bool:
        return self.success

    def is_fail(self) -> bool:
        return not self.success

    def unwrap(self) -> T:
        if not self.success:
            raise RuntimeError(self.error or "Error in Result")
        return self.data  # type: ignore

    def unwrap_or(self, default: T) -> T:
        if not self.success or self.data is None:
            return default
        return self.data


@dataclass
class ArchiveTask:
    task_id: str = field(default_factory=lambda: uuid4().hex)
    file_paths: list[Path] = field(default_factory=list)  # 单文件列表1个元素，分卷多个
    real_type: str = ""  # "7z" | "zip" | "rar" | "tar" ...
    declared_ext: str = ""
    is_encrypted: bool | None = None
    total_size_bytes: int = 0
    depth: int = 0
    parent_task_id: str | None = None
    password: str | None = None
    status: TaskStatus = TaskStatus.PENDING
    status_message: str = ""
    output_path: Path | None = None
    inner_archives: list["ArchiveTask"] = field(default_factory=list)
    created_at: float = 0.0
    finished_at: float | None = None

    def __post_init__(self) -> None:
        if self.created_at == 0.0:
            self.created_at = time.time()


@dataclass
class PasswordInfo:
    text: str
    hit_count: int = 0
    last_hit_at: float = 0.0  # 0=从未命中


@dataclass
class ScanSummary:
    root_dir: Path | None = None
    total_files: int = 0
    total_size_bytes: int = 0
    type_distribution: dict[str, int] = field(default_factory=dict)
    tasks: list[ArchiveTask] = field(default_factory=list)
    ignored_count: int = 0
    ignored_files: list[str] = field(default_factory=list)


@dataclass
class RunSummary:
    total_tasks: int = 0
    success_count: int = 0
    failed_count: int = 0
    error_count: int = 0
    skipped_count: int = 0
    total_duration_seconds: float = 0.0
    total_extracted_bytes: int = 0
    failed_tasks: list[ArchiveTask] = field(default_factory=list)
    error_tasks: list[ArchiveTask] = field(default_factory=list)
