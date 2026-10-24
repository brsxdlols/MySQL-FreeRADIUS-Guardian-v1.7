"""Validated native-layout backup, without invoking the vendor upgrade pipeline."""
import datetime
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import re
import secrets
import shutil
import sqlite3
import subprocess
import tarfile
import uuid
import stat
from guardian_safety import atomic_bytes,mysql_read,validate_maz

ROOT=Path('/var/lib/mkauth-guardian-recovery')
BACKUPS=Path('/opt/mk-auth/bckp')
INDEX=Path('/opt/mk-auth/dados/backup.db')

def discover_template():
    for candidate in sorted(BACKUPS.glob('*.maz'),key=lambda p:p.stat().st_mtime,reverse=True):
        if candidate.is_symlink() or not candidate.is_file():continue
        checked=validate_maz(candidate)
        if checked['classification']=='rejected':continue
        with tarfile.open(str(candidate),'r:bz2') as archive:
            members=archive.getmembers();script=next((m for m in members if m.name=='opt/mk-auth/bckp/tarbackup.sql'),None)
            if not script or script.size>65536:continue
            content=archive.extractfile(script).read().decode('ascii')
            sources=re.findall(r'^source /opt/mk-auth/dados/([A-Za-z0-9_-]{1,64})/([A-Za-z0-9_]+)\.sql;\s*$',content,re.M)
            if len(sources)<4 or len({x[0] for x in sources})!=1:continue
            tables=[x[1] for x in sources]
            if not {'radacct','radippool','sis_cliente','sis_provedor'}.issubset(tables) or len(tables)!=len(set(tables)):continue
            extras=[]
            for member in members:
                if not member.isfile() or member.name.endswith('.sql'):continue
                path=PurePosixPath(member.name)
                if '..' in path.parts or path.is_absolute() or not (member.name.startswith('opt/mk-auth/dados/') or member.name.startswith('opt/mk-auth/etc/')):raise RuntimeError('Native template contains unsupported paths')
                if len(path.parts)!=4:raise RuntimeError('Native template has unexpected nested metadata')
                extras.append(member.name)
            present={row.split('\t')[0] for row in mysql_read("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA='mkradius' AND TABLE_TYPE='BASE TABLE';").splitlines()}
            if not set(tables).issubset(present):raise RuntimeError('Native backup template references missing tables')
            info=candidate.stat()
            return {'template_file':candidate.name,'template_sha256':checked['sha256'],'tables':tables,'metadata':extras,'layout':'native_sources_per_table_v1','file_mode':stat.S_IMODE(info.st_mode)&0o666,'file_uid':info.st_uid,'file_gid':info.st_gid}
    raise RuntimeError('No structurally validated native .maz template; cannot infer compatibility safely')

def split_dump(source,folder,tables):
    expected=set(tables);found=set();header=bytearray();footer=bytearray();current=None;handle=None;in_footer=False
    try:
        with source.open('rb') as stream:
            for line in stream:
                match=re.match(rb'^-- Table structure for table `([A-Za-z0-9_]+)`\s*$',line)
                if match:
                    if handle:handle.close()
                    current=match[1].decode()
                    if current not in expected or current in found:raise RuntimeError('Unexpected/duplicate table in dump')
                    found.add(current);handle=(folder/(current+'.sql')).open('wb');os.chmod(str(folder/(current+'.sql')),0o600)
                    handle.write(header);handle.write(line);continue
                if current is None:header.extend(line);continue
                if len(found)==len(expected) and re.match(rb'^/\*![0-9]+ SET [A-Z_]+=@OLD_',line):in_footer=True
                if in_footer:footer.extend(line)
                else:handle.write(line)
        if handle:handle.close();handle=None
        if found!=expected or b'Dump completed' not in footer:raise RuntimeError('Dump incomplete: tables or final completion missing')
        for table in tables:
            with (folder/(table+'.sql')).open('ab') as stream:stream.write(footer)
    finally:
        if handle:handle.close()

def add_metadata(archive,copy,name,source_info):
    # Private snapshot permissions are not the permissions to restore.
    # Blank names make the original numeric uid/gid authoritative.
    header=archive.gettarinfo(str(copy),arcname=name)
    header.mode=stat.S_IMODE(source_info.st_mode)
    header.uid=source_info.st_uid;header.gid=source_info.st_gid
    header.uname='';header.gname='';header.mtime=source_info.st_mtime
    with copy.open('rb') as stream:archive.addfile(header,stream)

def generate(private):
    blueprint=json.loads((ROOT/'native-template.json').read_text())
    tables=blueprint['tables']
    if not all(re.fullmatch(r'[A-Za-z0-9_]+',table) for table in tables):raise RuntimeError('Unsafe template table')
    work=private/'compatible';work.mkdir(mode=0o700)
    cnf=next((str(p) for p in [Path('/etc/mysql/debian.cnf'),Path('/root/.my.cnf')] if p.is_file()),None)
    if not cnf:raise RuntimeError('No local MySQL defaults file')
    dump=work/'complete.sql';stderr=work/'mysqldump.log'
    with dump.open('wb') as output,stderr.open('wb') as errors:
        os.chmod(str(dump),0o600);os.chmod(str(stderr),0o600)
        # One MVCC transaction across the selected tables, no global read lock or DDL.
        result=subprocess.run(['mysqldump','--defaults-file='+cnf,'--single-transaction','--quick','--skip-lock-tables','--hex-blob','--max-allowed-packet=64M','mkradius']+tables,stdout=output,stderr=errors,close_fds=True)
    if result.returncode:raise RuntimeError('mysqldump failed; no artifact published; inspect private stderr')
    sql=work/'sql';sql.mkdir(mode=0o700);split_dump(dump,sql,tables)
    identifier=secrets.token_hex(8).upper()
    script=work/'tarbackup.sql'
    script.write_text('-- SISTEMA MK-AUTH\n'+''.join('source /opt/mk-auth/dados/'+identifier+'/'+table+'.sql;\n' for table in tables))
    metadata=work/'metadata';metadata.mkdir(mode=0o700)
    copies=[]
    for number,name in enumerate(blueprint['metadata']):
        original=Path('/')/name
        if original.is_symlink() or not original.is_file():raise RuntimeError('Native metadata missing or symlink: '+name)
        source_info=original.stat()
        copy=metadata/str(number)
        with original.open('rb') as stream:sqlite_header=stream.read(16)==b'SQLite format 3\x00'
        if sqlite_header:
            source=sqlite3.connect('file:'+str(original)+'?mode=ro',uri=True,timeout=5);target=sqlite3.connect(str(copy))
            try:
                source.backup(target)
                if target.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise RuntimeError('Metadata SQLite quick_check failed')
            finally:target.close();source.close()
        else:shutil.copyfile(str(original),str(copy))
        os.chmod(str(copy),0o600);copies.append((copy,name,source_info))
    stage=BACKUPS/'.guardian-staging';stage.mkdir(mode=0o700,exist_ok=True);os.chmod(str(stage),0o700)
    partial=stage/(identifier+'.maz.part')
    with tarfile.open(str(partial),'w:bz2',compresslevel=1) as archive:
        archive.add(str(script),arcname='opt/mk-auth/bckp/tarbackup.sql',recursive=False)
        for table in tables:archive.add(str(sql/(table+'.sql')),arcname='opt/mk-auth/dados/'+identifier+'/'+table+'.sql',recursive=False)
        for copy,name,source_info in copies:add_metadata(archive,copy,name,source_info)
    os.chmod(str(partial),0o600)
    checked=validate_maz(partial)
    if checked['classification']=='rejected':raise RuntimeError('Generated archive rejected; nothing published')
    # Match the known native artifact's read access only after full validation.
    os.chmod(str(partial),blueprint['file_mode'])
    os.chown(str(partial),blueprint['file_uid'],blueprint['file_gid'])
    db=sqlite3.connect(str(INDEX),timeout=5)
    try:
        if [r[1] for r in db.execute('PRAGMA table_info(backup)')]!=['uuid','data','descricao','arquivo','tipo']:raise RuntimeError('Unsupported native index schema')
        snapshot=sqlite3.connect(str(work/'backup-index-before.db'));db.backup(snapshot);snapshot.close();os.chmod(str(work/'backup-index-before.db'),0o600)
        final=BACKUPS/(identifier+'.maz')
        if final.exists():raise RuntimeError('Identifier collision')
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT INTO backup(uuid,data,descricao,arquivo,tipo) VALUES(?,?,?,?,?)',(str(uuid.uuid4()),datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),'backup automatico',identifier,'maz'))
        os.rename(str(partial),str(final))
        try:db.commit()
        except Exception:os.rename(str(final),str(partial));raise
    finally:db.close()
    checked.update(file=final.name,generator='guardian_compatible_single_transaction',tables=len(tables),metadata_files=len(copies),native_ui_restore_tested=False)
    atomic_bytes(private/'compatible-validation.json',json.dumps(checked,indent=2).encode())
    return checked
