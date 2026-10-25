import sys,os,time,json,hashlib,shutil,subprocess,fcntl
from pathlib import Path
sys.path.insert(0,'/usr/local/lib/mkauth-guardian-recovery')
from guardian_controller import Production,same_process
from exact_signal import send_radius
root=Path(sys.argv[1]);os.chmod(str(root),0o700)
dest=Path('/usr/lib/freeradius/rlm_sqlippool.so');candidate=root/'candidate.so';backup=root/'original.so'
old='e7d3e1c0bd902b8433e96c9e53a0070ac4b76fd499ceec1742bdc38b0a52d342';new='03b654562cd34cbc51381a8e435c51676d41a33f1e2acb24b837b9d32a2d4fba'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
class StartStillRunning(RuntimeError):pass
b=Production()
def emit(event,**fields):print(json.dumps(dict(event=event,**fields)),flush=True)
def pids(name):
 found=[]
 for p in Path('/proc').glob('[0-9]*'):
  try:
   if p.joinpath('comm').read_text().strip()==name and p.joinpath('stat').read_text().rsplit(')',1)[1].split()[0]!='Z':found.append(int(p.name))
  except OSError:pass
 return sorted(found)
def replace(source):
 tmp=dest.with_name(dest.name+'.guardian-stage');shutil.copy2(str(source),str(tmp));tmp.chmod(0o644);os.replace(str(tmp),str(dest))
def stop(record,reason):
 if not same_process(record):return
 incident={'started':time.time(),'reason':reason}
 send_radius(record,'TERM',incident,str(root/'signals'));emit('radius_TERM',pid=record['pid'])
 deadline=time.monotonic()+60
 while same_process(record) and time.monotonic()<deadline:time.sleep(.5)
 if same_process(record):
  assert json.loads(Path('/etc/default/mkauth-guardian-normal-recovery.json').read_text()).get('allow_sigkill_exact_radius')
  send_radius(record,'KILL',incident,str(root/'signals'));emit('radius_KILL',pid=record['pid'])
  deadline=time.monotonic()+15
  while same_process(record) and time.monotonic()<deadline:time.sleep(.5)
 assert not same_process(record),'Radius still alive; no duplicate start'
 assert not pids('freeradius'),'Unexpected second Radius; refuse'
def start():
 assert not pids('freeradius'),'Refuse duplicate start'
 with (root/'start.log').open('ab') as out:
  out.flush();os.chmod(str(root/'start.log'),0o600)
  child=subprocess.Popen(['service','freeradius','start'],stdin=subprocess.DEVNULL,stdout=out,stderr=out,close_fds=True,preexec_fn=lambda:os.umask(0o022))
  try:code=child.wait(timeout=35)
  except subprocess.TimeoutExpired:raise StartStillRunning('Start command still running; manual review required, no overlapping command')
  assert code==0,'Radius start failed'
 deadline=time.monotonic()+12
 while time.monotonic()<deadline:
  if b.radius_ready():return
  time.sleep(.5)
 raise RuntimeError('Radius health unavailable')
with open('/var/run/mkauth-guardian-global-recovery.lock','a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 statepath=Path('/var/lib/mkauth-guardian-recovery/state.json')
 state=json.loads(statepath.read_text()) if statepath.exists() else {}
 assert state.get('recovery',{}).get('phase') in (None,'done'),'Recovery active'
 assert not dest.is_symlink() and dest.stat().st_uid==0 and sha(dest)==old and sha(candidate)==new
 assert subprocess.check_output(['dpkg-query','-W','-f=${Version}','freeradius']).decode()=='3.0.17+dfsg-1.1'
 assert b.database_ready() and b.radius_ready()
 record=b.identity('radius');assert record and not backup.exists()
 before={name:pids(name) for name in ['mysqld','dockerd','freeradius']}
 hashes={path:sha(Path(path)) for path in ['/etc/default/check_backup_freeradius','/etc/cron.d/backup','/etc/default/mkauth-guardian-normal-recovery.json']}
 shutil.copy2(str(dest),str(backup));backup.chmod(0o600);assert sha(backup)==old
 with (root/'radius-config-before.tar').open('xb') as out:
  os.chmod(str(root/'radius-config-before.tar'),0o600);subprocess.run(['tar','-cpf','-','/etc/freeradius'],stdout=out,stderr=subprocess.DEVNULL,check=True,timeout=20)
 with (root/'dependencies.log').open('wb') as out:
  os.chmod(str(root/'dependencies.log'),0o600);r=subprocess.run(['ldd',str(candidate)],stdout=out,stderr=out,timeout=5)
 assert r.returncode==0 and 'not found' not in (root/'dependencies.log').read_text()
 replace(candidate)
 try:
  with (root/'configuration-check.log').open('wb') as out:
   os.chmod(str(root/'configuration-check.log'),0o600);check=subprocess.run(['/usr/sbin/freeradius','-C'],stdout=out,stderr=out,timeout=25,preexec_fn=lambda:os.umask(0o022))
  assert check.returncode==0,'Configuration check failed'
 finally:replace(backup)
 assert b.identity('radius')==record and b.database_ready()
 emit('preflight_passed',before=before)
 stop(record,'authorized_sqlippool_module_upgrade')
 try:
  replace(candidate);start()
  current=b.identity('radius');assert current
  maps=Path('/proc/{}/maps'.format(current['pid'])).read_text();inode=str(dest.stat().st_ino)
  assert any(str(dest) in row and row.split()[4]==inode and '(deleted)' not in row for row in maps.splitlines()),'Candidate not mapped'
  assert sha(dest)==new
  assert pids('mysqld')==before['mysqld'] and pids('dockerd')==before['dockerd']
  assert all(sha(Path(p))==h for p,h in hashes.items())
  assert b.database_ready() and b.radius_ready()
 except StartStillRunning:
  emit('start_command_pending_manual_review');raise
 except Exception as error:
  emit('trial_failed',type=type(error).__name__)
  trial=b.identity('radius')
  if trial:stop(trial,'sqlippool_upgrade_rollback')
  replace(backup);start();emit('rolled_back');raise
 result={'status':'applied','backup':str(root),'before':before,'after':{name:pids(name) for name in before},'module_sha256':new,'mapped_candidate':True,'database_ready':True,'radius_ready':True,'configs_unchanged':True,'commercial_rules_validated':False}
 (root/'deployment-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');(root/'deployment-result.json').chmod(0o600);emit('verified',**result)
