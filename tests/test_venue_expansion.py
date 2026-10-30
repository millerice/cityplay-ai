"""Synthetic tests for venue safety, diversity and bounded multi-category requests."""
import unittest
from cityplay.engine import DiscoveryEngine,FILTER_LOOKUPS
from cityplay.intent import Intent,Area,IntentValidationError
from test_core import FakeQloo,place,intent,verifier

class VenueQloo(FakeQloo):
    def get(self,path,params):
        if path=='/v2/tags':
            self.calls+=1;self.trace.append({'path':path,'query':params,'http_status':200})
            matching=[(k,v) for k,v in FILTER_LOOKUPS.items() if v[0]==params['filter.query']]
            return {'results':{'tags':[{'id':'urn:tag:category:synthetic:'+k,'name':v[1],'type':v[2]} for k,v in matching]}}
        return super().get(path,params)

class VenueExpansionTests(unittest.TestCase):
    def test_gallery_filter_does_not_accept_art_school_or_live_music(self):
        q=VenueQloo([place('school','Art school'),place('music','Live music venue'),place('gallery','Art gallery')])
        r=DiscoveryEngine(q,verifier()).run(intent(categories=['gallery']),Area(0,0))
        self.assertEqual([x['entity_id'] for x in r['cards']],['gallery'])
        self.assertEqual(r['diagnostics']['rejection_counts']['unsuitable_or_unknown_category'],2)
        call=next(x['query'] for x in q.trace if x['path']=='/v2/insights')
        self.assertEqual(call['filter.tags'],'urn:tag:category:synthetic:gallery')

    def test_auto_mixes_categories_before_six_verification_slots(self):
        values=[place(str(i),'Book store') for i in range(10)]+[place('film','Movie theater'),place('art','Art gallery'),place('mall','Shopping mall')]
        q=VenueQloo(values);r=DiscoveryEngine(q,verifier()).run(intent(categories=[]),Area(0,0))
        self.assertEqual({x['category'] for x in r['cards']},{'bookstore','cinema','gallery'})
        call=next(x['query'] for x in q.trace if x['path']=='/v2/insights')
        self.assertEqual(call['take'],30);self.assertNotIn('filter.tags',call)

    def test_multiple_directions_remain_strict_and_exclusions_win(self):
        q=VenueQloo([place('film','Movie theater'),place('art','Art gallery'),place('mall','Shopping mall')])
        r=DiscoveryEngine(q,verifier()).run(intent(categories=['cinema','gallery'],exclude_categories=['gallery']),Area(0,0))
        self.assertEqual([x['entity_id'] for x in r['cards']],['film'])
        calls=[x['query'] for x in q.trace if x['path']=='/v2/insights']
        self.assertEqual(len(calls),2)
        self.assertTrue(all(x['take']==10 for x in calls))

    def test_categories_bound_does_not_shrink_exclusion_capacity(self):
        with self.assertRaises(IntentValidationError):intent(categories=['cinema','gallery','coffee','bookstore'])
        i=intent(categories=[],exclude_categories=['cinema','gallery','coffee','bookstore','hotel','mall'])
        self.assertEqual(len(i.exclude_categories),6)
        with self.assertRaises(IntentValidationError):intent(categories=['pottery'])
