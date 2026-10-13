import hashlib
import os
from pathlib import Path

from qq_onebot_whitelist import knowledge_files


def source(**changes):
    row = {"scope": "group:123", "file_id": "real-file-1",
           "file_name": "report.txt", "file_size": 4}
    row.update(changes)
    return row


def downloader(monkeypatch, data, *, after=None):
    def fake(url, path, *, max_bytes):
        assert url == "https://refreshed.invalid/file"
        if len(data) > max_bytes:
            raise knowledge_files.FileTooLargeError()
        path.write_bytes(data)
        if after:
            after()
        return path
    monkeypatch.setattr(knowledge_files, "download_to_staging", fake)


def call(root, row=None, *, enabled=lambda: True, fetch=None, maximum=100, budget=1000):
    return knowledge_files.archive_file(
        row or source(), root, max_bytes=maximum, budget_bytes=budget,
        enabled=enabled,
        fetch_url=fetch or (lambda _: "https://refreshed.invalid/file"),
    )


def test_disabled_does_not_refresh_or_download(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("download should not run")
    monkeypatch.setattr(knowledge_files, "download_to_staging", forbidden)
    archive_root = tmp_path / "archive"
    result = call(archive_root, enabled=lambda: False,
                  fetch=lambda _: (_ for _ in ()).throw(AssertionError("url should not refresh")))
    assert result["status"] == "disabled"
    assert not archive_root.exists()


def test_switch_closed_after_download_cleans_staging(tmp_path, monkeypatch):
    active = {"value": True}
    downloader(monkeypatch, b"data", after=lambda: active.update(value=False))
    result = call(tmp_path, enabled=lambda: active["value"])
    assert result["status"] == "disabled"
    assert not list(tmp_path.rglob("*.part"))
    assert not list(tmp_path.rglob("*.stage"))
    assert not list(tmp_path.glob("[0-9a-f]*"))


def test_hard_byte_limit_is_enforced(tmp_path, monkeypatch):
    downloader(monkeypatch, b"12345")
    result = call(tmp_path, maximum=4)
    assert result["status"] == "skipped"
    assert result["error"] == "FileTooLarge"
    assert not list((tmp_path / knowledge_files._TEMP_NAME).glob("*"))


def test_budget_prevents_download_when_full(tmp_path, monkeypatch):
    (tmp_path / "existing.bin").write_bytes(b"123456")
    def forbidden(*args, **kwargs):
        raise AssertionError("download should not run")
    monkeypatch.setattr(knowledge_files, "download_to_staging", forbidden)
    result = call(tmp_path, budget=6)
    assert result["status"] == "skipped"
    assert result["error"] == "BudgetExceeded"


def test_lock_pid_does_not_consume_archive_budget(tmp_path, monkeypatch):
    downloader(monkeypatch, b"123456789")
    result = call(tmp_path, source(file_size=9), budget=9)
    assert result["status"] == "saved"
    assert result["size"] == 9


def test_content_deduplication_ignores_name_and_extension(tmp_path, monkeypatch):
    downloader(monkeypatch, b"same")
    first = call(tmp_path, source(file_name="one.txt"))
    downloader(monkeypatch, b"same")
    second = call(tmp_path, source(file_id="other", file_name="two.bin"))
    assert first["status"] == second["status"] == "saved"
    assert first["sha256"] == hashlib.sha256(b"same").hexdigest()
    assert first["path"] == second["path"]
    assert len([p for p in tmp_path.iterdir() if p.is_file()]) == 1


def test_same_name_different_content_has_distinct_paths(tmp_path, monkeypatch):
    downloader(monkeypatch, b"one!")
    first = call(tmp_path)
    downloader(monkeypatch, b"two!")
    second = call(tmp_path)
    assert first["status"] == second["status"] == "saved"
    assert first["path"] != second["path"]
    assert Path(first["path"]).name == first["sha256"] + ".txt"
    assert Path(second["path"]).name == second["sha256"] + ".txt"


def test_invalid_identifiers_are_rejected_before_fetch(tmp_path):
    for row in (source(file_id=""), source(file_id=None), source(file_id="https://example.invalid/file"),
                source(file_id="report.txt"),
                source(scope="123"), source(scope="group:1/../2")):
        result = call(tmp_path, row, fetch=lambda _: (_ for _ in ()).throw(AssertionError()))
        assert result["status"] == "failed"
        assert result["error"] == "InvalidSource"


def test_leading_slash_canonical_onebot_uuid_is_valid(tmp_path, monkeypatch):
    file_id = "/{550e8400-e29b-41d4-a716-446655440000}"
    downloader(monkeypatch, b"uuid")
    seen = []
    result = call(tmp_path, source(file_id=file_id),
                  fetch=lambda row: seen.append(row["file_id"]) or "https://refreshed.invalid/file")
    assert result["status"] == "saved"
    assert seen == [file_id]


def test_declared_size_mismatch_is_not_promoted(tmp_path, monkeypatch):
    downloader(monkeypatch, b"five!")
    result = call(tmp_path)
    assert result["status"] == "failed"
    assert result["error"] == "SizeMismatch"
    assert not list(tmp_path.glob("[0-9a-f]*"))


def test_stale_temporary_files_are_left_alone_without_touching_archives(tmp_path, monkeypatch):
    temp = tmp_path / knowledge_files._TEMP_NAME
    temp.mkdir()
    (temp / "abandoned.stage.part").write_bytes(b"partial")
    keep = tmp_path / "keep.txt"
    keep.write_bytes(b"persistent")
    downloader(monkeypatch, b"data")
    result = call(tmp_path)
    assert result["status"] == "saved"
    assert keep.read_bytes() == b"persistent"
    assert (temp / "abandoned.stage.part").read_bytes() == b"partial"
    assert len(list(temp.iterdir())) == 1
    assert Path(result["path"]).is_absolute()


def test_cross_process_lock_busy_skips_without_download(tmp_path, monkeypatch):
    (tmp_path / knowledge_files._LOCK_NAME).write_text(str(os.getpid()))
    def forbidden(*args, **kwargs):
        raise AssertionError("download should not run")
    monkeypatch.setattr(knowledge_files, "download_to_staging", forbidden)
    result = call(tmp_path)
    assert result["status"] == "skipped"
    assert result["error"] == "ArchiveBusy"
    assert (tmp_path / knowledge_files._LOCK_NAME).exists()


def test_dead_pid_lock_is_recovered(tmp_path, monkeypatch):
    lock = tmp_path / knowledge_files._LOCK_NAME
    lock.write_text("2147483647")
    downloader(monkeypatch, b"data")
    result = call(tmp_path)
    assert result["status"] == "saved"
    assert not lock.exists()


def test_digest_without_extension_is_verified_and_reused(tmp_path, monkeypatch):
    content = b"same"
    digest = hashlib.sha256(content).hexdigest()
    (tmp_path / digest).write_bytes(content)
    downloader(monkeypatch, content)
    result = call(tmp_path)
    assert result["status"] == "saved"
    assert Path(result["path"]).name == digest
    assert len([p for p in tmp_path.iterdir() if p.is_file() and p.name != knowledge_files._LOCK_NAME]) == 1


def test_corrupt_hash_named_file_is_not_reused_or_overwritten(tmp_path, monkeypatch):
    content = b"same"
    digest = hashlib.sha256(content).hexdigest()
    corrupt = tmp_path / (digest + ".txt")
    corrupt.write_bytes(b"corrupt")
    downloader(monkeypatch, content)
    result = call(tmp_path)
    assert result["status"] == "failed"
    assert result["error"] == "HashPathOccupied"
    assert corrupt.read_bytes() == b"corrupt"


def test_zero_size_and_actual_limit_are_checked(tmp_path, monkeypatch):
    result = call(tmp_path, source(file_size=0))
    assert result["status"] == "failed"
    downloader(monkeypatch, b"12345")
    result = call(tmp_path, source(file_size=None), maximum=4)
    assert result["status"] == "skipped"
    assert not list(tmp_path.glob("[0-9a-f]*"))
