import subprocess
from pathlib import Path
from ..types import Result
from .base import BaseEngine
from .factory import register_engine


class SevenZEngine(BaseEngine):
    def test_availability(self) -> Result[str]:
        """
        1. 尝试 import py7zr → "library"
        2. 失败 → shutil.which("7z") → "cli"
        3. 都失败 → Result.fail("ENGINE_UNAVAILABLE")
        """
        try:
            import py7zr  # noqa: F401
            return Result.ok("library")
        except ImportError:
            pass

        from ..config import Config

        p = Config.detect_7zip()
        if p:
            return Result.ok("cli")

        return Result.fail(
            "7z engine is not available on this system", "ENGINE_UNAVAILABLE"
        )

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

        avail = self.test_availability()
        if avail.is_fail():
            return Result.fail("7z engine not available", "ENGINE_UNAVAILABLE")

        mode = avail.unwrap()

        if mode == "library":
            try:
                import py7zr

                with py7zr.SevenZipFile(archive_path, "r", password=password) as sz:
                    sz.extractall(path=str(output_dir))
                return Result.ok(output_dir)
            except Exception as e:
                from ..config import Config

                cli_path = Config.detect_7zip()
                if cli_path:
                    return self._extract_cli(
                        cli_path, archive_path, output_dir, password
                    )

                err_str = str(e).lower()
                if (
                    "password" in err_str
                    or "encrypted" in err_str
                    or "passwordrequired" in e.__class__.__name__.lower()
                    or "bad7zfile" in e.__class__.__name__.lower()
                ):
                    return Result.fail(
                        f"Password failed or required: {e}", "PASSWORD_FAIL"
                    )
                return Result.fail(f"Library extraction failed: {e}", "ENGINE_ERROR")

        else:
            from ..config import Config

            cli_path = Config.detect_7zip()
            if not cli_path:
                return Result.fail(
                    "7z CLI executable not found", "ENGINE_UNAVAILABLE"
                )
            return self._extract_cli(cli_path, archive_path, output_dir, password)

    def _extract_cli(
        self,
        exe_path: Path,
        archive_path: Path,
        output_dir: Path,
        password: str | None,
    ) -> Result[Path]:
        cmd = [str(exe_path), "x", str(archive_path), f"-o{output_dir}", "-y"]
        if password is not None:
            cmd.append(f"-p{password}")

        try:
            res = subprocess.run(
                cmd, capture_output=True, text=False, stdin=subprocess.DEVNULL
            )

            stdout_str = ""
            stderr_str = ""
            for encoding in ("gbk", "utf-8", "latin1"):
                try:
                    stdout_str = res.stdout.decode(encoding)
                    stderr_str = res.stderr.decode(encoding)
                    break
                except UnicodeDecodeError:
                    pass

            if res.returncode == 0:
                return Result.ok(output_dir)
            elif res.returncode == 2:
                combined = (stdout_str + stderr_str).lower()
                if (
                    "password" in combined
                    or "wrong password" in combined
                    or "data error" in combined
                ):
                    return Result.fail("Incorrect password", "PASSWORD_FAIL")
                return Result.fail(
                    f"Fatal error (2): {stdout_str + stderr_str}", "ENGINE_ERROR"
                )
            else:
                combined = (stdout_str + stderr_str).lower()
                if "wrong password" in combined or "password" in combined:
                    return Result.fail("Incorrect password", "PASSWORD_FAIL")
                return Result.fail(
                    f"CLI extraction failed ({res.returncode}): {stdout_str + stderr_str}",
                    "ENGINE_ERROR",
                )

        except Exception as e:
            return Result.fail(f"CLI process execution failed: {e}", "ENGINE_ERROR")

    @staticmethod
    def supported_format() -> str:
        return "7z"


# 自注册
register_engine("7z", SevenZEngine)
