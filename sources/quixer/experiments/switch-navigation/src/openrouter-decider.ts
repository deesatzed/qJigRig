import { readFile } from 'node:fs/promises';
import { z } from 'zod';
import type { ChoiceAnswer, Decider, DecisionRequest, DecisionResult, JsonObject } from '@osolmaz/switch';

type ChoicePayload = {model:string;state:JsonObject;questions:{pick:{type:'choice';instructions:string;criteria:Record<string,string>}}};
type Transport = (payload:ChoicePayload, signal:AbortSignal)=>Promise<unknown>;
type Usage = {input_tokens?:number;output_tokens?:number;cost?:number};
export type DecisionReceipt = {status:'ok'|'timeout'|'invalid'|'error';resolved_model?:string;choice?:string;choice_order?:string[];usage?:Usage;elapsed_ms:number};
type Settings = {apiKey:string;model:string;trials:1|2;maxRequests:number;timeoutMs:number;transport?:Transport};

const answerSchema = z.object({
  model:z.string().min(1),
  answers:z.object({pick:z.object({type:z.literal('choice'),choice:z.string(),probabilities:z.record(z.string(),z.number().min(0).max(1)),confidence:z.number().min(0).max(1)})}),
  usage:z.object({input_tokens:z.number().int().nonnegative().optional(),output_tokens:z.number().int().nonnegative().optional(),cost:z.number().nonnegative().optional()}).optional(),
});

async function readBounded(response:Response):Promise<string> {
  if (!response.body) throw new Error('provider_empty_response');
  const reader=response.body.getReader(); const chunks:Uint8Array[]=[]; let total=0;
  try {
    for (;;) {
      const {done,value}=await reader.read();
      if (done) break;
      total+=value.byteLength;
      if (total>1_000_000) { await reader.cancel(); throw new Error('provider_response_too_large'); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  return new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks));
}

export async function loadOpenRouterSettings(path:string,slot:number): Promise<{apiKey:string;model:string}> {
  if (!Number.isInteger(slot) || slot<1 || slot>4) throw new Error('invalid model slot');
  const wanted=new Set(['OPENROUTER_API_KEY',`OPENROUTER_DEC_MODEL_${slot}`]);
  const values:Record<string,string>={};
  for (const raw of (await readFile(path,'utf8')).split(/\r?\n/)) {
    const line=raw.trim().replace(/^export\s+/,'');
    if (!line || line.startsWith('#') || !line.includes('=')) continue;
    const pos=line.indexOf('='); const key=line.slice(0,pos).trim();
    if (wanted.has(key)) values[key]=line.slice(pos+1).trim().replace(/^["']|["']$/g,'');
  }
  const apiKey=values.OPENROUTER_API_KEY; const model=values[`OPENROUTER_DEC_MODEL_${slot}`];
  if (!apiKey || !model) throw new Error('OpenRouter settings incomplete');
  return {apiKey,model};
}

export class OpenRouterDecider implements Decider {
  readonly model:string;
  readonly window=4096; // Local request ceiling, not a claim about the provider's full context window.
  readonly charsPerToken=3;
  readonly receipts:DecisionReceipt[]=[];
  #issuedRequests=0;
  readonly #config:Settings;
  readonly #transport:Transport;

  constructor(config:Settings) {
    if (!config.apiKey || !config.model || ![1,2].includes(config.trials) || !Number.isInteger(config.maxRequests) || config.maxRequests<1 || config.maxRequests>100 || !Number.isInteger(config.timeoutMs) || config.timeoutMs<1 || config.timeoutMs>60000) throw new Error('invalid OpenRouter configuration');
    this.model=config.model; this.#config=config;
    this.#transport=config.transport ?? (async (payload,signal)=>{
      const response=await fetch('https://openrouter.ai/api/alpha/decisions',{method:'POST',headers:{Authorization:`Bearer ${config.apiKey}`,'Content-Type':'application/json'},body:JSON.stringify(payload),signal});
      if (!response.ok) throw new Error('provider_http_error');
      const text=await readBounded(response);
      return JSON.parse(text) as unknown;
    });
  }

  async decide(request:DecisionRequest):Promise<DecisionResult> {
    const started=Date.now();
    const base={api:'openrouter-decisions',provider:'openrouter',model:this.model,timestamp:started,tooLong:false};
    const failure=(reason:string):DecisionResult=>({...base,decisionAnswers:{},stopReason:'error',errorMessage:reason,milliseconds:Date.now()-started});
    const q=request.decisionQuestions['pick'];
    if (Object.keys(request.decisionQuestions).length!==1 || q?.type!=='choice' || request.decisionImages?.length) return failure('unsupported_request');
    const keys=Object.keys(q.criteria);
    if (keys.length<2 || keys.length>255) return failure('unsupported_request');
    let selected:ChoiceAnswer|undefined; let resolved:string|undefined;
    for (let trial=0;trial<this.#config.trials;trial++) {
      if (this.#issuedRequests>=this.#config.maxRequests) return failure('request_limit');
      this.#issuedRequests += 1;
      const ordered=trial===0 ? keys : [...keys].reverse();
      const criteria=Object.fromEntries(ordered.map(key=>[key,q.criteria[key]!]));
      const payload:ChoicePayload={model:this.model,state:request.decisionState,questions:{pick:{type:'choice',instructions:q.instructions,criteria}}};
      const begin=Date.now(); const controller=new AbortController();
      let timer:ReturnType<typeof setTimeout>|undefined;
      try {
        const timed=new Promise<never>((_,reject)=>{timer=setTimeout(()=>{controller.abort(); reject(new Error('timeout'));},this.#config.timeoutMs);});
        const raw=await Promise.race([this.#transport(payload,controller.signal),timed]);
        const parsed=answerSchema.safeParse(raw);
        if (!parsed.success) { this.receipts.push({status:'invalid',elapsed_ms:Date.now()-begin}); return failure('invalid_response'); }
        const {model,answers,usage}=parsed.data; const answer=answers.pick;
        const probabilityKeys=Object.keys(answer.probabilities);
        const valid=probabilityKeys.length===keys.length && keys.every(k=>Object.hasOwn(answer.probabilities,k)) && keys.includes(answer.choice) && Math.abs(Object.values(answer.probabilities).reduce((a,b)=>a+b,0)-1)<0.01 && answer.probabilities[answer.choice]===Math.max(...Object.values(answer.probabilities));
        this.receipts.push({status:valid?'ok':'invalid',resolved_model:model,choice:answer.choice,choice_order:ordered,...(usage?{usage}:{}),elapsed_ms:Date.now()-begin});
        if (!valid) return failure('invalid_response');
        if (resolved!==undefined && resolved!==model) return failure('model_changed');
        if (selected!==undefined && selected.choice!==answer.choice) return failure('unstable_choice');
        resolved=model;
        selected={type:'choice',choice:answer.choice,probabilities:answer.probabilities,confidence:answer.confidence};
      } catch (error) {
        const timeout=error instanceof Error && error.message==='timeout';
        this.receipts.push({status:timeout?'timeout':'error',elapsed_ms:Date.now()-begin});
        return failure(timeout?'timeout':'provider_error');
      } finally { if (timer!==undefined) clearTimeout(timer); }
    }
    if (!selected || !resolved) return failure('invalid_response');
    return {...base,model:resolved,decisionAnswers:{pick:selected},stopReason:'stop',milliseconds:Date.now()-started};
  }
}
