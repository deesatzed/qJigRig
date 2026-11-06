import { createHash } from 'node:crypto';
import { picking, recordedModel, run, Trace, type Choice, type Decider, type DecisionRequest, type DomainShared, type JsonObject, type Replay, type RunResult, type StateMachine, type TraceEntry } from '@osolmaz/switch';
import { snapshotSchema, verifyCandidate, type Snapshot } from './quix-snapshot.ts';

export const NAVIGATION: DomainShared = {name:'quix-navigation',version:'0.1.0',limits:{steps:20,windowShare:0.9}};

interface EvidenceSource extends JsonObject { readonly path:string; readonly revision:string; readonly start_line:number|null; readonly end_line:number|null; readonly page_start:number|null; readonly page_end:number|null; readonly section_id:string|null }
interface Evidence extends JsonObject { readonly id:string; readonly record_type:string; readonly status:string; readonly index_status:string|null; readonly content_verification:string; readonly sources:readonly EvidenceSource[]; readonly text:string; readonly truncated:boolean }
interface TopicAnnotation extends JsonObject { readonly candidate_id:string; readonly status:string; readonly method:string }
interface TopicResult extends JsonObject { readonly topic:string; readonly candidate_ids:readonly string[]; readonly annotations:readonly TopicAnnotation[] }
interface NavigationState extends JsonObject {
  readonly evidence: readonly Evidence[];
  readonly visited_topics: readonly string[];
  readonly topics_found: readonly TopicResult[];
  readonly broadened:boolean;
  readonly done:boolean;
  readonly reason:string|null;
  readonly steps:number;
}
interface NavigationChoice extends Choice { readonly target:string }

function boundedView(snapshot: Snapshot, state: NavigationState, max: number): JsonObject {
  const evidence: {id:string; record_type:string; status:string; content_verification:string; text:string; truncated:boolean}[] = [];
  const topics: TopicResult[] = [];
  const view = {task:snapshot.task,role:snapshot.role,role_version:snapshot.role_version,topics_found:topics,evidence,view_truncated:false,omitted_topics:state.topics_found.length,omitted_evidence:state.evidence.length};
  const size = () => JSON.stringify(view).length;
  if (size() > max) throw new Error('view_budget_exceeded');
  for (const topic of state.topics_found) {
    topics.push(topic); view.omitted_topics -= 1;
    if (size() > max) { topics.pop(); view.omitted_topics += 1; view.view_truncated = true; }
  }
  for (const item of state.evidence) {
    const entry = {id:item.id,record_type:item.record_type,status:item.status,content_verification:item.content_verification,text:item.text,truncated:item.truncated};
    evidence.push(entry); view.omitted_evidence -= 1;
    if (size() <= max) { if (entry.truncated) view.view_truncated = true; continue; }
    view.view_truncated = true; entry.truncated = true;
    const chars = [...item.text]; let lo=0, hi=chars.length;
    entry.text = '';
    if (size() > max) { evidence.pop(); view.omitted_evidence += 1; continue; }
    while (lo < hi) {
      const mid = Math.ceil((lo+hi)/2); entry.text=chars.slice(0,mid).join('');
      if (size() <= max) lo=mid; else hi=mid-1;
    }
    entry.text=chars.slice(0,lo).join('');
    if (!entry.text) { evidence.pop(); view.omitted_evidence += 1; }
  }
  if (size() > max) throw new Error('view_budget_exceeded');
  return view;
}

export function createNavigation(input: unknown): StateMachine<NavigationState> {
  const snapshot: Snapshot = snapshotSchema.parse(input);
  const pick = picking<NavigationState, NavigationChoice>({
    instructions:'Choose one available evidence-gathering step or stop.', limit:100,
    choices: state => {
      if (snapshot.choice_mode === 'bounded-v1') {
        const words = (text:string) => new Set((text.toLowerCase().match(/[\p{L}\p{N}_]+/gu) ?? []));
        const query = words(snapshot.task);
        const ranked = [...snapshot.candidates].sort((a,b) => {
          const score = (c:typeof a) => [...words(c.title+' '+c.body+' '+c.topics.join(' '))].filter(w=>query.has(w)).length;
          return score(b)-score(a) || a.id.localeCompare(b.id);
        });
        const page = Math.min((typeof state['choice_page'] === 'number' ? state['choice_page'] : 0),Math.max(0,Math.ceil(ranked.length/6)-1));
        const visible = ranked.slice(page*6,page*6+6);
        const options:NavigationChoice[]=[];
        const topics=[...new Set(visible.flatMap(c=>c.topics))].filter(t=>[...words(t)].some(w=>query.has(w))).sort().slice(0,2);
        for (const topic of topics) if (!state.visited_topics.includes(topic)) options.push({type:'inspect_topic',key:`topic:${topic}`,target:topic,text:`Inspect topic: ${topic}`});
        for (const c of visible) if (!state.evidence.some(e=>e.id===c.id)) {
          const snippet=c.body.replace(/\s+/g,' ').slice(0,100);
          options.push({type:'inspect_span',key:`span:${c.id}`,target:c.id,text:`Inspect passage: ${c.title} [source ${c.id}] — ${snippet}`});
        }
        if (page>0) options.push({type:'broaden',key:'page:previous',target:'previous',text:'Previous candidates'});
        if ((page+1)*6<ranked.length) options.push({type:'broaden',key:'page:next',target:'next',text:'Next candidates'});
        options.push({type:'stop',key:'stop',target:'',text:'Stop gathering',priority:-1});
        return options;
      }
      const candidates = snapshot.candidates.filter(c => c.tier === 'initial' || state.broadened);
      const options: NavigationChoice[] = [];
      for (const topic of [...new Set(candidates.flatMap(c => c.topics))].sort()) {
        if (!state.visited_topics.includes(topic)) options.push({type:'inspect_topic',key:`topic:${topic}`,target:topic,text:`Inspect topic: ${topic}`});
      }
      for (const c of candidates) {
        const roleNote=c.role_annotation ? ` [uncalibrated role estimate ${c.role_annotation.score}; ${c.role_annotation.status}]` : '';
        if (!state.evidence.some(e => e.id === c.id)) options.push({type:'inspect_span',key:`span:${c.id}`,target:c.id,text:`Inspect passage: ${c.title}${roleNote} [source ${c.id}]`});
      }
      if (!state.broadened && snapshot.candidates.some(c => c.tier === 'broadened')) options.push({type:'broaden',key:'broaden',target:'',text:'Broaden the candidate set'});
      options.push({type:'stop',key:'stop',target:'',text:'Stop gathering',priority:-1});
      return options;
    },
    transition: async (state,choice) => {
      const steps = state.steps + 1;
      if (choice.type === 'stop') return {...state,steps,done:true,reason:null};
      if (choice.type === 'broaden') {
        if (snapshot.choice_mode === 'bounded-v1') return {...state,steps,broadened:true,choice_page:Math.max(0,(typeof state['choice_page'] === 'number' ? state['choice_page'] : 0)+(choice.target === 'previous' ? -1 : 1))};
        return {...state,steps,broadened:true};
      }
      if (choice.type === 'inspect_topic') {
        const members = snapshot.candidates.filter(c => (snapshot.choice_mode === 'bounded-v1' || c.tier === 'initial' || state.broadened) && c.topics.includes(choice.target));
        const candidate_ids = members.map(c => c.id);
        const annotations = members.flatMap(c => {
          const matches=(c.topic_annotations ?? []).filter(a => a.topic===choice.target);
          return matches.length ? matches.map(a=>({candidate_id:c.id,status:a.status,method:a.method})) : [{candidate_id:c.id,status:'unverified',method:'unknown'}];
        });
        return {...state,steps,visited_topics:[...state.visited_topics,choice.target],topics_found:[...state.topics_found,{topic:choice.target,candidate_ids,annotations}]};
      }
      const c = snapshot.candidates.find(item => item.id === choice.target);
      if (!c) return {...state,steps,done:true,reason:'missing_candidate'};
      try { await verifyCandidate(c); } catch (error) { return {...state,steps,done:true,reason:error instanceof Error && error.message === 'unsupported_evidence' ? 'unsupported_evidence' : 'source_unavailable_or_changed'}; }
      const used = state.evidence.reduce((n,e) => n + [...e.text].length,0);
      const available = Math.max(0,snapshot.max_characters-used);
      const chars = [...c.body];
      if (!available) return {...state,steps,done:true,reason:'character_budget_exhausted'};
      const rawSources = c.record_type === 'agent_record' ? c.evidence_sources ?? [] : [{path:c.path,revision:c.revision,start_line:c.start_line,end_line:c.end_line,page_start:c.page_start,page_end:c.page_end,section_id:c.id}];
      const sources: EvidenceSource[] = rawSources.map(s => ({path:s.path ?? '',revision:s.revision ?? '',start_line:s.start_line ?? null,end_line:s.end_line ?? null,page_start:s.page_start ?? null,page_end:s.page_end ?? null,section_id:s.section_id ?? null}));
      const content_verification = c.record_type === 'agent_record' ? 'agent_claim_unverified' : c.path?.toLowerCase().endsWith('.pdf') ? 'pdf_revision_only' : 'source_text_span';
      const evidence: Evidence = {id:c.id,record_type:c.record_type,status:c.source_status,index_status:typeof c['index_status'] === 'string' ? c['index_status'] : null,content_verification,sources,text:chars.slice(0,available).join(''),truncated:c.body_truncated === true || chars.length>available};
      return {...state,steps,evidence:[...state.evidence,evidence]};
    },
  });
  return {
    initial: async () => ({evidence:[],visited_topics:[],topics_found:[],broadened:false,done:false,reason:null,steps:0}),
    questions: state => state.done || state.steps >= snapshot.max_steps ? {} : pick.questions(state),
    transition: pick.transition,
    view: async (state,tokens,charsPerToken) => {
      const max = Math.min(snapshot.max_characters,Math.floor(tokens*charsPerToken));
      return {decisionState:boundedView(snapshot,state,max)};
    },
  };
}

function caseID(snapshot: Snapshot): string {
  return createHash('sha256').update(JSON.stringify(snapshot)).digest('hex');
}

async function finish(snapshot: Snapshot, result: RunResult<NavigationState>) {
  let state = result.state;
  for (const item of state.evidence) {
    const candidate = snapshot.candidates.find(c => c.id === item.id);
    try {
      if (!candidate) throw new Error('missing_candidate');
      await verifyCandidate(candidate);
    } catch {
      state = {...state,evidence:[],done:true,reason:'source_unavailable_or_changed'};
      break;
    }
  }
  const reason = state.reason ?? (result.ended === 'failed' ? 'decision_failed' : result.ended === 'step limit' || (!state.done && state.steps >= snapshot.max_steps) ? 'step_limit' : state.evidence.length ? null : 'no_evidence');
  return {...result,state,status:reason === null ? 'complete' as const : 'insufficient_evidence' as const,reason};
}

export async function navigate(input: unknown, decider: Decider) {
  const snapshot = snapshotSchema.parse(input);
  const machine = createNavigation(snapshot);
  const trace = new Trace();
  const model_requests: DecisionRequest[] = [];
  const safeDecider: Decider = {model:decider.model,window:decider.window,charsPerToken:decider.charsPerToken,decide:async request => {
    if (model_requests.length >= snapshot.max_model_calls) return {decisionAnswers:{},api:'unknown',provider:'unknown',model:decider.model,stopReason:'error',errorMessage:'model call limit reached',timestamp:Date.now(),tooLong:false,milliseconds:0};
    model_requests.push(structuredClone(request));
    try { return await decider.decide(request); }
    catch { return {decisionAnswers:{},api:'unknown',provider:'unknown',model:decider.model,stopReason:'error',errorMessage:'decision request failed',timestamp:Date.now(),tooLong:false,milliseconds:0}; }
  }};
  try {
    const result = await run({...NAVIGATION,limits:{...NAVIGATION.limits,steps:snapshot.max_steps}},machine,safeDecider,{case:caseID(snapshot),trace});
    return {...await finish(snapshot,result),model_requests,model_calls:model_requests.length};
  } catch {
    return {steps:0,ended:'failed' as const,error:'navigation failed',trace,state:await machine.initial(),status:'insufficient_evidence' as const,reason:'navigation_failed',model_requests,model_calls:model_requests.length};
  }
}

export async function replayNavigation(input: unknown, replay: Replay, entries: readonly TraceEntry[]) {
  const snapshot = snapshotSchema.parse(input);
  const result = await run({...NAVIGATION,limits:{...NAVIGATION.limits,steps:snapshot.max_steps}},createNavigation(snapshot),recordedModel(entries),{case:caseID(snapshot),replay});
  return finish(snapshot,result);
}
