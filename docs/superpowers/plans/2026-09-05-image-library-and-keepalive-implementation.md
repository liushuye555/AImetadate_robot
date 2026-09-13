# 图片库、聊天记录收藏与保活防循环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复图片完整性与竖图展示，准确分类高价值链接，允许显式保存合并聊天记录中的图片，并阻断保活/复读的自触发循环。

**Architecture:** 复用既有 `images` 表和归档管线：保存聊天记录图片时记录 `chat_record_saved` 与分类元数据，由图片视图从该记录生成 `06_聊天记录收藏`。图片修复以临时文件 + Pillow 完整解码验证 + `os.replace` 的原子替换实现。链接目标地址缓存在已有 `link_metadata` 表的新列中，资源页面按最终地址和本链接的标题/描述分类。入口级自消息过滤让保活、复读、采集与回复共享同一条安全边界。

**Tech Stack:** Python 3.11+, sqlite3, urllib.request, Pillow, pytest, OneBot/NapCat WebSocket。

---

### Task 1: 完整图片验证、修复与无裁切图库

**Files:**
- Modify: `qq_onebot_whitelist/images.py`
- Create: `qq_onebot_whitelist/image_repair.py`
- Modify: `qq_onebot_whitelist/build_image_view.py`
- Modify: `qq_onebot_whitelist/store.py`
- Test: `tests/test_image_repair.py`
- Test: `tests/test_view_index.py`

- [ ] **Step 1: 写失败测试**：`verify_image_file()` 必须拒绝缺失 PNG IEND 的文件；`repair_image()` 下载到临时文件，只有验证通过才能替换原文件；图库 HTML 不得再包含 `object-fit:cover` 与固定 `height:180px`。
- [ ] **Step 2: 运行目标测试并确认失败**：`pytest tests/test_image_repair.py tests/test_view_index.py -q`。
- [ ] **Step 3: 最小实现**：在 `images.py` 使用 `Image.open(...).verify()` 后重新 `load()` 验证；`image_repair.py` 用 `download_image`、临时路径、`os.replace`、哈希重算和 `Store` 的图片查找/更新方法实现单图和扫描修复；图库用 `aspect-ratio`/`object-fit:contain` 完整显示。
- [ ] **Step 4: 运行目标测试确认通过。**

### Task 2: 显式保存聊天记录图片

**Files:**
- Modify: `qq_onebot_whitelist/favorites.py`
- Modify: `qq_onebot_whitelist/onebot.py`
- Modify: `qq_onebot_whitelist/commands.py`
- Modify: `qq_onebot_whitelist/build_image_view.py`
- Modify: `qq_onebot_whitelist/i18n.py`
- Test: `tests/test_favorites.py`
- Test: `tests/test_view_index.py`

- [ ] **Step 1: 写失败测试**：私聊回复合并转发并输入 `/保存图片` 时默认分类为 `未分类`；指定分类名时保存到该分类；非回复、群聊或非合并记录返回明确的用法错误；自动私聊转发不再写入旧 favorites。
- [ ] **Step 2: 运行目标测试并确认失败**：`pytest tests/test_favorites.py tests/test_view_index.py -q`。
- [ ] **Step 3: 最小实现**：复用 `get_forward_msg` 和 `process_image_url`，以 `data/images/chat_favorites/<安全分类>` 为归档根，并写入 `chat_record_saved` 图片记录；在 `build_view` 从原始记录的 `saved_category` 生成 `06_聊天记录收藏/<分类>`；`onebot.handle_event` 在命令前异步处理该命令并发送统计回复。
- [ ] **Step 4: 运行目标测试确认通过。**

### Task 3: 短链落地、链接分类与资源页交互

**Files:**
- Modify: `qq_onebot_whitelist/store.py`
- Modify: `qq_onebot_whitelist/link_metadata.py`
- Modify: `qq_onebot_whitelist/resources.py`
- Modify: `qq_onebot_whitelist/resource_view.py`
- Test: `tests/test_resource_view.py`
- Test: `tests/test_resources.py` (create if absent)

- [ ] **Step 1: 写失败测试**：短链缓存落地 URL；`b23.tv` 落地 Bilibili 教程按最终地址分类；图片床/纯外链图不会进入资源页；网盘链接不会被默认标成 AI模型；生成页面包括复制链接按钮和安全的外部链接属性。
- [ ] **Step 2: 运行目标测试并确认失败**：`pytest tests/test_resource_view.py tests/test_resources.py -q`。
- [ ] **Step 3: 最小实现**：`link_metadata` 以受控重定向请求解析最终 URL，迁移 `link_metadata.resolved_url`；资源选择用最终 URL 和逐链接标题/描述而不是整条长消息关键词；页面使用标题、域名、隐藏/折叠的原 URL、复制按钮、`target="_blank" rel="noopener noreferrer"`。
- [ ] **Step 4: 运行目标测试确认通过。**

### Task 4: 机器人自消息过滤、复读发言人去重与保活冷却

**Files:**
- Modify: `qq_onebot_whitelist/onebot.py`
- Modify: `qq_onebot_whitelist/policy.py` (only if helper improves shared rule)
- Test: `tests/test_new_features.py`
- Test: `tests/test_onebot_self_events.py` (create)

- [ ] **Step 1: 写失败测试**：`user_id == self_id` 的消息在 `handle_event` 中不会发送、采集或更新活跃度；同一外部用户多次重复不触发 echo；不同用户达到阈值才触发；非管理员的清群样式公告不触发即时保活，重复管理员公告在冷却内不重复发送。
- [ ] **Step 2: 运行目标测试并确认失败**：`pytest tests/test_new_features.py tests/test_onebot_self_events.py -q`。
- [ ] **Step 3: 最小实现**：入口使用 `is_self_message` 早返回；echo 状态记录 `user_id` 集合；每群 `last_keepalive` 冷却防止公告重复保活。
- [ ] **Step 4: 运行目标测试确认通过。**

### Task 5: 集成、实际重修 #53619、重建视图与重启

**Files:**
- Modify: `qq_onebot_whitelist/commands.py`
- Modify: `qq_onebot_whitelist/onebot.py`
- Test: `tests/test_image_repair.py`

- [ ] **Step 1: 写失败测试**：私聊 `/修复图片 53619` 调度单图修复；无 ID 时调度损坏归档扫描；群聊拒绝该命令。
- [ ] **Step 2: 运行目标测试并确认失败**：`pytest tests/test_image_repair.py -q`。
- [ ] **Step 3: 最小实现**：解析修复命令，后台调用修复服务，发送成功/失败统计并请求重建图片视图。
- [ ] **Step 4: 运行全量测试与实际操作**：执行 `pytest -q`；尝试修复数据库中 ID 53619；重建 `data/view`；使用本项目现有控制脚本重启服务，并检查实时状态。
