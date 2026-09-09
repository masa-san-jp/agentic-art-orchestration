import unittest
from tools.delivery_completion import completion, resolve_contract

class DeliveryCompletionTests(unittest.TestCase):
    def test_project_request_cannot_silently_use_internal_profile(self):
        with self.assertRaisesRegex(ValueError,'DELIVERY_PROFILE_MISMATCH'):
            resolve_contract({'contract_version':'delivery-contract/v1','target':'project-local'}, {'delivery_mode':'internal','permissions':{}})

    def test_plan_ready_and_worker_success_are_not_delivery(self):
        contract={'target':'project-local'}
        for state in ({'status':'PASSED'},{'plan_status':'PLAN_READY'},{'plan_status':'PLAN_READY','projection_status':'SKIPPED','knowledge_status':'COMMITTED'}):
            self.assertEqual('INCOMPLETE',completion(state,contract)['status'])

    def test_internal_and_local_and_committed_evidence_are_distinct(self):
        state={'plan_status':'PLAN_READY','plan':{'artifacts':{'production-plan.md':'a'*64},'owner_verification':{'plan_status':'PLAN_READY'}},'knowledge_status':'COMMITTED','projection_status':'SKIPPED'}
        self.assertEqual('COMPLETED',completion(state,{'target':'internal'})['status'])
        self.assertEqual('INCOMPLETE',completion(state,{'target':'project-local'})['status'])
        state.update(projection_status='PROJECTED',local_delivery_receipt={'contract_version':'local-plan-delivery-receipt/v1','status':'VERIFIED','records':[{'record_id':'P0001'}]})
        self.assertEqual('COMPLETED',completion(state,{'target':'project-local'})['status'])
        self.assertEqual('INCOMPLETE',completion(state,{'target':'project-committed'})['status'])
        state['knowledge_status']='PARTIAL'
        self.assertEqual('INCOMPLETE',completion(state,{'target':'project-local'})['status'])
