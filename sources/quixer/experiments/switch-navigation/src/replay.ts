/** Replay a source-bound snapshot and recorded trace without contacting a model. */
import { createHash } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';
import { parseTrace, replayOf } from '@osolmaz/switch';
import { z } from 'zod';
import { replayNavigation } from './domain.ts';
import { snapshotSchema } from './quix-snapshot.ts';

async function main():Promise<void> {
  const chunks:Buffer[]=[]; let total=0;
  for await (const chunk of process.stdin) {
    const bytes=Buffer.from(chunk as Uint8Array); total+=bytes.byteLength;
    if (total>24_000_000) throw new Error('input limit');
    chunks.push(bytes);
  }
  const input=z.object({snapshot:snapshotSchema,trace:z.array(z.unknown()).min(1).max(1000)}).strict()
    .parse(JSON.parse(Buffer.concat(chunks).toString('utf8')));
  const jsonl=input.trace.map(entry=>JSON.stringify(entry)).join('\n');
  const entries=parseTrace(jsonl);
  const recorded=replayOf(entries);
  const result=await replayNavigation(input.snapshot,recorded,entries);
  if (!isDeepStrictEqual(result.state,recorded.states.at(-1))) throw new Error('state mismatch');
  console.log(JSON.stringify({status:result.status,reason:result.reason,ended:result.ended,
    evidence_count:result.state.evidence.length,model_calls:0,catalog_fingerprint:input.snapshot.catalog_fingerprint,
    trace_sha256:createHash('sha256').update(jsonl).digest('hex')}));
}

try { await main(); }
catch { console.log(JSON.stringify({error:'replay_failed'})); process.exitCode=1; }
