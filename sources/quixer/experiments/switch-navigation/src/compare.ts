/** One-shot comparison adapter: a frozen snapshot on stdin and one JSON result on stdout. */
import { answered, fakeDecider } from '@osolmaz/switch/testing';
import { navigate } from './domain.ts';
import { snapshotSchema } from './quix-snapshot.ts';
import { loadOpenRouterSettings, OpenRouterDecider } from './openrouter-decider.ts';

async function main():Promise<void> {
  const mode=process.argv[2];
  if (mode!=='fixture' && mode!=='openrouter') throw new Error('invalid_request');
  const chunks:Buffer[]=[]; let total=0;
  for await (const chunk of process.stdin) {
    const bytes=Buffer.from(chunk as Uint8Array); total+=bytes.byteLength;
    if (total>24_000_000) throw new Error('invalid_request');
    chunks.push(bytes);
  }
  const snapshot=snapshotSchema.parse(JSON.parse(Buffer.concat(chunks).toString('utf8')));
  let calls=0;
  const fixture=fakeDecider(request=>{
    calls++;
    const q=request.decisionQuestions['pick'];
    if (q?.type!=='choice') throw new Error('unsupported question');
    const desired=calls===1?'Inspect passage':'Stop';
    const label=Object.entries(q.criteria).find(([,text])=>text.startsWith(desired))?.[0] ?? Object.keys(q.criteria)[0];
    if (!label) throw new Error('no available choice');
    return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
  });
  const settings=mode==='openrouter' ? await loadOpenRouterSettings(process.env.QUIX_OPENROUTER_ENV ?? '/Volumes/WS4TB/QUIX/.env',Number(process.env.QUIX_MODEL_SLOT ?? '2')) : null;
  const provider=settings ? new OpenRouterDecider({...settings,model:process.env.QUIX_DECISION_MODEL ?? settings.model,trials:2,maxRequests:Math.min(100,snapshot.max_model_calls*2),timeoutMs:15000}) : null;
  const result=await navigate(snapshot,provider ?? fixture);
  console.log(JSON.stringify({status:result.status,reason:result.reason,decision_detail:result.error,state:result.state,trace:result.trace.entries,model_requests:result.model_requests,logical_calls:result.model_calls,provider:provider?.model ?? 'fixture',receipts:provider?.receipts ?? []}));
}

try { await main(); }
catch { console.log(JSON.stringify({error:'invalid_request'})); process.exitCode=1; }
