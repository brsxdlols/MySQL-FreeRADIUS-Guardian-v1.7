#!/usr/bin/env python3
import argparse
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import time
import urllib.parse
import urllib.request
from guardian_safety import ALTER, atomic_bytes, mysql_read, protector
from recovery_core import begin, step
from exact_signal import send as send_exact

ROOT=Path('/var/lib/mkauth-guardian-recovery')
CONFIG=Path('/etc/default/mkauth-guardian-normal-recovery.json')
LOG=Path('/var/log/mkauth-guardian-normal-recovery.log')

def log(event, **fields):
    record=dict(time=datetime.datetime.now(datetime.timezone.utc).isoformat(),event=event,**fields)
    with LOG.open('a') as stream:
        os.chmod(str(LOG),0o600);stream.write(json.dumps(record)+'\n')

def load_state():
    file=ROOT/'state.json'
    return json.loads(file.read_text()) if file.exists() else {'history':[],'bad_database':0,'bad_radius':0,'bad_queue':0}

def save(state):
    atomic_bytes(ROOT/'state.json',json.dumps(state,indent=2).encode())

def identity(pidfile, expected):
    try:
        pid=int(Path(pidfile).read_text().strip())
        if pid<2:return None
        proc=Path('/proc')/str(pid)
        if proc.joinpath('comm').read_text().strip() not in expected:return None
        return {'pid':pid,'start':proc.joinpath('stat').read_text().rsplit(')',1)[1].split()[19]}
    except (OSError,ValueError,IndexError):return None

def same_process(record):
    if not record:return False
    try:
        parts=Path('/proc/{}/stat'.format(record['pid'])).read_text().rsplit(')',1)[1].split()
        return parts[0]!='Z' and parts[19]==record['start']
    except (OSError,KeyError,IndexError):return False

def notify(message):
    # Reuse local credentials only; never print them or embed them in the package.
    values={}
    try:
        for row in Path('/etc/default/check_backup_freeradius').read_text().splitlines():
            match=re.match(r'^([A-Z_]+)=(.*)$',row)
            if match:
                parsed=shlex.split(match[2],comments=True)
                values[match[1]]=parsed[0] if len(parsed)==1 else ''
        if values.get('USAR_TELEGRAM')!='sim':return
        token=values.get('TELEGRAM_BOT','');chat=values.get('TELEGRAM_CHAT_ID','')
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+',token) or not chat:return
        name=values.get('MKAUTH_NAME','MK-AUTH')
        body=urllib.parse.urlencode({'chat_id':chat,'text':name+' — '+message}).encode()
        with urllib.request.urlopen('https://api.telegram.org/bot'+token+'/sendMessage',data=body,timeout=8) as response:
            reply=json.loads(response.read(65536))
            log('telegram_delivery',ok=bool(reply.get('ok')))
    except Exception as error:
        log('telegram_delivery',ok=False,error=type(error).__name__)

class Production:
    def __init__(self):self.children=[]
    def identity(self, kind):
        if kind=='database':
            found=identity('/run/mysqld/mysqld.pid',{'mysqld','mariadbd'})
            if found:return found
            # A missing PID file does not prove that the production daemon died.
            for proc in Path('/proc').glob('[0-9]*'):
                try:
                    if proc.joinpath('comm').read_text().strip() not in {'mysqld','mariadbd'}:continue
                    command=proc.joinpath('cmdline').read_bytes().replace(b'\x00',b' ').decode(errors='replace')
                    if re.search(r'--datadir(?:=| )/var/lib/mysql(?:/)?(?: |$)',command):
                        parts=proc.joinpath('stat').read_text().rsplit(')',1)[1].split()
                        if parts[0]!='Z':return {'pid':int(proc.name),'start':parts[19]}
                except (OSError,IndexError):pass
            return None
        return identity('/var/run/freeradius/freeradius.pid',{'freeradius','radiusd'})
    same_process=staticmethod(same_process)
    command_running=staticmethod(same_process)
    def spawn(self,args):
        stream=LOG.open('ab');os.chmod(str(LOG),0o600)
        child=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,close_fds=True,start_new_session=True)
        stream.close();self.children.append(child)
        try:
            proc=Path('/proc/{}/stat'.format(child.pid)).read_text().rsplit(')',1)[1].split()
            return {'pid':child.pid,'start':proc[19]}
        except OSError:return None
    def stop_radius(self,record):
        if same_process(record):os.kill(record['pid'],signal.SIGTERM)
        log('radius_TERM',pid=record['pid'])
    def shutdown_database(self):
        cnf=next((x for x in ['/etc/mysql/debian.cnf','/root/.my.cnf'] if Path(x).is_file()),None)
        if not cnf:raise RuntimeError('No local MySQL credentials')
        log('database_shutdown_requested')
        # Never use service mysql stop/restart: its init script contains killall -9.
        return self.spawn(['mysqladmin','--defaults-file='+cnf,'--connect-timeout=5','shutdown'])
    def signal_database(self,record,kind,incident):
        if not json.loads(CONFIG.read_text()).get('allow_sigkill_exact_mariadb'):
            raise RuntimeError('Exact MariaDB escalation disabled')
        evidence=send_exact(record,kind,incident,'/var/lib/mysql','/root/mkauth-normal-recovery-incidents')
        log('database_exact_signal',**evidence)
        notify('MariaDB nao encerrou no prazo. Sinal '+kind+' enviado somente ao processo confirmado; evidencias privadas registradas.')
    def start(self,kind):
        service='mysql' if kind=='database' else 'freeradius'
        log('service_start_requested',service=service)
        return self.spawn(['service',service,'start'])
    def database_ready(self):
        try:return mysql_read('SELECT 1;').strip()=='1'
        except Exception:return False
    def radius_ready(self):
        if not self.identity('radius'):return False
        try:
            out=subprocess.check_output(['ss','-H','-lun'],timeout=3).decode()
            ports={row.split()[3].rsplit(':',1)[-1] for row in out.splitlines() if len(row.split())>3}
            return '1812' in ports and '1813' in ports
        except Exception:return False
    def reap(self):
        for child in self.children:child.poll()

def queue_sample(state):
    path=Path('/var/log/freeradius/radius.log')
    try:
        info=path.stat();offset=state.get('radius_offset',info.st_size)
        if info.st_ino!=state.get('radius_inode',info.st_ino) or offset>info.st_size:offset=0
        with path.open('rb') as stream:
            stream.seek(max(offset,info.st_size-1048576));data=stream.read(1048576)
        state.update(radius_inode=info.st_ino,radius_offset=info.st_size)
        return len(re.findall(rb'unfinished request in component.*module <(?:queue|sql|sqlippool)>',data,re.I))
    except OSError:return 0

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--recover-now',choices=['database','radius']);parser.add_argument('--reason',default='authorized_manual_test')
    args=parser.parse_args()
    config=json.loads(CONFIG.read_text())
    ROOT.mkdir(mode=0o700,exist_ok=True);os.chmod(str(ROOT),0o700)
    sql=Path('/opt/mk-auth/mysql/up_database.sql')
    if sql.is_file() and any(ALTER.fullmatch(row) for row in sql.read_bytes().splitlines(keepends=True)):
        log('protector',result=protector(True))
    with open('/var/run/mkauth-guardian-global-recovery.lock','a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return 0
        state=load_state();backend=Production();now=time.time()
        active=state.get('recovery')
        if active and active['phase']=='manual':
            log('manual_intervention_required',phase=active['phase']);return 2
        if active and active['phase'] not in ('done','manual'):
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                step(active,backend);backend.reap();save(state)
                if active['phase'] in ('done','manual'):break
                time.sleep(.5)
            if active['phase']=='done':
                state['history']=(state.get('history',[])+[{'at':time.time(),'database':active['database'],'reason':active['reason']}])[-20:]
                state.update(bad_database=0,bad_radius=0,bad_queue=0,last_recovery=time.time())
                log('recovery_available',reason=active['reason'],availability_only=True)
                notify('Servicos disponiveis apos recuperacao coordenada. SIGKILL utilizado: '+str(bool(active.get('used_sigkill')))+'. Accounting ainda requer validacao funcional.')
            elif active['phase']=='manual':
                log('recovery_stopped',error=active.get('error'))
                notify('Recuperacao interrompida: '+active.get('error','ver logs')+'. Verificar evidencias antes de nova tentativa.')
            save(state);return 0
        if now-state.get('last_sample',0)<20 and not args.recover_now:return 0
        db=backend.database_ready();radius=backend.radius_ready();queue=queue_sample(state)
        blocked=False
        if db:
            try:
                blocked=int(mysql_read("SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE ID<>CONNECTION_ID() AND TIME>=60 AND STATE LIKE '%lock%' AND (INFO LIKE '%radacct%' OR INFO LIKE '%radippool%');").strip())>0
            except Exception:pass
        state['bad_database']=state.get('bad_database',0)+1 if not db else 0
        state['bad_radius']=state.get('bad_radius',0)+1 if not radius else 0
        state['bad_queue']=state.get('bad_queue',0)+1 if queue>=10 else 0
        state.update(last_sample=now,last_health={'database':db,'radius':radius,'queue_errors':queue,'critical_lock':blocked})
        request=ROOT/'request.json'
        if request.exists():
            requested=json.loads(request.read_text());request.unlink()
            if now-requested.get('at',0)<600:args.recover_now=requested['kind'];args.reason=requested.get('reason','backup_failure')
        need_database=bool(args.recover_now=='database' or state['bad_database']>=3 or (state['bad_queue']>=2 and blocked))
        need_radius=bool(args.recover_now=='radius' or state['bad_radius']>=3 or state['bad_queue']>=4)
        if not config.get('enabled'):
            if need_database or need_radius:log('recovery_disabled',database=need_database)
            save(state);return 0
        if need_database or need_radius:
            history=[x for x in state.get('history',[]) if now-x['at']<3600]
            if now-state.get('last_recovery',0)<300 or sum(x['database'] for x in history)>=2 or len(history)>=4:
                log('recovery_rate_limited');save(state);return 0
            reason=args.reason if args.recover_now else ('database_unavailable' if not db else 'persistent_queue_or_lock' if queue else 'radius_unavailable')
            state['recovery']=begin(reason,need_database,allow_sigkill=config.get('allow_sigkill_exact_mariadb',False))
            log('normal_recovery_begin',reason=reason,database=need_database)
            notify('Falha confirmada: '+reason+'. Recuperacao coordenada iniciada. Escalada exata autorizada: '+str(bool(config.get('allow_sigkill_exact_mariadb')))+'.')
        save(state);return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        try:log('controller_error',type=type(error).__name__)
        except Exception:pass
        raise SystemExit(2)
