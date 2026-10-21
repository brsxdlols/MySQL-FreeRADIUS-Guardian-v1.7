"""Linux pidfd signals with a durable, one-attempt incident marker."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal

def send(record, kind, incident, datadir, evidence_root):
    if kind not in ('TERM','KILL') or platform.machine()!='x86_64':
        raise RuntimeError('Unsupported signal or architecture')
    pid=int(record['pid'])
    if pid<2:raise RuntimeError('Unsafe PID')
    libc=ctypes.CDLL(None,use_errno=True)
    # Linux x86_64 pidfd_open / pidfd_send_signal; ENOSYS fails closed.
    fd=libc.syscall(434,pid,0)
    if fd<0:raise OSError(ctypes.get_errno(),'pidfd_open unavailable')
    try:
        proc=Path('/proc')/str(pid)
        parts=proc.joinpath('stat').read_text().rsplit(')',1)[1].split()
        command=proc.joinpath('cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
        if parts[19]!=record['start'] or parts[0]=='Z':raise RuntimeError('Process identity changed')
        if proc.joinpath('comm').read_text().strip() not in ('mysqld','mariadbd'):raise RuntimeError('Not MariaDB')
        if Path(os.readlink(str(proc/'exe'))).name not in ('mysqld','mariadbd'):raise RuntimeError('Unexpected executable')
        if not re.search(r'--datadir(?:=| )'+re.escape(str(datadir).rstrip('/'))+r'/?(?: |$)',command):raise RuntimeError('Datadir identity mismatch')
        root=Path(evidence_root);root.mkdir(mode=0o700,parents=True,exist_ok=True);os.chmod(str(root),0o700)
        key=hashlib.sha256((str(incident['started'])+':'+str(pid)+':'+record['start']+':'+kind).encode()).hexdigest()
        evidence={'pid':pid,'start':record['start'],'signal':kind,'process_state':parts[0],'datadir':str(datadir),'incident_started':incident['started'],'reason':incident['reason'],'attempt_reserved_before_signal':True}
        # O_EXCL refuses a replay after a crash. Never delete the reservation.
        marker=root/(key+'.json')
        out=os.open(str(marker),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(out,'w') as stream:
            json.dump(evidence,stream);stream.flush();os.fsync(stream.fileno())
        directory=os.open(str(root),os.O_DIRECTORY)
        try:os.fsync(directory)
        finally:os.close(directory)
        # The fd continues to identify the original process even after PID reuse.
        result=libc.syscall(424,fd,int(signal.SIGTERM if kind=='TERM' else signal.SIGKILL),0,0)
        if result<0:raise OSError(ctypes.get_errno(),'pidfd_send_signal failed')
        return evidence
    finally:os.close(fd)
