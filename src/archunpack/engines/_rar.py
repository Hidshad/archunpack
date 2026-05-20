import subprocess
from pathlib import Path
from ..types import Result
from .base import BaseEngine
from .factory import register_engine


class RarEngine(BaseEngine):
    def test_availability(self) -> Result[str]:
        """
        1. 尝试 import rarfile → "library"
        2. 失败 → check WinRAR or 7z CLI → "cli"
        3. 都失败 → Result.fail("ENGINE_UNAVAILABLE")
        """
        try:
            import rarfile  # noqa: F401
            return Result.ok("library")
        except ImportError:
            pass

        from ..config import Config

        if Config.detect_winrar() or Config.detect_7zip():
            return Result.ok("cli")

        return Result.fail("No RAR engine available", "ENGINE_UNAVAILABLE")

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

        # 1. 尝试 rarfile 库
        try:
            import rarfile

            with rarfile.RarFile(archive_path, "r") as rf:
                rf.extractall(path=str(output_dir), pwd=password)
            return Result.ok(output_dir)
        except Exception as e_rar:
            # 2. 库提取失败 → 尝试 WinRAR.exe
            from ..config import Config

            winrar_path = Config.detect_winrar()
            if winrar_path:
                res_winrar = self._extract_winrar(
                    winrar_path, archive_path, output_dir, password
                )
                if res_winrar.is_ok():
                    return res_winrar
                if res_winrar.error_code == "PASSWORD_FAIL":
                    return res_winrar

            # 3. WinRAR 提取失败或不存在 → 尝试 7z.exe
            cli_path = Config.detect_7zip()
            if cli_path:
                return self._extract_7z(
                    cli_path, archive_path, output_dir, password
                )

            err_str = str(e_rar).lower()
            if (
                "password" in err_str
                or "encrypted" in err_str
                or "crc" in err_str
                or "incorrect" in err_str
                or "need password" in err_str
            ):
                return Result.fail(
                    f"Password failed or required: {e_rar}", "PASSWORD_FAIL"
                )
            return Result.fail(
                f"RAR library extraction failed: {e_rar}", "ENGINE_ERROR"
            )

    def _extract_winrar(
        self,
        exe_path: Path,
        archive_path: Path,
        output_dir: Path,
        password: str | None,
    ) -> Result[Path]:
        cmd = [str(exe_path), "x", "-y"]
        if password is not None:
            cmd.append(f"-p{password}")
        else:
            cmd.append("-p-")
        cmd.extend([str(archive_path), str(output_dir) + "\\"])

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

            combined = (stdout_str + stderr_str).lower()
            if (
                "password" in combined
                or "checksum" in combined
                or "incorrect" in combined
            ):
                return Result.fail("Incorrect password", "PASSWORD_FAIL")
            return Result.fail(
                f"WinRAR extraction failed ({res.returncode}): {stdout_str + stderr_str}",
                "ENGINE_ERROR",
            )
        except Exception as e:
            return Result.fail(
                f"WinRAR process execution failed: {e}", "ENGINE_ERROR"
            )

    def _extract_7z(
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
        return "rar"


register_engine("rar", RarEngine)
