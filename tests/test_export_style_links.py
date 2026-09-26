"""稳定导入目录硬链接生成测试。"""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from qq_onebot_whitelist.export_style_links import build_links


def make_db(path: Path, rows: list[tuple[str, str, str, int]]) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE images (id INTEGER PRIMARY KEY AUTOINCREMENT, kept_path TEXT,"
        " ai_source TEXT, retention_reason TEXT, has_ai_metadata INTEGER, merged_into INTEGER)")
    conn.executemany(
        "INSERT INTO images (kept_path, ai_source, retention_reason, has_ai_metadata, merged_into)"
        " VALUES (?, ?, ?, 1, NULL)", rows)
    conn.commit()
    conn.close()


def make_image(path: Path) -> Path:
    Image.new('RGB', (4, 4), (1, 2, 3)).save(path)
    return path


class ExportStyleLinksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / 'bot.db'
        self.comfy = make_image(self.root / 'comfy.png')
        self.a1111 = make_image(self.root / 'a1111.png')

    def tearDown(self):
        self.tmp.cleanup()

    def test_links_grouped_by_source_and_deduped(self):
        make_db(self.db, [
            (str(self.comfy), 'ComfyUI', 'ai_metadata'),
            (str(self.comfy), 'suspect:ComfyUI', 'params_discussion'),  # 同文件多行：取 ai_metadata 来源
            (str(self.a1111), 'A1111', 'ai_metadata'),
            (str(self.root / 'missing.png'), 'NovelAI', 'ai_metadata'),  # 文件缺失：跳过
        ])

        stats = build_links(self.db, self.root / 'out')

        self.assertEqual(stats['linked'], 2)
        self.assertEqual([p.name for p in (self.root / 'out' / 'ComfyUI').iterdir()], ['comfy.png'])
        self.assertEqual([p.name for p in (self.root / 'out' / 'A1111').iterdir()], ['a1111.png'])
        self.assertFalse((self.root / 'out' / 'NovelAI').exists(), '缺失文件不建目录')

    def test_reremove_stale_links_and_survive_rerun(self):
        make_db(self.db, [(str(self.comfy), 'ComfyUI', 'ai_metadata')])
        out = self.root / 'out'
        build_links(self.db, out)
        stale = out / 'ComfyUI' / 'stale.png'
        stale.write_bytes(b'old')
        changed = build_links(self.db, out)  # 来源没变：应保留链接、清掉杂散文件

        self.assertEqual(changed['kept'], 1)
        self.assertEqual(changed['stale_removed'], 1)
        self.assertTrue((out / 'ComfyUI' / 'comfy.png').exists())

    def test_source_change_replaces_link(self):
        make_db(self.db, [(str(self.comfy), 'NovelAI', 'ai_metadata')])
        out = self.root / 'out'
        build_links(self.db, out)
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE images SET ai_source='ComfyUI'")
        conn.commit()
        conn.close()

        build_links(self.db, out)

        self.assertFalse((out / 'NovelAI' / 'comfy.png').exists())
        self.assertTrue((out / 'ComfyUI' / 'comfy.png').exists())


if __name__ == '__main__':
    unittest.main()
