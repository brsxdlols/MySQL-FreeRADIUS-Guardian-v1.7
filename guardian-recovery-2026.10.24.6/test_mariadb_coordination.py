import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch,Mock
import mariadb_coordination as m
class CoordinationTests(unittest.TestCase):
 def invoke(self,mode,state=None,existing=None,busy=False):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);s=root/'state';s.write_text(json.dumps(state or {}))
   with patch.object(m,'STATE',s),patch.object(m,'GLOBAL_LOCK',str(root/'global')),patch.object(m,'START_LOCK',str(root/'start')),patch.object(m,'processes',return_value=existing or []),patch.object(m,'log') as logs,patch.object(m.subprocess,'call',return_value=0) as call,patch.object(m.fcntl,'flock',side_effect=BlockingIOError if busy else None):
    result=m.run(mode)
   return result,call,logs
 def test_existing_database_never_starts_again(self):
  result,call,logs=self.invoke('start',existing=[123]);self.assertEqual(result,0);call.assert_not_called()
 def test_native_skipped_during_recovery(self):
  for phase in ['stop_radius','wait_database_stop','start_database','wait_database_ready','manual']:
   result,call,logs=self.invoke('native',{'recovery':{'phase':phase}});call.assert_not_called()
 def test_native_done_runs_once(self):
  result,call,logs=self.invoke('native',{'recovery':{'phase':'done'}});call.assert_called_once_with(['/opt/mk-auth/scripts/mysql.php'],close_fds=True)
 def test_native_lock_busy_never_launches(self):
  result,call,logs=self.invoke('native',busy=True);self.assertEqual(result,0);call.assert_not_called()
 def test_start_lock_busy_never_launches(self):
  result,call,logs=self.invoke('start',busy=True);self.assertEqual(result,1);call.assert_not_called()
 def test_absent_database_single_start_without_inherited_lock(self):
  result,call,logs=self.invoke('start');self.assertEqual(call.call_count,1);self.assertTrue(call.call_args[1]['close_fds']);self.assertEqual(call.call_args[1]['env']['MKAUTH_START_GATE_ACTIVE'],'1')
