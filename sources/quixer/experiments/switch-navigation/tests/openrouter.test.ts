import test from 'node:test';
import assert from 'node:assert/strict';
import { OpenRouterDecider } from '../src/openrouter-decider.ts';
import type { DecisionRequest } from '@osolmaz/switch';

const request: DecisionRequest = {decisionState:{task:'synthetic'},decisionQuestions:{pick:{type:'choice',instructions:'Pick one',criteria:{o1:'read',o2:'stop'}}}};

test('maps stable choice answers and records actual usage without credentials', async () => {
  const orders:string[][]=[];
  const decider=new OpenRouterDecider({apiKey:'fixture-secret',model:'fixture/model',trials:2,maxRequests:2,timeoutMs:1000,transport:async payload=>{
    const q=payload.questions.pick;
    orders.push(Object.keys(q.criteria));
    return {model:'fixture/resolved',answers:{pick:{type:'choice',choice:'o1',probabilities:{o1:0.8,o2:0.2},confidence:0.6}},usage:{input_tokens:10,output_tokens:1,cost:0.0001}};
  }});
  const result=await decider.decide(request);
  assert.equal(result.stopReason,'stop');
  assert.equal(result.decisionAnswers.pick?.type,'choice');
  assert.deepEqual(orders,[['o1','o2'],['o2','o1']]);
  assert.equal(decider.receipts.length,2);
  assert.equal(decider.receipts[0]?.choice,'o1');
  assert.deepEqual(decider.receipts[1]?.choice_order,['o2','o1']);
  assert.equal(decider.receipts[0]?.usage?.cost,0.0001);
  assert.equal(JSON.stringify(decider.receipts).includes('fixture-secret'),false);
  assert.equal(JSON.stringify(decider).includes('fixture-secret'),false);
});

test('abstains on inconsistent option order or malformed response', async () => {
  let calls=0;
  const decider=new OpenRouterDecider({apiKey:'fixture-secret',model:'fixture/model',trials:2,maxRequests:2,timeoutMs:1000,transport:async()=>{
    calls++;
    return {model:'fixture/resolved',answers:{pick:{type:'choice',choice:calls===1?'o1':'o2',probabilities:calls===1?{o1:0.8,o2:0.2}:{o1:0.2,o2:0.8},confidence:0.6}}};
  }});
  const unstable=await decider.decide(request);
  assert.equal(unstable.stopReason,'error');
  assert.equal(unstable.errorMessage,'unstable_choice');
  const invalid=new OpenRouterDecider({apiKey:'fixture-secret',model:'fixture/model',trials:1,maxRequests:1,timeoutMs:1000,transport:async()=>({answers:{pick:{type:'choice',choice:'not-offered'}}})});
  const malformed=await invalid.decide(request);
  assert.equal(malformed.stopReason,'error');
  assert.equal(malformed.errorMessage,'invalid_response');
});

test('bounds physical requests and times out a stalled transport', async () => {
  const decider=new OpenRouterDecider({apiKey:'fixture-secret',model:'fixture/model',trials:2,maxRequests:1,timeoutMs:20,transport:async()=>await new Promise(()=>{})});
  const result=await decider.decide(request);
  assert.equal(result.stopReason,'error');
  assert.equal(result.errorMessage,'timeout');
  assert.equal(decider.receipts.length,1);
  assert.equal(decider.receipts[0]?.status,'timeout');
});

test('physical request cap holds under concurrent calls', async () => {
  let calls=0;
  const decider=new OpenRouterDecider({apiKey:'fixture-secret',model:'fixture/model',trials:1,maxRequests:1,timeoutMs:1000,transport:async()=>{
    calls++;
    await new Promise(resolve=>setTimeout(resolve,10));
    return {model:'fixture/resolved',answers:{pick:{type:'choice',choice:'o1',probabilities:{o1:0.8,o2:0.2},confidence:0.6}}};
  }});
  const results=await Promise.all([decider.decide(request),decider.decide(request)]);
  assert.equal(calls,1);
  assert.equal(results.filter(result=>result.stopReason==='stop').length,1);
});

test('default transport stops reading an oversized response', async () => {
  const original=globalThis.fetch; let cancelled=false; let chunks=0;
  globalThis.fetch=async()=>new Response(new ReadableStream<Uint8Array>({
    pull(controller) { if (chunks===3) { controller.close(); return; } chunks++; controller.enqueue(new Uint8Array(600_000)); },
    cancel() { cancelled=true; },
  }));
  try {
    const decider=new OpenRouterDecider({apiKey:'fixture-secret',model:'fixture/model',trials:1,maxRequests:1,timeoutMs:1000});
    const result=await decider.decide(request);
    assert.equal(result.stopReason,'error');
    assert.equal(cancelled,true);
    assert.ok(chunks<=3);
  } finally { globalThis.fetch=original; }
});
