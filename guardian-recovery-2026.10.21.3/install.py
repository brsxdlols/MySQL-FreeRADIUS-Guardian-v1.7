#!/usr/bin/env python3
"""Install one normal-recovery coordinator. Reviewed hashes only; dry-run default."""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
from guardian_safety import atomic_bytes,mysql_read
from compatible_backup import discover_template
from installer_settings import parse_settings,validate

HERE=Path(__file__).resolve().parent
DEST='/usr/local/lib/mkauth-guardian-recovery'
OLD=['/var/check_backup_freeradius.sh','/usr/local/sbin/mkauth_mysql_radius_guardian.sh','/usr/local/sbin/mkauth_backup_guardian.sh']
SHIM=('#!/bin/sh\n# Guardian Recovery 2026.10.21.3 — single coordinator\nexec /usr/bin/python3 '+DEST+'/guardian_controller.py\n').encode()
LOCKS=['/var/run/mkauth-guardian-recovery-install.lock','/var/run/mkauth-guardian-global-recovery.lock','/var/run/check_backup_freeradius.lock','/var/run/mkauth_mysql_radius_guardian.lock','/var/run/mkauth_mysql_radius_guardian_v18.lock','/var/run/mkauth_backup_guardian.lock','/var/run/mkauth-limpeza.lock','/var/run/mkauth-native-backup-supervisor.lock']

def review_sources(paths,supported,shim_hash):
    existing=[Path(path).exists() or Path(path).is_symlink() for path in paths]
    if any(existing) and not all(existing):raise RuntimeError('Partial Guardian installation requires review')
    for path in paths if all(existing) else []:
        target=Path(path)
        if not target.is_file() or target.is_symlink():raise RuntimeError('Missing/symlink Guardian '+path)
        digest=hashlib.sha256(target.read_bytes()).hexdigest()
        if digest not in supported[str(path)]+[shim_hash]:raise RuntimeError('Unreviewed source '+str(path)+' '+digest)

def inherited_only(path):
    info=os.stat(path);holders=[]
    for proc in Path('/proc').glob('[0-9]*'):
        if proc.name==str(os.getpid()):continue
        try:
            for fd in proc.joinpath('fd').iterdir():
                try:
                    current=fd.stat()
                    if (current.st_dev,current.st_ino)==(info.st_dev,info.st_ino):
                        holders.append(proc.joinpath('comm').read_text().strip());break
                except OSError:pass
        except OSError:pass
    return bool(holders) and set(holders).issubset({'mysqld','mariadbd','mysqld_safe','freeradius','radiusd','logger','cron'})

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--expected-provider',required=True);parser.add_argument('--apply',action='store_true');parser.add_argument('--enable-normal-recovery',action='store_true');parser.add_argument('--allow-sigkill-exact-mariadb',action='store_true');parser.add_argument('--local-config-file');args=parser.parse_args()
    if os.geteuid()!=0:raise RuntimeError('root required')
    provider=mysql_read('SELECT nome FROM mkradius.sis_provedor LIMIT 1;').strip()
    if provider!=args.expected_provider:raise RuntimeError('Provider mismatch')
    datadir=mysql_read('SELECT @@datadir;').strip().rstrip('/')
    if datadir!='/var/lib/mysql':raise RuntimeError('Nonstandard datadir requires review')
    cnf=Path('/etc/default/check_backup_freeradius')
    candidate=None
    if cnf.is_symlink():raise RuntimeError('Local configuration symlink refused')
    if args.local_config_file:
        supplied=Path(args.local_config_file);info=supplied.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o077 or info.st_size>65536:raise RuntimeError('Setup data must be a private root-owned regular file')
        candidate=json.loads(supplied.read_text());validate(parse_settings(candidate['content']))
    if not cnf.is_file() and candidate is None:raise RuntimeError('Local configuration or private first-install setup required')
    supported=json.loads((HERE/'supported-source-hashes.json').read_text());shim_hash=hashlib.sha256(SHIM).hexdigest()
    review_sources(OLD,supported,shim_hash)
    handles=[]
    try:
        for path in LOCKS:
            handle=open(path,'a');handles.append(handle)
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                if path in LOCKS[2:-1] and inherited_only(path):
                    print(json.dumps({'inherited_lock_preserved':path}));continue
                raise
        if candidate is not None:
            actual=hashlib.sha256(cnf.read_bytes()).hexdigest() if cnf.exists() else None
            if actual!=candidate['base_sha256']:raise RuntimeError('Local configuration changed during setup; refusing overwrite')
        plan={}
        for name in ['guardian_safety.py','recovery_core.py','radius_signals.py','incident_capture.py','notification_messages.py','exact_signal.py','guardian_controller.py','backup_supervisor.py','compatible_backup.py','install.py','installer_settings.py','supported-source-hashes.json']:
            file=HERE/name;plan[DEST+'/'+file.name]=(file.read_bytes(),0o600)
        template=Path('/var/lib/mkauth-guardian-recovery/native-template.json')
        blueprint=json.loads(template.read_text()) if template.exists() else discover_template()
        plan[str(template)]=(json.dumps(blueprint,indent=2).encode()+b'\n',0o600)
        for path in OLD+['/usr/local/sbin/check_mariadb_freeradius_health.sh']:plan[path]=(SHIM,0o700)
        for cron in ['check_backup_freeradius','mkauth_mysql_radius_guardian','mkauth_backup_guardian']:
            plan['/etc/cron.d/'+cron]=(b'# Superseded by mkauth-guardian-normal-recovery. Previous content in private rollback backup.\n',0o644)
        plan['/etc/cron.d/mkauth-guardian-normal-recovery']=(('SHELL=/bin/sh\nPATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n* * * * * root /usr/bin/python3 '+DEST+'/guardian_controller.py >/dev/null 2>&1\n* * * * * root sleep 30; /usr/bin/python3 '+DEST+'/guardian_controller.py >/dev/null 2>&1\n').encode(),0o644)
        settings=Path('/etc/default/mkauth-guardian-normal-recovery.json')
        config=json.loads(settings.read_text()) if settings.exists() else {'enabled':False,'destructive_recovery':False}
        config.update(provider=provider,destructive_recovery=False)
        if args.allow_sigkill_exact_mariadb:config['allow_sigkill_exact_mariadb']=True
        config.setdefault('allow_sigkill_exact_mariadb',False)
        if args.enable_normal_recovery:config['enabled']=True
        plan[str(settings)]=(json.dumps(config,indent=2).encode()+b'\n',0o600)
        original=candidate['content'] if candidate is not None else cnf.read_text();original=re.sub(r'(?m)^\s*(?:export\s+)?GUARDIAN_ALLOW_DESTRUCTIVE_RECOVERY=.*$','GUARDIAN_ALLOW_DESTRUCTIVE_RECOVERY=nao',original)
        if 'GUARDIAN_ALLOW_DESTRUCTIVE_RECOVERY=nao' not in original:original+='\nGUARDIAN_ALLOW_DESTRUCTIVE_RECOVERY=nao\n'
        plan[str(cnf)]=(original.encode(),0o600)
        backupcron=Path('/etc/cron.d/backup').read_text()
        native='/opt/mk-auth/scripts/backup.php';wrapper='/usr/local/sbin/mkauth-backup-supervised'
        if backupcron.count(native)==1:backupcron=backupcron.replace(native,wrapper)
        elif backupcron.count(wrapper)!=1:raise RuntimeError('Unexpected native backup schedule')
        plan['/etc/cron.d/backup']=(backupcron.encode(),0o644)
        plan[wrapper]=(('#!/bin/sh\nexec /usr/bin/python3 '+DEST+'/backup_supervisor.py\n').encode(),0o700)
        disabled=b'#!/bin/sh\nlogger -t mkauth-guardian "Legacy destructive cleanup disabled; no data removed"\nexit 0\n'
        for path in ['/var/limpamemoria','/var/mkauthcleanfull.sh']:
            if Path(path).is_file():plan[path]=(disabled,0o700)
        crontab=Path('/etc/crontab').read_text()
        crontab=re.sub(r'(?m)^(?!\s*#)([^\n]*(?:/var/limpamemoria|/var/mkauthcleanfull\.sh)[^\n]*)$','# GUARDIAN NORMAL RECOVERY DISABLED: '+r'\1',crontab)
        plan['/etc/crontab']=(crontab.encode(),0o644)
        plan['/usr/local/sbin/mkauth-limpeza-diaria.sh']=(('#!/bin/sh\numask 077\nexec 9>/var/run/mkauth-limpeza.lock\nflock -n 9 || exit 0\nnice -n 15 timeout 900 python3 '+DEST+'/guardian_safety.py inventory >>/var/log/mkauth-limpeza.log 2>&1\n').encode(),0o700)
        plan['/etc/logrotate.d/mkauth-guardian-normal-recovery']=(b'/var/log/mkauth-guardian-normal-recovery.log {\n size 10M\n rotate 7\n missingok\n notifempty\n compress\n copytruncate\n}\n',0o644)
        changed={}
        for path,(content,mode) in plan.items():
            target=Path(path)
            if target.is_symlink():raise RuntimeError('Symlink target refused '+path)
            if path.endswith('.py'):compile(content,path,'exec')
            if content.startswith(b'#!/bin/sh'):subprocess.run(['bash','-n'],input=content,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            if not target.exists() or target.read_bytes()!=content or stat.S_IMODE(target.stat().st_mode)!=mode:changed[path]=(content,mode)
        print(json.dumps({'mode':'apply' if args.apply else 'dry-run','normal_recovery':config['enabled'],'allow_sigkill_exact_mariadb':config['allow_sigkill_exact_mariadb'],'legacy_destructive_recovery':False,'changed_paths':sorted(changed)}))
        if not args.apply or not changed:return 0
        backup=Path('/root/mkauth-normal-recovery-backups')/(datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid()))
        backup.mkdir(parents=True,mode=0o700);os.chmod(str(backup.parent),0o700)
        records=[]
        for path,(content,mode) in changed.items():
            target=Path(path);record={'path':path,'existed':target.exists(),'installed_sha256':hashlib.sha256(content).hexdigest()}
            if target.exists():
                info=target.stat();record.update(mode=stat.S_IMODE(info.st_mode),uid=info.st_uid,gid=info.st_gid,sha256=hashlib.sha256(target.read_bytes()).hexdigest())
                copy=backup/path.lstrip('/');copy.parent.mkdir(parents=True,exist_ok=True,mode=0o700);shutil.copyfile(str(target),str(copy));os.chmod(str(copy),0o600)
            records.append(record)
        atomic_bytes(backup/'manifest.json',json.dumps(records,indent=2).encode())
        installed=[]
        try:
            for path in ['/var/lib/mkauth-guardian-recovery','/var/lib/mkauth-guardian-safety']:
                Path(path).mkdir(mode=0o700,exist_ok=True);os.chmod(path,0o700)
            for path,(content,mode) in changed.items():
                Path(path).parent.mkdir(mode=0o700,parents=True,exist_ok=True);atomic_bytes(path,content,mode);installed.append(path)
        except Exception:
            for record in reversed(records):
                if record['path'] not in installed:continue
                if record['existed']:
                    atomic_bytes(record['path'],(backup/record['path'].lstrip('/')).read_bytes(),record['mode']);os.chown(record['path'],record['uid'],record['gid'])
                else:os.unlink(record['path'])
            raise
        print(json.dumps({'status':'installed','backup':str(backup),'service_restarts_during_install':0}))
        return 0
    finally:
        for handle in reversed(handles):handle.close()

if __name__=='__main__':
    try:raise SystemExit(main())
    except BlockingIOError:print('BUSY: active monitor/recovery/backup; retry, never delete locks');raise SystemExit(3)
    except Exception as error:print(json.dumps({'status':'refused','type':type(error).__name__,'reason':str(error)}));raise SystemExit(2)
