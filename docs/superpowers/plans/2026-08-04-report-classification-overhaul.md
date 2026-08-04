# 报告分类重构（03 绑定 + 01 折叠 + 性能）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 03_AI上下文 改为"提示词绑定区 + 参数/模型讨论区"（规则判定，LLM 模式可选），01_AI元数据 按 prompt 同批默认折叠，报告生成时间不再随总量线性暴涨，并迁移存量 03 数据。

**Architecture:** 新增 `prompt_binding.py`（提示词消息识别 + 时序/引用绑定）与 `ai_discussion_judge.py`（参数讨论判定，rule/llm/both 模式）；`images` 表新增 `bound_prompt`、`prompt_key` 列；`build_image_view` 输出两个 03 分类 + 01 同批折叠 + 每类 200 张上限；`ai_context` 批次摘要停用。

**Tech Stack:** Python 3.11（PIL、sqlite3、yaml）、pytest、DeepSeek API（可选 LLM 判定）。

规格：`docs/superpowers/specs/2026-08-04-report-classification-overhaul-design.md`

---

## 文件结构

- `qq_onebot_whitelist/prompt_binding.py`：提示词/参数消息识别、时序与引用绑定。
- `qq_onebot_whitelist/ai_discussion_judge.py`：参数讨论判定（rule/llm/both + token 日志）。
- `qq_onebot_whitelist/store.py`：`bound_prompt`、`prompt_key` 列 + 索引 + 回填。
- `qq_onebot_whitelist/collection.py`：入库按绑定结果分区。
- `qq_onebot_whitelist/maintenance.py`：存量 03 重分类。
- `qq_onebot_whitelist/config.py` / `config_bridge.py`：`images.ai_discussion_judge`；`features.ai_context` 默认关闭。
- `qq_onebot_whitelist/build_image_view.py`：新分类、提示词卡片页、同批折叠、200 张上限。
- `qq_onebot_whitelist/onebot.py`：`ai_context_loop` 依配置默认不启动。
- `tests/`：对应测试。

---

### Task 1: store.py 增加 bound_prompt / prompt_key 列与回填

**Files:**
- Modify: `qq_onebot_whitelist/store.py`
- Test: `tests/test_store_summary.py`

- [ ] **Step 1: 写失败测试**

```python
def test_bound_prompt_and_prompt_key_columns(tmp_path):
    import sqlite3
    from qq_onebot_whitelist.store import Store
    db = tmp_path / "data" / "bot.db"
    store = Store(db)
    store.record_image(scope="group:1", user_id="u", result={
        "sha256": "p1", "format": "PNG", "size": 1, "width": 64, "height": 64,
        "kept_path": str(tmp_path / "a.png"), "retention_reason": "prompt_bound",
        "bound_prompt": "1girl, solo",
        "prompt_key": "abc123",
    }, raw={})
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT bound_prompt, prompt_key FROM images WHERE sha256='p1'").fetchone()
    conn.close()
    assert row == ("1girl, solo", "abc123")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_store_summary.py::test_bound_prompt_and_prompt_key_columns -v`
Expected: FAIL（无 bound_prompt/prompt_key 列）

- [ ] **Step 3: 实现**

`_migrate` 中 `deobfuscated` 迁移之后追加：

```python
        if 'bound_prompt' not in image_cols:
            conn.execute('ALTER TABLE images ADD COLUMN bound_prompt TEXT')
        if 'prompt_key' not in image_cols:
            conn.execute('ALTER TABLE images ADD COLUMN prompt_key TEXT')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_images_prompt_key ON images(prompt_key)')
```

`record_image` 的 INSERT 列与参数追加 `bound_prompt, prompt_key`：

```python
                '''INSERT INTO images (
                  scope, user_id, url, sha256, size, format, width, height, metadata_keys_json,
                  has_ai_metadata, ai_source, text_excerpt, kept_path, retention_reason, restored_path,
                  deobfuscated, bound_prompt, prompt_key, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
```

参数元组在 `deobfuscated` 之后追加 `result.get('bound_prompt'), result.get('prompt_key'),`。

新增回填方法（供迁移与入库共用）：

```python
    def backfill_prompt_key(self, image_id: int, prompt_key: str) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute('UPDATE images SET prompt_key=? WHERE id=?', (prompt_key, int(image_id)))
            conn.commit()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_store_summary.py::test_bound_prompt_and_prompt_key_columns -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add qq_onebot_whitelist/store.py tests/test_store_summary.py
git commit -m "feat: bound_prompt and prompt_key columns"
```

---

### Task 2: prompt_binding.py 提示词/参数消息识别

**Files:**
- Create: `qq_onebot_whitelist/prompt_binding.py`
- Test: `tests/test_prompt_binding.py`

- [ ] **Step 1: 写失败测试**

```python
import re
from qq_onebot_whitelist.prompt_binding import is_prompt_message, is_params_message

def test_is_prompt_message_recognizes_real_prompts():
    assert is_prompt_message("/绘图 文生图 1girl, solo")
    assert is_prompt_message("1girl, solo, cat girl, blonde hair")
    assert is_prompt_message("prompt: 1girl, best quality")
    assert is_prompt_message("图生图 一个女孩坐在椅子上")

def test_is_prompt_message_rejects_false_positives():
    assert not is_prompt_message("我不写提示词")
    assert not is_prompt_message("提示词是什么")
    assert not is_prompt_message("fp8下好了，测测fp8")
    assert not is_prompt_message("4090 48g")

def test_is_params_message_detects_param_talk():
    assert is_params_message("低噪重绘效果没原来好")
    assert is_params_message("这模型用什么sampler跑的")
    assert is_params_message("4090 48g 出图快")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_prompt_binding.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

```python
"""提示词/参数讨论消息识别与图片绑定。

- 提示词消息：/绘图 文生图/图生图 指令、booru tag 行、prompt: 块。
- 参数讨论消息：提到模型/采样器/显卡/出图等 AI 生成参数话题。
"""
from __future__ import annotations

import re

PROMPT_RE = re.compile(
    r'(/绘图|文生图|图生图'
    r'|\b(1girl|1boy|masterpiece|best quality)\b'
    r'|prompt\s*[:：]'
    r'|\b(lora|sdxl|flux|novelai)\b)', re.I)

PARAMS_RE = re.compile(
    r'(ckpt|sampler|denoise|steps|seed|lora|模型|显卡|炼丹|出图|生成'
    r'|显存|fp8|低噪|重绘|画质|分辨率|seedvr)', re.I)


def is_prompt_message(text: str) -> bool:
    return bool(PROMPT_RE.search(text or ''))


def is_params_message(text: str) -> bool:
    return bool(PARAMS_RE.search(text or ''))
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_prompt_binding.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add qq_onebot_whitelist/prompt_binding.py tests/test_prompt_binding.py
git commit -m "feat: prompt/params message detection"
```

---

### Task 3: prompt_binding.py 时序与引用绑定

**Files:**
- Modify: `qq_onebot_whitelist/prompt_binding.py`
- Test: `tests/test_prompt_binding.py`

- [ ] **Step 1: 写失败测试**

```python
from qq_onebot_whitelist.prompt_binding import bind_prompt_for_image

def test_temporal_binding_uses_last_prompt_in_window():
    records = [
        {"text": "随便聊聊"},
        {"text": "/绘图 文生图 A girl", "id": 10},
        {"text": "真好看"},
        {"text": "1girl, solo, cat ears", "id": 12},
    ]
    kind, prompt = bind_prompt_for_image(records, reply_to=None)
    assert kind == "prompt"
    assert prompt == "1girl, solo, cat ears"

def test_quote_binding_image_quotes_prompt():
    records = [
        {"text": "/绘图 文生图 fox girl", "id": 20},
        {"text": "", "reply_to_message_id": "20", "quoted_text": "/绘图 文生图 fox girl"},
    ]
    kind, prompt = bind_prompt_for_image(records, reply_to="20")
    assert kind == "prompt"
    assert "fox girl" in prompt

def test_quote_binding_text_quotes_image():
    # 图片消息 id=30；其后的文本引用 30 且含提示词 → 绑定该文本
    records = [
        {"text": "1girl, solo", "id": 31, "reply_to_message_id": "30", "quoted_text": ""},
    ]
    kind, prompt = bind_prompt_for_image(records, reply_to=None, own_message_id="30")
    assert kind == "prompt"
    assert prompt == "1girl, solo"

def test_no_prompt_falls_through():
    records = [{"text": "这图好看"}, {"text": "fp8 出图快"}]
    kind, prompt = bind_prompt_for_image(records, reply_to=None)
    assert kind == "params"
    assert prompt == ""

def test_no_signal_returns_none():
    records = [{"text": "吃饭了吗"}, {"text": "哈哈"}]
    assert bind_prompt_for_image(records, reply_to=None) == (None, "")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_prompt_binding.py -v`
Expected: FAIL（bind_prompt_for_image 不存在）

- [ ] **Step 3: 实现**

`prompt_binding.py` 追加：

```python
def bind_prompt_for_image(
    records: list[dict],
    reply_to: str | None = None,
    own_message_id: str | None = None,
) -> tuple[str | None, str]:
    """为图片判定绑定：返回 (kind, prompt_text)。

    kind: 'prompt'（进提示词绑定区）| 'params'（进参数讨论区）| None（无信号）。
    records: 按时间正序的附近消息（recent_records 格式，含 quoted_text/reply_to_message_id）。
    reply_to: 图片消息引用的消息 id；own_message_id: 图片消息自身的 id。
    """
    # 引用绑定①：图片引用含提示词的文本
    if reply_to:
        for rec in records:
            if str(rec.get('id') or '') == str(reply_to):
                if is_prompt_message(str(rec.get('text') or '')):
                    return 'prompt', str(rec.get('text') or '')
                break
        for rec in records:
            if str(rec.get('reply_to_message_id') or '') == str(reply_to):
                quoted = str(rec.get('quoted_text') or '')
                if is_prompt_message(quoted):
                    return 'prompt', quoted
    # 引用绑定②：文本引用图片且含提示词
    if own_message_id:
        for rec in records:
            if str(rec.get('reply_to_message_id') or '') == str(own_message_id) \
                    and is_prompt_message(str(rec.get('text') or '')):
                return 'prompt', str(rec.get('text') or '')
    # 时序绑定：最近 6 条中最后一条提示词消息
    last_prompt = None
    for rec in records[-6:]:
        if is_prompt_message(str(rec.get('text') or '')):
            last_prompt = str(rec.get('text') or '')
    if last_prompt:
        return 'prompt', last_prompt
    # 参数/模型讨论
    if any(is_params_message(str(rec.get('text') or '')) for rec in records[-6:]):
        return 'params', ''
    return None, ''
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_prompt_binding.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add qq_onebot_whitelist/prompt_binding.py tests/test_prompt_binding.py
git commit -m "feat: temporal and quote prompt binding"
```

---

### Task 4: collection.py 入库分区

**Files:**
- Modify: `qq_onebot_whitelist/collection.py`
- Test: `tests/test_collection_restore.py`

- [ ] **Step 1: 写失败测试**

```python
def test_process_event_image_prompt_bound(tmp_path, monkeypatch):
    import sqlite3
    import qq_onebot_whitelist.collection as collection
    from qq_onebot_whitelist.config import AppConfig
    from qq_onebot_whitelist.store import Store
    data = tmp_path / "data"
    store = Store(data / "bot.db")
    config = AppConfig(data_dir=data)
    img = data / "images" / "ai" / "ab" / "abc.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"x")

    def fake_process_image_url(url, **kwargs):
        return {"url": url, "sha256": "abc", "phash": None, "blockiness": 0.0, "size": 1,
                "format": "PNG", "width": 4, "height": 4, "metadata_keys": [],
                "has_ai_metadata": False, "ai_source": None, "text_excerpt": "",
                "kept_path": str(img), "retention_reason": "candidate"}

    def fake_bind(records, reply_to=None, own_message_id=None):
        return "prompt", "1girl, solo"

    monkeypatch.setattr(collection, "process_image_url", fake_process_image_url)
    monkeypatch.setattr(collection, "bind_prompt_for_image", fake_bind)
    monkeypatch.setattr(collection, "analyze_image", lambda p: None)

    collection.process_event_image(store, scope="group:1", user_id="u",
        image={"url": "http://x/i.png"}, nearby_text="", message_db_id=1, config=config)

    conn = sqlite3.connect(data / "bot.db")
    row = conn.execute("SELECT retention_reason, bound_prompt FROM images").fetchone()
    conn.close()
    assert row == ("prompt_bound", "1girl, solo")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_collection_restore.py::test_process_event_image_prompt_bound -v`
Expected: FAIL（retention_reason 非 prompt_bound）

- [ ] **Step 3: 实现**

`collection.py` import 追加：

```python
from .prompt_binding import bind_prompt_for_image
from .store import reply_to_message_id
```

`process_event_image` 中 `result = process_image_url(...)` 之后、混淆检测之前插入：

```python
        # 03 提示词/参数绑定（无 AI 元数据图）
        if not result.get('has_ai_metadata'):
            try:
                records = store.recent_records(scope, limit=6)
            except Exception:
                records = []
            kind, prompt = bind_prompt_for_image(
                records,
                reply_to=reply_to_message_id(event or {}),
                own_message_id=str((event or {}).get('message_id') or '') or None,
            )
            if kind == 'prompt':
                result['retention_reason'] = 'prompt_bound'
                result['bound_prompt'] = prompt[:2000]
            elif kind == 'params':
                result['retention_reason'] = 'params_discussion'
```

`record_image` 调用已通过 Task 1 落库 `bound_prompt`。

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_collection_restore.py -v`
Expected: PASS

- [ ] **Step 5: 全量测试并提交**

Run: `.\.venv\Scripts\python.exe -m pytest tests -q`
Expected: 通过（既有 nearby_ai_context 断言需更新为新 reason）

```bash
git add qq_onebot_whitelist/collection.py tests/test_collection_restore.py
git commit -m "feat: ingest classifies prompt-bound / params-discussion"
```

---

### Task 5: ai_discussion_judge.py 判定模式（rule/llm/both）

**Files:**
- Create: `qq_onebot_whitelist/ai_discussion_judge.py`
- Modify: `qq_onebot_whitelist/config.py` / `config_bridge.py`
- Test: `tests/test_ai_discussion_judge.py`

- [ ] **Step 1: 写失败测试**

```python
def test_judge_rule_mode():
    from qq_onebot_whitelist.ai_discussion_judge import should_keep_params
    assert should_keep_params("fp8 出图快", mode="rule") is True
    assert should_keep_params("吃饭了吗", mode="rule") is False

def test_judge_llm_mode_records_cost(tmp_path, monkeypatch):
    from qq_onebot_whitelist.ai_discussion_judge import should_keep_params, reset_cost_log
    reset_cost_log()
    calls = {"n": 0}
    def fake_llm(texts):
        calls["n"] += 1
        return [True] * len(texts), 120, 60
    monkeypatch.setattr("qq_onebot_whitelist.ai_discussion_judge._llm_judge_batch", fake_llm)
    assert should_keep_params("fp8 出图快", mode="llm") is True
    assert calls["n"] == 1
    log = __import__("qq_onebot_whitelist.ai_discussion_judge", fromlist=["cost_log"]).cost_log
    assert log["total_tokens"] == 120
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ai_discussion_judge.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

```python
"""参数/模型讨论判定：rule（关键词）| llm（DeepSeek 复核）| both（规则预筛+LLM）。
LLM 调用按批处理并记录 token 成本（运行后可对比）。
"""
from __future__ import annotations

from .prompt_binding import is_params_message

cost_log = {"calls": 0, "total_tokens": 0}


def reset_cost_log() -> None:
    cost_log["calls"] = 0
    cost_log["total_tokens"] = 0


def _llm_judge_batch(texts: list[str]) -> tuple[list[bool], int, int]:
    """调用 DeepSeek 判定每段文本是否在讨论 AI 图像生成。

    返回 (bools, prompt_tokens, completion_tokens)；无配置/调用失败时全部回退 True
    （保持规则结果，不阻塞流程）。
    """
    import json
    import urllib.request
    from .llm_summary import LLMConfig

    cfg = LLMConfig.ds_fallback_from_env_file()
    if cfg is None or not cfg.api_key:
        return [True] * len(texts), 0, 0
    system = '你是判断助手：判断给出的聊天文本是否在讨论 AI 图像生成（模型/提示词/出图/画质等）。只回答每段: 是/否'
    payload = {
        'model': cfg.model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': '\n---\n'.join(f'{i}: {t}' for i, t in enumerate(texts))},
        ],
        'temperature': 0,
    }
    req = urllib.request.Request(
        cfg.base_url.rstrip('/') + '/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {cfg.api_key}'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_seconds or 60) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        content = (data.get('choices') or [{}])[0].get('message', {}).get('content', '')
        usage = data.get('usage') or {}
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        verdicts = ['是' in ln for ln in lines[:len(texts)]]
        verdicts += [True] * (len(texts) - len(verdicts))
        return verdicts, int(usage.get('prompt_tokens') or 0), int(usage.get('completion_tokens') or 0)
    except Exception:
        return [True] * len(texts), 0, 0


def should_keep_params(text: str, mode: str = "rule") -> bool:
    rule_hit = is_params_message(text)
    if mode == "rule":
        return rule_hit
    if mode == "llm":
        verdicts, pt, ct = _llm_judge_batch([text])
        cost_log["calls"] += 1
        cost_log["total_tokens"] += pt + ct
        return bool(verdicts[0])
    # both
    if not rule_hit:
        return False
    verdicts, pt, ct = _llm_judge_batch([text])
    cost_log["calls"] += 1
    cost_log["total_tokens"] += pt + ct
    return bool(verdicts[0])
```

`config.py` 增加字段：

```python
    ai_discussion_judge: str = 'rule'
```

`load_config` 解析：

```python
    ai_discussion_judge=str((images.get('ai_discussion_judge') or 'rule')).lower()
```

`config_bridge.py` 的 images 区追加字段：

```python
        field('images.ai_discussion_judge', 'select', str(images.get('ai_discussion_judge') or 'rule'),
              'Discussion judge mode', '参数讨论判定模式', section='images',
              options=['rule', 'llm', 'both']),
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ai_discussion_judge.py -v`
Expected: PASS

- [ ] **Step 5: 全量测试并提交**

Run: `.\.venv\Scripts\python.exe -m pytest tests -q`
Expected: 通过

```bash
git add qq_onebot_whitelist/ai_discussion_judge.py qq_onebot_whitelist/config.py qq_onebot_whitelist/config_bridge.py tests/test_ai_discussion_judge.py
git commit -m "feat: configurable discussion judge mode with cost log"
```

---

### Task 6: 停用 LLM 批次摘要（ai_context 默认关）

**Files:**
- Modify: `qq_onebot_whitelist/config.py`
- Modify: `qq_onebot_whitelist/onebot.py`
- Test: `tests/test_ai_context_auto_config.py`

- [ ] **Step 1: 写失败测试**

```python
def test_ai_context_default_disabled():
    from qq_onebot_whitelist.config import AppConfig
    assert AppConfig().feature_ai_context is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ai_context_auto_config.py::test_ai_context_default_disabled -v`
Expected: FAIL（当前默认 True）

- [ ] **Step 3: 实现**

`config.py` 中 `feature_ai_context` 默认值改为 `False`（确认现状字段名后改对应行，若为 `ai_context_enabled` 则同名处理）。`onebot.py` 的 `run()` 只在启用时创建 `ai_context_loop` 任务：

```python
        tasks = [startup_task, report_task, keepalive_task, status_task, sync_task, image_task]
        if config.feature_ai_context:
            ai_task = asyncio.create_task(ai_context_loop(config_path, store))
            tasks.append(ai_task)
```

`config.yaml` 将 `ai_context: true` 改为 `ai_context: false`。

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_ai_context_auto_config.py::test_ai_context_default_disabled -v`
Expected: PASS

- [ ] **Step 5: 全量测试并提交**

Run: `.\.venv\Scripts\python.exe -m pytest tests -q`
Expected: 通过（相关 ai_context 测试如断言默认开启需同步调整）

```bash
git add qq_onebot_whitelist/config.py qq_onebot_whitelist/onebot.py config.yaml
git commit -m "feat: disable ai_context batch summaries by default"
```

---

### Task 7: maintenance.py 存量 03 重分类

**Files:**
- Modify: `qq_onebot_whitelist/maintenance.py`
- Test: `tests/test_image_file_sync.py`

- [ ] **Step 1: 写失败测试**

```python
def test_reclassify_historical_03(tmp_path):
    import sqlite3
    from pathlib import Path
    from qq_onebot_whitelist.maintenance import reclassify_historical_03
    from qq_onebot_whitelist.store import Store
    data = tmp_path / "data"
    store = Store(data / "bot.db")
    img = data / "images" / "ai" / "ab" / "abc.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"x")
    store.record_message(scope="group:1", user_id="u", text="/绘图 文生图 fox girl", raw={"message_id": "m1"})
    msg_id = store.message_row_id("group:1", {"message_id": "m1"})
    # 直接以第一条消息 id 为图片所在消息
    store.record_image(scope="group:1", user_id="u", result={
        "sha256": "abc", "format": "PNG", "size": 1, "width": 64, "height": 64,
        "kept_path": str(img), "retention_reason": "nearby_ai_context",
        "raw": {}, "text_excerpt": "",
    }, raw={"message_db_id": msg_id})
    changed = reclassify_historical_03(tmp_path)
    assert changed == 1
    conn = sqlite3.connect(data / "bot.db")
    row = conn.execute("SELECT retention_reason, bound_prompt FROM images").fetchone()
    conn.close()
    assert row[0] == "prompt_bound"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_image_file_sync.py::test_reclassify_historical_03 -v`
Expected: FAIL（函数不存在）

- [ ] **Step 3: 实现**

```python
def reclassify_historical_03(project_dir: str | Path) -> int:
    """存量 03 重分类：按绑定规则重判 prompt_bound / params_discussion / candidate。"""
    from .prompt_binding import bind_prompt_for_image
    from .store import Store
    project_dir = Path(project_dir)
    db = project_dir / 'data' / 'bot.db'
    if not db.exists():
        return 0
    store = Store(db)
    changed = 0
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT id, scope, raw_json FROM images WHERE retention_reason='nearby_ai_context'"
        ).fetchall()
        for row_id, scope, raw_json in rows:
            try:
                message_db_id = int(json.loads(raw_json or '{}').get('message_db_id'))
            except Exception:
                message_db_id = None
            records = store.recent_records(str(scope), limit=6) if scope else []
            kind, prompt = bind_prompt_for_image(records)
            if kind == 'prompt':
                conn.execute("UPDATE images SET retention_reason='prompt_bound', bound_prompt=? WHERE id=?",
                             (prompt[:2000], row_id))
                changed += 1
            elif kind == 'params':
                conn.execute("UPDATE images SET retention_reason='params_discussion' WHERE id=?", (row_id,))
                changed += 1
            else:
                conn.execute("UPDATE images SET retention_reason='candidate' WHERE id=?", (row_id,))
                changed += 1
        conn.commit()
    return changed
```

并在 `sync_image_files` 中调用（在 `reclassify_possible_obfuscation` 之后）：

```python
    historical_03 = reclassify_historical_03(project_dir)
```

返回值 dict 增加 `historical_03_reclassified` 键。

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_image_file_sync.py::test_reclassify_historical_03 -v`
Expected: PASS

- [ ] **Step 5: 全量测试并提交**

Run: `.\.venv\Scripts\python.exe -m pytest tests -q`
Expected: 通过

```bash
git add qq_onebot_whitelist/maintenance.py tests/test_image_file_sync.py
git commit -m "feat: reclassify historical 03 images by binding rules"
```

---

### Task 8: build_image_view.py 新分类 + 提示词卡片页 + 同批折叠 + 200 上限

**Files:**
- Modify: `qq_onebot_whitelist/build_image_view.py`
- Test: `tests/test_view_index.py`

- [ ] **Step 1: 写失败测试**

```python
def test_view_prompt_bound_card_and_batch_collapse(tmp_path):
    import sqlite3
    from pathlib import Path
    from qq_onebot_whitelist.build_image_view import build_view
    data = tmp_path / "data"
    data.mkdir(parents=True)
    store = __import__("qq_onebot_whitelist.store", fromlist=["Store"]).Store(data / "bot.db")
    img = data / "images" / "ai" / "ab" / "a.png"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"x" * 10)
    img2 = data / "images" / "ai" / "ab" / "b.png"
    img2.write_bytes(b"y" * 10)
    store.record_image(scope="group:1", user_id="u", result={
        "sha256": "a", "format": "PNG", "size": 10, "width": 64, "height": 64,
        "kept_path": str(img), "retention_reason": "prompt_bound", "bound_prompt": "1girl, solo",
    }, raw={})
    store.record_image(scope="group:1", user_id="u", result={
        "sha256": "b", "format": "PNG", "size": 10, "width": 64, "height": 64,
        "kept_path": str(img2), "retention_reason": "ai_metadata", "ai_source": "ComfyUI",
        "text_excerpt": "1girl, solo", "prompt_key": "samekey",
    }, raw={})
    counts = build_view(tmp_path)
    bind_dir = tmp_path / "data" / "view" / "03_提示词绑定"
    page = next(bind_dir.rglob("index.html"))
    html = page.read_text(encoding="utf-8")
    assert "1girl, solo" in html
    ai_dir = tmp_path / "data" / "view" / "01_AI元数据_ComfyUI"
    html2 = next(ai_dir.rglob("index.html")).read_text(encoding="utf-8")
    assert "_pk" in html2 or "samekey" in html2
    index = (tmp_path / "data" / "view" / "index.html").read_text(encoding="utf-8")
    assert "同批折叠" in index
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_view_index.py::test_view_prompt_bound_card_and_batch_collapse -v`
Expected: FAIL（无 03_提示词绑定 分类 / 无同批折叠标记）

- [ ] **Step 3: 实现**

`CATEGORY_NAMES` 更新：

```python
    'prompt_bound': '03_提示词绑定',
    'params_discussion': '03_参数讨论',
```

移除 `'nearby_ai_context': '03_AI上下文'`（存量迁移后不再产生）。`build_view` 中不再调用 `build_context_view`，改为对 `prompt_bound` 分类调用新函数 `write_prompt_bound_gallery`；`params_discussion` 走普通图库。新增每类 200 张上限：

```python
NEWEST_PER_CATEGORY = 200
```

在 `build_view` 的行循环里按分类计数截断（`if counts.get(cat, 0) >= NEWEST_PER_CATEGORY: continue` 置于链接之前）。

01 文件名携带 `_pk` 标记（供同批折叠分组）：

```python
        pk = str(row['prompt_key'] or '')[:8] if 'prompt_key' in row.keys() and row['prompt_key'] else ''
        filename = safe_name(f"#{row['id']}_{w or 'x'}x{h or 'x'}_{reason}{'_pk' + pk if pk else ''}") + ext
```

遮罩标记条件更新（覆盖新的 03 分类）：

```python
        mask_marker = '_还原' if (is_deobfuscated and reason in (
            'positive_feedback', 'prompt_bound', 'params_discussion')) else ''
```

`build_view` 收集 `prompt_bound` 行并调用新函数（替换原来的 `build_context_view` 调用）：

```python
    prompt_bound_items = []
    ...
        if reason == 'prompt_bound':
            prompt_bound_items.append({
                'id': str(row['id']),
                'image_rel': os.path.relpath(dst, view / cat).replace(os.sep, '/'),
                'meta': f"{row['seen_at'] or ''} · {row['width'] or 'x'}x{row['height'] or 'x'}",
                'prompt': str(row['bound_prompt'] or ''),
            })
    ...
    if prompt_bound_items:
        write_prompt_bound_gallery(view / CATEGORY_NAMES['prompt_bound'], prompt_bound_items)
```

新增函数：

```python
def write_prompt_bound_gallery(cat_dir: Path, items: list[dict[str, object]]) -> None:
    """03 提示词绑定分类：图片 + 提示词成对卡片。"""
    cards = []
    for item in items:
        url = url_path(item['image_rel'])
        cards.append(
            '<article class="card">'
            f'<a href="{url}"><img src="{url}" loading="lazy"></a>'
            f'<p class="muted">#{html.escape(str(item["id"]))} · {html.escape(str(item["meta"]))}</p>'
            f'<pre style="white-space:pre-wrap;background:#151922;padding:10px;border-radius:8px">'
            f'{html.escape(str(item.get("prompt") or ""))}</pre>'
            '</article>'
        )
    doc = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
           '<title>03 提示词绑定</title><style>'
           'body{font-family:system-ui,sans-serif;margin:22px;background:#0d0f13;color:#eef1f6}'
           '.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}'
           '.card{background:#171a21;border:1px solid #2b313d;border-radius:12px;padding:10px}'
           '.card img{width:100%;max-height:60vh;object-fit:contain;background:#000;border-radius:8px}'
           'a{color:#9fc2ff}.muted{color:#aab2c0}</style></head><body>'
           f'<h1>03 提示词绑定</h1><div class="cards">{"".join(cards)}</div></body></html>')
    cat_dir.mkdir(parents=True, exist_ok=True)
    (cat_dir / 'index.html').write_text(doc, encoding='utf-8')
```

同时移除 `build_context_view` 的调用与相关上下文页生成（`context_view.py` 保留文件但不再被引用；相关测试更新）。

`write_category_gallery` 的 `.cell` 链接增加 `data-batch` 属性（01 分类文件名含 `_pk<hash8>`，JS 从 href 提取 `_pk([0-9a-f]{8})` 分组）；页面 `<script>` 增加同批折叠逻辑：

```python
const collapse=localStorage.getItem("collapseBatches")!=="0";
if(collapse){const groups={};cells.forEach(a=>{const m=(a.getAttribute('href')||'').match(/_pk([0-9a-f]{8})/);if(m){const k=m[1];(groups[k]=groups[k]||[]).push(a);}});Object.values(groups).forEach(g=>{if(g.length>1){g.forEach((a,i)=>{if(i>0){a.style.display='none';}});}});}
```

`write_view_index` 的 `mask_html` 之后追加"同批折叠"开关（localStorage key `collapseBatches`，默认开）。

```python
    collapse_html = (
        '<label style="display:inline-flex;align-items:center;gap:6px;margin:0 0 14px 18px;cursor:pointer">'
        '<input type="checkbox" id="collapseBatches" checked> 01 同批折叠（同一提示词的图合并）</label>'
        '<script>'
        'const cb=document.getElementById("collapseBatches");'
        'try{cb.checked=localStorage.getItem("collapseBatches")!=="0";}catch(e){}'
        'cb.addEventListener("change",()=>{try{localStorage.setItem("collapseBatches",cb.checked?"1":"0");}catch(e){}});'
        '</script>'
    )
    doc = doc.replace('</style><body><h1>QQ AI 图片视图</h1>',
                      '</style><body><h1>QQ AI 图片视图</h1>' + mask_html + collapse_html)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_view_index.py -v`
Expected: PASS

- [ ] **Step 5: 全量测试并提交**

Run: `.\.venv\Scripts\python.exe -m pytest tests -q`
Expected: 通过（涉及旧 `03_AI上下文`/context_view 的测试需更新）

```bash
git add qq_onebot_whitelist/build_image_view.py tests/test_view_index.py
git commit -m "feat: prompt-bound gallery, params gallery, batch collapse, 200 cap"
```

---

### Task 9: 01 prompt_key 回填（存量）

**Files:**
- Modify: `qq_onebot_whitelist/maintenance.py`
- Test: `tests/test_image_file_sync.py`

- [ ] **Step 1: 写失败测试**

```python
def test_backfill_prompt_keys(tmp_path):
    import sqlite3, hashlib
    from qq_onebot_whitelist.maintenance import backfill_prompt_keys
    from qq_onebot_whitelist.store import Store
    data = tmp_path / "data"
    store = Store(data / "bot.db")
    img = data / "a.png"
    img.write_bytes(b"x")
    store.record_image(scope="group:1", user_id="u", result={
        "sha256": "a", "format": "PNG", "size": 1, "width": 64, "height": 64,
        "kept_path": str(img), "retention_reason": "ai_metadata",
        "text_excerpt": "1girl, solo", "ai_source": "ComfyUI",
    }, raw={})
    changed = backfill_prompt_keys(tmp_path)
    assert changed == 1
    conn = sqlite3.connect(data / "bot.db")
    pk = conn.execute("SELECT prompt_key FROM images").fetchone()[0]
    conn.close()
    assert pk == hashlib.sha1(b"1girl, solo").hexdigest()[:16]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_image_file_sync.py::test_backfill_prompt_keys -v`
Expected: FAIL（函数不存在）

- [ ] **Step 3: 实现**

```python
def backfill_prompt_keys(project_dir: str | Path) -> int:
    """为存量 01 图按 text_excerpt 回填 prompt_key（sha1 前 16 位）。"""
    project_dir = Path(project_dir)
    db = project_dir / 'data' / 'bot.db'
    if not db.exists():
        return 0
    changed = 0
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT id, text_excerpt FROM images "
            "WHERE retention_reason='ai_metadata' AND prompt_key IS NULL AND text_excerpt IS NOT NULL"
        ).fetchall()
        for row_id, excerpt in rows:
            text = str(excerpt or '')
            if not text.strip():
                continue
            pk = hashlib.sha1(text.encode('utf-8', errors='replace')).hexdigest()[:16]
            conn.execute('UPDATE images SET prompt_key=? WHERE id=?', (pk, row_id))
            changed += 1
        conn.commit()
    return changed
```

`sync_image_files` 中调用并计入返回 dict（键 `prompt_keys_backfilled`）。

- [ ] **Step 4: 运行测试确认通过**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_image_file_sync.py::test_backfill_prompt_keys -v`
Expected: PASS

- [ ] **Step 5: 全量测试并提交**

Run: `.\.venv\Scripts\python.exe -m pytest tests -q`
Expected: 通过

```bash
git add qq_onebot_whitelist/maintenance.py tests/test_image_file_sync.py
git commit -m "feat: backfill prompt_key for existing ai_metadata images"
```

---

### Task 10: 真实数据迁移与验证

**Files:** 无（运行维护与重建）

- [ ] **Step 1: 停 bot**

Run: `taskkill /PID <run/bot.pid> /T /F`
Expected: 无残留 onebot 进程

- [ ] **Step 2: 迁移 + 回填 + 重建视图**

Run:
```bash
.\.venv\Scripts\python.exe -c "import sys; from pathlib import Path; sys.path.insert(0,'.'); from qq_onebot_whitelist.maintenance import reclassify_historical_03, backfill_prompt_keys, sync_image_files; print('h03:', reclassify_historical_03(Path('.'))); print('pk:', backfill_prompt_keys(Path('.'))); print('sync ok')"
```
Expected: 无报错；随后跑一次完整 `control view` 重建报告

- [ ] **Step 3: 验证**

Run: `.\.venv\Scripts\python.exe -c "import sqlite3; c=sqlite3.connect('data/bot.db'); print(c.execute(\"SELECT retention_reason, COUNT(*) FROM images GROUP BY retention_reason ORDER BY 2 DESC\").fetchall())"`
Expected: `prompt_bound` / `params_discussion` 出现，`nearby_ai_context` 为 0；视图出现 `03_提示词绑定`、`03_参数讨论`，无 `03_AI上下文`；`01_AI元数据_*` 每类 ≤200 张；index.html 含"同批折叠"开关

- [ ] **Step 4: 重启 bot 并确认**

Run: `Start-Process .\.venv\Scripts\python.exe -ArgumentList '-m','qq_onebot_whitelist.control','start' -WindowStyle Hidden`
Expected: `run/status.json` 全绿

- [ ] **Step 5: 收尾提交**

```bash
git status --short
```
如有遗留改动说明并提交。
