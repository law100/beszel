"""Route explicit Dashboard relogin through the Auth credential form.

No tests, builds, HTTP requests, browser checks, or business-worker restarts.
The existing short-lived flow binds password authentication to the callback.
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
updated=server.read_text()

def replace(old,new):
    global updated
    if updated.count(old)!=1:
        raise RuntimeError('Auth source changed; deployment stopped before writes')
    updated=updated.replace(old,new,1)

replace(
    "import { authContentSecurityPolicy, revokeApplicationLogin, DASHBOARD_SIGNED_OUT_COOKIE } from './dashboard-flow.mjs';",
    "import { authContentSecurityPolicy, revokeApplicationLogin, DASHBOARD_SIGNED_OUT_COOKIE, dashboardReauthBinding } from './dashboard-flow.mjs';")

replace("""  const config=configs.get(id), state=oidc.randomState(), nonce=oidc.randomNonce(), verifier=oidc.randomPKCECodeVerifier();
  const binding=random();
  run('INSERT INTO flows(id,app,payload,expires) VALUES(?,?,?,?)',hash(binding),id,JSON.stringify({state,nonce,verifier,returnTo:localPath(req.query.return)}),now()+900);
  cookie(res,'__Host-law100-flow',binding,900);
  const url=oidc.buildAuthorizationUrl(config,{redirect_uri:`https://${applications[id].host}/_auth/callback`,scope:'openid profile email',code_challenge:await oidc.calculatePKCECodeChallenge(verifier),code_challenge_method:'S256',state,nonce,prompt:'consent'});""",
"""  const config=configs.get(id);
  let binding, data;
  if (id==='dashboard' && req.query.reauth!==undefined) {
    binding=cookies(req)['__Host-law100-flow']||'';
    if (!equal(req.query.reauth,binding)) return res.redirect(303,'/_auth/login');
    const pending=get('SELECT payload FROM flows WHERE id=? AND app=? AND expires>?',hash(binding),id,now());
    data=pending && JSON.parse(pending.payload);
    if (!data?.reauth || !data.reauthenticatedSession) return res.redirect(303,'/_auth/login');
  } else {
    binding=random();
    data={state:oidc.randomState(),nonce:oidc.randomNonce(),verifier:oidc.randomPKCECodeVerifier(),returnTo:localPath(req.query.return)};
    data.reauth=id==='dashboard' && cookies(req)[DASHBOARD_SIGNED_OUT_COOKIE]==='1';
    run('INSERT INTO flows(id,app,payload,expires) VALUES(?,?,?,?)',hash(binding),id,JSON.stringify(data),now()+900);
    cookie(res,'__Host-law100-flow',binding,900);
    if (data.reauth) {
      const after=`https://${applications[id].host}/_auth/login?reauth=${binding}`;
      return res.redirect(303,issuer+'/login?after='+encodeURIComponent(after));
    }
  }
  const url=oidc.buildAuthorizationUrl(config,{redirect_uri:`https://${applications[id].host}/_auth/callback`,scope:'openid profile email',code_challenge:await oidc.calculatePKCECodeChallenge(data.verifier),code_challenge_method:'S256',state:data.state,nonce:data.nonce,prompt:'consent'});""")

replace(
    "    const key=random();\n    run('INSERT INTO app_sessions(id,app,session_id,csrf) VALUES(?,?,?,?)',hash(key),id,s.id,random());",
    "    if (id==='dashboard' && data.reauth && data.reauthenticatedSession!==s.id) return res.status(403).send('请使用刚刚验证的账户重新登录看板。');\n    const key=random();\n    run('INSERT INTO app_sessions(id,app,session_id,csrf) VALUES(?,?,?,?)',hash(key),id,s.id,random());")

replace(
    "const afterPath=(value)=>/^\\/interaction\\/[A-Za-z0-9_-]+$/.test(String(value)) || value==='/verify-email' || value===driveCredentialReturn ? value : accountOrigin+'/';",
    "const afterPath=(value)=>/^\\/interaction\\/[A-Za-z0-9_-]+$/.test(String(value)) || value==='/verify-email' || value===driveCredentialReturn || dashboardReauthBinding(value) ? value : accountOrigin+'/';")

replace(
    "  try { const user=await authenticate(req); const previous=session(req); if(previous) run('DELETE FROM sessions WHERE id=?',previous.id); signIn(req,res,user); res.redirect(303,after); }",
    """  try {
    const binding=dashboardReauthBinding(after);
    const pending=binding && get('SELECT payload FROM flows WHERE id=? AND app=? AND expires>?',hash(binding),'dashboard',now());
    const data=pending && JSON.parse(pending.payload);
    if (binding && (!data?.reauth || data.reauthenticatedSession)) throw new Error('看板登录请求已过期，请重新打开看板。');
    const user=await authenticate(req);
    const previous=session(req);
    if (previous && !binding) run('DELETE FROM sessions WHERE id=?',previous.id);
    const signedIn=signIn(req,res,user);
    if (binding) {
      data.reauthenticatedSession=signedIn.id;
      const result=run('UPDATE flows SET payload=? WHERE id=? AND app=? AND expires>?',JSON.stringify(data),hash(binding),'dashboard',now());
      if (!result.changes) throw new Error('看板登录请求已过期，请重新打开看板。');
    }
    res.redirect(303,after);
  }""")

backup=Path('/root/backups')/time.strftime('dashboard-auth-relogin-%Y%m%d-%H%M%S')
backup.mkdir(mode=0o700)
for path in (server,gate,helper):
    shutil.copy2(path,backup/path.name)

def install(content,path):
    previous=path.stat()
    temporary=path.with_name(path.name+'.relogin-next')
    temporary.write_text(content)
    os.chown(temporary,previous.st_uid,previous.st_gid)
    temporary.chmod(previous.st_mode & 0o777)
    os.replace(temporary,path)

try:
    install((root/'dashboard-flow.next.mjs').read_text(),helper)
    install(updated,server)
    install((root/'auth_gate.next.py').read_text(),gate)
    subprocess.run(['systemctl','restart','law100-auth','law100-dashboard-auth'],check=True)
except Exception:
    for path in (server,gate,helper):
        shutil.copy2(backup/path.name,path)
    subprocess.run(['systemctl','restart','law100-auth','law100-dashboard-auth'],check=False)
    raise

print('Auth relogin redirect deployed. No tests, builds or browser checks run. Backup:',backup)
