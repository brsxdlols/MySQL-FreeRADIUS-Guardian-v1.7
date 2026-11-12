#!/usr/bin/env python3
"""Native-only backup supervision. No SQL dumps, fallback, pruning or service restarts."""
import json,os,time,stat,fcntl,shutil,subprocess,selectors,signal,resource,datetime
from pathlib import Path
from guardian_safety import validate_maz,atomic_bytes,mysql_read
from guardian_controller import log,notify
POLICY=Path('/etc/default/mkauth-native-backup-safe.json')
LEGACY_POLICY=Path('/etc/default/mkauth-guardian-backup-policy.json')
BACKUPS=Path('/opt/mk-auth/bckp')
PRIVATE=Path('/root/mkauth-native-backup-safe')
LOCK=Path('/var/run/mkauth-native-backup-supervisor.lock')
COMMAND=['/opt/mk-auth/scripts/backup.php']
DEFAULTS={'mode':'native_only','reserve_min_bytes':2*1024**3,'reserve_percent':10,'start_headroom_bytes':1024**3,'max_file_bytes':1024**3,'max_seconds':600,'log_bytes':1024**2,'poll_seconds':1}
class LowSpace(RuntimeError):pass
def load_policy():
    if not POLICY.exists():
        if LEGACY_POLICY.exists() and json.loads(LEGACY_POLICY.read_text()).get('mode')=='compatible_primary':raise RuntimeError('Explicit native-only policy required; legacy compatible-primary not silently changed')
        return dict(DEFAULTS)
    fd=os.open(str(POLICY),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        info=os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o077 or info.st_size>4096:raise RuntimeError('Unsafe backup policy')
        supplied=json.loads(f.read(4097))
    if not isinstance(supplied,dict) or set(supplied)-set(DEFAULTS):raise RuntimeError('Unknown backup policy fields')
    result=dict(DEFAULTS,**supplied)
    if result['mode']!='native_only':raise RuntimeError('Only native-only mode is implemented')
    for key in set(DEFAULTS)-{'mode'}:
        if type(result[key]) is not int or result[key]<=0:raise RuntimeError('Invalid numeric backup policy')
    if result['reserve_percent']>50 or result['poll_seconds']>2 or result['max_seconds']>600 or result['log_bytes']>4*1024**2:raise RuntimeError('Backup policy exceeds reviewed bounds')
    return result
def check_space(paths,policy,starting=False):
    seen=set();reports=[]
    for path in paths:
        p=Path(path);device=p.stat().st_dev
        if device in seen:continue
        seen.add(device);usage=shutil.disk_usage(str(p));reserve=max(policy['reserve_min_bytes'],usage.total*policy['reserve_percent']//100)
        required=reserve+(policy['start_headroom_bytes'] if starting else 0)
        reports.append({'path':str(p),'free':usage.free,'reserve':reserve,'required':required})
        if usage.free<required:raise LowSpace('Backup refused: filesystem reserve reached at '+str(p))
    return reports
def snapshot():
    return {p.name:(p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns) for p in BACKUPS.glob('*.maz') if p.is_file() and not p.is_symlink()}
def live_group(pgid):
    found=[]
    for p in Path('/proc').glob('[0-9]*'):
        try:
            fields=p.joinpath('stat').read_text().rsplit(')',1)[1].split()
            if int(fields[2])==pgid and int(fields[3])==pgid and fields[0]!='Z':found.append(int(p.name))
        except (OSError,ValueError,IndexError):pass
    return found
def stop_owned_group(child,identity,grace=5):
    # Caller has NOT reaped the leader: its PID cannot be reused during these checks/signals.
    fields=Path('/proc/{}/stat'.format(child.pid)).read_text().rsplit(')',1)[1].split()
    if fields[19]!=identity or int(fields[2])!=child.pid or int(fields[3])!=child.pid:raise RuntimeError('Backup child identity changed; no signal sent')
    if live_group(child.pid):os.killpg(child.pid,signal.SIGTERM)
    deadline=time.monotonic()+grace
    while live_group(child.pid) and time.monotonic()<deadline:time.sleep(.1)
    killed=False
    if live_group(child.pid):os.killpg(child.pid,signal.SIGKILL);killed=True
    # Signals affect only the new session created for backup, never MariaDB or RADIUS daemons.
    child.wait(timeout=10)
    remaining=live_group(child.pid)
    if remaining:raise RuntimeError('Backup children remain; no overlapping backup permitted')
    return killed
def watch(command,output,paths,policy,space_check=check_space):
    limit=policy['max_file_bytes']
    def limits():
        os.umask(0o022);resource.setrlimit(resource.RLIMIT_FSIZE,(limit,limit))
    stream=output.open('xb');output.chmod(0o600)
    try:child=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,close_fds=True,start_new_session=True,preexec_fn=limits)
    except BaseException:stream.close();raise
    identity=Path('/proc/{}/stat'.format(child.pid)).read_text().rsplit(')',1)[1].split()[19]
    os.set_blocking(child.stdout.fileno(),False);selector=selectors.DefaultSelector();selector.register(child.stdout,selectors.EVENT_READ)
    start=time.monotonic();next_space=start;written=0;dropped=0;reason=None;killed=False
    with stream:
        try:
            while True:
                now=time.monotonic()
                if now>=next_space:
                    try:space_check(paths,policy)
                    except LowSpace:reason='space_reserve';break
                    next_space=now+policy['poll_seconds']
                if now-start>policy['max_seconds']:reason='deadline';break
                exited=os.waitid(os.P_PID,child.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT)
                for key,mask in selector.select(.2):
                    try:data=os.read(child.stdout.fileno(),65536)
                    except BlockingIOError:data=b''
                    if data:
                        keep=min(len(data),max(0,policy['log_bytes']-written));stream.write(data[:keep]);written+=keep;dropped+=len(data)-keep
                    else:
                        try:selector.unregister(child.stdout)
                        except KeyError:pass
                if exited is not None and not live_group(child.pid):break
            if reason:killed=stop_owned_group(child,identity)
            else:child.wait(timeout=5)
            # Drain a bounded pipe after normal completion; always cap bytes written to the log.
            while True:
                try:data=os.read(child.stdout.fileno(),65536)
                except BlockingIOError:break
                if not data:break
                keep=min(len(data),max(0,policy['log_bytes']-written));stream.write(data[:keep]);written+=keep;dropped+=len(data)-keep
        except BaseException:
            if child.returncode is None:
                try:stop_owned_group(child,identity)
                except Exception:pass
            raise
        finally:selector.close();child.stdout.close()
    return {'returncode':child.returncode,'aborted':reason,'backup_group_sigkill':killed,'log_bytes':written,'log_bytes_discarded':dropped}
def outcome(result,reports):
    if result.get('aborted'):return 'aborted_'+result['aborted'],3
    valid=bool(reports) and all(r.get('classification')=='structurally_valid_restore_required' for r in reports)
    if not valid:return 'native_artifact_unverified',2
    if result['returncode']!=0:return 'native_artifact_structural_ok_script_failed',2
    return 'native_artifact_structural_ok',0
def main():
    policy=load_policy()
    PRIVATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    if PRIVATE.is_symlink() or PRIVATE.stat().st_uid!=0:raise RuntimeError('Unsafe private evidence root')
    PRIVATE.chmod(0o700)
    with LOCK.open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:log('safe_backup_overlap_refused');return 3
        batch=PRIVATE/(time.strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid()));batch.mkdir(mode=0o700)
        paths=[Path('/'),BACKUPS,Path('/tmp'),PRIVATE]
        try:
            space=check_space(paths,policy,starting=True)
            if mysql_read('SELECT 1;').strip()!='1':raise RuntimeError('Database unavailable; no backup started')
        except (LowSpace,RuntimeError) as e:
            atomic_bytes(batch/'result.json',json.dumps({'status':'not_started','type':type(e).__name__,'services_restarted':False}).encode())
            log('safe_backup_not_started',type=type(e).__name__)
            notify('Backup nativo NAO iniciado: reserva de espaco ou banco indisponivel. Nenhum fallback, limpeza ou reinicio executado.')
            return 3
        if (PRIVATE/'blocked.json').exists():
            log('safe_backup_manual_review_required');return 3
        before=snapshot();log('safe_native_backup_started',evidence_path=str(batch))
        try:result=watch(COMMAND,batch/'native.log',paths,policy)
        except Exception as error:
            atomic_bytes(PRIVATE/'blocked.json',json.dumps({'type':type(error).__name__,'evidence':str(batch),'review_required':True}).encode())
            raise
        reports=[]
        for p in BACKUPS.glob('*.maz'):
            if p.is_symlink() or not p.is_file():continue
            st=p.stat()
            if before.get(p.name)==(st.st_ino,st.st_size,st.st_mtime_ns):continue
            reports.append(validate_maz(p))
        status,code=outcome(result,reports)
        result.update(status=status,reports=reports,services_restarted=False,fallback_executed=False,files_deleted=False,reserve_before=space)
        atomic_bytes(batch/'result.json',json.dumps(result,indent=2).encode())
        log('safe_native_backup_result',status=status,returncode=result['returncode'],artifacts=len(reports),evidence_path=str(batch))
        messages={
          'native_artifact_structural_ok':'Backup nativo gerado e estruturalmente validado. Restauracao deste arquivo ainda nao testada.',
          'native_artifact_structural_ok_script_failed':'ATENCAO: arquivo nativo passou na validacao estrutural, mas o script terminou com erro. Nenhum segundo dump foi gerado. Verificar native.log; restauracao ainda nao testada.',
          'native_artifact_unverified':'FALHA: nenhum novo backup nativo validado. Arquivos preservados; nenhum dump compativel adicional executado.',
          'aborted_space_reserve':'FALHA: tarefa de backup interrompida ao atingir reserva de espaco. MariaDB e RADIUS preservados; verificar artefatos parciais.',
          'aborted_deadline':'FALHA: tarefa de backup excedeu 10 minutos e foi interrompida. Nenhum servico reiniciado; verificar artefatos parciais.'}
        notify(messages[status]);return code
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as e:
        try:log('safe_backup_error',type=type(e).__name__,errno=getattr(e,'errno',None));notify('Falha no supervisor nativo seguro. Nenhum fallback ou limpeza automatica; verificar evidencia privada.')
        except Exception:pass
        raise SystemExit(2)
