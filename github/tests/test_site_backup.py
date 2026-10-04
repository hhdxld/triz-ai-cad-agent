"""验证在线备份可以恢复账本，且不会误删非备份文件。"""
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest

from site_backup import backup_database


class SiteBackupTests(unittest.TestCase):
    def test_backup_is_readable_and_retention_only_removes_owned_files(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source, target = root / "ledger.sqlite", root / "backups"
            with closing(sqlite3.connect(source)) as db, db:
                db.execute("CREATE TABLE example (value INTEGER)")
                db.execute("INSERT INTO example VALUES (42)")
            target.mkdir()
            unrelated = target / "owner-note.txt"
            unrelated.write_text("keep", encoding="utf-8")
            for _ in range(3):
                latest = backup_database(source, target, keep=2)
            self.assertEqual(len(list(target.glob("aicad-db-*.sqlite"))), 2)
            self.assertTrue(unrelated.exists())
            with closing(sqlite3.connect(latest)) as db:
                self.assertEqual(db.execute("SELECT value FROM example").fetchone()[0], 42)
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_missing_database_does_not_create_empty_ledger(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "missing.sqlite"
            self.assertIsNone(backup_database(source, Path(root) / "backups"))
            self.assertFalse(source.exists())
