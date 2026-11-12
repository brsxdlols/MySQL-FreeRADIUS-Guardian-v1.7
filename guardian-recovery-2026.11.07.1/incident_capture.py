"""Bounded, private, read-only evidence capture when queue symptoms appear."""
import datetime
import json
import os
from pathlib import Path
import subprocess
from guardian_safety import atomic_bytes

def capture_queue(health,root='/root/mkauth-guardian-queue-incidents'):
    parent=Path(root);parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if parent.is_symlink():raise RuntimeError('Evidence directory symlink refused')
    os.chmod(str(parent),0o700)
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d-%H%M%S')+'-'+str(os.getpid())
    folder=parent/stamp;folder.mkdir(mode=0o700)
    meta={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'health':health,'read_only':True,'services_restarted':False}
    for source,name,limit in [('/var/log/freeradius/radius.log','radius-tail.log',65536),('/proc/meminfo','meminfo.txt',16384),('/proc/loadavg','loadavg.txt',1024),('/proc/diskstats','diskstats.txt',16384),('/proc/pressure/io','pressure-io.txt',4096),('/proc/pressure/memory','pressure-memory.txt',4096)]:
        try:
            with open(source,'rb') as stream:
                if name=='radius-tail.log':stream.seek(max(0,os.fstat(stream.fileno()).st_size-limit))
                data=stream.read(limit)
            atomic_bytes(folder/name,data)
        except OSError:meta[name]='unavailable'
    cnf=next((p for p in ['/etc/mysql/debian.cnf','/root/.my.cnf'] if Path(p).is_file()),None)
    if cnf:
        # Raw SQL can contain client identifiers: keep only in root-private evidence.
        query="SELECT NOW(6); SELECT ID,USER,DB,COMMAND,TIME,STATE,LEFT(INFO,2048) FROM information_schema.PROCESSLIST WHERE ID<>CONNECTION_ID() ORDER BY TIME DESC LIMIT 80; SHOW GLOBAL STATUS LIKE 'Tokudb%checkpoint%'; SELECT * FROM information_schema.TOKUDB_TRX LIMIT 20;"
        try:
            result=subprocess.run(['mysql','--defaults-file='+cnf,'--connect-timeout=2','-N','-B','-e',query],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=4,close_fds=True)
            atomic_bytes(folder/'sql-processes-private.txt',result.stdout[:262144]);atomic_bytes(folder/'sql-errors-private.txt',result.stderr[:8192]);meta['sql_exit']=result.returncode
        except subprocess.TimeoutExpired as error:
            atomic_bytes(folder/'sql-processes-private.txt',(error.stdout or b'')[:262144]);meta['sql_timeout']=True
    atomic_bytes(folder/'metadata.json',json.dumps(meta,indent=2).encode())
    return str(folder)
