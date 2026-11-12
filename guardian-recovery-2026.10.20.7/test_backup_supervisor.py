import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
import backup_supervisor as supervisor

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
