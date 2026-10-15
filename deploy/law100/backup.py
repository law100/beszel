"""Private, online-consistent Beszel backups with bounded retention.

No business data, cloud credentials, unrelated Auth DB or other Docker volumes
are included. SQLite databases are copied with the online backup API, not cp.
"""
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
from zoneinfo import ZoneInfo

ROOT=Path('/opt/law100-dashboard')
BACKUPS=Path('/var/backups/law100-dashboard')
PATTERN=re.compile(r'^beszel-(\d{8}T\d{6}Z)-([0-9a-f]{8})\.tar\.gz$')
LIMIT=512*1024*1024

def run(args):return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT).strip()
def checksum(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):h.update(data)
    return h.hexdigest()

def protected_dir(path):
    if path.is_symlink():raise RuntimeError('Backup directory must not be a symlink')
    path.mkdir(mode=0o700,parents=True,exist_ok=True);path.chmod(0o700)

def safe_member(name):
    p=Path(name)
    return bool(name) and not p.is_absolute() and '..' not in p.parts

def validate_archive(path):
    """Restore archive to a temporary directory, checking checksums and SQLite.

    Never restores over a running Hub or modifies its database.
    """
    if path.is_symlink() or path.parent.resolve()!=BACKUPS.resolve() or not PATTERN.fullmatch(path.name):
        raise RuntimeError('Snapshot must be a regular managed archive in the backup directory')
    with tempfile.TemporaryDirectory(prefix='.restore-check-',dir=BACKUPS) as tmp:
        target=Path(tmp)
        with tarfile.open(path,'r:gz') as archive:
            members=archive.getmembers()
            if sum(m.size for m in members)>LIMIT:raise RuntimeError('Snapshot exceeds uncompressed validation limit')
            for m in members:
                if not m.isfile() or not safe_member(m.name):raise RuntimeError('Invalid archive member')
                out=target/m.name;out.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                with archive.extractfile(m) as src, out.open('xb') as dest:shutil.copyfileobj(src,dest)
                out.chmod(0o600)
        manifest=json.loads((target/'manifest.json').read_text())
        for name,expected in manifest['sha256'].items():
            if not safe_member(name) or checksum(target/name)!=expected:raise RuntimeError('Snapshot integrity check failed')
        counts={}
        for name in ['data.db','auxiliary.db']:
            db=sqlite3.connect('file:'+str(target/'data'/name)+'?mode=ro',uri=True)
            try:
                assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
                if name=='data.db':
                    for table in ['systems','network_monitors','alerts','users']:
                        counts[table]=db.execute('SELECT count(*) FROM '+table).fetchone()[0]
            finally:db.close()
        return {'snapshot':path.name,'sqlite':'ok','checksum':'ok','recordCounts':counts}

def retained(names):
    """Newest snapshot in each of seven days and four ISO weeks."""
    names=sorted(names,reverse=True)
    keep=set();days=set();weeks=set()
    for name in names:
        stamp=PATTERN.fullmatch(name).group(1)
        date=datetime.datetime.strptime(stamp,'%Y%m%dT%H%M%SZ').replace(tzinfo=datetime.timezone.utc).astimezone(ZoneInfo('Asia/Shanghai'))
        day=date.date()
        if day not in days and len(days)<7:
            days.add(day);keep.add(name)
        week=date.isocalendar()[:2]
        if week not in weeks and len(weeks)<4:
            weeks.add(week);keep.add(name)
    return keep

def backup():
    protected_dir(BACKUPS)
    if shutil.disk_usage(BACKUPS).free<512*1024*1024:raise RuntimeError('At least 512 MiB free required for safe backup')
    # One backup at a time; lock contains no credentials.
    with (BACKUPS/'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        before=run(['docker','inspect','--format','{{.Id}} {{.State.StartedAt}}','law100-beszel'])
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        import secrets
        name=f'beszel-{stamp}-{secrets.token_hex(4)}.tar.gz'
        partial=BACKUPS/('.'+name+'.partial');output=BACKUPS/name
        try:
            with tempfile.TemporaryDirectory(prefix='.snapshot-',dir=BACKUPS) as tmp:
                stage=Path(tmp);(stage/'data').mkdir(mode=0o700)
                for name_db in ['data.db','auxiliary.db']:
                    src=sqlite3.connect('file:'+str(ROOT/'data'/name_db)+'?mode=ro',uri=True,timeout=15)
                    dest=sqlite3.connect(stage/'data'/name_db)
                    try:
                        src.backup(dest,pages=128,sleep=.05)
                        assert dest.execute('PRAGMA quick_check').fetchone()[0]=='ok'
                    finally:dest.close();src.close()
                pairs=[(ROOT/'data/id_ed25519','data/id_ed25519'),
                       (ROOT/'images.json','deployment/images.json'),
                       (ROOT/'system.json','deployment/system.json'),
                       (ROOT/'recovery.json','deployment/recovery.json')]
                for parent,prefix in [(Path('/etc/law100-dashboard'),'config'),
                                      (ROOT,'deployment')]:
                    for p in parent.iterdir():
                        if p.is_file() and not p.is_symlink() and (
                            parent.name=='law100-dashboard' and parent!=ROOT or
                            p.suffix in ('.py','.md') or p.name in ('p0-config.json','p1-config.json')):
                            pairs.append((p,prefix+'/'+p.name))
                pairs.extend((Path('/etc/systemd/system')/name,'systemd/'+name) for name in [
                    'law100-beszel-agent.service','law100-dashboard-auth.service',
                    'law100-dashboard-business.service','law100-dashboard-business.timer',
                    'law100-dashboard-cert-renew.service','law100-dashboard-cert-renew.timer',
                    'law100-dashboard-backup.service','law100-dashboard-backup.timer'])
                drop=Path('/etc/systemd/system/law100-beszel-agent.service.d')
                if drop.exists():pairs.extend((p,'systemd/agent.service.d/'+p.name) for p in drop.glob('*.conf'))
                pairs.extend((Path('/etc/nginx/sites-available')/name,'nginx/'+name) for name in ['law100-dashboard-http','law100-dashboard-https'])
                ui=ROOT/'ui-current'
                if ui.exists():
                    pairs.extend((p,'ui/'+str(p.relative_to(ui))) for p in ui.rglob('*') if p.is_file())
                for source,name_out in pairs:
                    if not source.exists():continue
                    out=stage/name_out;out.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                    shutil.copyfile(source,out);out.chmod(0o600)
                # Keep the exact known-good Agent executable for rollback.
                agent=stage/'bin/beszel-agent';agent.parent.mkdir(mode=0o700)
                shutil.copyfile(ROOT/'bin/beszel-agent',agent)
                files=[p for p in stage.rglob('*') if p.is_file()]
                if sum(p.stat().st_size for p in files)>LIMIT:raise RuntimeError('Snapshot staging exceeds backup budget')
                manifest={'format':1,'createdUtc':stamp,'hubContainer':before,
                          'sha256':{str(p.relative_to(stage)):checksum(p) for p in files}}
                (stage/'manifest.json').write_text(json.dumps(manifest,indent=2))
                with tarfile.open(partial,'w:gz',compresslevel=3) as archive:
                    for p in sorted(stage.rglob('*')):
                        if p.is_file():archive.add(p,arcname=str(p.relative_to(stage)),recursive=False)
                partial.chmod(0o600);os.replace(partial,output)
            checked=validate_archive(output)
            after=run(['docker','inspect','--format','{{.Id}} {{.State.StartedAt}}','law100-beszel'])
            assert before==after,'Hub changed during backup'
            managed=[p for p in BACKUPS.iterdir() if p.is_file() and not p.is_symlink() and PATTERN.fullmatch(p.name)]
            keep=retained([p.name for p in managed]);removed=[]
            for p in managed:
                # Only known backup filenames under the resolved fixed backup directory.
                if p.name not in keep and p.parent.resolve()==BACKUPS.resolve():
                    p.unlink();removed.append(p.name)
            size=sum(p.stat().st_size for p in BACKUPS.iterdir() if p.is_file() and PATTERN.fullmatch(p.name))
            if size>LIMIT:raise RuntimeError('Retained snapshots exceed 512 MiB budget; manual review required')
            status={**checked,'bytes':output.stat().st_size,'retainedBytes':size,'expiredSnapshotsRemoved':len(removed),
                    'createdUtc':stamp,'liveHubUnchanged':True}
            (BACKUPS/'last-success.json').write_text(json.dumps(status,indent=2))
            (BACKUPS/'last-success.json').chmod(0o600)
            print(json.dumps(status,indent=2))
        except Exception:
            if partial.exists() and partial.parent.resolve()==BACKUPS.resolve():partial.unlink()
            raise

if __name__=='__main__':
    os.umask(0o077)
    p=argparse.ArgumentParser();p.add_argument('--check',type=Path)
    args=p.parse_args()
    if args.check:print(json.dumps(validate_archive(args.check),indent=2))
    else:backup()
