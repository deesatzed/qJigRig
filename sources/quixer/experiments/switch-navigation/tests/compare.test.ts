import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';

test('one-shot fixture runner returns source-bound evidence without a model', async () => {
  const dir=await mkdtemp(join(tmpdir(),'quix-compare-'));
  try {
    const path=join(dir,'manual.txt'); const body='retry after timeout'; await writeFile(path,body);
    const snapshot={version:1,task:'retry',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',candidate_scope:'sections_and_records',max_steps:3,max_model_calls:3,max_characters:5000,candidates:[{id:'s1',title:'retry',body,record_type:'section',source_status:'current',path,revision:createHash('sha256').update(body).digest('hex'),start_line:1,end_line:1,topics:[],tier:'initial'}]};
    const result=spawnSync(process.execPath,['src/compare.ts','fixture'],{input:JSON.stringify(snapshot),encoding:'utf8'});
    assert.equal(result.status,0,result.stderr);
    const output=JSON.parse(result.stdout);
    assert.equal(output.status,'complete');
    assert.equal(output.state.evidence[0].id,'s1');
    assert.deepEqual(output.receipts,[]);
  } finally { await rm(dir,{recursive:true,force:true}); }
});

test('one-shot runner returns a structured failure for malformed input', () => {
  const result=spawnSync(process.execPath,['src/compare.ts','fixture'],{input:'not json',encoding:'utf8'});
  assert.notEqual(result.status,0);
  assert.equal(JSON.parse(result.stdout).error,'invalid_request');
});
