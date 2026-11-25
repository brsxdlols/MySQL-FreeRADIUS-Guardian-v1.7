import hashlib,os,subprocess,tempfile,time,unittest,signal
from pathlib import Path
from legacy_migration import reviewed_legacy,read_legacy,migrate_cron,cron_updates,active_legacy_processes
from install import review_sources
FIXTURE=Path(__file__).with_name('legacy_monitor_fixture.sh').read_bytes()
class LegacyMigrationTests(unittest.TestCase):
 def test_reviewed_fixture_parses_without_shell(self):
  v=reviewed_legacy(FIXTURE);self.assertEqual(v['TELEGRAM_CHAT_ID'],'-1001234567890')
 def test_other_credentials_same_body_are_accepted(self):
  data=FIXTURE.replace(b'-1001234567890',b'-1009999999999').replace(b'123456789:',b'987654321:');self.assertIsNotNone(reviewed_legacy(data))
 def test_changed_command_is_rejected(self):self.assertIsNone(reviewed_legacy(FIXTURE.replace(b'service mysql restart',b'service mysql stop')))
 def test_command_substitution_is_rejected(self):self.assertIsNone(reviewed_legacy(FIXTURE.replace(b'"-1001234567890"',b'"$(touch /tmp/never-execute)"')))
 def test_injection_after_assignment_is_rejected(self):self.assertIsNone(reviewed_legacy(FIXTURE.replace(b'"-1001234567890"',b'"-1001234567890"; echo injected')))
 def test_duplicate_assignment_is_rejected(self):self.assertIsNone(reviewed_legacy(FIXTURE+b'TELEGRAM_CHAT_ID="-1001234567890"\n'))
 def test_invalid_utf8_is_rejected(self):self.assertIsNone(reviewed_legacy(b'\xff'+FIXTURE))
 def test_symlink_and_writable_source_are_refused(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'monitor';p.write_bytes(FIXTURE);p.chmod(0o700);link=Path(d)/'link';link.symlink_to(p)
   with self.assertRaises(OSError):read_legacy(link)
   p.chmod(0o777)
   with self.assertRaises(RuntimeError):read_legacy(p)
 def test_reviewed_single_monitor_accepted_unknown_partial_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   paths=[str(Path(d)/str(i)) for i in range(3)];Path(paths[0]).write_bytes(FIXTURE);Path(paths[0]).chmod(0o700)
   self.assertEqual(review_sources(paths,{p:[] for p in paths},'none'),'legacy_single_monitor')
   Path(paths[0]).write_bytes(b'unknown')
   with self.assertRaises(RuntimeError):review_sources(paths,{p:[] for p in paths},'none')
 def test_legacy_cron_preserves_unrelated_jobs_and_is_idempotent(self):
  line='*/10 * * * * root /var/check_backup_freeradius.sh >/dev/null 2>&1\n';other='*/5 * * * * root /opt/example/job.php\n';new,n=migrate_cron(line+other)
  self.assertEqual(n,1);self.assertIn(other,new);self.assertEqual(migrate_cron(new),(new,0))
 def test_sleep_and_flock_legacy_wrappers(self):
  for cmd in ['sleep 30; /bin/bash /var/check_backup_freeradius.sh >> /var/log/legacy.log 2>&1','flock -n /var/run/legacy.lock /var/check_backup_freeradius.sh']:
   self.assertEqual(migrate_cron('* * * * * root '+cmd+'\n')[1],1)
 def test_combined_job_is_not_silently_removed(self):
  with self.assertRaises(RuntimeError):migrate_cron('*/10 * * * * root /var/check_backup_freeradius.sh && /opt/important-job\n')
 def test_non_root_and_alias_schedule_refused(self):
  for text in ['* * * * * www-data /var/check_backup_freeradius.sh\n','@reboot root /var/check_backup_freeradius.sh\n']:
   with self.assertRaises(RuntimeError):migrate_cron(text)
 def test_lookalike_path_not_removed(self):
  s='* * * * * root /var/check_backup_freeradius.sh.extra\n';self.assertEqual(migrate_cron(s),(s,0))
 def test_root_spool_not_edited_through_filesystem(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'root';s='*/10 * * * * /var/check_backup_freeradius.sh\n';p.write_text(s)
   with self.assertRaises(RuntimeError):cron_updates([],p)
   self.assertEqual(p.read_text(),s)
 def test_cron_symlink_is_refused(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'cron';p.write_text('* * * * * root /var/check_backup_freeradius.sh\n');link=Path(d)/'link';link.symlink_to(p)
   with self.assertRaises(RuntimeError):cron_updates([link],Path(d)/'absent')
 def test_running_exact_script_is_detected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'monitor';p.write_text('#!/bin/sh\nsleep 15\n:\n');child=subprocess.Popen(['sh',str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
   try:
    self.assertIn(child.pid,active_legacy_processes([str(p)]));self.assertNotIn(child.pid,active_legacy_processes([str(p)+'.other']))
   finally:os.killpg(child.pid,signal.SIGTERM);child.wait(timeout=5)
if __name__=='__main__':unittest.main()
