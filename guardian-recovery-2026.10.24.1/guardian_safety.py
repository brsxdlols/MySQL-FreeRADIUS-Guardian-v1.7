#!/usr/bin/env python3
"""MK-AUTH safety utilities. No database writes, extraction or service actions."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile

VERSION = '2026.10.20'
REQUIRED = {'radacct.sql', 'radippool.sql', 'sis_cliente.sql', 'sis_provedor.sql'}
ALTER = re.compile(rb"^[ \t]*ALTER[ \t]+TABLE[ \t]+`?([A-Za-z0-9_]+)`?[ \t]+COLLATE[ \t]*=[ \t]*'latin1_swedish_ci'[ \t]*;[ \t]*(?:\r?\n)?$", re.I)

def protect_content(data, collations):
    result, changed = [], []
    for line in data.splitlines(keepends=True):
        match = ALTER.fullmatch(line)
        if match and collations.get(match[1].decode().lower()) == 'latin1_swedish_ci':
            result.append(b'-- GUARDIAN SAFETY ' + VERSION.encode() + b': redundant collation; ' + line)
            changed.append(match[1].decode().lower())
        else:
            result.append(line)
    return b''.join(result), changed

def mysql_read(query):
    cnf = next((p for p in ['/etc/mysql/debian.cnf', '/root/.my.cnf'] if Path(p).is_file()), None)
    if cnf is None:
        raise RuntimeError('No local MySQL defaults file; credentials must be configured locally')
    return subprocess.check_output(['mysql', '--defaults-file='+cnf, '--connect-timeout=4', '-N', '-B', '-e', 'SET SESSION max_statement_time=8; '+query], timeout=12, stderr=subprocess.DEVNULL).decode()

def atomic_bytes(path, data, mode=0o600):
    path = Path(path)
    if path.is_symlink():
        raise RuntimeError('Refusing symlink destination')
    fd, name = tempfile.mkstemp(prefix='.'+path.name+'.', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        if path.exists():
            old = path.stat()
            if hasattr(os, 'chown'):
                os.chown(name, old.st_uid, old.st_gid)
        os.replace(name, str(path))
        if hasattr(os, 'O_DIRECTORY'):
            dfd = os.open(str(path.parent), os.O_DIRECTORY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def protector(apply=False):
    import fcntl
    # Never delete this stable lock file. Shared with existing recovery paths.
    with open('/var/run/mkauth-guardian-global-recovery.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'busy'}
        target = Path('/opt/mk-auth/mysql/up_database.sql')
        if target.is_symlink() or not target.is_file():
            raise RuntimeError('SQL source must be a regular non-symlink file')
        before_stat = target.stat()
        before = target.read_bytes()
        rows = mysql_read("SELECT TABLE_NAME,TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA='mkradius';")
        collations = dict(row.split('\t') for row in rows.splitlines() if '\t' in row)
        after, changed = protect_content(before, collations)
        report = {'status': 'change_needed' if changed else 'unchanged', 'tables': changed}
        if apply and changed:
            backup = Path('/root/mkauth-guardian-safety-backups')
            backup.mkdir(mode=0o700, exist_ok=True)
            os.chmod(str(backup), 0o700)
            digest = hashlib.sha256(before).hexdigest()
            backup_file = backup / ('up_database.sql.'+digest)
            if not backup_file.exists():
                with backup_file.open('xb') as stream:
                    stream.write(before)
                os.chmod(str(backup_file), 0o600)
            current_stat = target.stat()
            if (current_stat.st_ino, current_stat.st_size, current_stat.st_mtime_ns) != (before_stat.st_ino, before_stat.st_size, before_stat.st_mtime_ns) or target.read_bytes() != before:
                raise RuntimeError('SQL source changed concurrently; no replacement made')
            atomic_bytes(target, after, stat.S_IMODE(before_stat.st_mode))
            report.update(status='protected', backup=str(backup_file))
        return report

def validate_maz(path):
    path = Path(path)
    report = {'file': path.name, 'classification': 'rejected', 'restore_tested': False}
    if path.is_symlink() or not path.is_file():
        report['reason'] = 'not a regular non-symlink file'
        return report
    before = path.stat()
    report['bytes'] = before.st_size
    found, failed, total, members = set(), [], 0, 0
    try:
        with tarfile.open(str(path), mode='r|*') as archive:
            for item in archive:
                members += 1
                if members > 5000:
                    raise ValueError('too many archive members')
                parts = PurePosixPath(item.name)
                if parts.is_absolute() or '..' in parts.parts or item.issym() or item.islnk() or (not item.isfile() and not item.isdir()):
                    raise ValueError('unsafe archive member')
                if not item.isfile():
                    continue
                total += item.size
                if total > 8 * 1024**3:
                    raise ValueError('uncompressed archive exceeds 8 GiB review limit')
                if not item.name.lower().endswith('.sql'):
                    continue
                name = parts.name
                if name in found:
                    raise ValueError('duplicate SQL basename')
                found.add(name)
                source = archive.extractfile(item)
                prefix, tail, count = b'', b'', 0
                while True:
                    chunk = source.read(65536)
                    if not chunk:
                        break
                    count += len(chunk)
                    if len(prefix) < 65536:
                        prefix = (prefix + chunk)[:65536]
                    tail = (tail + chunk)[-8192:]
                if count != item.size or item.size == 0:
                    failed.append(name+': empty or truncated')
                if name in REQUIRED:
                    table = name[:-4].encode()
                    if not re.search(rb'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?'+re.escape(table)+rb'`?\s*\(', prefix, re.I):
                        failed.append(name+': schema missing')
                    if b'Dump completed' not in tail:
                        failed.append(name+': dump completion missing')
        # Reading to end separately validates the compression trailer too.
        import bz2
        with bz2.open(str(path), 'rb') as compressed:
            read_total = 0
            while True:
                chunk = compressed.read(1048576)
                if not chunk:
                    break
                read_total += len(chunk)
                if read_total > 8 * 1024**3:
                    raise ValueError('decompressed stream exceeds review limit')
        missing = sorted(REQUIRED - found)
        if missing:
            failed.append('missing required dumps: '+','.join(missing))
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1048576), b''):
                digest.update(chunk)
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError('archive changed during validation; retry after backup finishes')
        report.update(sha256=digest.hexdigest(), sql_members=len(found), members=members, failures=failed)
        if not failed:
            report['classification'] = 'structurally_valid_restore_required'
    except (OSError, ValueError, EOFError, tarfile.TarError) as error:
        report['reason'] = str(error)
    return report

def inventory(directory, output):
    directory = Path(directory)
    reports = []
    previous = {}
    output = Path(output)
    if output.exists() and not output.is_symlink():
        try:
            previous = {r['file']:r for r in json.loads(output.read_text()).get('archives', [])}
        except (ValueError, KeyError, TypeError):
            pass
    for path in sorted(directory.glob('*.maz')):
        info = path.lstat()
        cached = previous.get(path.name, {})
        signature = [info.st_ino, info.st_size, info.st_mtime_ns]
        if cached.get('signature') == signature and cached.get('validator_version') == VERSION:
            reports.append(cached)
            continue
        result = validate_maz(path)
        result.update(signature=signature, validator_version=VERSION)
        reports.append(result)
    result = {'version':VERSION, 'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'retention':'disabled_no_files_deleted', 'archives':reports}
    atomic_bytes(output, json.dumps(result, indent=2).encode())
    print(json.dumps({'archives':len(reports), 'rejected':sum(r['classification']=='rejected' for r in reports), 'restore_tested':False}))
    return 1 if any(r['classification']=='rejected' for r in reports) else 0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['protect', 'validate', 'inventory'])
    parser.add_argument('path', nargs='?')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--output', default='/var/lib/mkauth-guardian-safety/maz-inventory.json')
    args = parser.parse_args()
    if args.action == 'protect':
        print(json.dumps(protector(args.apply)))
        return 0
    if args.action == 'validate':
        result = validate_maz(args.path)
        print(json.dumps(result, indent=2))
        return 0 if result['classification'] != 'rejected' else 1
    return inventory(args.path or '/opt/mk-auth/bckp', args.output)

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(json.dumps({'status':'error', 'type':type(error).__name__, 'reason':str(error)}))
        raise SystemExit(2)
