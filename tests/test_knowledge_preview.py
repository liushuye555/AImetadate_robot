import zipfile

from qq_onebot_whitelist.knowledge_preview import preview_file


def test_utf8_and_gb18030_text(tmp_path):
    utf = tmp_path / "note.txt"
    utf.write_text("你好", encoding="utf-8")
    gb = tmp_path / "legacy.txt"
    gb.write_bytes("中文内容".encode("gb18030"))
    assert preview_file(utf)["text"] == "你好"
    assert preview_file(gb)["text"] == "中文内容"


def test_text_and_character_truncation(tmp_path):
    path = tmp_path / "long.md"
    path.write_text("abcdef" * 20, encoding="utf-8")
    result = preview_file(path, max_bytes=12, max_chars=5)
    assert result["status"] == "ready"
    assert result["text"] == "abcde"
    assert result["truncated"] is True


def test_utf8_multibyte_byte_boundary_is_a_truncated_preview(tmp_path):
    path = tmp_path / "boundary.txt"
    path.write_text("abc中文", encoding="utf-8")
    result = preview_file(path, max_bytes=4)
    assert result["status"] == "ready"
    assert result["text"] == "abc"
    assert result["truncated"] is True


def test_redacts_secrets(tmp_path):
    path = tmp_path / "config.ini"
    path.write_text("api_key=abcdefghijk123", encoding="utf-8")
    result = preview_file(path)
    assert "abcdefghijk123" not in result["text"]


def test_zip_listing_and_small_text_preview_without_extracting(tmp_path):
    path = tmp_path / "workflow.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("README.md", "流程\n步骤二")
        archive.writestr("nested/job.yaml", "enabled: true")
    result = preview_file(path)
    assert result["status"] == "ready"
    assert "README.md" in result["text"] and "流程" in result["text"]
    assert "nested/job.yaml" in result["text"] and "enabled: true" in result["text"]
    assert not (tmp_path / "nested").exists()


def test_zip_skips_traversal_and_enforces_limits(tmp_path):
    path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("../escape.txt", "bad")
        archive.writestr("huge.txt", "x" * 70_000)
        archive.writestr("bomb.txt", "z" * 200_000)
    result = preview_file(path, max_bytes=300_000)
    assert result["status"] == "ready"
    assert "skipped unsafe" in result["text"]
    assert "../escape.txt" not in result["text"]
    assert "skipped compression ratio limit" in result["text"] or "skipped size limit" in result["text"]

    crowded = tmp_path / "many.zip"
    with zipfile.ZipFile(crowded, "w") as archive:
        for i in range(201):
            archive.writestr(f"{i}.txt", "x")
    assert preview_file(crowded)["status"] == "unsupported"


def test_binary_and_missing_file(tmp_path):
    binary = tmp_path / "model.safetensors"
    binary.write_bytes(b"\x00secret bytes")
    assert preview_file(binary)["status"] == "unsupported"
    absent = preview_file(tmp_path / "absent.txt")
    assert absent["status"] == "failed"
    assert absent["error"] == "FileNotFoundError"


def test_non_text_bytes_and_oversize_nontext(tmp_path):
    fake = tmp_path / "fake.txt"
    fake.write_bytes(b"a\x00b")
    assert preview_file(fake)["status"] == "unsupported"
    other = tmp_path / "unknown.bin"
    other.write_bytes(b"0" * 100)
    assert preview_file(other, max_bytes=10)["status"] == "unsupported"


def test_small_pdf_preview(tmp_path):
    from pypdf import PdfWriter

    path = tmp_path / "sample.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as stream:
        writer.write(stream)
    result = preview_file(path)
    assert result["status"] == "ready"
    assert result["format"] == "pdf"
    assert "Page 1" in result["text"]
