/** Bounded live OpenRouter integration check; raw trace stays in an ignored local directory. */
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { navigate } from './domain.ts';
import { loadOpenRouterSettings, OpenRouterDecider } from './openrouter-decider.ts';
import { projectSnapshot } from './project-snapshot.ts';

const snapshot=projectSnapshot();
const slot=Number(process.env.QUIX_MODEL_SLOT ?? '2');
const settings=await loadOpenRouterSettings(process.env.QUIX_OPENROUTER_ENV ?? '/Volumes/WS4TB/QUIX/.env',slot);
const decider=new OpenRouterDecider({...settings,trials:2,maxRequests:8,timeoutMs:15000});
const started=Date.now();
const result=await navigate(snapshot,decider);
const costs=decider.receipts.map(receipt=>receipt.usage?.cost);
const tokens=decider.receipts.map(receipt=>receipt.usage?.input_tokens);
const reportedCost=costs.length && costs.every((x):x is number=>x!==undefined) ? costs.reduce((a,b)=>a+b,0) : null;
const inputTokens=tokens.length && tokens.every((x):x is number=>x!==undefined) ? tokens.reduce((a,b)=>a+b,0) : null;
const local=resolve(dirname(fileURLToPath(import.meta.url)),'../../../.local');
await mkdir(local,{recursive:true});
const filename=resolve(local,`switch-live-${Date.now()}.json`);
await writeFile(filename,JSON.stringify({snapshot,result:{...result,trace:result.trace.entries},receipts:decider.receipts},null,2),{encoding:'utf8',flag:'wx'});
console.log(JSON.stringify({model:settings.model,resolved_models:[...new Set(decider.receipts.map(r=>r.resolved_model).filter(Boolean))],corpus_fingerprint:snapshot.catalog_fingerprint,candidates:snapshot.candidates.length,logical_calls:result.model_calls,physical_requests:decider.receipts.length,status:result.status,reason:result.reason,decision_detail:result.error,evidence_count:result.state.evidence.length,reported_cost:reportedCost,input_tokens:inputTokens,elapsed_ms:Date.now()-started,local_report:filename}));
