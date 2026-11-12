import hashlib
from pathlib import Path
import tempfile
import unittest
from install import review_sources
from install import backup_plan
from compatible_backup import TemplateUnavailable
from unittest.mock import patch

class BackupRoutingTests(unittest.TestCase):
    def test_unsupported_template_preserves_native_schedule(self):
        schedule='15 2 * * * root /opt/mk-auth/scripts/backup.php\n'
        with tempfile.TemporaryDirectory() as folder,patch('install.discover_template',side_effect=TemplateUnavailable('synthetic')):
            result=backup_plan(Path(folder)/'absent',schedule)
        self.assertFalse(result['supervised']);self.assertIsNone(result['blueprint']);self.assertEqual(result['schedule'],schedule)

    def test_existing_supervisor_without_template_requires_review(self):
        with tempfile.TemporaryDirectory() as folder,patch('install.discover_template',side_effect=TemplateUnavailable('synthetic')):
            with self.assertRaisesRegex(RuntimeError,'unexpected existing backup routing'):
                backup_plan(Path(folder)/'absent','15 2 * * * root /usr/local/sbin/mkauth-backup-supervised\n')

    def test_unexpected_discovery_failure_is_not_silently_downgraded(self):
        with tempfile.TemporaryDirectory() as folder,patch('install.discover_template',side_effect=OSError('synthetic IO error')):
            with self.assertRaises(OSError):backup_plan(Path(folder)/'absent','15 2 * * * root /opt/mk-auth/scripts/backup.php\n')

    def test_supported_template_enables_wrapper(self):
        with tempfile.TemporaryDirectory() as folder,patch('install.discover_template',return_value={'tables':['synthetic']}):
            result=backup_plan(Path(folder)/'absent','15 2 * * * root /opt/mk-auth/scripts/backup.php\n')
        self.assertTrue(result['supervised']);self.assertIn('/usr/local/sbin/mkauth-backup-supervised',result['schedule'])

    def test_reviewed_existing_template_remains_supervised(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'template.json';path.write_text('{"tables":["synthetic"]}')
            with patch('install.discover_template') as discover:
                result=backup_plan(path,'15 2 * * * root /usr/local/sbin/mkauth-backup-supervised\n')
                discover.assert_not_called()
        self.assertTrue(result['supervised'])

class SourceReviewTests(unittest.TestCase):
    def test_first_install_accepts_all_guardians_absent(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=[str(Path(folder)/str(i)) for i in range(3)]
            review_sources(paths,{p:[] for p in paths},'not-a-known-hash')
            self.assertFalse(any(Path(p).exists() for p in paths))
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
