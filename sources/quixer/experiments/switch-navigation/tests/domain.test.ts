import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, realpath, rm, writeFile } from 'node:fs/promises';
import { writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { fakeDecider, answered, failing } from '@osolmaz/switch/testing';
import { replayOf } from '@osolmaz/switch';
import { navigate, replayNavigation } from '../src/domain.ts';
import { capInitialCandidates, projectSnapshot } from '../src/project-snapshot.ts';

test('repeated headings remain distinct selectable passages', async () => {
  const dir=await mkdtemp(join(tmpdir(),'quix-duplicate-'));
  try {
    const path=join(dir,'guide.txt'); const text='same heading'; await writeFile(path,text);
    const candidate={title:'Introduction',body:text,record_type:'section',source_status:'current',path,revision:createHash('sha256').update(text).digest('hex'),start_line:1,end_line:1,topics:[],tier:'initial'};
    const snapshot={version:1,task:'intro',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:3,max_characters:5000,candidates:[{...candidate,id:'one'},{...candidate,id:'two'}]};
    const decider=fakeDecider((request,call)=>{
      const q=request.decisionQuestions['pick']; assert.equal(q?.type,'choice');
      const options=Object.entries(q.criteria).filter(([,text])=>text.startsWith('Inspect passage'));
      if (call===1) assert.equal(new Set(options.map(([,text])=>text)).size,2);
      const label=call===1 ? options[0]?.[0] : Object.entries(q.criteria).find(([,text])=>text.startsWith('Stop'))?.[0];
      assert.ok(label); return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
    });
    assert.equal((await navigate(snapshot,decider)).status,'complete');
  } finally { await rm(dir,{recursive:true,force:true}); }
});

test('inspects a source-bound section, stops, and replays without a model', async () => {
  const dir = await mkdtemp(join(tmpdir(),'quix-switch-'));
  try {
    const path = join(dir,'guide.md');
    const text = '# Retry\nRetry after timeout.';
    await writeFile(path,text);
    const snapshot = {version:1, task:'retry', role:'reviewer', role_version:'1', catalog_fingerprint:'fixture', max_steps:4, max_characters:5000, candidates:[{id:'s1',title:'Retry',body:text,record_type:'section',source_status:'current',path,revision:createHash('sha256').update(text).digest('hex'),start_line:1,end_line:2,topics:['resilience'],tier:'initial'}]};
    const decider = fakeDecider((request,call) => {
      const q = request.decisionQuestions['pick'];
      assert.equal(q?.type,'choice');
      const entries = Object.entries(q.criteria);
      const label = entries.find(([,text]) => text.startsWith(call === 1 ? 'Inspect passage' : 'Stop'))?.[0];
      assert.ok(label);
      return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
    });
    const result = await navigate(snapshot,decider);
    assert.equal(result.status,'complete');
    assert.deepEqual(result.state.evidence.map(e => e.id),['s1']);
    assert.equal(result.state.evidence[0]?.sources[0]?.path,path);
    assert.equal(result.state.evidence[0]?.sources[0]?.revision,createHash('sha256').update(text).digest('hex'));
    assert.equal(result.state.evidence[0]?.sources[0]?.start_line,1);
    const replay = replayOf(result.trace.entries);
    const repeated = await replayNavigation(snapshot,replay,result.trace.entries);
    assert.deepEqual(repeated.state,result.state);
    assert.equal(decider.requests.length,2);
    await writeFile(path,'changed');
    const stale = await replayNavigation(snapshot,replay,result.trace.entries);
    assert.equal(stale.status,'insufficient_evidence');
    assert.deepEqual(stale.state.evidence,[]);
  } finally { await rm(dir,{recursive:true,force:true}); }
});

test('withholds inspected evidence if its source changes before stop', async () => {
  const dir = await mkdtemp(join(tmpdir(),'quix-switch-'));
  try {
    const path = join(dir,'guide.md');
    const text = '# Retry\nRetry after timeout.';
    await writeFile(path,text);
    const snapshot = {version:1,task:'retry',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:4,max_characters:5000,candidates:[{id:'s1',title:'Retry',body:text,record_type:'section',source_status:'current',path,revision:createHash('sha256').update(text).digest('hex'),start_line:1,end_line:2,topics:[],tier:'initial'}]};
    const decider = fakeDecider((request,call) => {
      if (call === 2) writeFileSync(path,'changed');
      const q = request.decisionQuestions['pick'];
      assert.equal(q?.type,'choice');
      const label = Object.entries(q.criteria).find(([,text]) => text.startsWith(call === 1 ? 'Inspect passage' : 'Stop'))?.[0];
      assert.ok(label);
      return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
    });
    const result = await navigate(snapshot,decider);
    assert.equal(result.status,'insufficient_evidence');
    assert.equal(result.reason,'source_unavailable_or_changed');
    assert.deepEqual(result.state.evidence,[]);
  } finally { await rm(dir,{recursive:true,force:true}); }
});

test('inspecting a topic reveals its candidate IDs to the next decision', async () => {
  const snapshot = {version:1,task:'retry',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:3,max_characters:5000,candidates:[{id:'s1',title:'Retry',body:'retry',record_type:'section',source_status:'current',path:'/tmp/unread',revision:'a'.repeat(64),start_line:1,end_line:1,topics:['resilience'],topic_annotations:[{topic:'resilience',status:'proposed',method:'model'}],tier:'initial'}]};
  const decider = fakeDecider((request,call) => {
    if (call === 2) assert.deepEqual(request.decisionState['topics_found'],[{topic:'resilience',candidate_ids:['s1'],annotations:[{candidate_id:'s1',status:'proposed',method:'model'}]}]);
    const q = request.decisionQuestions['pick'];
    assert.equal(q?.type,'choice');
    const label = Object.entries(q.criteria).find(([,text]) => text.startsWith(call === 1 ? 'Inspect topic' : 'Stop'))?.[0];
    assert.ok(label);
    return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
  });
  const result = await navigate(snapshot,decider);
  assert.equal(result.status,'insufficient_evidence');
  assert.equal(result.reason,'no_evidence');
});

test('provider exceptions yield an explicit insufficient-evidence result', async () => {
  const snapshot = {version:1,task:'retry',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:3,max_characters:5000,candidates:[]};
  const decider = fakeDecider(() => { throw new Error('provider disconnected'); });
  const result = await navigate(snapshot,decider);
  assert.equal(result.status,'insufficient_evidence');
  assert.equal(result.reason,'decision_failed');
  assert.deepEqual(result.state.evidence,[]);
});

test('an agent record cannot substitute unrelated evidence sources', async () => {
  const dir = await mkdtemp(join(tmpdir(),'quix-switch-'));
  try {
    const path=join(dir,'source.md'); const text='source'; await writeFile(path,text);
    const source={section_id:'wrong',path,revision:createHash('sha256').update(text).digest('hex'),source_status:'current',start_line:1,end_line:1};
    const snapshot={version:1,task:'claim',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:2,max_characters:5000,candidates:[{id:'f1',title:'finding',body:'claim',record_type:'agent_record',source_status:'proposed',evidence_status:'current',unsupported:false,evidence:['expected'],evidence_sources:[source],topics:[],tier:'initial'}]};
    const decider=fakeDecider(request=>{
      const q=request.decisionQuestions['pick']; assert.equal(q?.type,'choice');
      const label=Object.entries(q.criteria).find(([,text])=>text.startsWith('Inspect passage'))?.[0]; assert.ok(label);
      return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
    });
    const result=await navigate(snapshot,decider);
    assert.equal(result.status,'insufficient_evidence');
    assert.equal(result.reason,'unsupported_evidence');
    assert.deepEqual(result.state.evidence,[]);
  } finally { await rm(dir,{recursive:true,force:true}); }
});

test('an agent record cannot duplicate one source to hide another missing source', async () => {
  const dir=await mkdtemp(join(tmpdir(),'quix-switch-'));
  try {
    const path=join(dir,'source.md'); const text='source'; await writeFile(path,text);
    const source={section_id:'s1',path,revision:createHash('sha256').update(text).digest('hex'),source_status:'current',start_line:1,end_line:1};
    const snapshot={version:1,task:'claim',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:2,max_characters:5000,candidates:[{id:'f1',title:'finding',body:'claim',record_type:'agent_record',source_status:'proposed',evidence_status:'current',unsupported:false,evidence:['s1','s2'],evidence_sources:[source,source],topics:[],tier:'initial'}]};
    const decider=fakeDecider(request=>{
      const q=request.decisionQuestions['pick']; assert.equal(q?.type,'choice');
      const label=Object.entries(q.criteria).find(([,text])=>text.startsWith('Inspect passage'))?.[0]; assert.ok(label);
      return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
    });
    const result=await navigate(snapshot,decider);
    assert.equal(result.reason,'unsupported_evidence');
  } finally { await rm(dir,{recursive:true,force:true}); }
});

test('step exhaustion is reported even after gathering evidence', async () => {
  const dir=await mkdtemp(join(tmpdir(),'quix-switch-'));
  try {
    const path=join(dir,'source.md'); const text='retry'; await writeFile(path,text);
    const snapshot={version:1,task:'retry',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:1,max_characters:5000,candidates:[{id:'s1',title:'retry',body:text,record_type:'section',source_status:'current',path,revision:createHash('sha256').update(text).digest('hex'),start_line:1,end_line:1,topics:[],tier:'initial'}]};
    const decider=fakeDecider(request=>{
      const q=request.decisionQuestions['pick']; assert.equal(q?.type,'choice');
      const label=Object.entries(q.criteria).find(([,text])=>text.startsWith('Inspect passage'))?.[0]; assert.ok(label);
      return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
    });
    const result=await navigate(snapshot,decider);
    assert.equal(result.status,'insufficient_evidence');
    assert.equal(result.reason,'step_limit');
  } finally { await rm(dir,{recursive:true,force:true}); }
});

test('navigates a real Python catalog snapshot without mutating it', async () => {
  const dir=await mkdtemp(join(tmpdir(),'quix-switch-'));
  try {
    const path=join(dir,'source.md'); await writeFile(path,'# Retry\nRetry after timeout.');
    const code="import json,sys; from quix_knowledge.store import open_catalog; from quix_knowledge.ingest import ingest; from quix_knowledge.switch_snapshot import build_snapshot; db=open_catalog(':memory:'); ingest(db,sys.argv[1]); before=db.total_changes; snapshot=build_snapshot(db,task='retry',role='reviewer',role_version='1',max_steps=3,max_characters=5000); assert db.total_changes==before; print(json.dumps(snapshot))";
    const py=spawnSync('python',['-c',code,path],{encoding:'utf8',env:{...process.env,PYTHONPATH:resolve('../../src')}});
    assert.equal(py.status,0,py.stderr);
    const snapshot:unknown=JSON.parse(py.stdout);
    const decider=fakeDecider((request,call)=>{
      const q=request.decisionQuestions['pick']; assert.equal(q?.type,'choice');
      const label=Object.entries(q.criteria).find(([,text])=>text.startsWith(call===1?'Inspect passage':'Stop'))?.[0]; assert.ok(label);
      return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
    });
    const result=await navigate(snapshot,decider);
    assert.equal(result.status,'complete');
    assert.equal(result.state.evidence[0]?.sources[0]?.path,await realpath(path));
  } finally { await rm(dir,{recursive:true,force:true}); }
});

test('verifies a generated passage using the source section offsets', async () => {
  const dir=await mkdtemp(join(tmpdir(),'quix-switch-'));
  try {
    const path=join(dir,'source.txt'); await writeFile(path,'Retry after timeout.\n\nRecord failure details.');
    const code="import json,sys; from quix_knowledge.store import open_catalog; from quix_knowledge.indexing import index_source; from quix_knowledge.switch_snapshot import build_snapshot; db=open_catalog(':memory:'); index_source(db,sys.argv[1]); print(json.dumps(build_snapshot(db,task='retry',role='reviewer',role_version='1',max_steps=3,max_characters=5000,include_proposed=True)))";
    const py=spawnSync('python',['-c',code,path],{encoding:'utf8',env:{...process.env,PYTHONPATH:resolve('../../src')}}); assert.equal(py.status,0,py.stderr);
    const snapshot:unknown=JSON.parse(py.stdout);
    const decider=fakeDecider((request,call)=>{
      const q=request.decisionQuestions['pick']; assert.equal(q?.type,'choice');
      const label=Object.entries(q.criteria).find(([,text])=>text.startsWith(call===1?'Inspect passage: Retry after timeout.':'Stop'))?.[0]; assert.ok(label);
      return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
    });
    const result=await navigate(snapshot,decider);
    assert.equal(result.status,'complete');
    assert.equal(result.state.evidence[0]?.record_type,'generated_index');
    assert.equal(result.state.evidence[0]?.index_status,'proposed');
    assert.equal(result.state.evidence[0]?.text,'Retry after timeout.');
  } finally { await rm(dir,{recursive:true,force:true}); }
});

test('keeps a supported agent finding distinct from its source evidence', async () => {
  const dir=await mkdtemp(join(tmpdir(),'quix-switch-'));
  try {
    const path=join(dir,'source.md'); await writeFile(path,'# Retry\nRetry after timeout.');
    const code="import json,sys; from quix_knowledge.store import open_catalog; from quix_knowledge.ingest import ingest; from quix_knowledge.records import add_record; from quix_knowledge.switch_snapshot import build_snapshot; db=open_catalog(':memory:'); ingest(db,sys.argv[1]); sid=db.execute('select id from sections').fetchone()[0]; add_record(db,'f1','finding','zorbnitz finding','agent',evidence=[sid]); print(json.dumps(build_snapshot(db,task='zorbnitz',role='reviewer',role_version='1',max_steps=3,max_characters=5000)))";
    const py=spawnSync('python',['-c',code,path],{encoding:'utf8',env:{...process.env,PYTHONPATH:resolve('../../src')}}); assert.equal(py.status,0,py.stderr);
    const snapshot:unknown=JSON.parse(py.stdout);
    const decider=fakeDecider((request,call)=>{
      const q=request.decisionQuestions['pick']; assert.equal(q?.type,'choice');
      const label=Object.entries(q.criteria).find(([,text])=>text.startsWith(call===1?'Inspect passage: finding':'Stop'))?.[0]; assert.ok(label);
      return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
    });
    const result=await navigate(snapshot,decider);
    assert.equal(result.status,'complete');
    assert.equal(result.state.evidence[0]?.record_type,'agent_record');
    assert.equal(result.state.evidence[0]?.status,'proposed');
    assert.equal(result.state.evidence[0]?.content_verification,'agent_claim_unverified');
  } finally { await rm(dir,{recursive:true,force:true}); }
});

test('rejects snapshot text that does not match the cited source span', async () => {
  const dir=await mkdtemp(join(tmpdir(),'quix-switch-'));
  try {
    const path=join(dir,'source.md'); const text='# Retry\nRetry after timeout.'; await writeFile(path,text);
    const snapshot={version:1,task:'retry',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:3,max_characters:5000,candidates:[{id:'s1',title:'Retry',body:'fabricated text',record_type:'section',source_status:'current',path,revision:createHash('sha256').update(text).digest('hex'),start_line:1,end_line:2,topics:[],tier:'initial'}]};
    const decider=fakeDecider(request=>{
      const q=request.decisionQuestions['pick']; assert.equal(q?.type,'choice');
      const label=Object.entries(q.criteria).find(([,text])=>text.startsWith('Inspect passage'))?.[0]; assert.ok(label);
      return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
    });
    const result=await navigate(snapshot,decider);
    assert.equal(result.status,'insufficient_evidence');
    assert.deepEqual(result.state.evidence,[]);
  } finally { await rm(dir,{recursive:true,force:true}); }
});

test('verifies a UTF-8 source containing a byte-order mark', async () => {
  const dir=await mkdtemp(join(tmpdir(),'quix-switch-'));
  try {
    const path=join(dir,'bom.txt'); const text='\uFEFFretry'; await writeFile(path,text);
    const snapshot={version:1,task:'retry',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:3,max_characters:5000,candidates:[{id:'s1',title:'retry',body:text,record_type:'section',source_status:'current',path,revision:createHash('sha256').update(text).digest('hex'),start_line:1,end_line:1,topics:[],tier:'initial'}]};
    const decider=fakeDecider((request,call)=>{
      const q=request.decisionQuestions['pick']; assert.equal(q?.type,'choice');
      const label=Object.entries(q.criteria).find(([,text])=>text.startsWith(call===1?'Inspect passage':'Stop'))?.[0]; assert.ok(label);
      return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
    });
    assert.equal((await navigate(snapshot,decider)).status,'complete');
  } finally { await rm(dir,{recursive:true,force:true}); }
});

test('model view truncates evidence to its budget and labels truncation', async () => {
  const dir=await mkdtemp(join(tmpdir(),'quix-switch-'));
  try {
    const path=join(dir,'long.txt'); const text='retry '.repeat(1000); await writeFile(path,text);
    const snapshot={version:1,task:'retry',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:3,max_characters:1000,candidates:[{id:'s1',title:'retry',body:text,record_type:'section',source_status:'current',path,revision:createHash('sha256').update(text).digest('hex'),start_line:1,end_line:1,topics:[],tier:'initial'}]};
    const decider=fakeDecider((request,call)=>{
      if (call===2) {
        assert.equal(request.decisionState['view_truncated'],true);
        assert.ok(JSON.stringify(request.decisionState).length<=1000);
      }
      const q=request.decisionQuestions['pick']; assert.equal(q?.type,'choice');
      const label=Object.entries(q.criteria).find(([,text])=>text.startsWith(call===1?'Inspect passage':'Stop'))?.[0]; assert.ok(label);
      return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
    });
    const result=await navigate(snapshot,decider);
    assert.equal(result.status,'complete');
    assert.equal(result.state.evidence[0]?.truncated,true);
    assert.equal(result.model_requests[1]?.decisionState['view_truncated'],true);
  } finally { await rm(dir,{recursive:true,force:true}); }
});

test('model-call cap includes switch retries', async () => {
  const snapshot={version:1,task:'retry',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:3,max_model_calls:1,max_characters:5000,candidates:[]};
  const decider=fakeDecider(()=>failing('window exceeded',true));
  const result=await navigate(snapshot,decider);
  assert.equal(result.status,'insufficient_evidence');
  assert.equal(decider.requests.length,1);
});

test('stale agent evidence is explicitly rejected without invalidating the snapshot', async () => {
  const source={section_id:'s1',path:'/tmp/stale',revision:'a'.repeat(64),source_status:'superseded',start_line:1,end_line:1};
  const snapshot={version:1,task:'claim',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:2,max_characters:5000,candidates:[{id:'f1',title:'finding',body:'claim',record_type:'agent_record',source_status:'proposed',evidence_status:'stale',unsupported:false,evidence:['s1'],evidence_sources:[source],topics:[],tier:'initial'}]};
  const decider=fakeDecider(request=>{
    const q=request.decisionQuestions['pick']; assert.equal(q?.type,'choice');
    const label=Object.entries(q.criteria).find(([,text])=>text.startsWith('Inspect passage'))?.[0]; assert.ok(label);
    return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
  });
  const result=await navigate(snapshot,decider);
  assert.equal(result.status,'insufficient_evidence');
  assert.equal(result.reason,'unsupported_evidence');
});

test('visited passages are not offered again', async () => {
  const dir=await mkdtemp(join(tmpdir(),'quix-switch-'));
  try {
    const path=join(dir,'source.txt'); const text='retry'; await writeFile(path,text);
    const snapshot={version:1,task:'retry',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:3,max_characters:5000,candidates:[{id:'s1',title:'retry',body:text,record_type:'section',source_status:'current',path,revision:createHash('sha256').update(text).digest('hex'),start_line:1,end_line:1,topics:[],tier:'initial'}]};
    const decider=fakeDecider((request,call)=>{
      const q=request.decisionQuestions['pick']; assert.equal(q?.type,'choice');
      if (call===2) assert.equal(Object.values(q.criteria).some(text=>text.startsWith('Inspect passage')),false);
      const label=Object.entries(q.criteria).find(([,text])=>text.startsWith(call===1?'Inspect passage':'Stop'))?.[0]; assert.ok(label);
      return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
    });
    assert.equal((await navigate(snapshot,decider)).status,'complete');
  } finally { await rm(dir,{recursive:true,force:true}); }
});

test('invalid model choice cannot cause an arbitrary action', async () => {
  const snapshot={version:1,task:'retry',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:3,max_characters:5000,candidates:[]};
  const decider=fakeDecider(()=>answered({pick:{type:'choice',choice:'invented',probabilities:{invented:1},confidence:1}}));
  const result=await navigate(snapshot,decider);
  assert.equal(result.status,'insufficient_evidence');
  assert.equal(result.reason,'decision_failed');
  assert.deepEqual(result.state.evidence,[]);
});

test('role estimates are labeled in choices without filtering other candidates', async () => {
  const candidate=(id:string,role_annotation:unknown)=>({id,title:id,body:'retry',record_type:'section',source_status:'current',path:'/tmp/'+id,revision:'a'.repeat(64),start_line:1,end_line:1,topics:[],tier:'initial',role_annotation});
  const snapshot={version:1,task:'retry',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:2,max_characters:5000,candidates:[candidate('a',{score:0.8,status:'proposed',method:'fixture',model:null,source_revision:'a'.repeat(64),scope:'section'}),candidate('b',null)]};
  const decider=fakeDecider(request=>{
    const q=request.decisionQuestions['pick']; assert.equal(q?.type,'choice');
    const choices=Object.values(q.criteria);
    assert.ok(choices.some(text=>text.includes('0.8') && text.includes('proposed')));
    assert.ok(choices.some(text=>text.includes('Inspect passage: b')));
    const label=Object.entries(q.criteria).find(([,text])=>text.startsWith('Stop'))?.[0]; assert.ok(label);
    return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
  });
  assert.equal((await navigate(snapshot,decider)).reason,'no_evidence');
});

test('a bounded initial set retains all other candidates for broadening', () => {
  const base={version:1,task:'retry timeout',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:3,max_model_calls:4,max_characters:5000,candidates:[
    {id:'a',title:'retry',body:'retry',record_type:'section',source_status:'current',path:'/tmp/a',revision:'a'.repeat(64),start_line:1,end_line:1,topics:[],tier:'initial'},
    {id:'b',title:'retry timeout',body:'retry timeout',record_type:'section',source_status:'current',path:'/tmp/b',revision:'b'.repeat(64),start_line:1,end_line:1,topics:[],tier:'initial'},
  ]};
  const bounded=capInitialCandidates(base,1);
  assert.equal(bounded.candidates.length,2);
  assert.equal(bounded.candidates.find(c=>c.id==='b')?.tier,'initial');
  assert.equal(bounded.candidates.find(c=>c.id==='a')?.tier,'broadened');
});

test('project snapshot refuses a missing source rather than silently narrowing the corpus', () => {
  assert.throws(()=>projectSnapshot(['/nonexistent/quix-missing-file.md']),/temporary catalog setup failed/);
});

test('bounded choices page through all candidates and distinguish duplicate titles', async () => {
  const candidates=Array.from({length:15},(_,i)=>({id:`id-${i.toString().padStart(2,'0')}`,title:'Same title',body:`source body ${i}`,record_type:'section',source_status:'current',path:'/tmp/unread',revision:'a'.repeat(64),start_line:1,end_line:1,topics:[],tier:'initial'}));
  const snapshot={version:1,task:'source',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:4,max_characters:5000,choice_mode:'bounded-v1',candidates};
  const seen=new Set<string>();
  const decider=fakeDecider((request,call)=>{
    const q=request.decisionQuestions['pick']; assert.equal(q?.type,'choice');
    const options=Object.entries(q.criteria); assert.ok(options.length<=9);
    for (const [,text] of options) if (text.startsWith('Inspect passage')) {
      const id=text.match(/source (id-\d+)/)?.[1]; assert.ok(id); seen.add(id);
      assert.match(text,/source body/);
    }
    const desired=call<3?'Next candidates':'Stop';
    const label=options.find(([,text])=>text.startsWith(desired))?.[0]; assert.ok(label);
    return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
  });
  await navigate(snapshot,decider);
  assert.equal(seen.size,15);
});

test('bounded pages expose the final candidate within the maximum step budget', async () => {
  const candidates=Array.from({length:100},(_,i)=>({id:`id-${i.toString().padStart(3,'0')}`,title:'Candidate',body:'matching source',record_type:'section',source_status:'current',path:'/tmp/unread',revision:'a'.repeat(64),start_line:1,end_line:1,topics:[],tier:'initial'}));
  const snapshot={version:1,task:'matching',role:'reviewer',role_version:'1',catalog_fingerprint:'fixture',max_steps:20,max_model_calls:20,max_characters:5000,choice_mode:'bounded-v1',candidates};
  let lastSeen=false;
  const decider=fakeDecider(request=>{
    const q=request.decisionQuestions['pick']; assert.equal(q?.type,'choice');
    const options=Object.entries(q.criteria);
    if (options.some(([,text])=>text.includes('source id-099'))) lastSeen=true;
    const label=options.find(([,text])=>text.startsWith(lastSeen?'Stop':'Next candidates'))?.[0]; assert.ok(label);
    return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
  });
  const result=await navigate(snapshot,decider);
  assert.equal(lastSeen,true);
  assert.equal(result.reason,'no_evidence');
  assert.ok(decider.requests.length<=20);
});
