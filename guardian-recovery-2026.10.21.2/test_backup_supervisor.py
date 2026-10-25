import json
import sqlite3
import tempfile
import os
from contextlib import ExitStack
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

class BackupPolicyTests(unittest.TestCase):
    def policy(self,content,mode=0o600,provider='Synthetic Demo'):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        path=Path(folder.name)/'policy.json';path.write_text(json.dumps(content));path.chmod(mode)
        with patch.object(supervisor,'POLICY',path),patch.object(supervisor,'mysql_read',return_value=provider):
            return supervisor.backup_policy()

    def test_missing_policy_preserves_native_first(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(supervisor,'POLICY',Path(folder)/'absent'):
            self.assertEqual(supervisor.backup_policy(),{'mode':'native_first'})

    def test_compatible_primary_requires_matching_provider(self):
        with self.assertRaisesRegex(RuntimeError,'provider mismatch'):
            self.policy({'mode':'compatible_primary','validated_provider':'Another Demo','restore_reference_sha256':'a'*64})

    def test_compatible_primary_requires_restore_reference(self):
        with self.assertRaisesRegex(RuntimeError,'restore reference'):
            self.policy({'mode':'compatible_primary','validated_provider':'Synthetic Demo'})

    def test_matching_provider_policy_accepted(self):
        policy={'mode':'compatible_primary','validated_provider':'Synthetic Demo','restore_reference_sha256':'a'*64}
        self.assertEqual(self.policy(policy),policy)

    def test_world_readable_policy_refused(self):
        with self.assertRaisesRegex(RuntimeError,'private root-owned'):
            self.policy({'mode':'native_first'},mode=0o644)

    def test_symlink_policy_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'target').write_text('{"mode":"native_first"}')
            (root/'link').symlink_to(root/'target')
            with patch.object(supervisor,'POLICY',root/'link'),self.assertRaises(OSError):
                supervisor.backup_policy()

    def run_primary(self,generator):
        with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
            root=Path(folder)
            for name,value in [('ROOT',root/'state'),('PRIVATE',root/'private'),('BACKUP_LOCK',root/'lock')]:
                stack.enter_context(patch.object(supervisor,name,value))
            stack.enter_context(patch.object(supervisor,'backup_policy',return_value={'mode':'compatible_primary'}))
            stack.enter_context(patch.object(supervisor,'database_ready',return_value=True))
            stack.enter_context(patch.object(supervisor,'wait_for_protector',return_value=True))
            stack.enter_context(patch.object(supervisor,'mysql_read',return_value='0'))
            stack.enter_context(patch.object(supervisor,'generate',side_effect=generator))
            notify=stack.enter_context(patch.object(supervisor,'notify'))
            stack.enter_context(patch.object(supervisor,'log'))
            popen=stack.enter_context(patch.object(supervisor.subprocess,'Popen'))
            try:return supervisor.main(),notify.call_count
            finally:popen.assert_not_called()

    def test_primary_generates_without_starting_vendor_backup(self):
        self.assertEqual(self.run_primary(lambda private:{'file':'synthetic.maz','bytes':123,'tables':55}),(0,1))

    def test_dump_failure_does_not_announce_success_or_launch_vendor(self):
        def fail(private):raise RuntimeError('synthetic dump failure')
        with self.assertRaisesRegex(RuntimeError,'synthetic dump failure'):self.run_primary(fail)

if __name__=='__main__':unittest.main()
