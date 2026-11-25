import unittest,tempfile,hashlib,subprocess,sys
from pathlib import Path
from unittest.mock import patch
import backup_timeout_install as b
import native_backup_timeout as n
class BackupTimeoutRoutingTests(unittest.TestCase):
 def test_native_schedule_preserved_only_executable_wrapped(self):
  old='15 08 * * * root '+b.NATIVE+'\n';new=b.review(old)
  self.assertEqual(new,'15 08 * * * root '+b.WRAPPER+'\n')
 def test_paused_schedule_stays_paused(self):
  old='# DESATIVADO - 11 09 * * * root '+b.LEGACY+'\n';data=b'#!/bin/sh\nexec /usr/bin/python3 /usr/local/lib/mkauth-guardian-recovery/safe_backup_supervisor.py\n'
  self.assertEqual(b.review(old,data),'# DESATIVADO - 11 09 * * * root '+b.WRAPPER+'\n')
 def test_active_native_ignores_historical_paused_wrapper(self):
  history='# DESATIVADO - 11 09 * * * root '+b.LEGACY+'\n'
  active='11 08 * * * root '+b.NATIVE+'\n'
  self.assertEqual(b.review(history+active),history+'11 08 * * * root '+b.WRAPPER+'\n')
 def test_active_wrapper_does_not_rewrite_historical_native(self):
  history='# 11 09 * * * root '+b.NATIVE+'\n';active='11 08 * * * root '+b.WRAPPER+'\n'
  self.assertEqual(b.review(history+active,b.WRAPPER_BYTES),history+active)
 def test_multiple_paused_routes_without_active_require_review(self):
  text='# 11 09 * * * root '+b.NATIVE+'\n# 11 08 * * * root '+b.LEGACY+'\n'
  self.assertRaises(RuntimeError,b.review,text)
 def test_two_active_routes_even_with_history_still_refused(self):
  text='# old '+b.LEGACY+'\n11 08 * * * root '+b.NATIVE+'\n11 09 * * * root '+b.WRAPPER+'\n'
  self.assertRaises(RuntimeError,b.review,text,b.WRAPPER_BYTES)
 def test_planner_does_not_read_archived_wrapper(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);cron=root/'cron';cron.write_text('# old '+b.LEGACY+'\n11 08 * * * root '+b.NATIVE+'\n');(root/'native_backup_timeout.py').write_bytes(b'# synthetic module\n')
   def mapped(value):
    self.assertNotEqual(str(value),b.LEGACY,'Historical wrapper must not be inspected')
    return cron if str(value)=='/etc/cron.d/backup' else Path(value)
   with patch.object(b,'Path',side_effect=mapped):result=b.plan(root)
   self.assertIn('11 08 * * * root '+b.WRAPPER,result[str(cron)][0].decode())
 def test_existing_guard_idempotent(self):
  old='15 08 * * * root '+b.WRAPPER+'\n';self.assertEqual(b.review(old,b.WRAPPER_BYTES),old)
 def test_unknown_wrapper_refused(self):self.assertRaises(RuntimeError,b.review,'15 08 * * * root '+b.LEGACY+'\n',b'unknown')
 def test_combined_command_refused(self):self.assertRaises(RuntimeError,b.review,'15 08 * * * root '+b.NATIVE+'; touch /tmp/no\n')
 def test_multiple_routes_refused(self):self.assertRaises(RuntimeError,b.review,'15 08 * * * root '+b.NATIVE+'\n15 09 * * * root '+b.NATIVE+'\n')
 def test_default_is_exactly_10_minutes(self):self.assertEqual(n.DEFAULTS['max_seconds'],600)
 def test_policy_cannot_extend_past_10_minutes(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'policy';p.write_text('{"mode":"native_only","max_seconds":601}');p.chmod(0o600)
   with patch.object(n,'POLICY',p):self.assertRaises(RuntimeError,n.load_policy)
 def test_backup_ignoring_term_is_killed_within_own_group(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);policy=dict(n.DEFAULTS,max_seconds=1,log_bytes=1024,max_file_bytes=1024**2)
   result=n.watch([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)'],p/'log',[p],policy,space_check=lambda *a:None)
   self.assertTrue(result['backup_group_sigkill']);self.assertEqual(result['aborted'],'deadline');self.assertEqual(result['returncode'],-9)
if __name__=='__main__':unittest.main()
