from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from tools.element import Engine, canonical
from tools.operation_relations import validate_edges
from tools.theme_elements import start, ranked, provenance
from tools.validate import validate_signal
from tests.test_operation_vocabulary import tagged, VOCAB
from tests.test_theme_elements import NOW, reply

V = deepcopy(VOCAB)
V['operations'] += [
 {'id':'decide-in-action','label':'行為の中で決める','definition':'行為を進めながら次の判断をその場で決める。'},
 {'id':'impose-constraints','label':'制約を課す','definition':'使用できる要素や行為の範囲に制約を課す。'}]
GRAPH = {'contract_version':'operation-relation-edges/v1', 'vocabulary_sha256':hashlib.sha256(canonical(V).encode()).hexdigest(), 'source_sha256':'a'*64, 'edges':{
 'contrast':{'defer':['decide-in-action'],'decide-in-action':['defer'],'release-control':['impose-constraints'],'impose-constraints':['release-control']},
 'complement':{'defer':['impose-constraints'],'impose-constraints':['defer'],'decide-in-action':['release-control'],'release-control':['decide-in-action']}}}

def rows():
    signals = tagged();art=signals[1]['domain']['art_history']
    art['operation_vocabulary']=deepcopy(V);art['operation_relations']=deepcopy(GRAPH)
    return signals


def candidate(original, entity, ids, evidence):
    row=deepcopy(original);row['signal_id']='art-history:'+entity;row['source']['entity_ids']=['movement/'+entity]
    template=row['domain']['art_history']['operation_tags'][0]
    row['domain']['art_history']['operation_tags']=[{**template,'operation_id':op,'evidence':evidence} for op in ids]
    return row


class OperationRelationTests(unittest.TestCase):
    def test_relation_priority_precedes_count_and_length_then_id(self):
        source=rows();original=source[1]
        art=[candidate(original,'same',['defer'],'短い'),
             candidate(original,'contrast',['decide-in-action'],'非常に長い根拠'*30),
             candidate(original,'b',['impose-constraints'],'規則を限定する'),
             candidate(original,'a',['impose-constraints'],'規則を限定する'),
             candidate(original,'long',['impose-constraints'],'規則を限定する長い根拠')]
        result=ranked('defer',[source[0],source[2],*reversed(art)],'art-history')
        self.assertEqual(['same','long','a','b','contrast'],[r['entity_id'].split('/')[-1] for r in result])
        self.assertEqual(['same','complement','complement','complement','contrast'],[r['relation_kind'] for r in result])
        # Two independent same-operation matches beat a longer single match.
        art=[candidate(original,'one',['defer'],'長い'*20),candidate(original,'two',['defer','decide-in-action'],'短い')]
        result=ranked(['defer','decide-in-action'],[source[0],source[2],*art],'art-history')
        self.assertEqual('movement/two',result[0]['entity_id']);self.assertEqual(2,result[0]['score'])

    def test_all_connection_types_are_recorded_with_distinct_roots(self):
        source=rows();art=candidate(source[1],'multi',['defer','impose-constraints','decide-in-action'],'根拠')
        result=ranked('defer',[source[0],source[2],art],'art-history')[0]
        self.assertEqual(1,result['score']);self.assertEqual(2,result['evidence_length'])
        self.assertEqual({'same','complement','contrast'},{r['relation'] for r in result['operation_connections']})
        self.assertEqual(3,len(result['operation_evidence']))

    def test_native_a5_receives_connection_and_tag_only_root_and_resume(self):
        source=rows();art=source[1]['domain']['art_history']
        art.pop('content');art['relations']=[]
        art['operation_tags'][0].update(operation_id='impose-constraints',evidence='規則に制約を課す')
        with tempfile.TemporaryDirectory() as root:
            engine=Engine('relation-test',Path(root).resolve())
            report=start(engine,source,requested_at=NOW)
            report=engine.answer(reply(report['next_action']['request'],'defer'))
            report=engine.answer(reply(report['next_action']['request'],'決定を後に回す'))
            q=report['next_action']['request']
            self.assertEqual('A5.art-history.1',q['element_id'])
            self.assertEqual('規則に制約を課す',q['inputs']['signal'])
            self.assertEqual('complement',q['inputs']['operation_connections'][0]['relation'])
            self.assertEqual(report,engine.next())
            state=json.loads(engine.path.read_text());h=state['context']['phase_a']['matching_history'][0]
            self.assertEqual('complement',h['rankings']['art-history'][0]['operation_connections'][0]['relation'])
            report=engine.answer(reply(q,{'answer':True,'reason':'決定を後に回す条件を規則の制約で確かめる。'}))
            report=engine.answer(reply(report['next_action']['request'],{'answer':True,'reason':'決定を後に回すことが余白を生む。'}))
            report=engine.answer(reply(report['next_action']['request'],'決定を後に回す条件と規則の制約は選択の余白になるか？'))
            self.assertEqual('COMPLETED',report['status'])
            result=provenance(json.loads(engine.path.read_text()))
            self.assertEqual(GRAPH,result['operation_relations'])
            self.assertEqual('complement',result['selected']['art-history']['operation_connections'][0]['relation'])

    def test_mixed_graphs_fail_before_checkpoint(self):
        source=rows();other=deepcopy(source[1]);other['signal_id']='other'
        other['domain']['art_history']['operation_relations']['source_sha256']='b'*64
        with tempfile.TemporaryDirectory() as root:
            engine=Engine('mixed',Path(root).resolve())
            with self.assertRaisesRegex(ValueError,'MIXED_OPERATION_RELATIONS'):start(engine,[*source,other],requested_at=NOW)
            self.assertFalse(engine.path.exists())

    def test_provenance_symmetry_cross_kind_and_shape_fail_closed(self):
        self.assertEqual([],validate_signal(rows()[1]))
        for change in ('hash','symmetry','cross','self','unknown','duplicate','null'):
            source=rows();graph=source[1]['domain']['art_history']['operation_relations']
            if change=='hash':graph['vocabulary_sha256']='0'*64
            elif change=='symmetry':graph['edges']['contrast']['decide-in-action']=[]
            elif change=='cross':graph['edges']['complement']['defer']=['decide-in-action']
            elif change=='self':graph['edges']['contrast']['defer']=['defer']
            elif change=='unknown':graph['edges']['contrast']['defer']=['unknown']
            elif change=='duplicate':graph['edges']['contrast']['defer'] *=2
            else:source[1]['domain']['art_history']['operation_relations']=None
            self.assertTrue(validate_signal(source[1]),change)
