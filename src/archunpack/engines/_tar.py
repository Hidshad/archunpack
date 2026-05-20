import tarfile
from pathlib import Path
from ..types import Result
from .base import BaseEngine
from .factory import register_engine


class TarEngine(BaseEngine):
    def test_availability(self) -> Result[str]:
        """tarfile 是标准库，始终返回 "library" """
        return Result.ok("library")

    def extract(
        self,
        archive_paths: list[Path],
        output_dir: Path,
        password: str | None,
        overwrite_mode: str = "skip",
    ) -> Result[Path]:
        if not archive_paths:
            return Result.fail("No archive files specified", "IO_ERROR")

        archive_path = archive_paths[0]
        output_dir.mkdir(parents=True, exist_ok=True)

        name_lower = archive_path.name.lower()

        # Determine packaging suffix
        mode = "r"
        if name_lower.endswith((".tar.gz", ".tgz")):
            mode = "r:gz"
        elif name_lower.endswith((".tar.bz2", ".tbz2")):
            mode = "r:bz2"
        elif name_lower.endswith((".tar.xz", ".txz")):
            mode = "r:xz"
        elif name_lower.endswith(".tar"):
            mode = "r"
        else:
            mode = "r:*"

        try:
            with tarfile.open(str(archive_path), mode) as tf:  # type: ignore[call-overload]
                tf.extractall(path=str(output_dir))
            return Result.ok(output_dir)
        except Exception as e:
            return Result.fail(f"Tar extraction failed: {e}", "ENGINE_ERROR")

    @staticmethod
    def supported_format() -> str:
        return "tar"


# 自注册所有支持的 tar 变体
register_engine("tar", TarEngine)
register_engine("tar.gz", TarEngine)
register_engine("tar.bz2", TarEngine)
register_engine("tar.xz", TarEngine)
