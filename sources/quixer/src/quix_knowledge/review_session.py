"""A local, resumable human-review draft without access to condition keys."""
import copy
from datetime import date
import json
import os
from pathlib import Path
import tempfile

_RUBRIC={'correctness':{'correct','partial','incorrect','unknown'},
    'source_support':{'supported','partial','unsupported','no_citations','unknown'},
    'missing_evidence':{'none','material','unknown'},'task_completion':{'complete','partial','incomplete','unknown'}}


def _immutable(packet):
    result=copy.deepcopy(packet)
    result.pop('reviewer',None)
    if result.get('schema')=='quix-blind-review-v1':
        for item in result['tasks']:
            for name in ('labels','reviewed','missing_reason','reviewed_at'): item.pop(name,None)
    elif result.get('schema')=='quix-agent-outcome-review-v1':
        result.pop('reviewed_at',None)
        for item in result['items']: item.pop('review',None)
    else:
        raise ValueError('unsupported review packet')
    return result


class ReviewSession:
    def __init__(self, source, output, reviewer):
        self.source=Path(source).resolve(); self.output=Path(output).resolve()
        if self.source==self.output: raise ValueError('draft must not overwrite source packet')
        if not isinstance(reviewer,str) or not reviewer.strip(): raise ValueError('reviewer is required')
        self.reviewer=reviewer.strip()
        original=json.loads(self.source.read_text(encoding='utf-8'))
        contract=_immutable(original)
        self.packet=json.loads(self.output.read_text(encoding='utf-8')) if self.output.exists() else copy.deepcopy(original)
        if _immutable(self.packet)!=contract: raise ValueError('draft contract changed')
        prior=self.packet.get('reviewer')
        if prior is not None and prior!=self.reviewer: raise ValueError('draft reviewer differs')
        self.packet['reviewer']=self.reviewer
        self.kind='retrieval' if self.packet['schema']=='quix-blind-review-v1' else 'outcome'
        self.items=self.packet['tasks' if self.kind=='retrieval' else 'items']
        self.candidates=self.packet.get('candidates' if self.kind=='retrieval' else 'source_candidates',[])
        if not isinstance(self.items,list) or not isinstance(self.candidates,list) or any(not isinstance(x,dict) or not isinstance(x.get('id'),str) for x in self.candidates):
            raise ValueError('invalid packet material')
        self.source_ids={x['id'] for x in self.candidates}
        if len(self.source_ids)!=len(self.candidates): raise ValueError('duplicate source IDs')

    def _valid_sources(self, ids):
        if not isinstance(ids,list) or any(not isinstance(x,str) or not x for x in ids) or len(set(ids))!=len(ids) or not set(ids)<=self.source_ids:
            raise ValueError('invalid source IDs')

    def _save(self):
        self.output.parent.mkdir(parents=True,exist_ok=True)
        path=None
        try:
            with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=self.output.parent,delete=False) as stream:
                path=Path(stream.name)
                json.dump(self.packet,stream,ensure_ascii=False,indent=2)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(path,self.output)
        finally:
            if path is not None and path.exists(): path.unlink()

    def record_retrieval(self, index, labels, *, missing_reason=None, reviewed_at=None):
        if self.kind!='retrieval' or type(index) is not int or not 0 <= index < len(self.items): raise ValueError('invalid retrieval task')
        self._valid_sources(labels)
        if not labels and (not isinstance(missing_reason,str) or not missing_reason.strip()): raise ValueError('empty labels require a reason')
        if reviewed_at is not None:
            try:
                if not isinstance(reviewed_at,str) or date.fromisoformat(reviewed_at).isoformat()!=reviewed_at: raise ValueError
            except ValueError:
                raise ValueError('invalid review date') from None
        self.items[index].update(labels=list(labels),reviewed=True,missing_reason=missing_reason.strip() if not labels else None)
        self.items[index]['reviewed_at']=reviewed_at
        self._save()

    def record_outcome(self,index,review,*,reviewed_at):
        if self.kind!='outcome' or type(index) is not int or not 0 <= index < len(self.items): raise ValueError('invalid outcome item')
        if not isinstance(review,dict) or set(review)!=set(_RUBRIC)|{'explanation','source_ids'} or any(review[k] not in options for k,options in _RUBRIC.items()):
            raise ValueError('invalid outcome review')
        if not isinstance(review['explanation'],str) or not review['explanation'].strip(): raise ValueError('explanation required')
        self._valid_sources(review['source_ids'])
        try: date.fromisoformat(reviewed_at)
        except (ValueError,TypeError): raise ValueError('invalid review date') from None
        self.items[index]['review']=copy.deepcopy(review)
        self.packet['reviewed_at']=reviewed_at
        self._save()
