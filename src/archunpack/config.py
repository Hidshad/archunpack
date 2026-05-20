import dataclasses
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Config:
    source_dir: Path | None = None
    output_dir: Path | None = None
    password_file: Path | None = None
    max_depth: int = 5
    delete_intermediate: bool = True
    delete_source: bool = False
    overwrite_mode: str = "skip"  # "skip" | "overwrite" | "rename"
    max_parallel: int = 0  # 0=自动
    log_dir: Path = field(default_factory=lambda: Path("./logs"))
    log_level: str = "INFO"
    skip_extensions: list[str] = field(
        default_factory=lambda: [
            ".mp4",
            ".mkv",
            ".avi",
            ".mov",
            ".jpg",
            ".png",
            ".txt",
            ".html",
            ".url",
            ".apk",
            ".exe",
            ".dll",
        ]
    )
    skip_prefixes: list[str] = field(default_factory=lambda: ["._"])
    seven_zip_path: Path | None = None  # None = 自动检测
    winrar_path: Path | None = None

    def __post_init__(self) -> None:
        if self.overwrite_mode not in ("skip", "overwrite", "rename"):
            raise ValueError("overwrite_mode must be 'skip', 'overwrite', or 'rename'")
        if isinstance(self.source_dir, str):
            self.source_dir = Path(self.source_dir)
        if isinstance(self.output_dir, str):
            self.output_dir = Path(self.output_dir)
        if isinstance(self.password_file, str):
            self.password_file = Path(self.password_file)
        if isinstance(self.log_dir, str):
            self.log_dir = Path(self.log_dir)
        if isinstance(self.seven_zip_path, str):
            self.seven_zip_path = Path(self.seven_zip_path)
        if isinstance(self.winrar_path, str):
            self.winrar_path = Path(self.winrar_path)

    @staticmethod
    def detect_7zip() -> Path | None:
        which_path = shutil.which("7z") or shutil.which("7z.exe")
        if which_path:
            return Path(which_path)

        common_paths = [
            Path("C:/Program Files/7-Zip/7z.exe"),
            Path("C:/Program Files (x86)/7-Zip/7z.exe"),
        ]
        for path in common_paths:
            if path.exists():
                return path

        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\7-Zip") as key:
                val, _ = winreg.QueryValueEx(key, "Path")
                path = Path(val) / "7z.exe"
                if path.exists():
                    return path
        except (ImportError, OSError):
            pass

        return None

    @staticmethod
    def detect_winrar() -> Path | None:
        which_path = shutil.which("WinRAR") or shutil.which("WinRAR.exe")
        if which_path:
            return Path(which_path)

        common_paths = [
            Path("C:/Program Files/WinRAR/WinRAR.exe"),
            Path("C:/Program Files (x86)/WinRAR/WinRAR.exe"),
        ]
        for path in common_paths:
            if path.exists():
                return path

        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\WinRAR.exe",
            ) as key:
                val, _ = winreg.QueryValueEx(key, "")
                path = Path(val)
                if path.exists():
                    return path
        except (ImportError, OSError):
            pass

        return None

    @classmethod
    def from_args(cls, **kwargs: Any) -> "Config":
        fields = {f.name: f.type for f in dataclasses.fields(cls)}
        init_kwargs: dict[str, Any] = {}
        for k, v in kwargs.items():
            if k in fields:
                if v is not None:
                    if "Path" in str(fields[k]) and isinstance(v, (str, Path)):
                        init_kwargs[k] = Path(v)
                    else:
                        init_kwargs[k] = v
                else:
                    init_kwargs[k] = None

        # Handle defaults for fields not supplied in kwargs
        for f in dataclasses.fields(cls):
            if f.name not in init_kwargs:
                if f.default is not dataclasses.MISSING:
                    init_kwargs[f.name] = f.default
                elif f.default_factory is not dataclasses.MISSING:
                    init_kwargs[f.name] = f.default_factory()

        return cls(**init_kwargs)

    def ensure_dirs(self) -> None:
        """确保 log_dir 等目录存在"""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)
