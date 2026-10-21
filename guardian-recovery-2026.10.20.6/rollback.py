#!/usr/bin/env python3
"""Manual rollback of files only; rejects an active normal-recovery operation."""
import argparse,fcntl,hashlib,json,os
from pathlib import Path
from guardian_safety import atomic_bytes,mysql_read

p=argparse.ArgumentParser();p.add_argument('backup');p.add_argument('--expected-provider',required=True);p.add_argument('--apply',action='store_true');a=p.parse_args()
if os.geteuid()!=0:raise SystemExit('root required')
root=Path(a.backup)
if root.is_symlink() or root.resolve().parent!=Path('/root/mkauth-normal-recovery-backups'):raise SystemExit('Unexpected backup path')
if mysql_read('SELECT nome FROM mkradius.sis_provedor LIMIT 1;').strip()!=a.expected_provider:raise SystemExit('Provider mismatch')
with open('/var/run/mkauth-guardian-global-recovery.lock','a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    state=Path('/var/lib/mkauth-guardian-recovery/state.json')
    if state.exists() and json.loads(state.read_text()).get('recovery',{}).get('phase') not in (None,'done','manual'):raise SystemExit('Recovery active; rollback refused')
    records=json.loads((root/'manifest.json').read_text())
    allowed={'/var/check_backup_freeradius.sh','/usr/local/sbin/mkauth_mysql_radius_guardian.sh','/usr/local/sbin/mkauth_backup_guardian.sh','/usr/local/sbin/check_mariadb_freeradius_health.sh','/usr/local/sbin/mkauth-limpeza-diaria.sh','/usr/local/sbin/mkauth-backup-supervised','/etc/cron.d/backup','/etc/cron.d/check_backup_freeradius','/etc/cron.d/mkauth_mysql_radius_guardian','/etc/cron.d/mkauth_backup_guardian','/etc/cron.d/mkauth-guardian-normal-recovery','/etc/default/check_backup_freeradius','/etc/default/mkauth-guardian-normal-recovery.json','/etc/logrotate.d/mkauth-guardian-normal-recovery','/var/limpamemoria','/var/mkauthcleanfull.sh','/etc/crontab','/var/lib/mkauth-guardian-recovery/native-template.json'}
    for r in records:
        path=Path(r['path'])
        if str(path) not in allowed and not (path.parent==Path('/usr/local/lib/mkauth-guardian-recovery') and path.name in {'guardian_safety.py','recovery_core.py','guardian_controller.py','radius_signals.py','incident_capture.py','exact_signal.py','backup_supervisor.py','compatible_backup.py','install.py','installer_settings.py','supported-source-hashes.json'}):raise SystemExit('Unexpected destination')
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=r['installed_sha256']:raise SystemExit('Current file diverged: '+str(path))
        if r['existed']:
            source=root/str(path).lstrip('/')
            if source.is_symlink() or hashlib.sha256(source.read_bytes()).hexdigest()!=r['sha256']:raise SystemExit('Backup hash mismatch')
    print(json.dumps({'mode':'apply' if a.apply else 'dry-run','paths':len(records),'warning':'Restores older behavior and schedules; does not reverse SQL protector comments or backup quarantine.'}))
    if a.apply:
        for r in reversed(records):
            if r['existed']:
                atomic_bytes(r['path'],(root/r['path'].lstrip('/')).read_bytes(),r['mode']);os.chown(r['path'],r['uid'],r['gid'])
            else:os.unlink(r['path'])
