"""Remember an explicit Dashboard logout without signing out other apps.

Uploads needed: auth_gate.next.py, dashboard-flow.next.mjs. This operation does
not run tests, build the frontend, request web pages, or mutate task records.
"""
from pathlib import Path
import os
import shutil
import subprocess
import time

os.umask(0o077)
root=Path('/opt/law100-dashboard')
auth=Path('/opt/law100-auth')
server=auth/'server.mjs'
gate=root/'auth_gate.py'
helper=auth/'dashboard-flow.mjs'
original=server.read_text()
updated=original
old="import { authContentSecurityPolicy, revokeApplicationLogin } from './dashboard-flow.mjs';"
new="import { authContentSecurityPolicy, revokeApplicationLogin, DASHBOARD_SIGNED_OUT_COOKIE } from './dashboard-flow.mjs';"
if old in updated:updated=updated.replace(old,new,1)
elif new not in updated:raise RuntimeError('Unexpected Auth integration version')
old="    audit(s.user_id,'app-login:'+id);"
new="    if (id==='dashboard') clearCookie(res,DASHBOARD_SIGNED_OUT_COOKIE);\n"+old
if new not in updated:
    if updated.count(old)!=1:raise RuntimeError('Unexpected login callback')
    updated=updated.replace(old,new,1)
old="  revokeApplicationLogin(run,req.application,hash(cookies(req)[appCookie]||''),s.id); clearCookie(res,appCookie);"
new=old+"\n  if (req.application==='dashboard') cookie(res,DASHBOARD_SIGNED_OUT_COOKIE,'1',15*24*3600);"
if new not in updated:
    if updated.count(old)!=1:raise RuntimeError('Unexpected logout handler')
    updated=updated.replace(old,new,1)
backup=Path('/root/backups')/time.strftime('dashboard-logout-marker-%Y%m%d-%H%M%S')
backup.mkdir(mode=0o700)
for p in [server,gate,helper]:shutil.copy2(p,backup/p.name)

def install(text,path):
    stat=path.stat()
    temp=path.with_name(path.name+'.logout-next')
    temp.write_text(text)
    os.chown(temp,stat.st_uid,stat.st_gid);temp.chmod(stat.st_mode & 0o777)
    os.replace(temp,path)

try:
    install((root/'dashboard-flow.next.mjs').read_text(),helper)
    install(updated,server)
    install((root/'auth_gate.next.py').read_text(),gate)
    subprocess.run(['systemctl','restart','law100-auth','law100-dashboard-auth'],check=True)
except Exception:
    for p in [server,gate,helper]:shutil.copy2(backup/p.name,p)
    subprocess.run(['systemctl','restart','law100-auth','law100-dashboard-auth'],check=False)
    raise
print('Logout marker deployed; no tests, builds or browser checks run. Backup:',backup)
