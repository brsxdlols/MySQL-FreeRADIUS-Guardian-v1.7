import unittest,tempfile,sys,os,time,json,subprocess
from pathlib import Path
from unittest.mock import patch,Mock
from contextlib import ExitStack
import native_backup_timeout as s
class NativeOutcomeTests(unittest.TestCase):
 def test_valid_archive_exit_zero_success(self):self.assertEqual(s.outcome({'returncode':0},[{'classification':'structurally_valid_restore_required'}]),('native_artifact_structural_ok',0))
 def test_valid_archive_exit_255_is_warning_not_fallback(self):self.assertEqual(s.outcome({'returncode':255},[{'classification':'structurally_valid_restore_required'}]),('native_artifact_structural_ok_script_failed',2))
 def test_missing_artifact_not_success(self):self.assertEqual(s.outcome({'returncode':0},[])[1],2)
 def test_rejected_artifact_not_success(self):self.assertEqual(s.outcome({'returncode':0},[{'classification':'rejected'}])[1],2)
 def test_abort_never_announces_success(self):self.assertEqual(s.outcome({'returncode':0,'aborted':'space_reserve'},[{'classification':'structurally_valid_restore_required'}])[1],3)
class PolicyAndSpaceTests(unittest.TestCase):
 def test_invalid_policy_unknown_field(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'policy';p.write_text('{"mode":"native_only","fallback":true}');p.chmod(0o600)
   with patch.object(s,'POLICY',p):self.assertRaises(RuntimeError,s.load_policy)
 def test_legacy_primary_requires_explicit_review(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);legacy=root/'legacy';legacy.write_text('{"mode":"compatible_primary"}')
   with patch.object(s,'POLICY',root/'missing'),patch.object(s,'LEGACY_POLICY',legacy):self.assertRaises(RuntimeError,s.load_policy)
 def test_policy_symlink_refused(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'target').write_text('{}');(root/'link').symlink_to(root/'target')
   with patch.object(s,'POLICY',root/'link'):self.assertRaises(OSError,s.load_policy)
 def test_low_space_refuses_before_start(self):
  usage=type('Usage',(),{'free':5,'total':100})()
  with tempfile.TemporaryDirectory() as folder,patch.object(s.shutil,'disk_usage',return_value=usage):self.assertRaises(s.LowSpace,s.check_space,[Path(folder)],dict(s.DEFAULTS,reserve_min_bytes=10,start_headroom_bytes=1),True)
 def test_filesystems_deduplicated(self):
  usage=type('Usage',(),{'free':90,'total':100})()
  with tempfile.TemporaryDirectory() as folder,patch.object(s.shutil,'disk_usage',return_value=usage) as read:
   result=s.check_space([Path(folder),Path(folder)],dict(s.DEFAULTS,reserve_min_bytes=10,start_headroom_bytes=1));self.assertEqual(len(result),1);self.assertEqual(read.call_count,1)
class RealProcessTests(unittest.TestCase):
 def policy(self,**kw):return dict(s.DEFAULTS,max_seconds=3,log_bytes=1024,max_file_bytes=1024**2,**kw)
 def test_native_log_is_bounded_and_nonzero_exit_returned(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);p=root/'native.log';r=s.watch([sys.executable,'-c',"import sys;print('x'*100000);sys.exit(255)"],p,[root],self.policy(),space_check=lambda *a:None)
   self.assertEqual(r['returncode'],255);self.assertEqual(p.stat().st_size,1024);self.assertGreater(r['log_bytes_discarded'],0)
 def test_file_size_limit_blocks_oversized_child_output(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);target=root/'large.sql';cmd=[sys.executable,'-c',"import os,sys;f=open(sys.argv[1],'wb');f.write(b'x'*2000000)",str(target)]
   r=s.watch(cmd,root/'native.log',[root],self.policy(),space_check=lambda *a:None)
   self.assertNotEqual(r['returncode'],0);self.assertLessEqual(target.stat().st_size,1024**2)
 def test_space_guard_terminates_only_own_backup_group(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);other=subprocess.Popen([sys.executable,'-c','import time;time.sleep(20)'],start_new_session=True)
   calls=[0]
   def low(*args):
    calls[0]+=1
    if calls[0]>1:raise s.LowSpace('synthetic')
   try:
    r=s.watch([sys.executable,'-c','import time;time.sleep(20)'],root/'native.log',[root],self.policy(),space_check=low)
    self.assertEqual(r['aborted'],'space_reserve');self.assertIsNone(other.poll())
   finally:other.terminate();other.wait(timeout=5)
 def test_deadline_stops_own_child(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);r=s.watch([sys.executable,'-c','import time;time.sleep(20)'],root/'native.log',[root],self.policy(),space_check=lambda *a:None)
   self.assertEqual(r['aborted'],'deadline')
 def test_refuses_signalling_changed_identity(self):
  child=type('Fake',(),{'pid':os.getpid()})()
  fields=Path('/proc/{}/stat'.format(os.getpid())).read_text().rsplit(')',1)[1].split()
  with patch.object(s.os,'killpg') as kill:self.assertRaises(RuntimeError,s.stop_owned_group,child,'changed-identity');kill.assert_not_called()
 def test_log_creation_failure_does_not_start_child(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'already.log';p.write_bytes(b'old')
   with patch.object(s.subprocess,'Popen') as launch:self.assertRaises(FileExistsError,s.watch,['never'],p,[],self.policy());launch.assert_not_called()
class FullFlowTests(unittest.TestCase):
 def run_native(self,exitcode,classification='structurally_valid_restore_required',low=False):
  with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
   root=Path(folder);backups=root/'backups';backups.mkdir();private=root/'private'
   policy=dict(s.DEFAULTS,reserve_min_bytes=1,reserve_percent=1,start_headroom_bytes=1,max_seconds=5)
   command=[sys.executable,'-c',"import pathlib,sys;pathlib.Path(sys.argv[1]).write_bytes(b'native archive');print('synthetic native');sys.exit(int(sys.argv[2]))",str(backups/'NATIVE.maz'),str(exitcode)]
   for name,value in [('BACKUPS',backups),('PRIVATE',private),('LOCK',root/'lock'),('COMMAND',command)]:stack.enter_context(patch.object(s,name,value))
   stack.enter_context(patch.object(s,'load_policy',return_value=policy));stack.enter_context(patch.object(s,'mysql_read',return_value='1'))
   stack.enter_context(patch.object(s,'log'));notice=stack.enter_context(patch.object(s,'notify'))
   validator=stack.enter_context(patch.object(s,'validate_maz',return_value={'file':'NATIVE.maz','classification':classification}))
   if low:stack.enter_context(patch.object(s,'check_space',side_effect=s.LowSpace('synthetic')))
   result=s.main();files=list(private.rglob('result.json'));self.assertEqual(len(files),1);report=json.loads(files[0].read_text())
   return result,report,(backups/'NATIVE.maz').exists(),list(private.rglob('*.sql')),notice.call_count
 def test_real_native_exit_255_published_file_no_second_dump(self):
  code,report,present,sql,notices=self.run_native(255)
  self.assertEqual(code,2);self.assertTrue(present);self.assertFalse(sql);self.assertFalse(report['fallback_executed']);self.assertFalse(report['files_deleted']);self.assertEqual(notices,1)
 def test_real_native_success(self):
  code,report,present,sql,notices=self.run_native(0);self.assertEqual(code,0);self.assertTrue(present);self.assertFalse(sql)
 def test_invalid_archive_preserved_no_sql_generated(self):
  code,report,present,sql,notices=self.run_native(0,'rejected');self.assertEqual(code,2);self.assertTrue(present);self.assertFalse(sql)
 def test_preflight_low_space_does_not_launch_native(self):
  code,report,present,sql,notices=self.run_native(0,low=True);self.assertEqual(code,3);self.assertFalse(present);self.assertFalse(sql)
