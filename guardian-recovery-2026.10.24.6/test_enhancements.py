import unittest,tempfile,json,contextlib,io
from pathlib import Path
from unittest.mock import patch,Mock
import enhancements as e
import install_frontend as f
class NativeTransactionTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.lib=self.root/'lib';self.lib.mkdir()
  self.init=self.root/'init';self.cron=self.root/'cron';self.native=self.root/'mysql.php';self.native.write_bytes(b'fixture')
  self.a=b"#!/bin/bash\ncase x in\n  'start')\n  sanity_checks;\n;;\nesac\n"
  self.b=b'## SISTEMA MK-AUTH\n\n# CONTROLE DO BD\n*/15 *\t* * *\troot\t/opt/mk-auth/scripts/mysql.php\n'
  self.init.write_bytes(self.a);self.cron.write_bytes(self.b)
  aa,bb=e.native_contents(self.a,self.b)
  self.patches=[patch.object(e,'LIB',self.lib),patch.object(e,'INIT',self.init),patch.object(e,'CRON',self.cron),patch.object(e,'NATIVE',self.native),patch.object(e,'INIT_OLD',e.digest(self.a)),patch.object(e,'INIT_NEW',e.digest(aa)),patch.object(e,'CRON_OLD',e.digest(self.b))]
  for p in self.patches:p.start()
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
  self.temp.cleanup()
 def backup(self):
  p=self.root/'backup';p.mkdir();return p
 def test_native_application_and_idempotence(self):
  plan=e.review_native();self.assertTrue(plan['changed']);e.apply_native(plan,self.backup());self.assertFalse(e.review_native()['changed'])
 def test_unreviewed_init_refused(self):
  self.init.write_bytes(self.a+b'# modified');self.assertRaises(RuntimeError,e.review_native)
 def test_unreviewed_cron_refused(self):
  self.cron.write_bytes(self.b+b'other job');self.assertRaises(RuntimeError,e.review_native)
 def test_symlink_refused(self):
  self.init.unlink();self.init.symlink_to(self.native);self.assertRaises(RuntimeError,e.review_native)
 def test_changed_source_before_apply_refused(self):
  plan=e.review_native();self.init.write_bytes(b'changed');self.assertRaises(RuntimeError,e.apply_native,plan,self.backup());self.assertFalse((self.lib/'mariadb_coordination.py').exists())
 def test_partial_apply_rolls_back(self):
  plan=e.review_native();real=e.replace;failed=[False]
  def replace(path,data,mode):
   if path==str(self.cron) and not failed[0]:failed[0]=True;raise OSError('synthetic write failure')
   return real(path,data,mode)
  with patch.object(e,'replace',side_effect=replace):self.assertRaises(OSError,e.apply_native,plan,self.backup())
  self.assertEqual(self.init.read_bytes(),self.a);self.assertEqual(self.cron.read_bytes(),self.b);self.assertFalse((self.lib/'mariadb_coordination.py').exists())
 def test_existing_different_helper_refused(self):
  (self.lib/'mariadb_coordination.py').write_bytes(b'unknown');self.assertRaises(RuntimeError,e.review_native)
 def test_live_global_lock_prevents_changes(self):
  lockpath=str(self.root/'lock')
  with open(lockpath,'a') as lock:
   e.fcntl.flock(lock,e.fcntl.LOCK_EX|e.fcntl.LOCK_NB)
   with patch.object(e,'GLOBAL_LOCK',lockpath):self.assertRaises(BlockingIOError,e.apply,{'native':{'changed':True},'module':None})
  self.assertEqual(self.init.read_bytes(),self.a)
class EnhancementPolicyTests(unittest.TestCase):
 def test_already_patched_module_does_not_restart(self):
  with patch.object(e,'review_module',return_value={'changed':False}),patch.object(e.subprocess,'run') as run:
   self.assertFalse(e.apply({'native':None,'module':{'changed':True}}));run.assert_not_called()
 def test_unknown_module_refused(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'module';p.write_bytes(b'unknown')
   with patch.object(e,'MODULE',p):self.assertRaises(RuntimeError,e.review_module)
 def test_frontend_unknown_enhancement_refused_before_core(self):
  with patch.object(f,'mysql_read',return_value='PROVIDER'),patch.object(e,'review',side_effect=RuntimeError('Unreviewed binary')),patch.object(f.subprocess,'run') as run,contextlib.redirect_stdout(io.StringIO()):
   result=f.main(['--coordinate-native-mariadb','--upgrade-reviewed-sqlippool','--dry-run'])
  self.assertEqual(result,2);run.assert_not_called()
 def test_native_running_recovery_prevents_apply(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);state=root/'state';state.write_text(json.dumps({'recovery':{'phase':'wait_database_stop'}}))
   with patch.object(e,'GLOBAL_LOCK',str(root/'lock')),patch.object(e,'STATE',state),patch.object(e,'apply_native') as apply:
    self.assertRaises(RuntimeError,e.apply,{'native':{'changed':True},'module':None});apply.assert_not_called()
