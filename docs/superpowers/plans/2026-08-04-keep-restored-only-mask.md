# 只留还原图 + 报告遮罩开关 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 确认混淆图还原成功后删除混淆原图、只保留还原图（含存量迁移），并在报告 02/03 分组对还原图默认遮罩（首页开关、点击显示）。

**Architecture:** 还原图通过 `promote_restored()` 原子覆盖归档区原文件，`kept_path` 改为还原图、新增 `deobfuscated` 标记列；`build_image_view` 停止生成"原图+解混淆"双份，改为单份 + `_还原` 文件名标记；`index.html` 与图库页用 localStorage 实现遮罩开关与点击显示。

**Tech Stack:** Python 3.11（PIL、sqlite3）、pytest；报告为静态 HTML。

规格：`docs/superpowers/specs/2026-08-04-keep-restored-only-mask-design.md`

---

## 文件结构

- `qq_onebot_whitelist/store.py`：`images.deobfuscated` 列迁移、`record_image` 落库、`mark_image_deobfuscated`。
- `qq_onebot_whitelist/gilbert_obfuscation.py`：新增 `promote_restored()`（还原图提升为唯一存档）。
- `qq_onebot_whitelist/collection.py`：`process_event_image` 还原成功后走替换流程。
- `qq_onebot_whitelist/maintenance.py`：`restore_confirmed_obfuscation` 对存量执行替换。
- `qq_onebot_whitelist/build_image_view.py`：单份输出 + `_还原` 标记 + `index.html` 遮罩开关 + 图库页模糊 JS。
- `qq_onebot_whitelist/context_view.py`：03 上下文页图片卡片同样遮罩。
- `tests/`：对应测试。

---

### Task 1: store.py 增加 deobfuscated 列与落库/更新方法

**Files:**
- Modify: `qq_onebot_whitelist/store.py`
- Test: `tests/test_store_summary.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_store_summary.py 追加
def test_image_deobfuscated_flag_and_mark(tmp_path):
    from qq_onebot_whitelist.store import Store
    db = tmp_path / "data" / "bot.db"
    store = Store(db)
    store.record_image(scope="group:1", user_id="u", result={
        "sha256": "d1", "format": "PNG", "size": 1, "width": 64, "height": 64,
        "kept_path": str(tmp_path / "a.png"), "retention_reason": "xiaofanqie_obfuscated",
        "deobfuscated": True,
    }, raw={})
    import sqlite3
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT deobfuscated FROM images WHERE sha256='d1'").fetchone()
    conn.close()
    assert row[0] == 1

    store.mark_image_deobfuscated(1, kept_path=str(tmp_path / "r.png"), restored_path=str(tmp_path / "r.png"))
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT kept_path, restored_path, deobfuscated FROM images WHERE id=1").fetchone()
    conn.close()
    assert row == (str(tmp_path / "r.png"), str(tmp_path / "r.png"), 1)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_store_summary.py::test_image_deobfuscated_flag_and_mark -v`
Expected: FAIL（无 deobfuscated 列 / 无 mark_image_deobfuscated）

- [ ] **Step 3: 实现**

`qq_onebot_whitelist/store.py` 的 `_migrate` 中，在 `restored_path` 迁移之后追加：

```python
        if 'deobfuscated' not in image_cols:
            conn.execute('ALTER TABLE images ADD COLUMN deobfuscated INTEGER DEFAULT 0')
```

`record_image` 的 INSERT 列与参数追加 `deobfuscated`：

```python
                '''INSERT INTO images (
                  scope, user_id, url, sha256, size, format, width, height, metadata_keys_json,
                  has_ai_metadata, ai_source, text_excerpt, kept_path, retention_reason, restored_path, deobfuscated, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
```

参数元组在 `result.get('restored_path')` 之后加 `1 if result.get('deobfuscated') else 0,`。

`update_image_restored` 之后新增：

```python
    def mark_image_deobfuscated(self, image_id: int, *, kept_path: str, restored_path: str) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                'UPDATE images SET kept_path=?, restored_path=?, deobfuscated=1 WHERE id=?',
                (kept_path, restored_path, int(image_id)),
            )
            conn.commit()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_store_summary.py::test_image_deobfuscated_flag_and_mark -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add qq_onebot_whitelist/store.py tests/test_store_summary.py
git commit -m "feat: images.deobfuscated column and mark helper"
```

---

### Task 2: gilbert_obfuscation.py 增加 promote_restored()

**Files:**
- Modify: `qq_onebot_whitelist/gilbert_obfuscation.py`
- Test: `tests/test_gilbert_obfuscation.py`

- [ ] **Step 1: 写失败测试**

```python
def test_promote_restored_replaces_original(tmp_path):
    from qq_onebot_whitelist.gilbert_obfuscation import promote_restored
    archive = tmp_path / "ai" / "ab"
    archive.mkdir(parents=True)
    original = archive / "abc.png"
    original.write_bytes(b"obfuscated")
    restored = tmp_path / "restored" / "abc.png"
    restored.parent.mkdir(parents=True)
    restored.write_bytes(b"restored-content")

    dest = promote_restored(original, restored, tmp_path / "ai", "abc")

    assert dest == archive / "abc.png"
    assert dest.read_bytes() == b"restored-content"
    assert not (tmp_path / "restored" / "abc.png").exists() or True  # 临时文件可留可清，重点是归档内容被替换
    assert original.exists() is False or original.read_bytes() == b"restored-content"


def test_promote_restored_skips_when_missing(tmp_path):
    from qq_onebot_whitelist.gilbert_obfuscation import promote_restored
    archive = tmp_path / "ai"
    archive.mkdir()
    try:
        promote_restored(tmp_path / "orig.png", tmp_path / "missing.png", archive, "abc")
        raise AssertionError("should raise")
    except FileNotFoundError:
        pass
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_gilbert_obfuscation.py::test_promote_restored_replaces_original tests/test_gilbert_obfuscation.py::test_promote_restored_skips_when_missing -v`
Expected: FAIL（promote_restored 不存在）

- [ ] **Step 3: 实现**

`qq_onebot_whitelist/gilbert_obfuscation.py` 文件末尾（`is_obfuscated` 之后）追加：

```python
def promote_restored(
    original_path: str | Path,
    restored_path: str | Path,
    archive_root: str | Path,
    digest: str,
) -> Path:
    """把还原图提升为唯一存档：原子覆盖归档区原文件，随后删除混淆原图。

    返回最终归档路径。还原图缺失或为空时抛 FileNotFoundError（调用方必须保留原图）。
    """
    import shutil

    original = Path(original_path)
    restored = Path(restored_path)
    if not restored.exists() or restored.stat().st_size <= 0:
        raise FileNotFoundError(f'restored image missing or empty: {restored}')
    archive_root = Path(archive_root)
    dest = archive_root / digest[:2] / f'{digest}{restored.suffix}'
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = restored.with_suffix(restored.suffix + '.tmp')
    shutil.copy2(str(restored), str(tmp))
    tmp.replace(dest)
    if original.exists() and original.resolve() != dest.resolve():
        original.unlink(missing_ok=True)
    return dest
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_gilbert_obfuscation.py::test_promote_restored_replaces_original tests/test_gilbert_obfuscation.py::test_promote_restored_skips_when_missing -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add qq_onebot_whitelist/gilbert_obfuscation.py tests/test_gilbert_obfuscation.py
git commit -m "feat: promote_restored replaces obfuscated original atomically"
```

---

### Task 3: collection.py 入库时还原即替换

**Files:**
- Modify: `qq_onebot_whitelist/collection.py`
- Test: `tests/test_load_aware.py`（或新增 `tests/test_collection_restore.py`）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_collection_restore.py`：

```python
def test_process_event_image_replaces_with_restored(tmp_path, monkeypatch):
    from pathlib import Path
    import qq_onebot_whitelist.collection as collection
    from qq_onebot_whitelist.config import AppConfig
    from qq_onebot_whitelist.store import Store

    data = tmp_path / "data"
    store = Store(data / "bot.db")
    config = AppConfig(data_dir=data)
    archive = data / "images" / "ai"
    original = archive / "ab" / "abc.png"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"obfuscated")
    restored = data / "tmp" / "restored.png"
    restored.write_bytes(b"restored-content")

    def fake_process_image_url(url, **kwargs):
        return {
            "url": url, "sha256": "abc", "phash": None, "blockiness": 0.0,
            "size": 10, "format": "PNG", "width": 4, "height": 4,
            "metadata_keys": [], "has_ai_metadata": False, "ai_source": None,
            "text_excerpt": "", "kept_path": str(original), "retention_reason": "candidate",
        }

    def fake_analyze(path):
        return {"obfuscated": True, "confidence": "confirmed", "ratio": 0.5, "layers": 1}

    def fake_restore(src, out, layers=None):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"restored-content")
        return out, 1

    monkeypatch.setattr(collection, "process_image_url", fake_process_image_url)
    monkeypatch.setattr(collection, "analyze_image", fake_analyze)
    monkeypatch.setattr(collection, "restore_image", fake_restore)

    image = {"url": "http://x/img.png", "file": "img.png"}
    collection.process_event_image(
        store, scope="group:1", user_id="u", image=image,
        nearby_text="", message_db_id=None, config=config,
    )

    import sqlite3
    conn = sqlite3.connect(data / "bot.db")
    row = conn.execute("SELECT retention_reason, kept_path, deobfuscated, restored_path FROM images").fetchone()
    conn.close()
    assert row[0] == "xiaofanqie_obfuscated"
    assert row[1] == str(archive / "ab" / "abc.png")
    assert row[2] == 1
    assert row[3] == row[1]
    assert (archive / "ab" / "abc.png").read_bytes() == b"restored-content"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_collection_restore.py -v`
Expected: FAIL（还原后 kept_path 仍指向原文件/deobfuscated 未置位）

- [ ] **Step 3: 实现**

`qq_onebot_whitelist/collection.py` 顶部 import 追加 `promote_restored`：

```python
from .gilbert_obfuscation import analyze_image, promote_restored, restore_image
```

`process_event_image` 中"确认档自动解混淆"块替换为：

```python
                    # 确认档自动解混淆：还原到临时文件后提升为唯一存档（删原图）
                    if confidence == 'confirmed' and result.get('kept_path'):
                        try:
                            tmp_dir = config.data_dir / 'tmp'
                            tmp_dir.mkdir(parents=True, exist_ok=True)
                            restored, _ = restore_image(
                                result['kept_path'],
                                tmp_dir / f"{result.get('sha256')}.restore.png",
                                layers=xfq_result.get('layers'),
                            )
                            final = promote_restored(
                                result['kept_path'],
                                restored,
                                config.data_dir / 'images' / 'ai',
                                str(result.get('sha256') or ''),
                            )
                            result['kept_path'] = str(final)
                            result['restored_path'] = str(final)
                            result['deobfuscated'] = True
                        except Exception as exc:
                            print(f'restore failed: {type(exc).__name__}: {exc}')
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_collection_restore.py -v`
Expected: PASS

- [ ] **Step 5: 全量测试并提交**

Run: `.\.venv\Scripts\python.exe -m pytest tests -q`
Expected: 全部通过（如有既有测试断言 `images/restored/` 路径，需同步更新为替换语义）

```bash
git add qq_onebot_whitelist/collection.py tests/test_collection_restore.py
git commit -m "feat: ingest replaces obfuscated original with restored image"
```

---

### Task 4: maintenance.py 存量迁移替换

**Files:**
- Modify: `qq_onebot_whitelist/maintenance.py`
- Test: `tests/test_image_file_sync.py`

- [ ] **Step 1: 写失败测试**

```python
def test_restore_confirmed_obfuscation_replaces_and_marks(tmp_path, monkeypatch):
    import sqlite3
    from pathlib import Path
    from qq_onebot_whitelist.maintenance import restore_confirmed_obfuscation
    from qq_onebot_whitelist.store import Store

    data = tmp_path / "data"
    store = Store(data / "bot.db")
    archive = data / "images" / "ai" / "ab"
    archive.mkdir(parents=True)
    original = archive / "abc.png"
    original.write_bytes(b"obfuscated")
    restored_file = tmp_path / "restored" / "abc.png"
    restored_file.parent.mkdir(parents=True)
    restored_file.write_bytes(b"restored-content")

    store.record_image(scope="group:1", user_id="u", result={
        "sha256": "abc", "format": "PNG", "size": 1, "width": 64, "height": 64,
        "kept_path": str(original), "retention_reason": "xiaofanqie_obfuscated",
    }, raw={})
    store.save_obfuscation_score("abc", ratio=0.5, layers=1, obfuscated=True, confidence="confirmed")

    def fake_restore(src, out, layers=None):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"restored-content")
        return out, 1

    import qq_onebot_whitelist.maintenance as m
    monkeypatch.setattr(m, "restore_image", fake_restore)

    changed = restore_confirmed_obfuscation(tmp_path)
    assert changed == 1
    conn = sqlite3.connect(data / "bot.db")
    row = conn.execute("SELECT kept_path, restored_path, deobfuscated FROM images WHERE sha256='abc'").fetchone()
    conn.close()
    assert row[2] == 1
    assert row[1] == row[0]
    assert Path(row[0]).read_bytes() == b"restored-content"


def test_restore_confirmed_obfuscation_skips_missing_restored(tmp_path, monkeypatch):
    import sqlite3
    from pathlib import Path
    from qq_onebot_whitelist.maintenance import restore_confirmed_obfuscation
    from qq_onebot_whitelist.store import Store

    data = tmp_path / "data"
    store = Store(data / "bot.db")
    archive = data / "images" / "ai" / "ab"
    archive.mkdir(parents=True)
    original = archive / "abc.png"
    original.write_bytes(b"obfuscated")
    store.record_image(scope="group:1", user_id="u", result={
        "sha256": "abc", "format": "PNG", "size": 1, "width": 64, "height": 64,
        "kept_path": str(original), "retention_reason": "xiaofanqie_obfuscated",
    }, raw={})
    store.save_obfuscation_score("abc", ratio=0.5, layers=1, obfuscated=True, confidence="confirmed")

    def fake_restore(src, out, layers=None):
        raise FileNotFoundError("restore failed")

    import qq_onebot_whitelist.maintenance as m
    monkeypatch.setattr(m, "restore_image", fake_restore)

    changed = restore_confirmed_obfuscation(tmp_path)
    assert changed == 0
    assert original.exists()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_image_file_sync.py::test_restore_confirmed_obfuscation_replaces_and_marks -v`
Expected: FAIL（deobfuscated 未置位或 kept_path 未指向还原图）

- [ ] **Step 3: 实现**

`qq_onebot_whitelist/maintenance.py` 的 `restore_confirmed_obfuscation` 整体替换为：

```python
def restore_confirmed_obfuscation(project_dir: str | Path) -> int:
    """为已确认的小番茄混淆图补齐自动还原并替换为唯一存档（删原图）。"""
    from .gilbert_obfuscation import promote_restored, restore_image
    from .store import Store
    project_dir = Path(project_dir)
    db = project_dir / 'data' / 'bot.db'
    if not db.exists():
        return 0
    store = Store(db)
    archive_root = project_dir / 'data' / 'images' / 'ai'
    changed = 0
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT id, sha256, kept_path FROM images "
            "WHERE retention_reason='xiaofanqie_obfuscated' AND deobfuscated=0 "
            "AND kept_path IS NOT NULL"
        ).fetchall()
        for row_id, sha256, kept_path in rows:
            path = Path(kept_path)
            if not path.exists():
                continue
            cached = store.obfuscation_score(str(sha256 or '')) if sha256 else None
            layers = cached[1] if cached else None
            try:
                tmp_dir = project_dir / 'data' / 'tmp'
                tmp_dir.mkdir(parents=True, exist_ok=True)
                restored, _ = restore_image(
                    path,
                    tmp_dir / f'{sha256}.restore.png',
                    layers=layers,
                )
                final = promote_restored(path, restored, archive_root, str(sha256 or ''))
                store.mark_image_deobfuscated(row_id, kept_path=str(final), restored_path=str(final))
                changed += 1
            except Exception:
                continue
        conn.commit()
    return changed
```

（`restore_confirmed_obfuscation` 顶部原有的 `restored_root` 相关行一并移除。）

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_image_file_sync.py -v`
Expected: PASS（含新增两例与既有文件同步用例）

- [ ] **Step 5: 全量测试并提交**

Run: `.\.venv\Scripts\python.exe -m pytest tests -q`
Expected: 全部通过

```bash
git add qq_onebot_whitelist/maintenance.py tests/test_image_file_sync.py
git commit -m "feat: migrate existing confirmed obfuscation to restored-only"
```

---

### Task 5: build_image_view.py 单份输出 + _还原 标记 + 遮罩开关

**Files:**
- Modify: `qq_onebot_whitelist/build_image_view.py`
- Test: `tests/test_view_index.py`

- [ ] **Step 1: 写失败测试**

```python
def test_build_view_single_file_with_mask_marker_and_toggle(tmp_path):
    import sqlite3
    from pathlib import Path
    from qq_onebot_whitelist.build_image_view import build_view

    data = tmp_path / "data"
    data.mkdir(parents=True)
    conn = sqlite3.connect(data / "bot.db")
    conn.execute("""CREATE TABLE images (
        id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, user_id TEXT, seen_at TEXT,
        format TEXT, width INTEGER, height INTEGER, size INTEGER, has_ai_metadata INTEGER,
        ai_source TEXT, retention_reason TEXT, kept_path TEXT, restored_path TEXT,
        deobfuscated INTEGER DEFAULT 0, text_excerpt TEXT, raw_json TEXT)""")
    conn.execute("""CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, user_id TEXT, seen_at TEXT,
        text TEXT, links_json TEXT, raw_json TEXT, message_key TEXT)""")
    conn.execute("""CREATE TABLE ai_context_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, scope TEXT,
        start_message_id INTEGER, end_message_id INTEGER, model TEXT, summary TEXT, raw_json TEXT)""")
    img = tmp_path / "img.png"
    img.write_bytes(b"x" * 10)
    conn.execute(
        "INSERT INTO images (scope, user_id, format, width, height, retention_reason, kept_path, restored_path, deobfuscated) "
        "VALUES ('group:1', 'u', 'PNG', 64, 64, 'positive_feedback', ?, ?, 1)",
        (str(img), str(img)),
    )
    conn.commit()
    conn.close()

    counts = build_view(tmp_path)
    cat = tmp_path / "data" / "view" / "02_群友好评"
    files = [p.name for p in cat.rglob("*") if p.is_file() and p.name != "index.html"]
    assert len(files) == 1
    assert "_还原" in files[0]
    assert "解混淆" not in files[0]
    index = (tmp_path / "data" / "view" / "index.html").read_text(encoding="utf-8")
    assert "遮罩混淆还原图" in index
    assert "maskRestored" in index
    gallery = (cat / "index.html").read_text(encoding="utf-8")
    assert "maskRestored" in gallery
    assert "blur" in gallery
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_view_index.py::test_build_view_single_file_with_mask_marker_and_toggle -v`
Expected: FAIL（存在 `_解混淆` 副本或 index.html 无开关）

- [ ] **Step 3: 实现**

`build_image_view.py`：

1) `build_view` 的 SELECT 增加动态列：

```python
    deobfuscated_col = 'deobfuscated, ' if 'deobfuscated' in image_cols else ''
    rows = conn.execute(
        '''SELECT id, scope, user_id, seen_at, format, width, height, size, has_ai_metadata, ai_source, retention_reason, kept_path, ''' + restored_col + deobfuscated_col + '''text_excerpt, raw_json
           FROM images WHERE kept_path IS NOT NULL ORDER BY retention_reason, id DESC'''
    ).fetchall()
```

2) 文件名加标记、移除"解混淆副本"块：

```python
        is_deobfuscated = bool(row['deobfuscated']) if 'deobfuscated' in row.keys() else False
        # 遮罩标记只加在 02/03（05 小番茄混淆不遮罩）
        mask_marker = '_还原' if (is_deobfuscated and reason in ('positive_feedback', 'nearby_ai_context')) else ''
        filename = safe_name(f"#{row['id']}_{w or 'x'}x{h or 'x'}_{reason}{mask_marker}") + ext
        dst = view / cat / size_class / filename
        mode = make_link_or_copy(src, dst)
        counts[cat] = counts.get(cat, 0) + 1
        # 替换后 kept_path 即还原图，不再生成"原图+解混淆"双份
```

删除原有的 `restored_path` 副本块（`restored_path = row['restored_path'] ... make_link_or_copy(restored_src, restored_dst)`）。

3) `write_view_index` 中，在 `doc = '''...` 模板字符串定义之前插入遮罩开关 HTML，
   并把模板里 `</style><body><h1>QQ AI 图片视图</h1>` 替换为 `</style><body><h1>QQ AI 图片视图</h1>` + mask_html：

```python
    mask_html = (
        '<label style="display:inline-flex;align-items:center;gap:6px;margin-bottom:14px;cursor:pointer">'
        '<input type="checkbox" id="maskRestored" checked> 遮罩混淆还原图（02/03 分组默认模糊，点击图片显示）</label>'
        '<script>'
        'const maskBox=document.getElementById("maskRestored");'
        'try{maskBox.checked=localStorage.getItem("maskRestored")!=="0";}catch(e){}'
        'maskBox.addEventListener("change",()=>{try{localStorage.setItem("maskRestored",maskBox.checked?"1":"0");}catch(e){}});'
        '</script>'
    )
    doc = (doc.replace('</style><body><h1>QQ AI 图片视图</h1>',
                       '</style><body><h1>QQ AI 图片视图</h1>' + mask_html))
```

4) `write_category_gallery` 的 `<script>` 增加遮罩逻辑：

```python
const masked=localStorage.getItem("maskRestored")!=="0";
const cells=[...document.querySelectorAll('.cell')];
cells.forEach(a=>{if(masked&&/还原/.test(a.getAttribute('href')||'')){const img=a.querySelector('img');img.style.filter='blur(14px)';a.dataset.masked='1';}});
```

并在 `.cell img` 点击处理里：若 `a.dataset.masked==='1'`，点击先取消模糊再进灯箱：

```python
cells.forEach((a,i)=>a.addEventListener('click',e=>{
  e.preventDefault();
  if(a.dataset.masked==='1'){
    const img=a.querySelector('img');
    img.style.filter='none';
    delete a.dataset.masked;
    return;
  }
  show(i);
}));
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_view_index.py -v`
Expected: PASS

- [ ] **Step 5: 全量测试并提交**

Run: `.\.venv\Scripts\python.exe -m pytest tests -q`
Expected: 全部通过

```bash
git add qq_onebot_whitelist/build_image_view.py tests/test_view_index.py
git commit -m "feat: single restored file per image + mask toggle on report"
```

---

### Task 6: context_view.py 03 上下文页同样遮罩

**Files:**
- Modify: `qq_onebot_whitelist/context_view.py`
- Modify: `qq_onebot_whitelist/build_image_view.py`（context_items 携带 deobfuscated）
- Test: `tests/test_context_html_view.py`

- [ ] **Step 1: 写失败测试**

```python
def test_context_image_cards_mask_deobfuscated():
    from qq_onebot_whitelist.context_view import _image_cards
    items = [
        {"id": "1", "image_rel": "a.png", "meta": "m", "deobfuscated": True, "text_excerpt": ""},
        {"id": "2", "image_rel": "b.png", "meta": "m", "deobfuscated": False, "text_excerpt": ""},
    ]
    html = _image_cards(items, "x/")
    assert "masked" in html or "blur" in html
    assert "x/a.png" in html and "x/b.png" in html
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_context_html_view.py::test_context_image_cards_mask_deobfuscated -v`
Expected: FAIL（卡片无遮罩标记）

- [ ] **Step 3: 实现**

`context_view.py` 的 `_image_cards` 中，图片标签增加遮罩类与点击取消：

```python
        masked = ' data-masked="1"' if item.get('deobfuscated') else ''
        cards.append(
            '<article class="card">'
            f'<a href="{html.escape(image_url)}" class="img-link"{masked}><img src="{html.escape(image_url)}" loading="lazy"></a>'
            ...
        )
```

并在 `_document` 引入的页面样式/脚本区加全局 JS（`build_context_view` 输出末尾追加）：

```python
    body += (
        '<script>'
        'try{const m=localStorage.getItem("maskRestored")!=="0";'
        'if(m){document.querySelectorAll("a.img-link[data-masked]").forEach(a=>{'
        'a.querySelector("img").style.filter="blur(14px)";'
        'a.addEventListener("click",e=>{e.preventDefault();a.querySelector("img").style.filter="none";a.removeAttribute("data-masked");});});}'
        '}catch(e){}'
        '</script>'
    )
```

`build_image_view.py` 的 `context_items.append` 增加 `'deobfuscated': bool(row['deobfuscated']) if 'deobfuscated' in row.keys() else False,`。

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_context_html_view.py -v`
Expected: PASS

- [ ] **Step 5: 全量测试并提交**

Run: `.\.venv\Scripts\python.exe -m pytest tests -q`
Expected: 全部通过

```bash
git add qq_onebot_whitelist/context_view.py qq_onebot_whitelist/build_image_view.py tests/test_context_html_view.py
git commit -m "feat: mask deobfuscated images on 03 context page"
```

---

### Task 7: 真实数据迁移与验证

**Files:** 无（运行维护与重建）

- [ ] **Step 1: 先停 bot，避免 DB 锁**

Run: 读取 `run/bot.pid` 并 `taskkill /PID <pid> /T /F`。
Expected: 无残留 `qq_onebot_whitelist.onebot` 进程

- [ ] **Step 2: 执行存量迁移 + 重建视图**

Run:
```bash
.\.venv\Scripts\python.exe -c "import sys; from pathlib import Path; sys.path.insert(0,'.'); from qq_onebot_whitelist.maintenance import restore_confirmed_obfuscation, sync_image_files; print('migrated:', restore_confirmed_obfuscation(Path('.'))); print('synced:', sync_image_files(Path('.'))['image_duplicates_removed'])"
```
Expected: `migrated: >=1`（存量确认图被替换），无报错

- [ ] **Step 3: 验证结果**

Run:
```bash
.\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('data/bot.db'); print(c.execute(\"SELECT COUNT(*) FROM images WHERE retention_reason='xiaofanqie_obfuscated' AND deobfuscated=1\").fetchone())"
```
Expected: 与确认图总数一致；`data/view/05_小番茄混淆` 下每张图只有一份（无 `_解混淆` 副本），`index.html` 含"遮罩混淆还原图"开关

- [ ] **Step 4: 重启 bot 并确认状态**

Run: `Start-Process .\.venv\Scripts\python.exe -ArgumentList '-m','qq_onebot_whitelist.control','start' -WindowStyle Hidden`
随后等待 `run/status.json` 更新为 `"bot": true`。
Expected: 状态全绿

- [ ] **Step 5: 提交（如有遗留改动）并收尾**

```bash
git status --short
```
如有未提交改动，说明并提交；无则结束。
