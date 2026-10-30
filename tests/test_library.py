import tempfile
from pathlib import Path
import unittest
from cityplay.library import LibraryStore

class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.now=100
        self.store=LibraryStore(Path(self.temp.name)/'private'/'library.sqlite3',clock=lambda:self.now)
        self.card={'id':'book-1','name':'Example Book','entity_type':'book','detail':'1943, Example Author','year':1943,'aliases':[{'language':'zh','value':'测试书名'}]}
    def tearDown(self):self.temp.cleanup()
    def test_persists_catalog_aliases_and_hides_expired_content(self):
        self.store.put_entities([self.card])
        self.assertEqual(self.store.browse(query='测试书名')['cards'][0]['id'],'book-1')
        reopened=LibraryStore(self.store.path,clock=lambda:self.now)
        self.assertEqual(reopened.browse()['total'],1)
        self.now+=3601
        self.assertEqual(reopened.browse()['cards'],[])
    def test_preferences_are_scoped_and_survive_catalog_expiry(self):
        self.store.put_entities([self.card]);self.store.choose('owner',self.card,'curious')
        self.assertTrue(self.store.has_profile('owner'));self.assertEqual(self.store.choices('other'),[])
        self.now+=3601;self.store.browse()
        self.assertEqual(self.store.choices('owner')[0]['choice'],'curious')
        self.store.clear('other');self.assertEqual(len(self.store.choices('owner')),1)
        self.store.clear('owner');self.assertFalse(self.store.has_profile('owner'))
    def test_library_keeps_many_likes_and_curiosities(self):
        for n in range(12):self.store.choose('p',{**self.card,'id':str(n)},'like' if n<7 else 'curious')
        saved=self.store.choices('p')
        self.assertEqual(sum(x['choice']=='like' for x in saved),7)
        self.assertEqual(sum(x['choice']=='curious' for x in saved),5)
        self.now+=1
        self.store.merge_choices('p',[({**self.card,'id':'0'},'like')])
        self.assertEqual(self.store.choices('p'),saved)
        self.store.choose('p',{**self.card,'id':'8'},'clear')
        self.assertEqual(len(self.store.choices('p')),11)
    def test_snapshots_include_full_context_owner_and_expiry(self):
        context={'interests':['x'],'area':{'radius':10000},'seen':[],'exclusions':['hotel']}
        self.store.put_snapshot('owner',context,{'status':'partial','cards':[],'source':'live_qloo','tools':['must not persist']})
        result=self.store.get_snapshot('owner',context)
        self.assertEqual(result['cache_origin'],'sqlite');self.assertNotIn('tools',result)
        self.assertIsNone(self.store.get_snapshot('other',context))
        self.assertIsNone(self.store.get_snapshot('owner',{**context,'seen':['x']}))
        self.assertIsNone(self.store.get_snapshot('owner',{**context,'area':{'radius':20000}}))
        self.now+=301;self.assertIsNone(self.store.get_snapshot('owner',context))
    def test_discovery_feed_excludes_search_cache_but_search_keeps_it(self):
        self.store.put_entities([{**self.card,'id':'search'}])
        self.store.put_entities([{**self.card,'id':'editor','name':'Edited Book'}],discovery=True)
        self.assertEqual([x['id'] for x in self.store.browse(discovery_only=True)['cards']],['editor'])
        self.assertIn('search',[x['id'] for x in self.store.browse(query='Example')['cards']])
        self.store.put_entities([{**self.card,'id':'editor','name':'Edited Book'}])
        self.assertEqual(self.store.browse(discovery_only=True)['total'],1)

    def test_query_is_bound_and_database_private(self):
        self.store.put_entities([self.card]);self.assertEqual(self.store.browse(query="' OR 1=1 --")['total'],0)
        self.assertEqual(self.store.path.stat().st_mode&0o777,0o600)
