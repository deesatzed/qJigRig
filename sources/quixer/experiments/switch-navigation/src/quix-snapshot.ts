import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { extname, isAbsolute } from 'node:path';
import { z } from 'zod';

const source = z.object({
  section_id:z.string().min(1).optional(),
  path:z.string().min(1).max(4096).refine(isAbsolute),
  revision:z.string().regex(/^[0-9a-f]{64}$/),
  source_status:z.enum(['current','superseded','invalidated']),
  start_line:z.number().int().positive().optional().nullable(), end_line:z.number().int().positive().optional().nullable(),
  page_start:z.number().int().positive().optional().nullable(), page_end:z.number().int().positive().optional().nullable(),
  start_offset:z.number().int().nonnegative().optional(), end_offset:z.number().int().positive().optional(), body_truncated:z.boolean().optional(),
}).passthrough().refine(s => (s.start_line != null && s.end_line != null && s.end_line >= s.start_line) || (s.page_start != null && s.page_end != null && s.page_end >= s.page_start));

const candidate = z.object({
  id:z.string().min(1).max(256), title:z.string().min(1).max(1000), body:z.string().min(1).max(100000),
  record_type:z.enum(['section','generated_index','agent_record']), source_status:z.string(),
  path:z.string().optional().nullable(), revision:z.string().optional().nullable(),
  start_line:z.number().int().positive().optional().nullable(), end_line:z.number().int().positive().optional().nullable(),
  page_start:z.number().int().positive().optional().nullable(), page_end:z.number().int().positive().optional().nullable(),
  start_offset:z.number().int().nonnegative().optional(), end_offset:z.number().int().positive().optional(), body_truncated:z.boolean().optional(),
  evidence_status:z.string().optional(), evidence:z.array(z.string().min(1)).max(100).optional(), evidence_sources:z.array(source).max(100).optional(),
  role_annotation:z.object({score:z.number().min(0).max(1),status:z.enum(['accepted','proposed']),method:z.string(),model:z.string().nullable(),source_revision:z.string().nullable(),scope:z.enum(['record','section','generated_index'])}).nullable().optional(),
  unsupported:z.boolean().optional(), topics:z.array(z.string().min(1).max(200)).max(50),
  topic_annotations:z.array(z.object({topic:z.string().min(1),status:z.enum(['accepted','proposed']),method:z.string()})).max(100).optional(),
  tier:z.enum(['initial','broadened']),
}).passthrough();

export const snapshotSchema = z.object({
  version:z.literal(1), task:z.string().min(1).max(1000), role:z.string().min(1).max(200),
  role_version:z.string().min(1).max(100), catalog_fingerprint:z.string().min(1).max(256),
  max_steps:z.number().int().min(1).max(20), max_characters:z.number().int().min(256).max(100000),
  max_model_calls:z.number().int().min(1).max(60).default(20),
  candidate_scope:z.enum(['sections_and_records','variant_specific']).default('variant_specific'),
  choice_mode:z.literal('bounded-v1').optional(),
  source_verification:z.literal('deferred_per_candidate').optional(),
  candidates:z.array(candidate).max(100),
}).strict().refine(s => new Set(s.candidates.map(c => c.id)).size === s.candidates.length, 'candidate IDs must be unique');

export type Snapshot = z.infer<typeof snapshotSchema>;
export type Candidate = z.infer<typeof candidate>;

async function verifySource(input: unknown): Promise<string|null> {
  const s = source.parse(input);
  if (s.source_status !== 'current') throw new Error('unsupported_evidence');
  const bytes = await readFile(s.path);
  let hashed = bytes;
  let text: string|null = null;
  if (extname(s.path).toLowerCase() !== '.pdf') {
    text = new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes).replace(/\r\n?/g,'\n');
    hashed = Buffer.from(text,'utf8');
  }
  if (createHash('sha256').update(hashed).digest('hex') !== s.revision) throw new Error('source_changed');
  return text;
}

export async function verifyCandidate(c: Candidate): Promise<void> {
  if (c.record_type === 'agent_record') {
    if (!['current','proposed'].includes(c.source_status) || c.unsupported !== false || c.evidence_status !== 'current' || !c.evidence_sources?.length || !c.evidence?.length || c.evidence.length !== c.evidence_sources.length || new Set(c.evidence).size !== c.evidence.length || new Set(c.evidence_sources.map(s=>s.section_id)).size !== c.evidence.length || c.evidence_sources.some(s => !s.section_id || !c.evidence?.includes(s.section_id))) throw new Error('unsupported_evidence');
    for (const evidence of c.evidence_sources) await verifySource(evidence);
  } else {
    const text = await verifySource(c);
    if (text !== null) {
      if (c.start_line == null || c.end_line == null) throw new Error('unsupported_evidence');
      const lines = text.split(/[\n\v\f\u001c-\u001e\u0085\u2028\u2029]/u);
      if (lines.at(-1) === '') lines.pop();
      if (c.end_line > lines.length) throw new Error('source_span_mismatch');
      let span = lines.slice(c.start_line-1,c.end_line).join('\n');
      if (c.record_type === 'generated_index') {
        if (c.start_offset === undefined || c.end_offset === undefined || c.end_offset <= c.start_offset) throw new Error('source_span_mismatch');
        span = [...span].slice(c.start_offset,c.end_offset).join('');
      }
      if (c.body_truncated ? !span.startsWith(c.body) : span !== c.body) throw new Error('source_span_mismatch');
    }
  }
}
