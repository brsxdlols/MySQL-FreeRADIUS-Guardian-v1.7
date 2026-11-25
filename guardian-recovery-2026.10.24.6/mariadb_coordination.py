#!/usr/bin/env python3
"""Coordinate native checks and serialize MariaDB starts; never stop or signal."""
import fcntl,json,os,subprocess,sys,time
from pathlib import Path
LOG=Path('/var/log/mkauth-mariadb-coordination.log')
STATE=Path('/var/lib/mkauth-guardian-recovery/state.json')
GLOBAL_LOCK='/var/run/mkauth-guardian-global-recovery.lock'
START_LOCK='/var/run/mkauth-mariadb-start.lock'
def log(event,**fields):
    with LOG.open('a') as f:
        os.chmod(str(LOG),0o600)
        f.write(json.dumps(dict(at=time.time(),event=event,**fields))+'\n')
def processes():
    found=[]
    for p in Path('/proc').glob('[0-9]*'):
        try:
            if p.joinpath('comm').read_text().strip() not in ('mysqld','mariadbd'):continue
            st=p.joinpath('stat').read_text().rsplit(')',1)[1].split()
            if st[0]!='Z':found.append(int(p.name))
        except OSError:pass
    return found
def run(mode):
    if mode not in ('native','start'):raise RuntimeError('Unknown mode')
    lockpath=GLOBAL_LOCK if mode=='native' else START_LOCK
    with open(lockpath,'a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            log('busy',mode=mode);return 0 if mode=='native' else 1
        if mode=='native':
            state=json.loads(STATE.read_text()) if STATE.exists() else {}
            phase=state.get('recovery',{}).get('phase')
            if phase and phase!='done':
                log('native_skipped_recovery',phase=phase);return 0
            log('native_begin')
            result=subprocess.call(['/opt/mk-auth/scripts/mysql.php'],close_fds=True)
            log('native_end',code=result);return result
        found=processes()
        log('start_checked',existing_pids=found,parent=os.getppid())
        if found:
            # A live daemon may still be initializing. Never use ping failure to start another.
            log('start_suppressed_existing_process',pids=found)
            return 0
        env=dict(os.environ,MKAUTH_START_GATE_ACTIVE='1')
        result=subprocess.call(['/etc/init.d/mysql','start'],env=env,close_fds=True)
        log('start_end',code=result);return result
if __name__=='__main__':
    try:raise SystemExit(run(sys.argv[1]))
    except Exception as e:
        try:log('coordination_error',type=type(e).__name__)
        except Exception:pass
        raise SystemExit(1)
