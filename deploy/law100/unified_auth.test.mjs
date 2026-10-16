import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { authContentSecurityPolicy, revokeApplicationLogin } from './dashboard-flow.mjs';
import { endUnifiedSession } from '../../internal/site/src/lib/unified-auth.ts';

const json=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
test('CSP follows registered clients, never arbitrary input',()=> {
 const csp=authContentSecurityPolicy({dashboard:{host:'dashboard.law100.xyz'},drive:{host:'drive.law100.xyz'}},'https://auth.law100.xyz');
 assert.match(csp,/form-action 'self' https:\/\/auth.law100.xyz https:\/\/dashboard.law100.xyz https:\/\/drive.law100.xyz;/);
 assert.ok(!csp.includes('*'));assert.match(csp,/frame-ancestors 'none'/);
});
test('Dashboard logout retains central session and all other clients',()=> {
 const db=new DatabaseSync(':memory:');
 db.exec("CREATE TABLE sessions(id TEXT PRIMARY KEY); CREATE TABLE app_sessions(id TEXT PRIMARY KEY,app TEXT,session_id TEXT); INSERT INTO sessions VALUES ('central'); INSERT INTO app_sessions VALUES ('dashboard-one','dashboard','central'),('drive-one','drive','central'),('dashboard-two','dashboard','central')");
 revokeApplicationLogin((sql,...params)=>db.prepare(sql).run(...params),'dashboard','dashboard-one','central');
 assert.equal(db.prepare('SELECT COUNT(*) n FROM sessions').get().n,1);
 assert.equal(db.prepare('SELECT COUNT(*) n FROM app_sessions').get().n,2);
 assert.ok(db.prepare("SELECT id FROM app_sessions WHERE id='drive-one'").get());
 assert.ok(db.prepare("SELECT id FROM app_sessions WHERE id='dashboard-two'").get());db.close();
});
test('client obtains same-origin CSRF and waits for revocation',async()=> {
 const calls=[];
 await endUnifiedSession(async(url,options)=> {
  calls.push([url,options]);
  return calls.length===1 ? json({data:{authenticated:true,csrfToken:'test-csrf'}}) : json({data:{authenticated:false}});
 });
 assert.equal(calls.length,2);assert.equal(calls[1][0],'/_auth/logout');assert.equal(calls[1][1].method,'POST');
 assert.equal(calls[1][1].headers['X-Auth-CSRF'],'test-csrf');assert.equal(calls[1][1].credentials,'same-origin');assert.equal(calls[1][1].redirect,'error');
});
test('already-expired login does not send a revoke request',async()=> {
 let count=0;await endUnifiedSession(async()=> {count++;return json({data:{authenticated:false}})});assert.equal(count,1);
});
test('missing CSRF, server errors and unconfirmed success cannot fake logout',async()=> {
 await assert.rejects(endUnifiedSession(async()=>json({data:{authenticated:true}})));
 await assert.rejects(endUnifiedSession(async()=>json({},503)));
 let count=0;await assert.rejects(endUnifiedSession(async()=> ++count===1 ? json({data:{authenticated:true,csrfToken:'test'}}) : json({data:{authenticated:true}})));
});
