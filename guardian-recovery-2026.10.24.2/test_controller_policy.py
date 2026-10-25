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
    def invoke(self,state,config,backend=None,queue=10,locks='0'):
        b=backend or Backend()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);cfg=root/'config.json';cfg.write_text(json.dumps(dict(enabled=True,**config)));(root/'state.json').write_text(json.dumps(state))
            with patch.object(c,'ROOT',root),patch.object(c,'CONFIG',cfg),patch.object(c,'Production',return_value=b),patch.object(c,'protector',return_value={}),patch.object(c,'queue_sample',return_value=queue),patch.object(c,'capture_queue',return_value='/private/synthetic'),patch.object(c,'mysql_read',return_value=locks),patch.object(c,'notify'),patch.object(c,'log'),patch.object(c.time,'sleep'),patch.object(sys,'argv',['guardian_controller.py']):
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
