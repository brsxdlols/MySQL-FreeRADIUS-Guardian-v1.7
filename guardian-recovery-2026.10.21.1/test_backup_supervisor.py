import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import backup_supervisor as supervisor

class PreflightTests(unittest.TestCase):
    def test_available_lock_needs_no_wait(self):
        with patch.object(supervisor,'protector',return_value={'status':'unchanged'}) as protect, patch.object(supervisor.time,'sleep') as sleep, patch.object(supervisor,'notify') as notify:
            self.assertTrue(supervisor.wait_for_protector())
            protect.assert_called_once_with(True)
            sleep.assert_not_called();notify.assert_not_called()

    def test_normal_sample_contention_retries_then_proceeds(self):
        with patch.object(supervisor,'protector',side_effect=[{'status':'busy'},{'status':'busy'},{'status':'unchanged'}]) as protect, patch.object(supervisor.time,'sleep') as sleep, patch.object(supervisor,'log'), patch.object(supervisor,'notify') as notify:
            self.assertTrue(supervisor.wait_for_protector())
            self.assertEqual(protect.call_count,3);self.assertEqual(sleep.call_count,2)
            notify.assert_not_called()

    def test_persistent_contention_has_deadline_and_alert(self):
        with patch.object(supervisor,'protector',return_value={'status':'busy'}) as protect, patch.object(supervisor.time,'monotonic',side_effect=[100,100,102,104]), patch.object(supervisor.time,'sleep') as sleep, patch.object(supervisor,'log'), patch.object(supervisor,'notify') as notify:
            self.assertFalse(supervisor.wait_for_protector(timeout=4))
            self.assertEqual(protect.call_count,3);self.assertEqual(sleep.call_count,2)
            notify.assert_called_once()

    def test_preflight_error_is_not_treated_as_success(self):
        with patch.object(supervisor,'protector',side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError):supervisor.wait_for_protector()

class QuarantineTests(unittest.TestCase):
    def test_incomplete_backup_is_preserved_and_index_no_longer_says_maz(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);backups=root/'backups';backups.mkdir();batch=root/'private';batch.mkdir()
            index=root/'backup.db';db=sqlite3.connect(str(index))
            db.execute('CREATE TABLE backup(uuid VARCHAR(64) PRIMARY KEY,data DATETIME,descricao VARCHAR(255),arquivo VARCHAR(16),tipo VARCHAR(3))')
            db.execute("INSERT INTO backup VALUES('synthetic','2026-01-01','backup automatico','LAB123','maz')");db.commit();db.close()
            file=backups/'LAB123.maz';file.write_bytes(b'synthetic-incomplete-archive')
            old_dir,old_index=supervisor.BACKUPS,supervisor.INDEX
            try:
                supervisor.BACKUPS=backups;supervisor.INDEX=index
                supervisor.quarantine(file,{'classification':'rejected'},batch)
                self.assertFalse(file.exists())
                rejected=backups/'.guardian-rejected'/batch.name/file.name
                self.assertEqual(rejected.read_bytes(),b'synthetic-incomplete-archive')
                db=sqlite3.connect(str(index));self.assertEqual(db.execute('SELECT tipo FROM backup').fetchone()[0],'err');self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0],'ok');db.close()
                snapshot=sqlite3.connect(str(batch/'backup-index-before.db'));self.assertEqual(snapshot.execute('SELECT tipo FROM backup').fetchone()[0],'maz');snapshot.close()
            finally:supervisor.BACKUPS=old_dir;supervisor.INDEX=old_index

    def test_unsafe_name_refused_without_changing_index(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);file=root/'unexpected name.maz';file.write_bytes(b'x')
            with self.assertRaises(RuntimeError):supervisor.quarantine(file,{},root)
            self.assertEqual(file.read_bytes(),b'x')

if __name__=='__main__':unittest.main()
