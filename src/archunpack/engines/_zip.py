import subprocess
import zipfile
from pathlib import Path
from ..types import Result
from .base import BaseEngine
from .factory import register_engine


class ZipEngine(BaseEngine):
    def test_availability(self) -> Result[str]:
        # Standard zipfile is always available
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

        pwd_bytes = password.encode("utf-8") if password else None

        # 1. 优先尝试 7z.exe (如果已安装)，因为 7z 判断密码错误的速度极快（瞬间），
        # 而 Python 原生的 zipfile / pyzipper 会在内存中尝试解压整个文件，导致大文件卡死
        from ..config import Config
        cli_path = Config.detect_7zip()
        if cli_path:
            cli_res = self._extract_cli(cli_path, archive_path, output_dir, password)
            # 如果解压成功，或者明确是密码错误，直接返回，不再尝试 Python 库
            if cli_res.is_ok() or cli_res.error_code == "PASSWORD_FAIL":
                return cli_res

        # 2. 如果 7z 不可用，或者 7z 报其他错，回退到 pyzipper (支持 AES 加密)
        try:
            import pyzipper

            with pyzipper.AESZipFile(archive_path, "r") as zf:
                if password:
                    zf.setpassword(pwd_bytes)
                zf.extractall(path=str(output_dir))
            return Result.ok(output_dir)
        except Exception as e_pyzip:
            pyzip_err = str(e_pyzip).lower()
            if (
                "bad password" in pyzip_err
                or "decryption failed" in pyzip_err
                or "password required" in pyzip_err
            ):
                return Result.fail(f"Incorrect password: {e_pyzip}", "PASSWORD_FAIL")

        # 3. 最后尝试标准 zipfile
        try:
            with zipfile.ZipFile(archive_path, "r") as zf:
                if pwd_bytes:
                    zf.setpassword(pwd_bytes)
                zf.extractall(path=str(output_dir))
            return Result.ok(output_dir)
        except Exception as e_zip:
            err_str = str(e_zip).lower()
            if (
                "password" in err_str
                or "decrypt" in err_str
                or "crc" in err_str
                or "bad password" in err_str
                or "encrypted" in err_str
            ):
                return Result.fail(f"Password failed or required: {e_zip}", "PASSWORD_FAIL")
            
            return Result.fail(f"ZIP extraction failed: {e_zip}", "ENGINE_ERROR")

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
        return "zip"


register_engine("zip", ZipEngine)
