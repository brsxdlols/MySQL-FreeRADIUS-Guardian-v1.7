"""Whole installer transaction in a redirected filesystem; never touch live services."""
import contextlib,hashlib,io,json,os,tempfile,unittest,shutil
from pathlib import Path as RealPath
from unittest.mock import patch
import install

class InstallerMigrationTransactionTests(unittest.TestCase):
 def scenario(self,fail=False,busy=False,combined=False,boundary=False,changed_source=False,raced=False):
  with tempfile.TemporaryDirectory(prefix='guardian-migration-fixture.') as folder:
   root=RealPath(folder)
   def physical(value):
    value=str(value)
    if value.startswith(str(root)) or not value.startswith('/'):return RealPath(value)
    return root/value.lstrip('/')
   class RedirectPath:
    def __init__(self,value):self.logical=str(value)
    def __str__(self):return self.logical
    def __fspath__(self):return str(physical(self.logical))
    def __truediv__(self,other):return RedirectPath(self.logical.rstrip('/')+'/'+str(other))
    @property
    def parent(self):return RedirectPath(str(RealPath(self.logical).parent))
    @property
    def name(self):return RealPath(self.logical).name
    def glob(self,pattern):
     for p in physical(self.logical).glob(pattern):yield self/str(p.relative_to(physical(self.logical)))
    def __getattr__(self,key):return getattr(physical(self.logical),key)
   class SafeOS:
    def __getattr__(self,key):return getattr(os,key)
    def chmod(self,path,mode):return os.chmod(physical(path),mode)
    def chown(self,path,uid,gid):return os.chown(physical(path),uid,gid)
    def unlink(self,path):return os.unlink(physical(path))
   class SafeShutil:
    def copyfile(self,src,dst):return shutil.copyfile(physical(src),physical(dst))
   def put(name,data,mode=0o600):
    p=physical(name);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);p.chmod(mode)
   physical('/var/lib').mkdir(parents=True)
   fixture=RealPath(__file__).with_name('legacy_monitor_fixture.sh').read_bytes()
   put('/var/check_backup_freeradius.sh',fixture,0o700)
   cron=b'*/10 * * * * root /var/check_backup_freeradius.sh >/dev/null 2>&1\n*/5 * * * * root /opt/keep-this-job\n'
   if combined:cron=cron.replace(b' >/dev/null 2>&1',b' && /opt/keep-also')
   put('/etc/crontab',cron,0o644);put('/etc/cron.d/backup',b'11 07 * * * root /opt/mk-auth/scripts/backup.php\n',0o644)
   put('/etc/default/check_backup_freeradius',b"MKAUTH_NAME='FIXTURE PROVIDER'\nUSAR_TELEGRAM=nao\nGUARDIAN_ALLOW_DESTRUCTIVE_RECOVERY=nao\n")
   if changed_source:
    cfg=physical('/etc/default/check_backup_freeradius').read_bytes()
    put('/root/fixture-settings.json',json.dumps({'base_sha256':hashlib.sha256(cfg).hexdigest(),'content':cfg.decode(),'legacy_source_sha256':'0'*64}).encode())
   before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()};writes=[]
   from guardian_safety import atomic_bytes as real_atomic
   def atomic(path,content,mode=0o600):
    name=str(path);writes.append(name)
    if fail and name.endswith('/guardian_controller.py'):raise OSError('injected write failure')
    return real_atomic(physical(path),content,mode)
   def query(q):
    if 'sis_provedor' in q:return 'FIXTURE PROVIDER'
    if '@@datadir' in q:return '/var/lib/mysql/'
    return '1'
   lockpaths=[str(root/('lock'+str(i))) for i in range(len(install.LOCKS))]
   args=['install.py','--expected-provider','FIXTURE PROVIDER','--enable-normal-recovery','--allow-sigkill-exact-radius','--apply']
   if changed_source:args+=['--local-config-file','/root/fixture-settings.json']
   probes=[]
   def active():
    probes.append(1);return [123] if busy or (raced and len(probes)>=3) else []
   with patch.object(install,'Path',RedirectPath),patch.object(install,'os',SafeOS()),patch.object(install,'shutil',SafeShutil()),patch.object(install,'LOCKS',lockpaths),patch.object(install,'mysql_read',side_effect=query),patch.object(install,'exact_signals_supported',return_value=True),patch.object(install,'active_legacy_processes',side_effect=active),patch.object(install,'discover_template',return_value={'tables':['synthetic'],'metadata':[]}),patch.object(install.time,'localtime',return_value=type('Clock',(),{'tm_sec':45 if boundary else 20})()),patch('sys.argv',args),patch.object(install,'atomic_bytes',side_effect=atomic),contextlib.redirect_stdout(io.StringIO()) as out:
    if busy or combined or fail or boundary or changed_source or raced:
     with self.assertRaises((BlockingIOError,RuntimeError,OSError)):install.main()
    else:
     self.assertEqual(install.main(),0)
     self.assertEqual(physical('/etc/crontab').read_text().count('# GUARDIAN MIGRATED:'),1)
     self.assertIn('/opt/keep-this-job',physical('/etc/crontab').read_text())
     coordinator='/etc/cron.d/mkauth-guardian-normal-recovery'
     self.assertEqual(writes[-1],coordinator)
     self.assertLess(writes.index('/etc/crontab'),writes.index('/var/check_backup_freeradius.sh'))
     snapshots=list(physical('/root/mkauth-normal-recovery-backups').glob('*/manifest.json'));self.assertEqual(len(snapshots),1)
     records=json.loads(snapshots[0].read_text());old=next(x for x in records if x['path']=='/var/check_backup_freeradius.sh');self.assertEqual(old['sha256'],hashlib.sha256(fixture).hexdigest())
     count=len(writes);self.assertEqual(install.main(),0);self.assertEqual(len(writes),count,'Second apply must not write files')
   if busy or combined or fail or boundary or changed_source or raced:
    for path,content in before.items():self.assertEqual((root/path).read_bytes(),content)
    self.assertFalse(physical('/etc/cron.d/mkauth-guardian-normal-recovery').exists())
   # Never invoke service/restart; subprocess use in install is syntax checking only.
 def test_whole_migration_and_second_apply_idempotence(self):self.scenario()
 def test_failure_after_cron_change_rolls_back_original_files(self):self.scenario(fail=True)
 def test_active_legacy_monitor_prevents_mutation(self):self.scenario(busy=True)
 def test_combined_cron_prevents_mutation(self):self.scenario(combined=True)
 def test_cron_boundary_prevents_mutation(self):self.scenario(boundary=True)
 def test_changed_legacy_binding_prevents_mutation(self):self.scenario(changed_source=True)
 def test_legacy_start_after_cron_change_rolls_back(self):self.scenario(raced=True)
if __name__=='__main__':unittest.main()
