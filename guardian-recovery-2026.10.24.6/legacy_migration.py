"""Strict migration of a reviewed legacy monitor, without executing shell configuration."""
import hashlib,os,re,shlex,stat
from pathlib import Path

LEGACY_BODY_SHA256='88984a27f48873e5a099c47fee19466d4e5d0428fded84480e9635804920bc84'
CREDENTIAL_KEYS=('TELEGRAM_BOT','TELEGRAM_CHAT_ID')
MONITORS=('/var/check_backup_freeradius.sh','/usr/local/sbin/mkauth_mysql_radius_guardian.sh','/usr/local/sbin/mkauth_backup_guardian.sh','/usr/local/sbin/check_mariadb_freeradius_health.sh')
MENTION=re.compile(r'(?<![\w/.-])(?:'+'|'.join(re.escape(x) for x in MONITORS)+r')(?![\w/.-])')
LITERAL=re.compile(r"(?:'[^'\r\n]*'|\"[^\"$`\\\r\n]*\"|[A-Za-z0-9_:@.\-]+)")

def reviewed_legacy(data):
    try:text=data.decode('utf-8').replace('\r\n','\n')
    except UnicodeDecodeError:return None
    normal=[];values={}
    for line in text.splitlines(keepends=True):
        match=re.fullmatch(r'(TELEGRAM_BOT|TELEGRAM_CHAT_ID)=(.*?)(\r?\n)?',line)
        if match:
            if match[1] in values or not LITERAL.fullmatch(match[2]):return None
            parts=shlex.split(match[2],comments=False)
            if len(parts)!=1:return None
            values[match[1]]=parts[0];normal.append(match[1]+'=<private>\n')
        else:normal.append(line)
    if set(values)!=set(CREDENTIAL_KEYS):return None
    if hashlib.sha256(''.join(normal).encode()).hexdigest()!=LEGACY_BODY_SHA256:return None
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,}',values['TELEGRAM_BOT']):return None
    if not re.fullmatch(r'-?[0-9]{1,20}',values['TELEGRAM_CHAT_ID']):return None
    return values

def read_legacy(path):
    path=Path(path)
    fd=os.open(str(path),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or info.st_size>131072:
            raise RuntimeError('Legacy monitor must be a root-owned regular file without group/world write access')
        data=stream.read(131073)
    values=reviewed_legacy(data)
    if values is None:raise RuntimeError('Unreviewed legacy monitor; credentials omitted')
    return values,hashlib.sha256(data).hexdigest()

def active_legacy_processes(paths=MONITORS):
    targets={os.fsencode(x) for x in paths};found=[]
    for proc in Path('/proc').glob('[0-9]*'):
        if proc.name==str(os.getpid()):continue
        try:
            args=proc.joinpath('cmdline').read_bytes().split(b'\0')
            if targets.intersection(args):found.append(int(proc.name))
        except OSError:pass
    return found

# Exact logging/timeout wrappers reviewed in the native Demo installation.
REVIEWED_WRAPPERS={'68e1ec99bcc2a443f9f2251ddb23c158e1ff6f853f1a637d22e0e2ae22962d50', 'b7f46f55580c45738ff1cb6025c7de698bbe5953ad450d4ef4e4859da2a0693c', 'ad57c2bd1f946e2cb413976f98115f77d0c9b839fa1f3f5aaa69ce6a8fa41d3f', '1f7e97530ca371c4863ba6bda9b76ad4793b3af01dd97edc02c6f7b9183d13fa', '378dfc970dc3fa226126b331067c9bde230f03e108d01f32d50a59731955399e', '8e62a1d313263507fedde5de96a017654c522c5ccb272ca0b9830df0e74ef5d2'}

def migrate_cron(text,system=True):
    output=[];count=0
    for row in text.splitlines(keepends=True):
        if row.lstrip().startswith('#') or not MENTION.search(row):output.append(row);continue
        fields=row.strip().split(None,6 if system else 5)
        if len(fields)!=(7 if system else 6) or not all(re.fullmatch(r'[0-9*/,\-]+',x) for x in fields[:5]):
            raise RuntimeError('Legacy cron syntax requires review; no cron changed')
        if system and fields[5]!='root':raise RuntimeError('Legacy cron user requires review; no cron changed')
        command=fields[-1]
        target='(?:'+'|'.join(re.escape(x) for x in MONITORS)+')'
        prefix=r'(?:(?:/bin/|/usr/bin/)?sleep\s+(?:[0-9]|[1-5][0-9])\s*;\s*)?(?:(?:/usr/bin/)?flock\s+-n\s+/var/run/[A-Za-z0-9_.-]+\s+)?(?:(?:/bin/|/usr/bin/)?(?:ba)?sh\s+)?'
        redirects=r'(?:\s*(?:[12]?>{1,2}\s*(?:/dev/null|/var/log/[A-Za-z0-9_.-]+)|2>&1))*'
        if hashlib.sha256(command.encode()).hexdigest() not in REVIEWED_WRAPPERS and not re.fullmatch(prefix+target+redirects+r'\s*',command):
            raise RuntimeError('Combined or unreviewed legacy cron command; no cron changed')
        output.append('# GUARDIAN MIGRATED: '+row);count+=1
    return ''.join(output),count

def cron_updates(files,root_spool):
    updates={};total=0
    # Spool edits need crontab(1), not an atomic filesystem replacement that changes its group.
    if root_spool.exists():
        if root_spool.is_symlink():raise RuntimeError('Root crontab symlink refused')
        _,count=migrate_cron(root_spool.read_text(),system=False)
        if count:raise RuntimeError('Legacy monitor in root user crontab requires reviewed crontab migration; no changes applied')
    for path in files:
        if path.is_symlink():raise RuntimeError('Cron symlink refused')
        if not path.is_file():continue
        text=path.read_text();new,count=migrate_cron(text)
        if count:
            info=path.stat()
            if info.st_uid!=0 or info.st_mode&0o022:raise RuntimeError('Unsafe cron ownership or permissions')
            updates[str(path)]=(new.encode(),stat.S_IMODE(info.st_mode));total+=count
    return updates,total
