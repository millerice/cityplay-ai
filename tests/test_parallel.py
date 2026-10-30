"""Synthetic multi-hop provenance and constraint preservation."""
import copy
from types import SimpleNamespace
import unittest
from cityplay.parallel import build_parallel
from cityplay.web import Application, Session
from cityplay.config import Settings
from cityplay.transport import ServiceError
from test_core import FakeQloo, place, verifier, intent
from dataclasses import asdict

class Graph(FakeQloo):
    def get(self,path,params):
        if path=='/v2/insights' and params.get('filter.type')=='urn:entity:artist':
            self.trace.append({'path':path,'query':params})
            return {'results':{'entities':[{'entity_id':'bridge','name':'Synthetic Bridge','subtype':'urn:entity:artist',
              'query':{'explainability':{'signal.interests.entities':[{'entity_id':'original','score':1}]}}}]}}
        if path=='/search':
            return {'results':[{'entity_id':'bridge','name':'Synthetic Bridge','subtype':'urn:entity:artist'}]}
        return super().get(path,params)

class ParallelTests(unittest.TestCase):
    def test_graph_hop_keeps_original_intent_and_constraints(self):
        values=asdict(intent(categories=['bookstore'],exclude_categories=['hotel']));values.pop('parser')
        s=Session(confirmed=values,area={'lat':0,'lon':0,'radius_m':10000},qloo=Graph(),verifier=verifier())
        s.parallel_familiar={'status':'partial','cards':[place()], 'taste_inputs':[{'id':'original','name':'Original','type':'urn:entity:artist'}]}
        before=copy.deepcopy(s.confirmed)
        versions=build_parallel(s)
        self.assertEqual(len(versions),2)
        self.assertEqual(versions[1]['path'][0]['to'],'Synthetic Bridge')
        self.assertEqual(versions[1]['path'][0]['evidence']['contributors'],[{'name':'Original','score':1}])
        self.assertEqual(versions[1]['intent']['categories'],values['categories'])
        self.assertEqual(versions[1]['intent']['exclude_categories'],['hotel'])
        self.assertEqual(s.confirmed,before)
        self.assertEqual(versions[1]['result']['status'],'partial')

    def test_activation_filters_feedback_and_rejects_forged_version(self):
        app=Application(Settings('fake','fake','deepseek-v4-pro'))
        s=Session(draft_id='draft',parallel_versions=[{'id':'familiar','intent':{},'result':{'status':'partial','cards':[place()]}}])
        s.feedback={'synthetic-a':'experienced_dislike'}
        self.assertEqual(app.select_parallel(s,{'draft_id':'draft','version':'familiar'})['result']['status'],'empty')
        with self.assertRaises(ValueError):app.select_parallel(s,{'draft_id':'draft','version':'forged'})
        with self.assertRaises(ServiceError):app.select_parallel(s,{'draft_id':'old','version':'familiar'})
