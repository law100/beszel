"""Nginx auth_request gate. No credentials, cookies or query strings are logged."""
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import urllib.request
import urllib.error

CONFIG = json.loads(Path('/etc/law100-dashboard/gate.json').read_text())

def authorized_identity(cookie_header):
    jar = SimpleCookie()
    try:
        jar.load(cookie_header)
    except CookieError:
        return 401, None
    cookie = jar.get('__Host-law100-app')
    if not cookie or len(cookie.value) > 256:
        return 401, None
    req = urllib.request.Request('http://127.0.0.1:3090/internal/session',
        data=json.dumps({'app':'dashboard','token':cookie.value}).encode(),
        headers={'Content-Type':'application/json','X-Auth-Bridge':CONFIG['bridge']})
    try:
        with urllib.request.urlopen(req, timeout=4) as response:
            identity = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return 503, None
    if not identity.get('authenticated'):
        return 401, None
    if identity.get('userId') != CONFIG['owner'] or identity.get('role') != 'super_admin':
        return 403, None
    # Only the stable configured owner email is forwarded, never browser headers.
    return 204, CONFIG['email']

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ('/verify','/business'):
            self.send_error(404)
            return
        status, email = authorized_identity(self.headers.get('Cookie',''))
        if self.path == '/business':
            if status != 204:
                self.send_response(status)
                self.send_header('Cache-Control','private, no-store')
                self.send_header('Content-Length','0')
                self.end_headers()
                return
            try:
                path=Path('/var/lib/law100-dashboard-business/overview.json')
                if path.stat().st_size > 1024*1024:raise ValueError('Invalid overview')
                payload=path.read_bytes()
                value=json.loads(payload)
                if value.get('version') != 1:raise ValueError('Invalid overview')
            except (OSError,ValueError,AttributeError):
                self.send_response(503)
                self.send_header('Cache-Control','private, no-store')
                self.send_header('Content-Length','0')
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','private, no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Length',str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(status)
        if email:
            self.send_header('X-Dashboard-Email', email)
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length','0')
        self.end_headers()
    def do_POST(self):
        self.send_response(405)
        self.send_header('Allow','GET')
        self.send_header('Content-Length','0')
        self.end_headers()
    def log_message(self, *args):
        pass

if __name__ == '__main__':
    ThreadingHTTPServer(('127.0.0.1',8091),Handler).serve_forever()
