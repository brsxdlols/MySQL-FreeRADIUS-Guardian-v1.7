import unittest,tempfile,json,sys
from pathlib import Path
from unittest.mock import patch
import guardian_controller as c
class Backend:
    def __init__(self):self.radius={'pid':21,'start':'x'};self.db=True;self.events=[]
    def database_ready(self):return self.db
    def radius_ready(self):return bool(self.radius)
    def identity(self,k):return self.radius if k=='radius' else {'pid':10,'start':'db'}
    def same_process(self,r):return r==self.radius and r is not None
    def command_running(self,r):return False
    def reap(self):pass
    def start(self,k):self.events.append('start_'+k);self.radius={'pid':22,'start':'new'}
    def signal_radius(self,r,k,i):self.events.append('radius_'+k);self.radius=None
class ControllerTests(unittest.TestCase):
    def invoke(self,state,config,backend=None,queue=10,locks='0',full=0):
        b=backend or Backend()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cfg=root/'config.json';cfg.write_text(json.dumps(dict({'enabled':True},**config)));(root/'state.json').write_text(json.dumps(state))
            def sampled(saved):
                saved['queue_full_errors']=full;return queue
            with patch.object(c,'ROOT',root),patch.object(c,'CONFIG',cfg),patch.object(c,'Production',return_value=b),patch.object(c,'protector',return_value={}),patch.object(c,'queue_sample',side_effect=sampled),patch.object(c,'capture_queue',return_value='/private/synthetic'),patch.object(c,'mysql_read',return_value=locks),patch.object(c,'notify'),patch.object(c,'log'),patch.object(c.time,'sleep'),patch.object(sys,'argv',['guardian_controller.py']):
                result=c.main()
            saved=json.loads((root/'state.json').read_text())
        return result,saved,b
    def test_persistent_queue_policy_selects_both_services(self):
        _,s,_=self.invoke({'bad_queue':3,'history':[]},{'restart_database_on_persistent_queue':True})
        self.assertTrue(s['recovery']['database'])
    def test_legacy_policy_does_not_silently_select_database(self):
        _,s,_=self.invoke({'bad_queue':3,'history':[]},{})
        self.assertFalse(s['recovery']['database'])
    def test_one_sample_does_not_restart_services(self):
        _,s,b=self.invoke({'history':[]},{'restart_database_on_persistent_queue':True})
        self.assertNotIn('recovery',s);self.assertEqual(b.events,[])
    def test_one_full_queue_sample_does_not_recover(self):
        _,state,b=self.invoke({'history':[]},{'restart_database_on_persistent_queue':True},queue=0,full=1)
        self.assertEqual(state['bad_queue_full'],1);self.assertNotIn('recovery',state);self.assertEqual(b.events,[])
    def test_two_full_samples_without_duplicate_warning_recover_both(self):
        _,state,b=self.invoke({'history':[],'bad_queue_full':1},{'restart_database_on_persistent_queue':True},queue=0,full=1)
        self.assertTrue(state['recovery']['database']);self.assertEqual(state['recovery']['reason'],'queue_capacity_exhausted')
        self.assertEqual(state['recovery']['initial_health']['queue_full_errors'],1)
    def test_full_queue_without_database_permission_selects_only_radius(self):
        _,state,b=self.invoke({'history':[],'bad_queue_full':1},{},queue=0,full=1)
        self.assertFalse(state['recovery']['database'])
    def test_fresh_clear_sample_resets_full_counter(self):
        _,state,b=self.invoke({'history':[],'bad_queue_full':1},{'restart_database_on_persistent_queue':True},queue=0,full=0)
        self.assertEqual(state['bad_queue_full'],0);self.assertNotIn('recovery',state)
    def test_full_queue_still_obeys_cooldown(self):
        import time
        _,state,b=self.invoke({'history':[],'bad_queue_full':1,'last_recovery':time.time()},{'restart_database_on_persistent_queue':True},queue=0,full=1)
        self.assertNotIn('recovery',state);self.assertEqual(b.events,[])
    def test_disabled_monitor_never_recovers_full_queue(self):
        _,state,b=self.invoke({'history':[],'bad_queue_full':1},{'enabled':False,'restart_database_on_persistent_queue':True},queue=0,full=1)
        self.assertNotIn('recovery',state);self.assertEqual(b.events,[])
    def test_missing_database_without_full_queue_database_permission_waits_for_db_confirmation(self):
        b=Backend();b.db=False
        _,state,b=self.invoke({'history':[],'bad_queue_full':1,'bad_database':1},{},b,queue=0,full=1)
        self.assertNotIn('recovery',state)
    def test_full_queue_and_confirmed_missing_db_recover_database(self):
        b=Backend();b.db=False
        _,state,b=self.invoke({'history':[],'bad_queue_full':1,'bad_database':2},{},b,queue=0,full=1)
        self.assertTrue(state['recovery']['database'])
    def test_late_exit_resumes_and_starts_once(self):
        b=Backend();b.radius=None
        record={'phase':'manual','error':'Radius did not exit after TERM; no SIGKILL permitted','old_radius':{'pid':20,'start':'old'},'database':False,'events':[],'started':1,'reason':'persistent_queue_or_lock'}
        _,s,b=self.invoke({'history':[],'recovery':record},{},b)
        self.assertEqual(s['recovery']['phase'],'done');self.assertEqual(b.events,['start_radius'])
    def test_unrelated_manual_failure_refreshes_health_without_restart(self):
        b=Backend();b.radius=None;b.db=False
        record={'phase':'manual','error':'Database failed to become available','events':[],'started':1,'reason':'database_unavailable'}
        _,s,b=self.invoke({'history':[],'recovery':record},{},b,queue=0)
        self.assertFalse(s['last_health']['database']);self.assertFalse(s['last_health']['radius']);self.assertEqual(b.events,[])
if __name__=='__main__':unittest.main()


class RealProductionDescriptorTests(unittest.TestCase):
    def test_real_command_running_descriptor_is_callable(self):
        backend=c.Production()
        self.assertTrue(callable(backend.command_running))
        self.assertFalse(backend.command_running(None))
        self.assertFalse(backend.command_running({'pid':2147483647,'start':'missing'}))
    def test_wait_database_stop_advances_with_real_command_checker(self):
        from recovery_core import begin,step
        backend=c.Production()
        state=begin('synthetic',True,now=1)
        state.update(phase='wait_database_stop',phase_at=1,old_database=None,command={'pid':2147483647,'start':'missing'})
        with patch.object(backend,'identity',return_value=None):step(state,backend,now=2)
        self.assertEqual(state['phase'],'start_database')

class QueueSamplingTests(unittest.TestCase):
    def test_old_full_queue_log_is_skipped_but_new_warning_is_counted(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'radius.log';line=b'Error: Something is blocking the server.  There are 65536 packets in the queue, waiting to be processed.  Ignoring the new request.\n';path.write_bytes(line)
            state={}
            with patch.object(c,'Path',return_value=path):
                self.assertEqual(c.queue_sample(state),0);self.assertEqual(state['queue_full_errors'],0)
                with path.open('ab') as stream:stream.write(line)
                self.assertEqual(c.queue_sample(state),0);self.assertEqual(state['queue_full_errors'],1)
                self.assertEqual(c.queue_sample(state),0);self.assertEqual(state['queue_full_errors'],0)
