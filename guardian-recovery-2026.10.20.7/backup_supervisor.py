#!/usr/bin/env python3
"""Supervise the vendor backup; reject incomplete artifacts, preserve evidence."""
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
from guardian_safety import atomic_bytes,mysql_read,protector,validate_maz
from guardian_controller import ROOT,log,notify
from compatible_backup import generate

BACKUPS=Path('/opt/mk-auth/bckp')
INDEX=Path('/opt/mk-auth/dados/backup.db')

def database_ready():
    try:return mysql_read('SELECT 1;').strip()=='1'
    except Exception:return False

def quarantine(path, report, batch):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}\.maz',path.name) or path.is_symlink():
        raise RuntimeError('Unsafe backup filename; manual review required')
    rejected=BACKUPS/'.guardian-rejected'/batch.name
    rejected.mkdir(parents=True,mode=0o700,exist_ok=True)
    os.chmod(str(rejected.parent),0o700)
    destination=rejected/path.name
    connection=sqlite3.connect(str(INDEX),timeout=5)
    try:
        schema=[row[1] for row in connection.execute('PRAGMA table_info(backup)')]
        if schema!=['uuid','data','descricao','arquivo','tipo']:raise RuntimeError('Unsupported native backup index schema')
        if not (batch/'backup-index-before.db').exists():
            snapshot=sqlite3.connect(str(batch/'backup-index-before.db'))
            connection.backup(snapshot);snapshot.close();os.chmod(str(batch/'backup-index-before.db'),0o600)
        connection.execute('BEGIN IMMEDIATE')
        connection.execute("UPDATE backup SET descricao=?,tipo='err' WHERE arquivo IN (?,?)",('FALHOU VALIDACAO GUARDIAN; arquivo preservado em quarentena',path.name,path.stem))
        os.rename(str(path),str(destination));os.chmod(str(destination),0o600)
        try:connection.commit()
        except Exception:
            os.rename(str(destination),str(path));raise
        report['quarantine_path']=str(destination)
        atomic_bytes(batch/(path.name+'.json'),json.dumps(report,indent=2).encode())
    finally:connection.close()

def request_recovery():
    atomic_bytes(ROOT/'request.json',json.dumps({'kind':'database','reason':'backup_database_unavailable','at':time.time()}).encode())
    for _ in range(90):
        subprocess.run(['python3',str(Path(__file__).parent/'guardian_controller.py')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            state=json.loads((ROOT/'state.json').read_text());recovery=state.get('recovery',{})
            if recovery.get('phase')=='manual':return False
            if recovery.get('phase')=='done' and database_ready():return True
        except (OSError,ValueError):pass
        time.sleep(3)
    return False

def main():
    ROOT.mkdir(mode=0o700,exist_ok=True)
    with open('/var/run/mkauth-native-backup-supervisor.lock','a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:log('backup_skipped_overlap');return 3
        stamp=time.strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid())
        private=Path('/root/mkauth-backup-supervised')/stamp
        private.mkdir(mode=0o700,parents=True);os.chmod(str(private.parent),0o700)
        for attempt in (1,2):
            if not database_ready():
                if attempt>1 or not request_recovery():log('backup_deferred_database_unavailable');return 2
            result=protector(True)
            if result.get('status')=='busy':log('backup_deferred_recovery_active');return 3
            locks=int(mysql_read("SELECT COUNT(*) FROM information_schema.PROCESSLIST WHERE ID<>CONNECTION_ID() AND STATE LIKE '%lock%' AND (INFO LIKE '%radacct%' OR INFO LIKE '%radippool%');").strip())
            if locks:
                notify('Backup adiado: bloqueios SQL ativos. O monitor verificara recuperacao normal; nenhum dump vazio sera aceito.');return 3
            before={p.name:(p.stat().st_size,p.stat().st_mtime_ns) for p in BACKUPS.glob('*.maz') if p.is_file() and not p.is_symlink()}
            output=private/('native-'+str(attempt)+'.log')
            unavailable=False;started=time.time();warned=False
            with output.open('wb') as stream:
                os.chmod(str(output),0o600)
                child=subprocess.Popen(['/opt/mk-auth/scripts/backup.php'],stdout=stream,stderr=stream,close_fds=True,start_new_session=True)
                log('native_backup_started',pid=child.pid,attempt=attempt)
                while child.poll() is None:
                    if not database_ready():unavailable=True
                    if time.time()-started>900 and not warned:
                        notify('Backup permanece em execucao por mais de 15 minutos. Sem encerramento forcado; nova execucao bloqueada pelo lock.');warned=True
                    time.sleep(5)
            reports=[]
            for path in BACKUPS.glob('*.maz'):
                if path.is_symlink() or not path.is_file():continue
                info=path.stat()
                if before.get(path.name)==(info.st_size,info.st_mtime_ns):continue
                report=validate_maz(path);reports.append(report)
                if report['classification']=='rejected':quarantine(path,report,private)
            atomic_bytes(private/('validation-'+str(attempt)+'.json'),json.dumps(reports,indent=2).encode())
            passed=child.returncode==0 and bool(reports) and all(r['classification']!='rejected' for r in reports)
            log('native_backup_result',attempt=attempt,returncode=child.returncode,artifacts=len(reports),passed=passed,database_unavailable=unavailable)
            if passed:
                notify('Backup nativo gerado e validado: dumps presentes, esquemas essenciais e compressao integros. Restauração completa ainda nao certificada.');return 0
            notify('Backup FALHOU na validacao. Artefatos incompletos preservados em quarentena e marcados como erro no indice nativo; nao contam como backup valido.')
            if attempt==1 and unavailable and request_recovery():continue
            if database_ready():
                fallback=generate(private)
                log('compatible_backup_published',file=fallback['file'],bytes=fallback['bytes'],tables=fallback['tables'])
                notify('Backup de contingencia gerado no layout .maz: dump unico com transacao, '+str(fallback['tables'])+' tabelas e metadados verificados. Restauração pelo painel nativo ainda nao certificada.')
                return 0
            return 1
    return 1

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        log('backup_supervisor_error',type=type(error).__name__)
        notify('Falha no supervisor do backup; verificar log privado. Nenhuma recuperacao destrutiva executada.')
        raise SystemExit(2)
