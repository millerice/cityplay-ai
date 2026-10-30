"""Explicit identities, no manufactured preferences, and optional curiosity."""
import unittest
from cityplay.taste_cards import load_cards,selected_tastes
from cityplay.web import Session
from cityplay.transport import ServiceError

class Search:
    calls=0
    max_calls=40
    def get(self,path,params):
        self.calls+=1
        return {'results':[{'entity_id':'known','name':'A real returned name','types':['urn:entity:artist']},
                           {'entity_id':'wrong-type','name':params['query'],'types':['urn:entity:place']}]}

class CardTests(unittest.TestCase):
    def test_editorial_search_does_not_substitute_unrelated_result(self):
        session=Session(qloo=Search())
        self.assertEqual(load_cards(session,{'domain':'music'})['cards'],[])
        self.assertEqual(session.taste_catalog,{})

    def test_explicit_search_returns_real_id_and_type_and_rejects_secrets(self):
        session=Session(qloo=Search())
        cards=load_cards(session,{'domain':'music','query':'some query'})['cards']
        self.assertEqual(cards,[{'id':'known','name':'A real returned name','entity_type':'artist'}])
        with self.assertRaises(ServiceError):load_cards(session,{'query':'secret'},('secret',))
        with self.assertRaises(ValueError):load_cards(session,{'page':99})

    def test_curiosity_is_not_promoted_to_like_and_unseen_ids_rejected(self):
        session=Session(taste_catalog={'known':{'id':'known','name':'Example','entity_type':'artist'}})
        likes,curious=selected_tastes(session,[{'id':'known','choice':'curious'}])
        self.assertEqual(likes,[]);self.assertEqual(len(curious),1)
        for items in [[],[{'id':'forged','choice':'like'}],[{'id':'known','choice':'dislike'}],
                      [{'id':'known','choice':'like'},{'id':'known','choice':'curious'}]]:
            with self.assertRaises(ValueError):selected_tastes(session,items)

    def test_large_saved_catalog_still_allows_discovering_new_objects(self):
        session=Session(qloo=Search(),taste_catalog={str(i):{'id':str(i)} for i in range(130)})
        result=load_cards(session,{'domain':'music','query':'some query'})
        self.assertEqual(result['cards'][0]['id'],'known')
        self.assertIn('known',session.taste_catalog)

    def test_auth_failure_does_not_repeat_across_editorial_queries(self):
        class Auth(Search):
            def get(self,*args):
                self.calls+=1
                raise ServiceError('QLOO_AUTH',status=401)
        q=Auth()
        with self.assertRaises(ServiceError):load_cards(Session(qloo=q),{'domain':'all'})
        self.assertEqual(q.calls,1)

    def test_browsing_cards_does_not_consume_discovery_submission_slots(self):
        import time
        from cityplay.web import Application
        from cityplay.config import Settings
        app=Application(Settings('fake','fake'))
        session=Session(card_submissions=[time.monotonic()]*10)
        with self.assertRaises(ServiceError):app.start(session,'taste_cards',{})
        self.assertEqual(session.submissions,[])
        session.submissions=[time.monotonic()]*6
        with self.assertRaises(ServiceError):app.start(session,'discover',{})

    def test_editorial_cards_do_not_repeat_editions_or_autoconfirm_ambiguity(self):
        class Editions(Search):
            def get(self,path,params):
                return {'results':[{'entity_id':'a'+params['query'],'name':params['query'],'types':['urn:entity:book'],'properties':{'publication_year':2008},'disambiguation':'2008, Example author'},
                                   {'entity_id':'b'+params['query'],'name':params['query'],'types':['urn:entity:book'],'properties':{'publication_year':1943},'disambiguation':'1943, Example author'}]}
        result=load_cards(Session(qloo=Editions()),{'domain':'book'})
        self.assertEqual(len(result['cards']),3)
        self.assertTrue(all(x['year']==1943 and x['ambiguous'] for x in result['cards']))
        self.assertTrue(all(x['detail']=='1943, Example author' for x in result['cards']))
