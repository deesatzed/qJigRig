/** Local, fake-decider smoke using the two project plan documents; no model calls. */
import { answered, fakeDecider } from '@osolmaz/switch/testing';
import { navigate } from './domain.ts';
import { projectSnapshot } from './project-snapshot.ts';

const snapshot = projectSnapshot();
const decider = fakeDecider((request,call)=>{
  const question=request.decisionQuestions['pick'];
  if (question?.type !== 'choice') throw new Error('unexpected question');
  const label=Object.entries(question.criteria).find(([,text])=>text.startsWith(call===1?'Inspect passage':'Stop'))?.[0];
  if (!label) throw new Error('expected choice unavailable');
  return answered({pick:{type:'choice',choice:label,probabilities:{[label]:1},confidence:1}});
});
const result=await navigate(snapshot,decider);
console.log(JSON.stringify({provider:'fixture',corpus_fingerprint:snapshot.catalog_fingerprint,candidates:snapshot.candidates.length,calls:result.model_calls,status:result.status,reason:result.reason,evidence:result.state.evidence.map(item=>({id:item.id,record_type:item.record_type,content_verification:item.content_verification}))}));
if (result.status !== 'complete') process.exitCode=1;
