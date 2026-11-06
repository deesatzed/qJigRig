"""Guide a human through a blind review packet, saving a separate draft locally."""
import argparse
from datetime import date
import json

from quix_knowledge.review_session import ReviewSession

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('packet',help='original blind packet; never overwritten')
parser.add_argument('draft',help='separate draft file; existing drafts can be resumed')
parser.add_argument('--reviewer',required=True,help='reviewer identity, recorded as self-reported')
parser.add_argument('--date',default=date.today().isoformat(),help='review date in YYYY-MM-DD format')
args=parser.parse_args()
session=ReviewSession(args.packet,args.draft,args.reviewer)


def source_numbers(raw):
    raw=raw.strip()
    if not raw: return []
    try: numbers=[int(part.strip()) for part in raw.split(',')]
    except ValueError: raise ValueError('enter source numbers separated by commas') from None
    if any(number<1 or number>len(session.candidates) for number in numbers) or len(set(numbers))!=len(numbers):
        raise ValueError('source numbers must be unique and within the list')
    return [session.candidates[number-1]['id'] for number in numbers]


def sources(query=''):
    count=0
    for number,item in enumerate(session.candidates,1):
        text=' '.join(str(item.get(k,'')) for k in ('id','title','body'))
        if query.casefold() in text.casefold():
            print(f"{number}. {item.get('title','Untitled')} [{item['id']}] ({item.get('record_type','source')})")
            count+=1
    if not count: print('No matching sources.')


def show(number):
    try: index=int(number)-1
    except ValueError: raise ValueError('show requires a source number') from None
    if not 0 <= index < len(session.candidates): raise ValueError('source number is out of range')
    item=session.candidates[index]
    print(json.dumps(item,ensure_ascii=False,indent=2))


def choice(label,allowed):
    while True:
        value=input(f"{label} ({'/'.join(allowed)}): ").strip()
        if value in allowed: return value
        print('Choose one of the listed values.')


def outcome_review():
    review={
        'correctness':choice('Correctness',['correct','partial','incorrect','unknown']),
        'source_support':choice('Source support',['supported','partial','unsupported','no_citations','unknown']),
        'missing_evidence':choice('Missing evidence',['none','material','unknown']),
        'task_completion':choice('Task completion',['complete','partial','incomplete','unknown']),
    }
    explanation=input('Brief explanation: ').strip()
    while not explanation:
        print('An explanation is required.')
        explanation=input('Brief explanation: ').strip()
    review['explanation']=explanation
    review['source_ids']=source_numbers(input('Supporting source numbers (comma-separated; blank if none): '))
    return review


print(f"Blind {session.kind} review: {len(session.items)} items; {len(session.candidates)} sources.")
print('Sources are not ranked. Inspect all relevant material; skip leaves an item unreviewed.')
try:
    for index,item in enumerate(session.items):
        done=item.get('reviewed') is True if session.kind=='retrieval' else item.get('review') is not None
        if done: continue
        print(f"\nItem {index+1}/{len(session.items)}: {item.get('id',item.get('blind_id'))}")
        print(item.get('query',item.get('task','')))
        if session.kind=='outcome':
            try: print(json.dumps(json.loads(item['output']),ensure_ascii=False,indent=2))
            except (ValueError,TypeError): print(item.get('output',''))
        while True:
            if session.kind=='retrieval':
                prompt='list | search WORD | show N | mark N,N | none REASON | skip | quit: '
            else:
                prompt='list | search WORD | show N | review | skip | quit: '
            command=input(prompt).strip()
            action,_,argument=command.partition(' ')
            try:
                if action=='quit': raise EOFError
                if action=='skip': break
                if action=='list': sources()
                elif action=='search' and argument.strip(): sources(argument.strip())
                elif action=='show': show(argument)
                elif action=='mark' and session.kind=='retrieval':
                    ids=source_numbers(argument)
                    if not ids: raise ValueError('select at least one source; use none with a reason if unanswerable')
                    session.record_retrieval(index,ids,reviewed_at=args.date); print('Saved.'); break
                elif action=='none' and session.kind=='retrieval':
                    session.record_retrieval(index,[],missing_reason=argument,reviewed_at=args.date); print('Saved.'); break
                elif action=='review' and session.kind=='outcome':
                    session.record_outcome(index,outcome_review(),reviewed_at=args.date); print('Saved.'); break
                elif action not in ('list','skip'): print('Unknown command.')
            except ValueError as error:
                print(f'Not saved: {error}')
except (EOFError,KeyboardInterrupt):
    print('\nStopped; completed items remain saved in the draft.')
else:
    print('Session complete. Skipped items remain unreviewed.')
