"""Scoped Dashboard SSO repair. Run on the existing configured server as root.

Upload auth_gate.next.py and dashboard-flow.next.mjs to the Dashboard directory
first. No secrets or session tokens are emitted; SQLite backup stays root-only.
"""
from pathlib import Path
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time

os.umask(0o077)
root=Path('/opt/law100-dashboard')
auth=Path('/opt/law100-auth')
site=Path('/etc/nginx/sites-available/law100-dashboard-https')
server=auth/'server.mjs'
gate=root/'auth_gate.py'
node=Path('/opt/node-v24.21.0-linux-x64/bin/node')
original=server.read_text()
updated=original
if "from './dashboard-flow.mjs'" not in updated:
    anchor="import { AvatarError, normalizeAvatar, saveAvatar, removeAvatar, serveAvatar, avatarUrl } from './avatars.mjs';"
    assert updated.count(anchor)==1
    updated=updated.replace(anchor,anchor+"\nimport { authContentSecurityPolicy, revokeApplicationLogin } from './dashboard-flow.mjs';")
    old=re.search(r"'Content-Security-Policy':\"[^\"]+\"",updated)
    assert old and 'form-action' in old.group(0)
    updated=updated.replace(old.group(0),"'Content-Security-Policy':authContentSecurityPolicy(applications,issuer)",1)
    old="run('DELETE FROM sessions WHERE id=?',s.id); clearCookie(res,appCookie);"
    assert updated.count(old)==1
    updated=updated.replace(old,"revokeApplicationLogin(run,req.application,hash(cookies(req)[appCookie]||''),s.id); clearCookie(res,appCookie);")
assert 'revokeApplicationLogin(run,req.application' in updated
nginx_before=site.read_text()
nginx_after=nginx_before
old='''    location = /_dashboard_login {
        internal;
        return 302 /_auth/login;
    }'''
new='''    location = /_dashboard_login {
        internal;
        proxy_pass http://127.0.0.1:8091/login;
        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Original-URI $request_uri;
        proxy_connect_timeout 2s;
        proxy_read_timeout 6s;
    }'''
if old in nginx_after:
    assert nginx_after.count(old)==1
    nginx_after=nginx_after.replace(old,new)
else:assert new in nginx_after
if 'location = /_auth/signed-out' not in nginx_after:
    anchor='    location ^~ /_auth/ {'
    assert nginx_after.count(anchor)==1
    nginx_after=nginx_after.replace(anchor,'''    location = /_auth/signed-out {
        proxy_pass http://127.0.0.1:8091/signed-out;
        proxy_set_header Cookie "";
        proxy_read_timeout 6s;
    }
'''+anchor)
compile((root/'auth_gate.next.py').read_text(),'auth_gate.py','exec')
stage=root/'auth-server.next.mjs';stage.write_text(updated)
for p in [stage,root/'dashboard-flow.next.mjs']:subprocess.run([str(node),'--check',str(p)],check=True)
backup=Path('/root/backups')/time.strftime('dashboard-auth-flow-%Y%m%d-%H%M%S')
backup.mkdir(mode=0o700)
paths=[server,gate,site,auth/'dashboard-flow.mjs']
existed={str(p):p.exists() for p in paths}
for p in paths:
    if p.exists():shutil.copy2(p,backup/p.name)
with sqlite3.connect('file:/var/lib/law100-auth/accounts.sqlite?mode=ro',uri=True) as src,sqlite3.connect(backup/'auth-before.sqlite') as dest:src.backup(dest)
units=['law100-resource-migration','law100-resource','law100-resource-shares','law100-drive-app','law100-unicom-auth','law100-beszel-agent']
before={u:subprocess.check_output(['systemctl','show',u,'-p','MainPID','-p','ExecMainStartTimestampMonotonic'],text=True) for u in units}
before['hub']=subprocess.check_output(['docker','inspect','--format','{{.Id}} {{.State.StartedAt}}','law100-beszel'],text=True)
(backup/'baseline.json').write_text(json.dumps(before))
(backup/'ui-path.txt').write_text(str((root/'ui-current').resolve()))

def install(content,target,metadata):
    temp=target.with_name(target.name+'.sso-next')
    temp.write_text(content)
    stat=metadata.stat();os.chown(temp,stat.st_uid,stat.st_gid);temp.chmod(stat.st_mode & 0o777)
    os.replace(temp,target)

try:
    install(updated,server,server)
    install((root/'dashboard-flow.next.mjs').read_text(),auth/'dashboard-flow.mjs',server)
    install((root/'auth_gate.next.py').read_text(),gate,gate)
    install(nginx_after,site,site)
    subprocess.run(['nginx','-t'],check=True)
    subprocess.run(['systemctl','restart','law100-auth'],check=True)
    subprocess.run(['systemctl','restart','law100-dashboard-auth'],check=True)
    subprocess.run(['systemctl','reload','nginx'],check=True)
    subprocess.run(['systemctl','is-active','law100-auth','law100-dashboard-auth'],check=True)
except Exception:
    for p in paths:
        if existed[str(p)]:shutil.copy2(backup/p.name,p)
    subprocess.run(['systemctl','restart','law100-auth','law100-dashboard-auth'],check=False)
    subprocess.run(['nginx','-t'],check=False)
    subprocess.run(['systemctl','reload','nginx'],check=False)
    raise
for u in units:
    assert before[u]==subprocess.check_output(['systemctl','show',u,'-p','MainPID','-p','ExecMainStartTimestampMonotonic'],text=True),u+' unexpectedly changed'
assert before['hub']==subprocess.check_output(['docker','inspect','--format','{{.Id}} {{.State.StartedAt}}','law100-beszel'],text=True)
(root/'auth-flow-backup-path').write_text(str(backup))
print(json.dumps({'deployed':True,'businessServicesUnchanged':True,'backup':str(backup)}))
