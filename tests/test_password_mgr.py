import time
import threading
from pathlib import Path
from archunpack.config import Config
from archunpack.password_mgr import PasswordManager


def test_load_from_file(tmp_path: Path) -> None:
    config = Config()
    mgr = PasswordManager(config)

    pw_file = tmp_path / "passwords.txt"
    pw_file.write_text(
        "# This is a comment\n"
        "pass1\n"
        "  \n"  # empty line
        "pass2\n"
        "# Another comment\n"
        "pass3\n"
        "pass4\n"
        "pass5\n"
    )

    res = mgr.load_from_file(pw_file)
    assert res.is_ok()
    assert res.unwrap() == 5
    assert len(mgr) == 5
    assert "pass1" in mgr.passwords
    assert "pass2" in mgr.passwords


def test_load_from_file_not_found() -> None:
    config = Config()
    mgr = PasswordManager(config)
    res = mgr.load_from_file(Path("nonexistent_pass.txt"))
    assert res.is_fail()
    assert res.error_code == "FILE_NOT_FOUND"


def test_add_password() -> None:
    config = Config()
    mgr = PasswordManager(config)
    assert len(mgr) == 0

    mgr.add_password("pass123")
    assert len(mgr) == 1
    assert "pass123" in mgr.passwords


def test_record_hit_ordering() -> None:
    config = Config()
    mgr = PasswordManager(config)
    mgr.add_password("p1")
    mgr.add_password("p2")
    mgr.add_password("p3")

    # Originally, ordered is insertion-based or whatever (stable)
    ordered = mgr.get_ordered_passwords()
    assert ordered == ["p1", "p2", "p3"]

    # Record hit on p2
    mgr.record_hit("p2")
    ordered = mgr.get_ordered_passwords()
    assert ordered[0] == "p2"

    # Record hit on p3, p3 should be first now because it is the most recent
    mgr.record_hit("p3")
    ordered = mgr.get_ordered_passwords()
    assert ordered[0] == "p3"
    assert ordered[1] == "p2"
    assert ordered[2] == "p1"  # unhit is at the end


def test_multiple_hits_ordering() -> None:
    config = Config()
    mgr = PasswordManager(config)
    mgr.add_password("p1")
    mgr.add_password("p2")
    mgr.add_password("p3")

    mgr.record_hit("p1")
    time.sleep(0.01)
    mgr.record_hit("p2")
    
    # p2 was hit later than p1, so p2 comes first
    ordered = mgr.get_ordered_passwords()
    assert ordered == ["p2", "p1", "p3"]


def test_save_load_hot_passwords(tmp_path: Path) -> None:
    pw_file = tmp_path / "passwords.txt"
    pw_file.write_text("p1\np2\np3\n")

    config = Config(password_file=pw_file)
    mgr = PasswordManager(config)
    
    mgr.record_hit("p2")
    time.sleep(0.01)
    mgr.record_hit("p1")

    res_save = mgr.save_hot_passwords()
    assert res_save.is_ok()
    hot_file = res_save.unwrap()
    assert hot_file.exists()

    # Create a new manager and load hot passwords to verify
    mgr2 = PasswordManager(config)
    res_load = mgr2.load_hot_passwords(hot_file)
    assert res_load.is_ok()
    assert res_load.unwrap() == 3

    ordered = mgr2.get_ordered_passwords()
    assert ordered == ["p1", "p2", "p3"]


def test_len_and_iter() -> None:
    config = Config()
    mgr = PasswordManager(config)
    mgr.add_password("a")
    mgr.add_password("b")
    
    assert len(mgr) == 2
    lst = list(mgr)
    assert lst == ["a", "b"]


def test_thread_safety() -> None:
    config = Config()
    mgr = PasswordManager(config)
    mgr.add_password("secret")

    def worker() -> None:
        for _ in range(100):
            mgr.record_hit("secret")

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert mgr.passwords["secret"].hit_count == 1000
