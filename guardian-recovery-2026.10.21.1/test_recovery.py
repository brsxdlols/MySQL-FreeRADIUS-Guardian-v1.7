import unittest
from recovery_core import begin,step

class Backend:
    def __init__(self):self.db={'pid':10,'start':'1'};self.radius={'pid':20,'start':'2'};self.events=[];self.pending=False;self.db_stuck=False;self.rad_stuck=False;self.db_ready=True;self.radius_ready_flag=True
    def identity(self,kind):return self.db if kind=='database' else self.radius
    def same_process(self,r):return bool(r and r in [self.db,self.radius])
    def command_running(self,r):return self.pending
    def stop_radius(self,r):
        self.events.append('radius_TERM')
        if not self.rad_stuck:self.radius=None
    def shutdown_database(self):
        self.events.append('mysqladmin_shutdown')
        if not self.db_stuck:self.db=None
        return None
    def start(self,kind):
        self.events.append('start_'+kind)
        if kind=='database':self.db={'pid':11,'start':'3'}
        else:self.radius={'pid':21,'start':'4'}
        return None
    def database_ready(self):return bool(self.db and self.db_ready)
    def radius_ready(self):return bool(self.radius and self.radius_ready_flag)
    def signal_database(self,record,kind,incident):
        self.events.append('database_'+kind)
        if kind=='KILL' and not getattr(self,'unkillable',False):self.db=None

class RecoveryTests(unittest.TestCase):
    def run_machine(self,b,database=True,allow_sigkill=False):
        s=begin('test',database,0,allow_sigkill=allow_sigkill)
        for now in range(0,1000,10):
            step(s,b,now)
            if s['phase'] in ['done','manual']:break
        return s
    def test_order_and_single_start(self):
        b=Backend();s=self.run_machine(b);self.assertEqual(s['phase'],'done');self.assertEqual(b.events,['radius_TERM','mysqladmin_shutdown','start_database','start_radius'])
    def test_radius_failure_does_not_restart_database(self):
        b=Backend();self.assertEqual(self.run_machine(b,False)['phase'],'done');self.assertEqual(b.events,['radius_TERM','start_radius'])
    def test_database_slow_shutdown_never_starts_duplicate(self):
        b=Backend();b.db_stuck=True;s=self.run_machine(b);self.assertEqual(s['phase'],'manual');self.assertNotIn('start_database',b.events);self.assertNotIn('start_radius',b.events)
    def test_radius_ignoring_TERM_never_escalates(self):
        b=Backend();b.rad_stuck=True;s=self.run_machine(b);self.assertEqual(s['phase'],'manual');self.assertEqual(b.events,['radius_TERM'])
    def test_database_failure_to_start_stops_recovery(self):
        b=Backend();b.db_ready=False;s=self.run_machine(b);self.assertEqual(s['phase'],'manual');self.assertNotIn('start_radius',b.events)
    def test_command_still_running_blocks_next_action(self):
        b=Backend();b.pending=True;s=begin('pending',True,0);s.update(phase='wait_database_ready',command={'pid':5})
        step(s,b,100);self.assertEqual(b.events,[]);step(s,b,301);self.assertEqual(s['phase'],'manual');self.assertEqual(b.events,[])
    def test_database_already_restarted_by_other_actor_is_not_started_again(self):
        b=Backend();s=begin('other',True,0);s.update(phase='wait_database_stop',old_database={'pid':9,'start':'old'})
        for now in range(10):step(s,b,now)
        self.assertNotIn('start_database',b.events);self.assertEqual(s['phase'],'done')
    def test_authorized_escalation_term_then_kill_once(self):
        b=Backend();b.db_stuck=True;s=self.run_machine(b,allow_sigkill=True)
        self.assertEqual(s['phase'],'done');self.assertTrue(s['used_sigkill'])
        self.assertEqual(b.events,['radius_TERM','mysqladmin_shutdown','database_TERM','database_KILL','start_database','start_radius'])
    def test_unkillable_database_never_starts_duplicate(self):
        b=Backend();b.db_stuck=True;b.unkillable=True;s=self.run_machine(b,allow_sigkill=True)
        self.assertEqual(s['phase'],'manual');self.assertEqual(b.events.count('database_KILL'),1);self.assertNotIn('start_database',b.events)
    def test_signal_evidence_failure_stops_recovery(self):
        b=Backend();b.db_stuck=True
        def fail(*args):raise OSError('evidence unavailable')
        b.signal_database=fail;s=self.run_machine(b,allow_sigkill=True)
        self.assertEqual(s['phase'],'manual');self.assertNotIn('start_database',b.events)
    def test_hung_shutdown_client_does_not_block_escalation(self):
        b=Backend();b.db_stuck=True;s=begin('hung client',True,0,allow_sigkill=True)
        s.update(phase='wait_database_stop',old_database=dict(b.db),command={'pid':999});b.pending=True
        step(s,b,241);self.assertEqual(s['phase'],'database_TERM');step(s,b,242);self.assertIn('database_TERM',b.events)
    def test_changed_pid_identity_never_signalled(self):
        b=Backend();s=begin('PID changed',True,0,allow_sigkill=True)
        s.update(phase='database_KILL',old_database={'pid':10,'start':'previous'})
        step(s,b,10);self.assertNotIn('database_KILL',b.events)

if __name__=='__main__':unittest.main()
