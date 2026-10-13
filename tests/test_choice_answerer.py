from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.choice_answerer import orders, presentation, original_value, check_observations
from tools.element import Engine
from tools.element_answerer import RoutingAnswerer, StableChoiceAnswerer
from tests.test_element import single, answer


def request(numeric=False):
    return {'contract_version':'element-request/v1','run_id':'choice-test','element_id':'A4.art.screen.01',
            'attempt':1,'instruction':'関係のあるカードを選び、どれもなければ 0 を返す。' if numeric else '関係を一つ選ぶ。',
            'inputs':{'cards':{'1':'target','2':'other'}} if numeric else {'link_types':{'same':'同じ','opposite':'逆','none':'なし'}},
            'answer_format':{'type':'choice','choices':['0','1','2'] if numeric else ['same','opposite','none']},
            'checks':['non_empty'],'previous_failure':None}


class Worker:
    def __init__(self, pick): self.pick=pick; self.calls=[]
    def answer(self, req):
        self.calls.append(deepcopy(req))
        return answer(req,self.pick(req))


class ChoiceAnswererTests(unittest.TestCase):
    def test_deterministic_different_order_and_no_mutation(self):
        req=request(True);before=deepcopy(req)
        self.assertEqual(orders(req),orders(deepcopy(req)))
        self.assertNotEqual(*orders(req))
        presentation(req,orders(req)[1])
        self.assertEqual(before,req)

    def test_numeric_card_identity_survives_relabelling(self):
        req=request(True)
        worker=Worker(lambda r:next(k for k,v in r['inputs']['cards'].items() if v=='target'))
        reply=StableChoiceAnswerer(worker,'judge-test').answer(req)
        self.assertEqual('1',reply['value'])
        self.assertNotEqual(worker.calls[0]['inputs']['cards'],worker.calls[1]['inputs']['cards'])
        self.assertEqual([],check_observations(req,reply))

    def test_numeric_none_including_binary_moves_with_instruction(self):
        req=request(True);req['inputs']['cards']={'1':'other'};req['answer_format']['choices']=['0','1']
        changed=presentation(req,orders(req)[1])
        self.assertEqual({'0':'other'},changed['inputs']['cards'])
        self.assertIn('1 を返す',changed['instruction'])
        self.assertEqual('0',original_value(req,orders(req)[1],'1'))

    def test_categorical_order_and_definitions_are_permuted(self):
        req=request();worker=Worker(lambda r:'opposite')
        reply=StableChoiceAnswerer(worker,'judge-test').answer(req)
        self.assertNotEqual(worker.calls[0]['answer_format']['choices'],worker.calls[1]['answer_format']['choices'])
        self.assertNotEqual(list(worker.calls[0]['inputs']['link_types']),list(worker.calls[1]['inputs']['link_types']))
        self.assertEqual([],check_observations(req,reply))

    def test_position_biased_worker_is_rejected(self):
        for req in [request(),request(True)]:
            reply=StableChoiceAnswerer(Worker(lambda r:r['answer_format']['choices'][0]),'judge-test').answer(req)
            self.assertEqual('choice_stability',check_observations(req,reply)[0]['check'])

    def test_forged_hash_order_or_final_value_is_rejected(self):
        req=request();valid=StableChoiceAnswerer(Worker(lambda r:'same'),'judge-test').answer(req)
        for change in ['hash','order','value']:
            reply=deepcopy(valid)
            if change=='hash':reply['choice_observations'][1]['request_sha256']='0'*64
            elif change=='order':reply['choice_observations'][1]['order'].reverse()
            else:reply['value']='none'
            self.assertTrue(check_observations(req,reply))

    def test_judge_without_observations_is_rejected_legacy_unchanged(self):
        req=request();reply=answer(req,'same')
        self.assertEqual([],check_observations(req,reply))
        reply['answerer_kind']='judge-test'
        self.assertTrue(check_observations(req,reply))

    def test_unstable_attempts_are_bounded_and_saved_on_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine=Engine('choice-test',Path(tmp).resolve())
            seq=single(fmt={'type':'choice','choices':['same','opposite','none']})
            report=engine.next(sequence=seq)
            worker=Worker(lambda r:r['answer_format']['choices'][0])
            for attempt in range(1,6):
                req=report['next_action']['request'];self.assertEqual(attempt,req['attempt'])
                report=engine.answer(StableChoiceAnswerer(worker,'judge-test').answer(req))
            self.assertEqual('BLOCKED',report['status']);self.assertEqual(0,report['accepted_count'])
            self.assertEqual(10,len(worker.calls))
            state=json.loads(engine.path.read_text());self.assertEqual(5,len(state['history']))
            self.assertEqual(2,len(state['history'][0]['choice_observations']))
            self.assertEqual(report,Engine('choice-test',Path(tmp).resolve()).status())

    def test_stable_answer_is_accepted_and_exact_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine=Engine('choice-test',Path(tmp).resolve())
            req=engine.next(sequence=single(fmt={'type':'choice','choices':['same','opposite']}))['next_action']['request']
            reply=StableChoiceAnswerer(Worker(lambda r:'same'),'judge-test').answer(req)
            report=engine.answer(reply);self.assertEqual('COMPLETED',report['status'])
            self.assertEqual(report,engine.answer(reply))

    def test_format_router_only_pairs_judgement_choices(self):
        route={'command':[sys.executable,'worker.py'],'timeout_seconds':2,'answerer_kind':'llm-test'}
        config={'contract_version':'element-answerer/v2','default':route,'formats':{'choice':{**route,'answerer_kind':'judge-test'}}}
        worker=Worker(lambda r:'same' if r['answer_format']['type']=='choice' else '文')
        with patch('tools.element_answerer.LocalAnswerer.answer',side_effect=worker.answer):
            router=RoutingAnswerer(config)
            self.assertEqual('judge-test',router.answer(request())['answerer_kind'])
            text=request();text['answer_format']={'type':'text','max_chars':10}
            self.assertEqual('llm-test',router.answer(text)['answerer_kind'])
        self.assertEqual(3,len(worker.calls))

    def test_bad_config_cannot_send_text_to_judgement_backend(self):
        route={'command':['worker'],'timeout_seconds':2,'answerer_kind':'judge-test'}
        with self.assertRaises(ValueError):RoutingAnswerer({'contract_version':'element-answerer/v2','default':route,'formats':{}})

class ComparisonTests(unittest.TestCase):
    def test_interrupted_pair_never_reports_partial_cost_as_total(self):
        from tools.element_benchmark import compare
        class PartialWorker:
            calls=0
            def answer(self, req):
                self.calls+=1
                if self.calls==2: raise ValueError('failure after a billed call')
                reply=answer(req,'same');reply['inference_usage']={'cost_usd':1}
                return reply
        result=compare([request(),request()],PartialWorker(),Worker(lambda r:'same'))
        self.assertEqual(1,result['backends']['llm']['errors'])
        self.assertIsNone(result['backends']['llm']['cost_usd'])
        self.assertEqual('completed_pairs_only',result['backends']['llm']['seconds_scope'])

    def test_report_excludes_input_bodies_and_records_bias(self):
        from tools.element_benchmark import compare
        req=request(True);req['inputs']['cards']['1']='PRIVATE BODY MUST NOT APPEAR'
        result=compare([req],Worker(lambda r:next(k for k,v in r['inputs']['cards'].items() if v!='other')),
                       Worker(lambda r:r['answer_format']['choices'][0]))
        self.assertEqual(1,result['backends']['llm']['stable'])
        self.assertEqual(0,result['backends']['judge']['stable'])
        self.assertEqual({'1':2},result['backends']['judge']['position_counts'])
        self.assertIsNone(result['backends']['judge']['cost_usd'])
        self.assertNotIn('PRIVATE BODY',json.dumps(result))
        self.assertEqual('KEEP_LLM_DEFAULT',result['decision'])
