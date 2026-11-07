import hashlib
from pathlib import Path
import tempfile
import unittest
from install import review_sources
from install import backup_plan
from unittest.mock import patch

class BackupRoutingTests(unittest.TestCase):
    def test_native_backup_never_discovered_or_replaced(self):
        schedule='15 2 * * * root /opt/mk-auth/scripts/backup.php\n'
        with tempfile.TemporaryDirectory() as folder:
            result=backup_plan(Path(folder)/'absent',schedule)
        self.assertIsNone(result['supervised']);self.assertEqual(result['schedule'],schedule);self.assertEqual(result['status'],'preserved_not_managed')
    def test_existing_supervisor_and_paused_cron_are_preserved(self):
        schedule='# paused /usr/local/sbin/mkauth-backup-supervised\n'
        result=backup_plan(Path('/unused'),schedule)
        self.assertEqual(result['schedule'],schedule);self.assertIsNone(result['blueprint'])

class SourceReviewTests(unittest.TestCase):
    def test_first_install_accepts_all_guardians_absent(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=[str(Path(folder)/str(i)) for i in range(3)]
            review_sources(paths,{p:[] for p in paths},'not-a-known-hash')
            self.assertFalse(any(Path(p).exists() for p in paths))
    def test_reviewed_partial_coordinator_shim_can_be_repaired(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=[str(Path(folder)/str(i)) for i in range(3)];data=b'reviewed shim';Path(paths[0]).write_bytes(data)
            review_sources(paths,{p:[] for p in paths},hashlib.sha256(data).hexdigest())
            self.assertFalse(Path(paths[1]).exists())
    def test_partial_installation_is_rejected_without_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=[str(Path(folder)/str(i)) for i in range(3)];Path(paths[0]).write_bytes(b'partial')
            with self.assertRaises(RuntimeError):review_sources(paths,{p:[] for p in paths},'unknown')
            self.assertEqual(Path(paths[0]).read_bytes(),b'partial')
    def test_unknown_existing_script_is_rejected_without_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=[str(Path(folder)/str(i)) for i in range(3)]
            for p in paths:Path(p).write_bytes(b'custom-guardian')
            with self.assertRaises(RuntimeError):review_sources(paths,{p:[] for p in paths},'unknown')
            self.assertTrue(all(Path(p).read_bytes()==b'custom-guardian' for p in paths))
    def test_reviewed_existing_scripts_allow_upgrade(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=[str(Path(folder)/str(i)) for i in range(3)];data=b'reviewed-guardian'
            for p in paths:Path(p).write_bytes(data)
            review_sources(paths,{p:[hashlib.sha256(data).hexdigest()] for p in paths},'other-shim')

if __name__=='__main__':unittest.main()
