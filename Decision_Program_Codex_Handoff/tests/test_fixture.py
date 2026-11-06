import unittest
from workbench.fixture import BASE, CHANGED, MISSING, RULE, demo, evaluate

class FixtureTests(unittest.TestCase):
    def test_exception_flip_and_missing(self):
        cases=demo()['cases']
        self.assertEqual(cases['original']['answer'],'permit not required')
        self.assertEqual(cases['exception_withdrawn']['answer'],'permit required')
        self.assertEqual(cases['exception_unknown']['status'],'deferred')
        self.assertTrue(all(case['network_calls']==0 for case in cases.values()))
    def test_missing_entity_and_conflict_do_not_become_negative(self):
        self.assertEqual(evaluate(RULE+'\nSchool event: no')['status'],'deferred')
        self.assertEqual(evaluate(BASE+'\nSchool event: no')['status'],'deferred')
    def test_irrelevant_change_is_invariant_and_rule_is_required(self):
        self.assertEqual(evaluate(BASE+'\nColor: blue')['answer'],evaluate(BASE)['answer'])
        self.assertEqual(evaluate('Attendance: 75\nSchool event: yes')['status'],'deferred')
