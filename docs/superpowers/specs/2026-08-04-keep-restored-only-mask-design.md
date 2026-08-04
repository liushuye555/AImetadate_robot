# 混淆图只留还原图 + 报告遮罩开关（设计文档）

日期：2026-08-04
范围：子项目 1。子项目 2（03_AI上下文 提示词绑定优化）另行设计，本文档不覆盖。

## 背景与目标

当前确认混淆图后，磁盘同时保留**混淆原图**和**还原图**，报告（02/03/05）两者都显示。
用户要求：

1. 混淆原图不必保留，只保留还原图（磁盘与报告中都只留还原图）。
2. 02_群友好评、03_AI上下文 分组里，混淆还原的图**默认遮罩**（缩略图模糊，点击显示）。
3. 遮罩开关放在报告首页 `data/view/index.html`，不在面板设置里。

## 现状

- `images` 表：`kept_path` = 混淆原图，`restored_path` = 还原图（`data/images/restored/<混淆sha>.png`）。
- `build_image_view.py`：分类目录里同时放原图与 `_解混淆` 副本。
- 混淆原图无任何元数据（工具输出 JPEG q95 已剥离），删除不损失文件内信息。
- 溯源信息在库：scope / user_id / seen_at / 尺寸 / sha256（混淆摘要）/ 还原层数（`image_hashes.xfq_layers`）。

## 设计

### 1. 存储：还原即替换

采集时（`collection.process_event_image`）确认混淆且还原成功后：

- 还原图先写临时文件（`data/tmp/`），校验成功后替换归档区原文件
  `data/images/ai/<混淆sha>.png`（即覆盖原混淆图所在路径；先删原文件再 rename，避免半成品）。
- 删除混淆原图文件。
- `kept_path` 指向还原图；`restored_path` 保留指向同一文件（作为"已还原"线索）。
- 新增 `deobfuscated INTEGER DEFAULT 0` 列标记"由混淆还原而来"。

`sha256` 列仍存混淆图摘要（溯源口径），磁盘文件虽为还原内容但沿用混淆 sha 作为文件名，
去重/统计按文件名 stem 不变。

维护时（`maintenance.restore_confirmed_obfuscation`）对存量执行同一替换：

- 遍历 `xiaofanqie_obfuscated` 且 `deobfuscated=0` 的行；校验还原图存在且非空后，移动还原图进归档、删除原图、更新 `kept_path`/`restored_path`/`deobfuscated`。
- 还原图缺失或还原失败 → 跳过不删（保留现状）。

疑似档（`xiaofanqie_compressed`）不删不替换（还原不完整，原图仍有参考价值）。

### 2. 溯源保留

- `sha256` 继续存混淆图摘要（去重/统计口径不变，还原图文件名沿用混淆 sha）。
- 还原层数继续缓存在 `image_hashes.xfq_layers`。
- `deobfuscated` 标记供遮罩与报告标注使用。

### 3. 报告遮罩（首页开关）

- `build_view` 生成 `data/view/index.html` 时，顶部加"遮罩混淆还原图"勾选框，**默认勾选**，状态存 `localStorage`。
- 02/03 图库页 JS：对文件名带 `_还原` 标记的图默认加 CSS 模糊，点击显示原图。
- 05_小番茄混淆 不遮罩（该分组用途就是查看内容）。
- localStorage 不可用（如 file:// 限制）→ 兜底默认遮罩。

实现细节：由于替换后 `kept_path` 即还原图，`build_image_view` **移除原有的
"原图 + _解混淆 副本"双份逻辑**，分类目录只放 `kept_path` 一份；`deobfuscated=1`
的行在文件名中加 `_还原` 标记，图库页 JS 依据标记选择遮罩；
index.html 的勾选框写入 localStorage，图库页读取同一 key。

### 4. 错误处理

- 还原失败/超时 → 保留混淆原图，照常记录 `deobfuscated=0`，不进入替换流程。
- 迁移删原图前必须确认还原图存在、文件大小 > 0；否则跳过并打印告警。
- 归档预算不受影响（仍只清理 04 候选）。

### 5. 测试

- 单测：还原替换逻辑（原图删除、kept_path 更新、deobfuscated 置位）。
- 单测：迁移逻辑（含"还原图缺失则跳过"）。
- 单测：还原失败不删。
- 单测：报告标记与遮罩（index.html 含开关、图库页对标记图应用模糊类）。
- 全量 pytest 保持通过。

## 明确不做（本子项目范围外）

- 面板设置里加遮罩开关（用户要求放报告首页）。
- 03_AI上下文 提示词绑定优化（子项目 2）。
- 99_普通无元数据 分组处理。
- 归档预算/清理策略改动。

## 交付物

- `store.py`：`deobfuscated` 列 + 迁移。
- `collection.py` / `maintenance.py`：还原替换与存量迁移。
- `build_image_view.py` / `context_view.py`：报告标记与遮罩开关。
- 测试用例更新与新增。
