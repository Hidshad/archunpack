from pathlib import Path
import pyzipper

from archunpack.config import Config
from archunpack.logger import AppLogger
from archunpack.password_mgr import PasswordManager
from archunpack.scanner import Scanner
from archunpack.extractor import Extractor
from archunpack.task_queue import TaskQueue


def test_end_to_end_recursive_extraction(tmp_path: Path) -> None:
    # 1. Prepare directory structure
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    output_dir.mkdir()

    # 2. Create password text file
    password_file = tmp_path / "passwords.txt"
    password_file.write_text("wrong_pwd_1\nwrong_pwd_2\ncorrect_pwd\n", encoding="utf-8")

    # 3. Create nested.zip (encrypted with correct_pwd)
    nested_zip_path = tmp_path / "nested.zip"
    with pyzipper.AESZipFile(
        nested_zip_path,
        "w",
        compression=pyzipper.ZIP_DEFLATED,
        encryption=pyzipper.WZ_AES,
    ) as zf:
        zf.setpassword(b"correct_pwd")
        zf.writestr("deep.txt", "deep nested content")

    # 4. Create parent.zip (not encrypted, containing hello.txt and nested.zip)
    parent_zip_path = source_dir / "parent.zip"
    with pyzipper.AESZipFile(parent_zip_path, "w") as zf:
        zf.writestr("hello.txt", "hello parent content")
        zf.write(nested_zip_path, arcname="nested.zip")

    # 5. Set up Config
    config = Config(
        source_dir=source_dir,
        output_dir=output_dir,
        password_file=password_file,
        max_depth=5,
        delete_intermediate=True,
        overwrite_mode="skip",
        max_parallel=2,
    )

    # 6. Setup core stack
    logger = AppLogger(config)
    assert logger.setup().is_ok()

    password_mgr = PasswordManager(config)
    assert len(password_mgr) == 3

    scanner = Scanner(config)
    scan_res = scanner.scan(source_dir)
    assert scan_res.is_ok()
    summary = scan_res.unwrap()
    assert len(summary.tasks) == 1
    parent_task = summary.tasks[0]
    assert parent_task.real_type == "zip"
    assert parent_task.file_paths[0] == parent_zip_path

    extractor = Extractor(config, password_mgr, logger)
    queue = TaskQueue(config, extractor.extract)

    # 7. Add tasks and start
    queue.add_task(parent_task)
    queue.start()
    
    # Wait for completion
    finished = queue.join(timeout=5.0)
    assert finished

    # Save hot passwords
    save_res = password_mgr.save_hot_passwords()
    assert save_res.is_ok()
    hot_file = save_res.unwrap()
    assert hot_file.exists()

    # 8. Verifications
    # Verify primary extraction
    extracted_hello = output_dir / "parent" / "hello.txt"
    assert extracted_hello.exists()
    assert extracted_hello.read_text(encoding="utf-8") == "hello parent content"

    # Verify recursive nested extraction
    extracted_deep = output_dir / "parent" / "nested" / "deep.txt"
    assert extracted_deep.exists()
    assert extracted_deep.read_text(encoding="utf-8") == "deep nested content"

    # Verify intermediate file deletion (depth > 0)
    # output_dir / "parent" / "nested.zip" was the intermediate archive, should be cleaned up!
    extracted_nested_zip = output_dir / "parent" / "nested.zip"
    assert not extracted_nested_zip.exists()

    # Verify source archive (depth == 0) was NOT deleted
    assert parent_zip_path.exists()

    # Verify password success recording
    ordered_pwds = password_mgr.get_ordered_passwords()
    assert ordered_pwds[0] == "correct_pwd"  # correct_pwd became the hottest!

    logger.close()
