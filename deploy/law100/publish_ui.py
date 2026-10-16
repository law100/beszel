"""Publish a frontend-only release using the installed runtime configuration."""
import json
import os
from pathlib import Path
import re
import tarfile
import time

root=Path('/opt/law100-dashboard')
public=Path('/var/www/law100-dashboard')
previous=(public/'current').resolve(strict=True)
installed=(previous/'index.html').read_text()
match=re.search(r'globalThis\.BESZEL\s*=\s*(\{[^\n]*?\})',installed)
if not match:
    raise RuntimeError('Installed frontend configuration missing')
runtime=json.loads(match.group(1))

release=public/'releases'/time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())
release.mkdir(mode=0o755)
with tarfile.open(root/'business-ui.tar.gz') as archive:
    for member in archive.getmembers():
        path=Path(member.name)
        if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
            raise ValueError('Unsafe UI archive')
    archive.extractall(release,filter='data')

index=release/'index.html'
html=index.read_text()
placeholder='globalThis.BESZEL = "{info}"'
if html.count(placeholder)!=1:
    raise RuntimeError('Frontend runtime placeholder missing')
html=html.replace('<head>','<head>\n\t\t<base href="/">').replace('./assets/','/_law100-ui/assets/')
index.write_text(html.replace(placeholder,'globalThis.BESZEL = '+json.dumps(runtime)))
release.chmod(0o755)
for path in release.rglob('*'):
    path.chmod(0o755 if path.is_dir() else 0o644)

stamp=time.strftime('%Y%m%d-%H%M%S')
backup=Path('/root/backups')/('dashboard-ui-'+stamp)
backup.mkdir(mode=0o700)
(backup/'previous-release.txt').write_text(str(previous)+'\n')

def point(link,target):
    temporary=link.with_name(link.name+'.publish-'+stamp)
    temporary.symlink_to(target,target_is_directory=True)
    os.replace(temporary,link)

try:
    point(root/'ui-current',release)
    point(public/'current',release)
except Exception:
    point(root/'ui-current',previous)
    point(public/'current',previous)
    raise

print('Frontend published:',release.name)
print('Previous release preserved:',previous.name)
