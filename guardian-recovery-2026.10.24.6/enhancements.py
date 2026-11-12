"""Reviewed native-start coordination and opt-in sqlippool upgrade."""
import base64,fcntl,hashlib,json,os,shutil,subprocess,tempfile,time,platform
from pathlib import Path
HERE=Path(__file__).resolve().parent
LIB=Path('/usr/local/lib/mkauth-guardian-recovery')
INIT=Path('/etc/init.d/mysql');CRON=Path('/etc/cron.d/mysql')
GLOBAL_LOCK='/var/run/mkauth-guardian-global-recovery.lock'
STATE=Path('/var/lib/mkauth-guardian-recovery/state.json')
NATIVE=Path('/opt/mk-auth/scripts/mysql.php')
MODULE=Path('/usr/lib/freeradius/rlm_sqlippool.so')
MYSQL_MODULE=Path('/usr/lib/freeradius/rlm_sql_mysql.so')
OLD_MODULE='e7d3e1c0bd902b8433e96c9e53a0070ac4b76fd499ceec1742bdc38b0a52d342'
NEW_MODULE='03b654562cd34cbc51381a8e435c51676d41a33f1e2acb24b837b9d32a2d4fba'
INIT_OLD='333b7444d847fabea63f823458be726ae754e1e0cc0fac6b77c75692bd4070be'
INIT_NEW='c7da8e0ba579dcd127992bb9d32df77f0247f20d86a9c4ba04bbf29f25f821b9'
CRON_OLD='e39bcef084b86b65b23264f64dd0afd901f2d1449b9009f1a2d7c4ad4d33a9d3'
def digest(data):return hashlib.sha256(data).hexdigest()
def reviewed_file(path):
    if path.is_symlink() or not path.is_file():raise RuntimeError('Missing or symlink reviewed file: '+str(path))
    st=path.stat()
    if st.st_uid!=0 or st.st_mode&0o022:raise RuntimeError('Unsafe ownership/mode: '+str(path))
    return path.read_bytes()
def native_contents(original_init,original_cron):
    needle=b"  'start')\n  sanity_checks;"
    inject=b"  'start')\n  if [ \"${MKAUTH_START_GATE_ACTIVE:-}\" != 1 ]; then\n    exec /usr/bin/python3 /usr/local/lib/mkauth-guardian-recovery/mariadb_coordination.py start\n  fi\n  sanity_checks;"
    original=b'/opt/mk-auth/scripts/mysql.php'
    wrapper=b'/usr/bin/python3 /usr/local/lib/mkauth-guardian-recovery/mariadb_coordination.py native'
    if original_init.count(needle)!=1 or original_cron.count(original)!=1:raise RuntimeError('Unreviewed native routing')
    return original_init.replace(needle,inject),original_cron.replace(original,wrapper)
def review_native():
    a=reviewed_file(INIT);b=reviewed_file(CRON);helper=LIB/'mariadb_coordination.py';payload=(HERE/'mariadb_coordination.py').read_bytes()
    compile(payload,str(helper),'exec')
    patched_cron=b'# SISTEMA MK-AUTH\n\n# CONTROLE DO BD\n*/15 *\t* * *\troot\t/usr/bin/python3 /usr/local/lib/mkauth-guardian-recovery/mariadb_coordination.py native\n'
    if digest(a)==INIT_NEW and digest(b) in {digest(patched_cron),digest(b'#'+patched_cron)}:
        if reviewed_file(helper)!=payload:raise RuntimeError('Coordination helper differs; review required')
        return {'changed':False,'files':{}}
    if digest(a)!=INIT_OLD or digest(b) not in {CRON_OLD,'d60e6c63df4da38eb4be62d5ebe0091c00f63002f235cef18718b4913e693f4c'}:raise RuntimeError('Native init/cron variant not reviewed; no automatic patch')
    reviewed_file(NATIVE)
    if helper.exists() or helper.is_symlink():raise RuntimeError('Unexpected pre-existing coordination helper')
    aa,bb=native_contents(a,b)
    return {'changed':True,'files':{str(INIT):(aa,INIT.stat().st_mode&0o777),str(CRON):(bb,CRON.stat().st_mode&0o777),str(helper):(payload,0o600)},'base':{str(INIT):digest(a),str(CRON):digest(b)}}
def review_module():
    data=reviewed_file(MODULE);sha=digest(data)
    if sha not in (OLD_MODULE,NEW_MODULE):raise RuntimeError('Unreviewed sqlippool binary; automatic replacement refused')
    if platform.machine()!='x86_64':raise RuntimeError('sqlippool candidate requires reviewed x86_64 architecture')
    for package,version in [('freeradius','3.0.17+dfsg-1.1'),('freeradius-mysql','3.0.17+dfsg-1.1'),('libmariadb3','1:10.3.27-0+deb10u1')]:
        actual=subprocess.check_output(['dpkg-query','-W','-f=${Version}',package],timeout=3).decode()
        if actual!=version:raise RuntimeError('Unreviewed package version: '+package)
    if digest(reviewed_file(MYSQL_MODULE))!='e385364d1e3fe682c1489b1e4ceacef1e3a321eaeb1f4abb3016a05c079b3a1a':raise RuntimeError('Unreviewed MySQL driver binary')
    blob=base64.b64decode((HERE/'sqlippool-candidate.b64').read_bytes(),validate=False)
    if digest(blob)!=NEW_MODULE:raise RuntimeError('Candidate checksum mismatch')
    if sha==NEW_MODULE:
        from guardian_controller import Production
        record=Production().identity('radius')
        if not record:raise RuntimeError('RADIUS absent; recover services before binary installation')
        inode=str(MODULE.stat().st_ino)
        maps=Path('/proc/{}/maps'.format(record['pid'])).read_text()
        if not any(str(MODULE) in row and row.split()[4]==inode and '(deleted)' not in row for row in maps.splitlines()):raise RuntimeError('Patched file not loaded; manual review required')
    return {'changed':sha==OLD_MODULE,'binary':blob}
def review(native,module):
    plan={'native':review_native() if native else None,'module':review_module() if module else None}
    print(json.dumps({'enhancements_preflight':True,'native_coordination_change':bool(plan['native'] and plan['native']['changed']),'sqlippool_change':bool(plan['module'] and plan['module']['changed']),'radius_restart_required':bool(plan['module'] and plan['module']['changed'])}),flush=True)
    return plan
def native_running():
    for p in Path('/proc').glob('[0-9]*'):
        try:
            if b'/opt/mk-auth/scripts/mysql.php' in p.joinpath('cmdline').read_bytes().split(b'\0'):return True
        except OSError:pass
    return False
def replace(path,data,mode):
    target=Path(path);temp=target.with_name(target.name+'.guardian-coordination-tmp')
    with temp.open('wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    temp.chmod(mode);os.replace(str(temp),str(target))
def apply_native(plan,backup):
    if not plan['changed']:return
    records=[]
    for path,(data,mode) in plan['files'].items():
        p=Path(path)
        if p.is_symlink():raise RuntimeError('Symlink at apply')
        if path in plan['base'] and digest(p.read_bytes())!=plan['base'][path]:raise RuntimeError('Native source changed since review')
        records.append({'path':path,'exists':p.exists(),'mode':p.stat().st_mode&0o777 if p.exists() else mode,'uid':p.stat().st_uid if p.exists() else 0,'gid':p.stat().st_gid if p.exists() else 0})
        if p.exists():shutil.copy2(str(p),str(backup/str(len(records))))
    (backup/'manifest.json').write_text(json.dumps(records,indent=2),encoding='utf-8');(backup/'manifest.json').chmod(0o600)
    changed=[]
    try:
        # Helper first: a new cron/init route must never reference a missing helper.
        order=sorted(plan['files'],key=lambda p:0 if p.endswith('mariadb_coordination.py') else 1)
        for path in order:
            data,mode=plan['files'][path];replace(path,data,mode);changed.append(path)
    except Exception:
        for index,r in enumerate(records,1):
            if r['path'] not in changed:continue
            if r['exists']:
                replace(r['path'],(backup/str(index)).read_bytes(),r['mode']);os.chown(r['path'],r['uid'],r['gid'])
            else:Path(r['path']).unlink()
        raise
    print(json.dumps({'native_coordination_applied':True,'backup':str(backup),'services_restarted':False}),flush=True)
def apply(plan):
    restart=False
    if plan['native'] and plan['native']['changed']:
        with open(GLOBAL_LOCK,'a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            state=json.loads(STATE.read_text()) if STATE.exists() else {}
            if state.get('recovery',{}).get('phase') not in (None,'done') or native_running():raise RuntimeError('Recovery/native check active; retry without removing locks')
            fresh=review_native()
            root=Path(tempfile.mkdtemp(prefix='mkauth-native-coordination-',dir='/root'));root.chmod(0o700)
            apply_native(fresh,root)
    if plan['module'] and plan['module']['changed']:
        fresh=review_module()
        if fresh['changed']:
            root=Path(tempfile.mkdtemp(prefix='mkauth-sqlippool-upgrade-',dir='/root'));root.chmod(0o700)
            candidate=root/'candidate.so';candidate.write_bytes(fresh['binary']);candidate.chmod(0o600)
            shutil.copy2(str(HERE/'sqlippool_upgrade.py'),str(root/'apply.py'))
            # This subprocess owns the global lock through the entire module operation.
            result=subprocess.run([os.sys.executable,str(root/'apply.py'),str(root)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=360)
            for row in result.stdout.splitlines():
                try:record=json.loads(row)
                except ValueError:continue
                print(json.dumps(record),flush=True)
            if result.returncode:raise RuntimeError('sqlippool phase failed; see private deployment logs in '+str(root))
            restart=True
    return restart
