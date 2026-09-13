# 图库单页按需加载性能优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 保留单个 `index.html` 的浏览体验，但让图库只在初次打开时加载首批卡片，滚动或点击“继续加载”后才按批次追加其余卡片。

**Architecture:** `write_category_gallery()` 继续生成每个分类的单页入口，但不再把全部图片 HTML 写入入口。图片 URL 元数据按固定批次写入分类目录下的 `chunks/chunk-*.js`，入口页用经典脚本动态加载（兼容 `file://`）并通过 IntersectionObserver 追加卡片。事件改为网格委托，同批折叠和灯箱只处理已加载节点。

**Tech Stack:** Python 标准库（`pathlib`、`json`、`html`）、静态 HTML/CSS/JavaScript、pytest。

---

### Task 1: 先写按需加载回归测试

**Files:**
- Modify: `tests/test_view_index.py`

- [ ] **Step 1: Add tests**
  - 验证大量图片生成的 `index.html` 不包含全部图片 URL，而是包含 `chunks/chunk-0001.js`、按需加载脚本和首批容量信息。
  - 验证第二个 chunk 文件存在且包含后续图片 URL。
  - 验证生成页保留 `IntersectionObserver`、`loading="lazy"`、`decoding="async"`、事件委托和同批折叠关键字。

- [ ] **Step 2: Run the focused tests and confirm they fail**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_view_index.py -q
```

Expected: 新增的按需加载断言失败，旧行为测试继续通过。

### Task 2: 实现静态 chunk + 单页按需加载

**Files:**
- Modify: `qq_onebot_whitelist/build_image_view.py`

- [ ] **Step 1: Add the smallest generator change**
  - 增加固定首批/分批常量（每批 120 条）。
  - 把图片记录序列化成 `chunks/chunk-NNNN.js`，每个脚本只调用 `window.__galleryAcceptChunk(index, items)`。
  - 将 `write_category_gallery()` 和 `_write_context_gallery()` 都改为只生成空网格、工具栏、哨兵和运行时脚本；初始只加载第一个 chunk，所有图库类页面保持单页入口。
  - 运行时按需加载下一 chunk，不使用 `fetch`，避免本地 `file://` 页面被跨源限制；滚动接近底部或点击按钮才追加。
  - 用单个网格点击监听器处理遮罩、同批角标和灯箱；保留跳转、回顶部、展开全部/恢复折叠。
  - 增加 `content-visibility:auto`、`contain-intrinsic-size`、`decoding="async"`，移除 sticky header 的 `backdrop-filter`。

- [ ] **Step 2: Run focused tests**

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_view_index.py -q
```

Expected: 全部通过。

### Task 3: 更新维护文档并重建实际视图

**Files:**
- Modify: `docs/使用说明.md`
- Modify: `docs/交接文档.md`

- [ ] **Step 1: Document behavior**
  - 说明分类仍是单个页面，不做分页；首次只加载 120 张，继续滚动才加载后续本地 chunk。
  - 说明 `chunks/` 是自动生成目录，不要手工编辑；页面必须通过入口 `index.html` 打开。

- [ ] **Step 2: Rebuild and verify output size/count**

```powershell
& .\.venv\Scripts\python.exe -m qq_onebot_whitelist.build_image_view --project-dir .
```

检查 `01_AI元数据_ComfyUI/index.html` 显著小于原 1.3 MB，且 `chunks/` 中有多个文件。

### Task 4: Full verification and restart

**Files:**
- No additional source files.

- [ ] **Step 1: Run full test suite**

```powershell
& .\.venv\Scripts\python.exe -m pytest -q
```

- [ ] **Step 2: Restart the service and verify status**

```powershell
& '.\scripts\windows\stop-qq-onebot-whitelist-hidden.ps1'
& '.\scripts\windows\start-qq-onebot-whitelist-hidden.ps1'
& '.\scripts\windows\get-qq-onebot-status.ps1'
```

- [ ] **Step 3: Confirm no unrelated files are reverted or cleaned**

```powershell
git status --short
```

Do not commit, reset, stash, checkout, or remove existing user changes.
