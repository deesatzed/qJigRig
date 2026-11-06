import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';

test('one-shot replay uses recorded decisions and rejects changed source bytes', async () => {
  const dir=await mkdtemp(join(tmpdir(),'quix-replay-'));
  try {
    const path=join(dir,'manual.txt'), body='retry after timeout'; await writeFile(path,body);
    const snapshot={version:1,task:'retry',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',candidate_scope:'sections_and_records',max_steps:3,max_model_calls:3,max_characters:5000,candidates:[{id:'s1',title:'retry',body,record_type:'section',source_status:'current',path,revision:createHash('sha256').update(body).digest('hex'),start_line:1,end_line:1,topics:[],tier:'initial'}]};
    const initial=spawnSync(process.execPath,['src/compare.ts','fixture'],{input:JSON.stringify(snapshot),encoding:'utf8'});
    assert.equal(initial.status,0,initial.stderr);
    const trace=JSON.parse(initial.stdout).trace;
    const replay=()=>spawnSync(process.execPath,['src/replay.ts'],{input:JSON.stringify({snapshot,trace}),encoding:'utf8',env:{PATH:process.env.PATH ?? '/usr/bin:/bin'}});
    const first=replay(); assert.equal(first.status,0,first.stderr);
    const receipt=JSON.parse(first.stdout);
    assert.equal(receipt.status,'complete'); assert.equal(receipt.model_calls,0); assert.equal(receipt.evidence_count,1);
    await writeFile(path,'changed');
    const changed=replay(); assert.notEqual(changed.status,0);
    assert.equal(JSON.parse(changed.stdout).error,'replay_failed');
  } finally { await rm(dir,{recursive:true,force:true}); }
});

test('one-shot replay rejects malformed input',()=>{
  const result=spawnSync(process.execPath,['src/replay.ts'],{input:'not json',encoding:'utf8'});
  assert.notEqual(result.status,0);
  assert.equal(JSON.parse(result.stdout).error,'replay_failed');
});

test('replaying an insufficient-evidence trace keeps the failure explicit',()=>{
  const snapshot={version:1,task:'retry',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',candidate_scope:'sections_and_records',max_steps:3,max_model_calls:3,max_characters:5000,candidates:[]};
  const initial=spawnSync(process.execPath,['src/compare.ts','fixture'],{input:JSON.stringify(snapshot),encoding:'utf8'});
  assert.equal(initial.status,0,initial.stderr);
  const trace=JSON.parse(initial.stdout).trace;
  const result=spawnSync(process.execPath,['src/replay.ts'],{input:JSON.stringify({snapshot,trace}),encoding:'utf8',env:{PATH:process.env.PATH ?? '/usr/bin:/bin'}});
  assert.equal(result.status,0,result.stderr);
  const receipt=JSON.parse(result.stdout);
  assert.equal(receipt.status,'insufficient_evidence');
  assert.equal(receipt.reason,'no_evidence');
  assert.equal(receipt.evidence_count,0);
  assert.equal(receipt.model_calls,0);
});
