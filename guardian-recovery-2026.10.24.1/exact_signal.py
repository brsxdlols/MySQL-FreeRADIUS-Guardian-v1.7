"""Linux pidfd signals with a durable, one-attempt incident marker."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal

def _send(record, kind, incident, datadir, evidence_root,service):
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
        comm=proc.joinpath('comm').read_text().strip()
        exe=Path(os.readlink(str(proc/'exe')))
        if service=='database':
            if comm not in ('mysqld','mariadbd') or exe.name not in ('mysqld','mariadbd'):raise RuntimeError('Not MariaDB')
            if not re.search(r'--datadir(?:=| )'+re.escape(str(datadir).rstrip('/'))+r'/?(?: |$)',command):raise RuntimeError('Datadir identity mismatch')
        elif service=='radius':
            if comm not in ('freeradius','radiusd') or str(exe) not in ('/usr/sbin/freeradius','/usr/sbin/radiusd'):raise RuntimeError('Not approved Radius executable')
            binary=exe.stat()
            if binary.st_uid!=0 or binary.st_mode&0o022:raise RuntimeError('Radius executable ownership/mode unsafe')
            if proc.joinpath('exe').stat().st_ino!=binary.st_ino:raise RuntimeError('Executable identity changed')
        else:raise RuntimeError('Unsupported service')
        root=Path(evidence_root);root.mkdir(mode=0o700,parents=True,exist_ok=True);os.chmod(str(root),0o700)
        key=hashlib.sha256((service+':'+str(incident['started'])+':'+str(pid)+':'+record['start']+':'+kind).encode()).hexdigest()
        evidence={'service':service,'pid':pid,'start':record['start'],'signal':kind,'process_state':parts[0],'datadir':str(datadir),'incident_started':incident['started'],'reason':incident['reason'],'attempt_reserved_before_signal':True}
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


def send(record,kind,incident,datadir,evidence_root):
    return _send(record,kind,incident,datadir,evidence_root,'database')

def send_radius(record,kind,incident,evidence_root):
    return _send(record,kind,incident,None,evidence_root,'radius')


def supported():
    """Signal zero checks kernel support against this caller only; never a service."""
    if platform.machine()!='x86_64':return False
    libc=ctypes.CDLL(None,use_errno=True);fd=libc.syscall(434,os.getpid(),0)
    if fd<0:return False
    try:return libc.syscall(424,fd,0,0,0)==0
    finally:os.close(fd)
