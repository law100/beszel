import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('gate',Path(__file__).with_name('auth_gate.py'))
gate=importlib.util.module_from_spec(spec)
with patch.object(Path,'read_text',return_value=json.dumps({'owner':'owner','email':'owner@example.test','bridge':'test-only'})):
    spec.loader.exec_module(gate)

class Response:
    def __init__(self,value):self.value=value
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self):return json.dumps(self.value).encode()

class GateTests(unittest.TestCase):
    def test_anonymous_and_non_owner(self):
        self.assertEqual(gate.authorized_identity(''),(401,None))
        with patch.object(gate.urllib.request,'urlopen',return_value=Response({'authenticated':True,'userId':'another','role':'super_admin'})):
            self.assertEqual(gate.authorized_identity('__Host-law100-app=sample'),(403,None))

    def test_owner_role_and_stable_email(self):
        for role,expected in [('user',403),('admin',403),('super_admin',204)]:
            with patch.object(gate.urllib.request,'urlopen',return_value=Response({'authenticated':True,'userId':'owner','role':role,'email':'forged@example.test'})):
                status,email=gate.authorized_identity('__Host-law100-app=sample')
                self.assertEqual(status,expected)
                if status==204:self.assertEqual(email,'owner@example.test')

    def request(self,status=204):
        h=object.__new__(gate.Handler);h.path='/business';h.headers={};h.wfile=io.BytesIO()
        codes=[];headers={}
        h.send_response=codes.append;h.send_header=lambda k,v:headers.update({k:v});h.end_headers=lambda:None
        with patch.object(gate,'authorized_identity',return_value=(status,'owner@example.test' if status==204 else None)),patch.object(Path,'stat',return_value=SimpleNamespace(st_size=42)),patch.object(Path,'read_bytes',return_value=b'{"version":1,"generatedAt":1000}'):
            h.do_GET()
        return codes,headers,h.wfile.getvalue()

    def test_owner_snapshot_and_cache_policy(self):
        codes,headers,body=self.request()
        self.assertEqual(codes,[200]);self.assertIn('no-store',headers['Cache-Control'])
        self.assertEqual(json.loads(body)['version'],1)

    def test_rejected_request_never_reads_snapshot(self):
        for status in [401,403,503]:
            codes,_,body=self.request(status)
            self.assertEqual(codes,[status]);self.assertEqual(body,b'')

if __name__=='__main__':unittest.main()
