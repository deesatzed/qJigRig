import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { snapshotSchema } from './quix-snapshot.ts';

/** Rank the initial candidates deterministically; every other candidate remains broadenable. */
export function capInitialCandidates(input:unknown, limit:number) {
  const snapshot=snapshotSchema.parse(input);
  if (!Number.isInteger(limit) || limit<1 || limit>100) throw new Error('invalid initial candidate limit');
  const terms=new Set(snapshot.task.toLowerCase().match(/[\p{L}\p{N}_]+/gu) ?? []);
  const rank=(text:string) => new Set(text.toLowerCase().match(/[\p{L}\p{N}_]+/gu) ?? []);
  const initial=snapshot.candidates.filter(c=>c.tier==='initial').map(c=>({id:c.id,score:[...rank(c.title+' '+c.body)].filter(t=>terms.has(t)).length})).sort((a,b)=>b.score-a.score || a.id.localeCompare(b.id)).slice(0,limit);
  const selected=new Set(initial.map(item=>item.id));
  return {...snapshot,candidates:snapshot.candidates.map(c=>({...c,tier:selected.has(c.id)?'initial' as const:'broadened' as const}))};
}

/** Build a fresh in-memory catalog of the two approved project documents. */
export function projectSnapshot(sourceFiles?: readonly string[]) {
  const repo=resolve(dirname(fileURLToPath(import.meta.url)),'../../..');
  const files=sourceFiles ?? ['docs/plans/2026-10-29-shared-knowledge-design.md','docs/plans/2026-10-29-shared-knowledge-implementation.md'].map(p=>resolve(repo,p));
  if (!files.length) throw new Error('temporary catalog setup failed');
  const script="import json,sys; from quix_knowledge.store import open_catalog; from quix_knowledge.ingest import ingest; from quix_knowledge.switch_snapshot import build_snapshot; db=open_catalog(':memory:'); sources=[ingest(db,p) for p in sys.argv[1:]]; assert all(sources); print(json.dumps(build_snapshot(db,task='retrieval evidence role',role='reviewer',role_version='1',max_steps=4,max_model_calls=4,max_characters=5000)))";
  const result=spawnSync('python',['-c',script,...files],{encoding:'utf8',env:{PATH:process.env.PATH ?? '/usr/bin:/bin',PYTHONPATH:resolve(repo,'src')},maxBuffer:10_000_000});
  if (result.status!==0) throw new Error('temporary catalog setup failed');
  return capInitialCandidates(JSON.parse(result.stdout),3);
}
