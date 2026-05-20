from abc import ABC, abstractmethod
from pathlib import Path
from ..types import Result


class BaseEngine(ABC):
    @abstractmethod
    def extract(
        self,
        archive_paths: list[Path],  # 单文件或分卷列表
        output_dir: Path,
        password: str | None,
        overwrite_mode: str = "skip",
    ) -> Result[Path]:
        pass

    @abstractmethod
    def test_availability(self) -> Result[str]:
        """返回 "library" 或 "cli" 表示使用方式"""
        pass

    @staticmethod
    @abstractmethod
    def supported_format() -> str:
        pass
