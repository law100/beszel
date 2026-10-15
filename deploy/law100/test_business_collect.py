import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('collect',Path(__file__).with_name('business_collect.py'))
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)

class CollectorTests(unittest.TestCase):
    def test_enhanced_parts(self):
        e={'path':'a.bin','size':12*1024**2,'enhanced':{'version':1,'parts':[1,1,2,99,'3']}}
        r=c.transfer([e],'a.bin',8*1024**2,e['size'])
        self.assertEqual(r['uploadedBytes'],10*1024**2)
        self.assertEqual(r['downloadedBytes'],8*1024**2)
        e['enhanced']['parts']=None
        self.assertEqual(c.transfer([e],'a.bin',0,e['size'])['uploadedBytes'],0)

    def test_legacy_floor_final_part_and_zero(self):
        e={'path':'x','size':19*1024**2,'nextPart':2,'downloaded':True}
        self.assertEqual(c.transfer([e],'x',0,e['size'])['uploadedBytes'],e['size'])
        r=c.transfer([{'path':'empty','size':0,'done':True}],None,0,0)
        self.assertEqual(r['completedFiles'],1)
        self.assertEqual(r['uploadedBytes'],0)

    def test_redaction_and_unknown(self):
        self.assertNotIn('secret',c.text('failure https://example.test/?token=secret'))
        self.assertIsNone(c.number(None))
        self.assertIsNone(c.number(float('nan')))
        self.assertIsNone(c.number(True))
        self.assertEqual(c.number(0),0)

    def test_sqlite_projection_readonly_dedup_and_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'jobs.sqlite3'
            db=sqlite3.connect(path)
            db.executescript('CREATE TABLE jobs(id TEXT PRIMARY KEY,created INTEGER,doc TEXT,control TEXT); CREATE TABLE migration_job_views(job_id TEXT,removed_at INTEGER); CREATE TABLE migration_shares(job_id TEXT,revoked INTEGER,doc TEXT,token TEXT);')
            e={'path':'file','size':20,'done':True,'fileId':'private-file-id','targetParent':'parent','md5':'private-hash'}
            doc={'label':'test','status':'needs_attention','updated':990,'totalBytes':40,'totalFiles':2,'errorCode':'target_directory_name_rejected','unicomAccount':'a','entries':[e,{'path':'next','size':20,'enhancedUpload':{'version':1,'parts':None,'token':'private-token'}}],'shareId':'private-share'}
            db.execute('INSERT INTO jobs VALUES (?,?,?,?)',('one',900,json.dumps(doc),'pause'))
            db.execute('INSERT INTO migration_shares VALUES (?,?,?,?)',('one',None,json.dumps({'unicomAccount':'a','files':[e]}),'private-share-token'))
            db.commit();db.close()
            before=path.read_bytes()
            with patch.object(c,'JOBS',path):
                tasks,samples,library=c.migrations(1000,{})
            self.assertEqual(tasks[0]['status'],'paused')
            self.assertEqual(library['fileCount'],1)
            self.assertEqual(library['totalBytes'],20)
            self.assertEqual(tasks[0]['percent'],50)
            serialized=json.dumps([tasks,samples,library])
            for secret in ['private-token','private-hash','private-file-id','private-share']:self.assertNotIn(secret,serialized)
            self.assertEqual(before,path.read_bytes())
            ro=c.db_open(path)
            try:
                with self.assertRaises(sqlite3.OperationalError):ro.execute('DELETE FROM jobs')
            finally:ro.close()

    def test_partial_data_is_unknown_not_zero(self):
        with patch.object(c,'accounts',side_effect=OSError),patch.object(c,'migrations',side_effect=OSError),patch.object(c,'maintenance',return_value={'backup':None,'certificates':[]}):
            result,_=c.overview(1000,{})
        self.assertIsNone(result['accounts']);self.assertIsNone(result['tasks']);self.assertIsNone(result['library'])
        self.assertGreaterEqual(len(result['issues']),2)

if __name__=='__main__':unittest.main()
