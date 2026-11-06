"""Run the synthetic source-access experiment, or emit a blinded model prompt."""

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCES = {path.stem: path.read_bytes() for path in sorted((ROOT / 'corpus').glob('*.json'))}
CASES = json.loads((ROOT / 'cases.json').read_text())


def build_source_index():
    index = {}
    for source_id, raw in SOURCES.items():
        doc = json.loads(raw)
        index[source_id] = {'role': doc['role'], 'authority': doc['authority'],
                            'from': doc.get('from'), 'through': doc.get('through')}
    return index


SOURCE_INDEX = build_source_index()


def source_available(case, source_id):
    return source_id not in case['unavailable_source_ids']


class SourceAccess:
    def __init__(self, case, full, keyed_rows):
        self.case = case
        self.keyed_rows = keyed_rows
        self.reads = {}
        if full:
            for source_id in SOURCES:
                self.fetch(source_id)

    def fetch(self, source_id):
        if not source_available(self.case, source_id):
            return None
        if source_id not in self.reads:
            doc = json.loads(SOURCES[source_id])
            if self.keyed_rows and 'rows' in doc:
                doc['rows'] = [row for row in doc['rows']
                               if row['report'] == self.case['report']
                               and ('route' not in row or row['route'] == self.case['route'])]
            self.reads[source_id] = doc
        return self.reads[source_id]

    def payload_size(self):
        return sum(len((json.dumps(doc, indent=2, ensure_ascii=False) + '\n').encode())
                   for doc in self.reads.values())


def applicable(doc, case, by_route=False):
    if not doc:
        return []
    rows = [row for row in doc['rows'] if row['report'] == case['report']
            and (not by_route or row.get('route') == case['route'])
            and row['from'] <= case['as_of'] <= row['through']]
    if not rows:
        return []
    latest = max(row['from'] for row in rows)
    return [row for row in rows if row['from'] == latest]


def value(rows, field):
    vals = {row[field] for row in rows}
    return next(iter(vals)) if len(vals) == 1 else None


def run_case(case, full, keyed_rows=False):
    reader = SourceAccess(case, full, keyed_rows)
    findings = []

    def record(predicate, verdict, *citations):
        findings.append({'predicate': predicate, 'value': verdict,
                         'citations': [s for s in citations if s in reader.reads]})

    def finish():
        blockers = [f for f in findings if f['value'] == 'BLOCK']
        unresolved = [f for f in findings if f['value'] == 'UNKNOWN']
        verdict = 'BLOCK' if blockers else 'DEFER' if unresolved else 'RELEASE'
        decisive = blockers or unresolved or findings
        return {'id': case['id'], 'label': verdict, 'findings': findings,
                'cites': sorted({s for f in decisive for s in f['citations']}),
                'documents_read': len(reader.reads),
                'source_payload_bytes': reader.payload_size(),
                'source_ids_read': sorted(reader.reads)}

    if not case['route']:
        record('route specified', 'UNKNOWN')
        return finish()
    route = value(applicable(reader.fetch('R01'), case, by_route=True), 'status')
    record('route authorized', {'allowed': 'PASS', 'denied': 'BLOCK'}.get(route, 'UNKNOWN'), 'R01')
    if route == 'denied' and not full:
        return finish()

    hold = value(applicable(reader.fetch('H01'), case), 'status')
    record('hold clear', {'clear': 'PASS', 'active': 'BLOCK'}.get(hold, 'UNKNOWN'), 'H01')
    if hold == 'active' and not full:
        return finish()

    candidates = [sid for sid, entry in SOURCE_INDEX.items()
                  if entry['role'] == 'policy' and entry['authority'] == 'binding'
                  and entry['from'] <= case['as_of'] <= entry['through']]
    policy_id = candidates[0] if len(candidates) == 1 else ''
    policy = reader.fetch(policy_id) if policy_id else None
    if not policy or not policy['from'] <= case['as_of'] <= policy['through']:
        record('governing policy', 'UNKNOWN')
        return finish()
    record('governing policy', 'PASS', policy_id)

    if case['route'] in policy['signed_review_routes']:
        review = value(applicable(reader.fetch('V01'), case, by_route=True), 'status')
        record('peer review', {'signed': 'PASS', 'pending': 'BLOCK', 'rejected': 'BLOCK'}.get(review, 'UNKNOWN'), policy_id, 'V01')
        if review in ('pending', 'rejected') and not full:
            return finish()

    lag = value(applicable(reader.fetch('L01'), case), 'lag_minutes')
    if lag is None:
        record('lag known', 'UNKNOWN', 'L01')
    elif lag <= policy['maximum_lag_minutes']:
        record('lag cap met', 'PASS', policy_id, 'L01')
    else:
        waiver = reader.fetch('W01')
        if not waiver or not waiver['coverage_from'] <= case['as_of'] <= waiver['coverage_through']:
            record('lag exception', 'UNKNOWN', policy_id, 'L01', 'W01')
        else:
            rows = applicable(waiver, case, by_route=True)
            states = {r['status'] == 'signed' and lag <= r['maximum_lag_minutes'] for r in rows}
            result = {frozenset(): 'BLOCK', frozenset({False}): 'BLOCK',
                      frozenset({True}): 'PASS'}.get(frozenset(states), 'UNKNOWN')
            record('lag exception', result, policy_id, 'L01', 'W01')
    return finish()


def score(rows, gold):
    return {
        'cases': len(rows),
        'correct_decisions': sum(row['label'] == gold[row['id']]['label'] for row in rows),
        'expected_source_ids_present': sum(set(gold[row['id']]['required_source_ids']) <= set(row['cites']) for row in rows),
        'document_accesses': sum(row['documents_read'] for row in rows),
        'source_payload_bytes': sum(row['source_payload_bytes'] for row in rows),
        'outcomes': {k: sum(row['label'] == k for row in rows) for k in ('RELEASE', 'BLOCK', 'DEFER')},
    }


def compare():
    gold = {row['id']: row for row in json.loads((ROOT / 'evaluation' / 'gold.json').read_text())}
    result = {'mode': 'deterministic fixture with authored decision structure', 'arms': {},
              'live_model_calls': 0, 'model_accuracy_cost_latency': None}
    arms = [('whole_folder', True, False), ('predicate_directed', False, False),
            ('predicate_directed_keyed_rows', False, True)]
    for name, full, keyed_rows in arms:
        rows = [run_case(case, full, keyed_rows) for case in CASES]
        result['arms'][name] = {'score': score(rows, gold), 'rows': rows}
    return result


def prompt(case, mode):
    intro = ('This is a fictional source-grounded task. Do not use external knowledge or tools. '
             'Choose RELEASE, BLOCK, or DEFER using the applicable source records. '
             'Respond with the label, the decisive reason or evidence gap, and source IDs. '
             'Keep missing evidence distinct from an explicit negative finding.\n\n')
    if mode == 'blind':
        return intro + case['question']
    if mode == 'planner':
        roles = [{'source_id': sid, **entry} for sid, entry in SOURCE_INDEX.items()
                 if source_available(case, sid)]
        return ('Frame an evidence plan for this fictional source-grounded decision. Use only the '
                'question and source index below. Return a minimal first round of decision predicates, '
                'potential exceptions, and source IDs to request. Give the evidence needed to settle '
                'each predicate. Treat unavailable source contents as unknown. No external tools.\n\n'
                + case['question'] + '\n\nSource index:\n' + json.dumps(roles, indent=2))
    source_ids = SOURCES if mode == 'full' else run_case(case, full=False)['source_ids_read']
    return (intro + case['question'] + '\n\nSources:\n'
            + '\n'.join(SOURCES[sid].decode() for sid in source_ids if source_available(case, sid)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('compare')
    emit = sub.add_parser('prompt')
    emit.add_argument('case_id', choices=[c['id'] for c in CASES])
    emit.add_argument('--mode', choices=['blind', 'full', 'planner', 'scripted-packet'], default='full')
    args = parser.parse_args()
    if args.command == 'compare':
        print(json.dumps(compare(), indent=2))
    else:
        print(prompt(next(c for c in CASES if c['id'] == args.case_id), args.mode))


if __name__ == '__main__':
    main()
