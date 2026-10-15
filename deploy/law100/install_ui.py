"""Deploy a locally built frontend without replacing/restarting the Beszel Hub.

Run as root after uploading dist as /opt/law100-dashboard/business-ui.tar.gz.
The existing owner-only auth_request gate is required. No credential is embedded.
"""
import json
from pathlib import Path
import os
import subprocess
import tarfile
import time

root=Path('/opt/law100-dashboard')
public=Path('/var/www/law100-dashboard')
release=public/'releases'/time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
release.mkdir(parents=True,mode=0o755)
release.parent.chmod(0o755)
public.chmod(0o755)
with tarfile.open(root/'business-ui.tar.gz') as archive:
    for member in archive.getmembers():
        p=Path(member.name)
        if p.is_absolute() or '..' in p.parts or not (member.isfile() or member.isdir()):raise ValueError('Unsafe UI archive')
    archive.extractall(release,filter='data')
index=release/'index.html'
html=index.read_text()
assert 'globalThis.BESZEL = "{info}"' in html
html=html.replace('<head>','<head>\n\t\t<base href="/">').replace('./assets/','/_law100-ui/assets/')
html=html.replace('globalThis.BESZEL = "{info}"','globalThis.BESZEL = '+json.dumps({'BASE_PATH':'/','HUB_URL':'https://dashboard.law100.xyz','HUB_VERSION':'0.21.0','OAUTH_DISABLE_POPUP':False}))
index.write_text(html)
release.chmod(0o755)
for p in release.rglob('*'):p.chmod(0o755 if p.is_dir() else 0o644)
temp=root/'ui-next'
if temp.is_symlink():temp.unlink()
temp.symlink_to(release,target_is_directory=True);os.replace(temp,root/'ui-current')
temp=public/'next'
temp.symlink_to(release,target_is_directory=True);os.replace(temp,public/'current')
site=Path('/etc/nginx/sites-available/law100-dashboard-https')
original=site.read_text()
installed='# LAW100 BUSINESS UI BEGIN' in original
auth='''        auth_request /_dashboard_verify;
        error_page 401 = /_dashboard_login;
'''
cache='''        add_header Cache-Control "private, no-store" always;
        add_header X-Content-Type-Options nosniff always;
        add_header Referrer-Policy no-referrer always;
        add_header X-Frame-Options DENY always;
        add_header X-Robots-Tag "noindex, nofollow" always;
'''
static='''        root /var/www/law100-dashboard/current;
        try_files /index.html =503;
'''
block='''    # LAW100 BUSINESS UI BEGIN
    location = /api/law100/overview {
        if ($request_method != GET) { return 405; }
        auth_request /_dashboard_verify;
        proxy_pass http://127.0.0.1:8091/business;
        proxy_set_header Cookie $http_cookie;
        proxy_set_header Authorization "";
        proxy_set_header X-Dashboard-Email "";
        proxy_connect_timeout 2s;
        proxy_read_timeout 6s;
'''+cache+'''    }
    location ^~ /_law100-ui/assets/ {
'''+auth+'''        alias /var/www/law100-dashboard/current/assets/;
'''+cache+'''    }
'''
for route in ['location = /','location = /business',r'location ~ ^/(?:system|settings|containers|monitors|smart|forgot-password|request-otp)(?:/|$)']:
    block+='    '+route+' {\n'+auth+static+cache+'    }\n'
block+='    # LAW100 BUSINESS UI END\n'
if not installed:site.write_text(original.replace('    location / {',block+'    location / {',1))
try:subprocess.run(['nginx','-t'],check=True)
except Exception:
    site.write_text(original)
    raise
subprocess.run(['systemctl','restart','law100-dashboard-auth.service'],check=True)
subprocess.run(['systemctl','reload','nginx'],check=True)
subprocess.run(['systemctl','enable','--now','law100-dashboard-business.timer'],check=True)
print('Custom frontend published:',release.name)
