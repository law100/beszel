"""Read-only business overview collector. No network calls or credential refresh.

Only projected fields are read from task documents; the JSON exposed to browsers
never contains source-share tokens, cloud credentials, signed URLs or file IDs.
"""
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import ssl
import subprocess
import time

STATE=Path('/var/lib/law100-dashboard-business')
DRIVE=Path('/srv/law100-drive/.state')
JOBS=Path('/var/lib/law100-resource-migration/jobs.sqlite3')
REGISTRY=Path('/etc/law100-drive-cloud-accounts/registry.json')
AUTH=Path('/var/lib/law100-unicom-auth')
OPENLIST=Path('/opt/law100-openlist/data/data.db')
ACTIVE={'queued','preparing','saving','downloading','uploading','checking','confirming','source_waiting','resting'}
STATES=ACTIVE|{'paused','needs_attention','complete','cancelled'}
ISSUES={'target_directory_name_rejected':'目标目录名称被云盘拒绝',
        'cache_full':'搬运缓存空间不足','cache_unmounted':'搬运缓存未挂载',
        'server_disk_low':'服务器磁盘空间不足','target_rejected':'目标云盘授权异常',
        'target_credentials_changed':'目标云盘授权发生变化','quark_login_required':'来源账户需要重新登录',
        'quark_rejected':'来源云盘授权异常','target_conflict':'目标文件存在冲突',
        'upload_uncertain':'上传结果仍待核对'}

def text(value,limit=160):
    value=re.sub(r'https?://\S+','［链接已隐藏］',str(value or ''))
    return ''.join(c for c in value if ord(c)>=32)[:limit]

def number(value):
    return value if type(value) in (int,float) and math.isfinite(value) and value>=0 else None

def db_open(path):
    conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.75)
    conn.row_factory=sqlite3.Row;conn.execute('PRAGMA query_only=ON');conn.execute('BEGIN')
    return conn

def read_json(path):
    value=json.loads(path.read_text())
    if not isinstance(value,dict):raise ValueError('Expected object')
    return value

def atomic(path,value):
    temp=path.with_name('.'+path.name+'.tmp')
    fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o640)
    with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False,allow_nan=False)
    os.chmod(temp,0o640);os.replace(temp,path)

def accounts(now):
    registry=read_json(REGISTRY)
    db=db_open(OPENLIST)
    try:mounts={r['id']:dict(r) for r in db.execute('SELECT id,disabled,status FROM x_storages')}
    finally:db.close()
    result=[]
    for a in registry['accounts']:
        if not a.get('enabled'):continue
        aid=a.get('id','')
        if not re.fullmatch(r'unicom|[a-f0-9-]{36}',aid):continue
        prefix='unicom' if aid=='unicom' else 'cloud-'+aid
        usage_path=DRIVE/(prefix+'-usage.json')
        meta_path=AUTH/'account.json' if aid=='unicom' else AUTH/'accounts'/aid/'account.json'
        try:usage=read_json(usage_path)
        except (OSError,ValueError):usage={}
        try:meta=read_json(meta_path)
        except (OSError,ValueError):meta={}
        scanned=number(usage.get('scannedAt'));used=number(usage.get('used')) if scanned else None
        total=number(usage.get('limit'))
        # Existing Drive defines 2 TiB per Unicom account; explicitly a configured
        # quota, not an assertion that the provider returned official capacity.
        if total is None and a.get('provider')=='unicom':total=2*1024**4
        mount=mounts.get(a.get('storageId'),{})
        ready=bool(mount and not mount.get('disabled') and mount.get('status')=='work')
        expires=number(meta.get('expiresAt'))
        blocked=(DRIVE/(prefix+'-authorization-blocked')).exists()
        authorization='expired' if expires is not None and expires<=now else ('needs_attention' if blocked or not ready else 'ready')
        result.append({'id':aid,'name':text(a.get('name') or '云盘账户',40),
            'totalBytes':total,'usedBytes':used,'remainingBytes':max(0,total-used) if total is not None and used is not None else None,
            'capacitySource':'configured','usageSource':'cached_inventory','scannedAt':scanned,
            'usageState':usage.get('status') if usage.get('status') in ('ready','scanning','error') else 'unknown',
            'usageStale':scanned is None or now-scanned>86400,
            'mountReady':ready,'authorization':authorization,'validatedAt':number(meta.get('validatedAt')),
            'expiresAt':expires})
    return result

def transfer(entries,current_path,current_download,total):
    completed_files=completed_bytes=downloaded=uploaded=0;current=None
    for e in entries:
        if e.get('directory'):continue
        size=number(e.get('size')) or 0
        if e.get('done'):
            completed_files+=1;completed_bytes+=size;downloaded+=size;uploaded+=size;continue
        if current is not None:
            if e.get('downloaded'):downloaded+=size
            continue
        enhanced=e.get('enhanced') or {}
        if enhanced.get('version')==1:
            block=5*1024**2;parts=max(1,math.ceil(size/block))
            confirmed={p for p in (enhanced.get('parts') or []) if type(p) is int and 1<=p<=parts}
            up=size if enhanced.get('complete') else sum(min(block,size-(p-1)*block) for p in confirmed)
        else:
            # Match the deployed uploader's legacy protocol; final part may be
            # larger than CHUNK. Do not replace its floor count with ceil.
            block=8*1024**2;parts=max(1,int(size)//block)
            n=min(parts,int(number(e.get('nextPart')) or 0));up=size if n==parts else min(size,n*block)
        down=size if e.get('downloaded') else min(size,current_download or 0) if e.get('path')==current_path else 0
        downloaded+=down;uploaded+=up
        current={'name':text(str(e.get('path','')).rsplit('/',1)[-1]),'size':size,
                 'downloadedBytes':down,'uploadedBytes':up,'uploadPhase':text(e.get('uploadPhase'),30)}
    return {'completedFiles':completed_files,'completedBytes':completed_bytes,
            'downloadedBytes':min(total,downloaded) if total is not None else downloaded,
            'uploadedBytes':min(total,uploaded) if total is not None else uploaded,'currentFile':current}

ENTRY_SQL="""SELECT json_object('path',json_extract(value,'$.path'),'size',json_extract(value,'$.size'),
 'directory',json_extract(value,'$.directory'),'done',json_extract(value,'$.done'),
 'downloaded',json_extract(value,'$.downloaded'),'nextPart',json_extract(value,'$.nextPart'),
 'uploadPhase',json_extract(value,'$.uploadPhase'),
 'enhanced',json_object('version',json_extract(value,'$.enhancedUpload.version'),
 'parts',json_extract(value,'$.enhancedUpload.parts'),'complete',CASE WHEN json_extract(value,'$.enhancedUpload.fid') IS NOT NULL THEN 1 ELSE 0 END))
 FROM json_each((SELECT doc FROM jobs WHERE id=?),'$.entries')"""

def migrations(now,previous):
    db=db_open(JOBS)
    try:
        rows=db.execute("""SELECT j.id,j.created,j.control,
          json_extract(j.doc,'$.label') label,json_extract(j.doc,'$.status') status,
          json_extract(j.doc,'$.updated') updated,json_extract(j.doc,'$.totalFiles') totalFiles,
          json_extract(j.doc,'$.totalBytes') totalBytes,json_extract(j.doc,'$.currentFile') currentFile,
          json_extract(j.doc,'$.downloadedBytes') downloadedBytes,
          json_extract(j.doc,'$.completedFiles') completedFiles,json_extract(j.doc,'$.completedBytes') completedBytes,
          json_extract(j.doc,'$.errorCode') errorCode
          FROM jobs j LEFT JOIN migration_job_views v ON v.job_id=j.id
          WHERE v.removed_at IS NULL ORDER BY j.created DESC,j.rowid DESC LIMIT 30""").fetchall()
        result=[];next_samples={}
        for row in rows:
            status=row['status'] if row['status'] in STATES else 'unknown'
            total=number(row['totalBytes']);updated=number(row['updated'])
            task={'id':row['id'],'label':text(row['label'] or '资料导入'), 'status':status,
                  'createdAt':number(row['created']),'updatedAt':updated,'totalFiles':number(row['totalFiles']),
                  'totalBytes':total,'completedFiles':number(row['completedFiles']),
                  'completedBytes':number(row['completedBytes']),'issue':None,'currentFile':None,
                  'downloadBytesPerSecond':None,'uploadBytesPerSecond':None,'etaSeconds':None,'percent':None}
            if status not in ('complete','cancelled'):
                entries=[json.loads(r[0]) for r in db.execute(ENTRY_SQL,(row['id'],))]
                task.update(transfer(entries,row['currentFile'],number(row['downloadedBytes']),total))
                if row['control']=='pause':task['status']='paused'
                if status=='needs_attention':task['issue']=ISSUES.get(row['errorCode'],'任务需要检查，请到 Resource 查看详情')
                old=previous.get(row['id'],{})
                sample={'at':now,'down':task['downloadedBytes'],'up':task['uploadedBytes']}
                next_samples[row['id']]=sample
                elapsed=now-(old.get('at') or now)
                if task['status'] in ACTIVE and updated and now-updated<90 and 5<=elapsed<=120:
                    for key,field in [('down','downloadBytesPerSecond'),('up','uploadBytesPerSecond')]:
                        delta=sample[key]-old.get(key,sample[key])
                        if delta>=0:task[field]=delta/elapsed
                    speed=(task['downloadBytesPerSecond'] or 0)+(task['uploadBytesPerSecond'] or 0)
                    if total and speed>0:
                        task['etaSeconds']=min(365*86400,max(0,(2*total-sample['up']-sample['down'])/speed))
                if total:task['percent']=min(99.9,(task['downloadedBytes']+task['uploadedBytes'])/(2*total)*100)
            elif status=='complete':task['percent']=100
            elapsed=(updated or now)-(task['createdAt'] or now)
            task['elapsedSeconds']=max(0,elapsed)
            task['averageBytesPerSecond']=task['completedBytes']/elapsed if status=='complete' and task['completedBytes'] is not None and elapsed>0 else None
            result.append(task)
        # Physical target identity deduplicates task records and frozen shares.
        # No directory scan or provider request; this is historical confirmation,
        # not proof that files weren't later deleted directly on the cloud.
        unique_files={}
        # Keep each json_each bound to one document. Joining giant JSON documents
        # and grouping extracted values made SQLite repeatedly parse whole arrays.
        for table,array,condition in [('jobs','entries',"WHERE json_extract(value,'$.done')=1 AND COALESCE(json_extract(value,'$.directory'),0)=0"),('migration_shares','files','')]:
            documents=db.execute('SELECT rowid,json_extract(doc,\'$.unicomAccount\') FROM '+table).fetchall()
            for rid,account in documents:
                sql="SELECT json_object('p',json_extract(value,'$.targetParent'),'f',json_extract(value,'$.fileId'),'s',json_extract(value,'$.size')) FROM json_each((SELECT doc FROM "+table+" WHERE rowid=?),'$."+array+"') "+condition
                for record in db.execute(sql,(rid,)):
                    f=json.loads(record[0])
                    if account is not None and f['p'] is not None and f['f'] is not None:
                        key=(account,f['p'],f['f']);unique_files[key]=max(unique_files.get(key,0),number(f['s']) or 0)
        shares=db.execute('SELECT COUNT(*) FROM migration_shares WHERE revoked IS NULL').fetchone()[0]
        summary={'fileCount':len(unique_files),'totalBytes':sum(unique_files.values()),'shareCount':shares,
                 'source':'confirmed_import_records','updatedAt':now,
                 'recent':[{'label':t['label'],'status':t['status'],'fileCount':t['completedFiles'],
                            'totalBytes':t['completedBytes'],'updatedAt':t['updatedAt']} for t in result
                           if t['completedFiles'] is not None and t['completedFiles']>0][:5]}
        return result,next_samples,summary
    finally:db.close()

def maintenance(now):
    backup=None
    try:
        b=read_json(Path('/var/backups/law100-dashboard/last-success.json'))
        at=dt.datetime.strptime(b['createdUtc'],'%Y%m%dT%H%M%SZ').replace(tzinfo=dt.timezone.utc).timestamp()
        result=subprocess.check_output(['systemctl','show','law100-dashboard-backup.service','--property=Result','--value'],text=True,timeout=3).strip()
        backup={'completedAt':at,'sizeBytes':number(b.get('bytes')),'verified':b.get('sqlite')=='ok' and b.get('checksum')=='ok',
                'state':'error' if result not in ('','success') else 'stale' if now-at>48*3600 else 'ready','offServer':False}
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):pass
    certificates=[]
    for domain in ['dashboard.law100.xyz','resource.law100.xyz','drive.law100.xyz','auth.law100.xyz']:
        found=None
        for p in Path('/etc/nginx/sites-enabled').iterdir():
            try:s=p.read_text()
            except OSError:continue
            if not re.search(r'\bserver_name\s+[^;]*\b'+re.escape(domain)+r'(?=\s|;)',s):continue
            m=re.search(r'^\s*ssl_certificate\s+([^;]+);',s,re.M)
            if m:
                try:
                    cert=ssl._ssl._test_decode_cert(m[1].strip())
                    expires=ssl.cert_time_to_seconds(cert['notAfter']);found={'domain':domain,'expiresAt':expires,'daysRemaining':math.floor((expires-now)/86400)}
                except (OSError,ValueError,ssl.SSLError):pass
                break
        certificates.append(found or {'domain':domain,'expiresAt':None,'daysRemaining':None})
    return {'backup':backup,'certificates':certificates}

def overview(now,previous):
    errors=[];samples={}
    result={'version':1,'generatedAt':now,'accounts':None,'tasks':None,'library':None,'maintenance':None,'issues':[]}
    try:result['accounts']=accounts(now)
    except (OSError,ValueError,KeyError,sqlite3.Error):errors.append('网盘数据暂不可用')
    try:result['tasks'],samples,result['library']=migrations(now,previous)
    except (OSError,ValueError,KeyError,sqlite3.Error):errors.append('导入和资料库数据暂不可用')
    try:result['maintenance']=maintenance(now)
    except (OSError,ValueError):errors.append('维护数据暂不可用')
    for message in errors:result['issues'].append({'severity':'warning','title':message,'area':'data'})
    for a in result['accounts'] or []:
        if a['authorization']!='ready':result['issues'].append({'severity':'error','title':a['name']+'的授权或挂载需要检查','area':'storage'})
        elif a['usageStale']:result['issues'].append({'severity':'warning','title':a['name']+'的容量统计尚未更新','area':'storage'})
    for t in result['tasks'] or []:
        if t['issue'] and t['status']!='paused':result['issues'].append({'severity':'error','title':t['label']+'：'+t['issue'],'area':'import'})
    m=result['maintenance']
    if m:
        if not m['backup'] or m['backup']['state']!='ready' or not m['backup']['verified']:
            result['issues'].append({'severity':'warning','title':'备份状态需要检查','area':'maintenance'})
        for c in m['certificates']:
            days=c['daysRemaining']
            if days is not None and days<14:result['issues'].append({'severity':'error' if days<0 else 'warning','title':c['domain']+'证书即将到期' if days>=0 else c['domain']+'证书已过期','area':'maintenance'})
    return result,samples

if __name__=='__main__':
    os.umask(0o027);now=time.time()
    try:previous=read_json(STATE/'samples.json')
    except (OSError,ValueError):previous={}
    result,samples=overview(now,previous)
    atomic(STATE/'overview.json',result);atomic(STATE/'samples.json',samples)
    print('Business overview refreshed; unavailable sections:',sum(result[k] is None for k in ['accounts','tasks','library','maintenance']))
