"""Review a bounded wrapper around the native backup. Never create a fallback."""
import hashlib,re
from pathlib import Path
NATIVE='/opt/mk-auth/scripts/backup.php'
LEGACY='/usr/local/sbin/mkauth-backup-supervised'
WRAPPER='/usr/local/sbin/mkauth-native-backup-10m'
MODULE='/usr/local/lib/mkauth-guardian-recovery/native_backup_timeout.py'
POLICY='/etc/default/mkauth-native-backup-safe.json'
WRAPPER_BYTES=('#!/bin/sh\nexec /usr/bin/python3 '+MODULE+'\n').encode()
KNOWN={'02e4639919da772678498b3986478c87e77b441938c615957af89e860daeefa8','5a3afbc057acc57f202c4f553f1bcdecbf7e2a5b85b7e647140b5f763f2f23f2'}
def selected_reference(schedule):
    references=[];offset=0
    for line in schedule.splitlines(keepends=True):
        for target in [NATIVE,LEGACY,WRAPPER]:
            pattern=r'(?<![\w/.-])'+re.escape(target)+r'(?![\w/.-])'
            for match in re.finditer(pattern,line):
                references.append((target,offset+match.start(),offset+match.end(),line,not line.lstrip().startswith('#')))
        offset+=len(line)
    active=[item for item in references if item[4]]
    candidates=active if active else references
    if len(candidates)!=1:raise RuntimeError('Backup routing requires review; expected one active native or reviewed wrapper, or one paused reference')
    return candidates[0]

def review(schedule,wrapper_data=None):
    # Historical commented references are preserved when exactly one active route exists.
    target,start,end,line,active=selected_reference(schedule)
    if target==LEGACY and (wrapper_data is None or hashlib.sha256(wrapper_data).hexdigest() not in KNOWN):raise RuntimeError('Unknown backup wrapper; no replacement made')
    if target==WRAPPER and wrapper_data!=WRAPPER_BYTES:raise RuntimeError('Existing 10-minute wrapper differs; review required')
    if active:
        fields=line.split(None,6)
        if len(fields)!=7 or fields[5]!='root' or not all(re.fullmatch(r'[0-9*/,\-]+',x) for x in fields[:5]):raise RuntimeError('Native backup cron syntax requires review')
        if not re.fullmatch(re.escape(target)+r'(?:\s+(?:[12]?>{1,2}\s*(?:/dev/null|/var/log/[A-Za-z0-9_.-]+)|2>&1))*\s*',fields[6]):raise RuntimeError('Native backup command requires review')
    return schedule[:start]+WRAPPER+schedule[end:]

def plan(here):
    cron=Path('/etc/cron.d/backup')
    if cron.is_symlink() or not cron.is_file():raise RuntimeError('Missing/symlink native backup cron')
    schedule=cron.read_text();selected=selected_reference(schedule)[0];target=Path(selected)
    data=None
    if selected in [LEGACY,WRAPPER]:
        if target.is_symlink() or not target.is_file():raise RuntimeError('Missing/symlink existing backup wrapper')
        st=target.stat()
        if st.st_uid!=0 or st.st_mode&0o022:raise RuntimeError('Unsafe backup wrapper ownership/mode')
        data=target.read_bytes()
    changed=review(schedule,data)
    return {str(cron):(changed.encode(),0o644),WRAPPER:(WRAPPER_BYTES,0o700),MODULE:((here/'native_backup_timeout.py').read_bytes(),0o600),POLICY:(b'{"mode":"native_only","max_seconds":600}\n',0o600)}
