"""Nginx auth_request gate. No credentials, cookies or query strings are logged."""
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import urllib.request
import urllib.error
import urllib.parse
import re
import secrets

CONFIG = json.loads(Path('/etc/law100-dashboard/gate.json').read_text())

def login_location(value):
    if not isinstance(value,str) or len(value)>2048 or re.search(r'[\x00-\x1f\x7f\\]',value):value='/'
    parts=urllib.parse.urlsplit(value)
    if parts.scheme or parts.netloc or not re.fullmatch(r'/(?:business/?|containers/?|smart/?|monitors/?|settings(?:/[A-Za-z0-9_-]+)?/?|system/[A-Za-z0-9_-]+/?)?',parts.path):value='/'
    return '/_auth/login?return='+urllib.parse.quote(value,safe='')

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
        if self.path == '/login':
            self.send_response(302)
            self.send_header('Location',login_location(self.headers.get('X-Original-URI','/')))
            self.send_header('Cache-Control','private, no-store')
            self.send_header('Content-Length','0')
            self.end_headers()
            return
        if self.path == '/signed-out':
            nonce=secrets.token_urlsafe(24)
            page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>已退出 · Dashboard</title><style nonce="NONCE">:root{color-scheme:light dark;font-family:system-ui,sans-serif;background:light-dark(#fafafa,#171819);color:light-dark(#202124,#ececec)}body{margin:0;min-height:100svh;display:grid;place-items:center}main{margin:24px;padding:36px;max-width:360px;border:1px solid light-dark(#e4e4e7,#303134);border-radius:14px;background:light-dark(#fff,#1c1d1f)}h1{font-size:24px;margin:0 0 14px}p{font-size:14px;line-height:1.7;opacity:.7}a{display:inline-block;margin-top:12px;padding:12px 20px;border-radius:8px;background:light-dark(#202124,#ececec);color:light-dark(#fff,#202124);text-decoration:none;font-size:14px}a:focus-visible{outline:3px solid #6699ee;outline-offset:4px}</style><main><h1>已退出 Dashboard</h1><p>看板登录状态已撤销，其他站点的登录不受影响。</p><a href="/_auth/login?return=%2F">使用 Auth 重新登录</a></main></html>'''.replace('NONCE',nonce).encode()
            self.send_response(200)
            self.send_header('Content-Type','text/html; charset=utf-8')
            self.send_header('Cache-Control','private, no-store')
            self.send_header('Content-Security-Policy',"default-src 'none'; style-src 'nonce-"+nonce+"'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('Content-Length',str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
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
