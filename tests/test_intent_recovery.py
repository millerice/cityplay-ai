"""Bounded model repair and profile-to-retriever handoff, synthetic outputs."""
import unittest
from cityplay.intent import ModelIntentParser
from cityplay.transport import ServiceError


class Model:
    model='synthetic'
    def __init__(self, outputs):self.outputs=outputs;self.calls=[]
    def parse_json(self,system,query):
        self.calls.append((system,query));value=self.outputs[min(len(self.calls)-1,len(self.outputs)-1)]
        if isinstance(value,Exception):raise value
        return value


class RecoveryTests(unittest.TestCase):
    def test_empty_query_repairs_once_without_rewriting_user_query(self):
        model=Model([{'interests':[{'kind':'tag','query':''}]},{'interests':[{'kind':'tag','query':'movies'}]}])
        intent=ModelIntentParser(model).parse('喜欢看电影')
        self.assertEqual(intent.interests[0].query,'movies');self.assertEqual(len(model.calls),2)
        self.assertEqual(model.calls[0][1],model.calls[1][1]);self.assertIn('interests[0].query',model.calls[1][0])

    def test_two_invalid_outputs_expose_only_safe_field_diagnostic(self):
        model=Model([{'clarifications':['']}])
        with self.assertRaises(ServiceError) as caught:ModelIntentParser(model).parse('public input')
        self.assertEqual(len(model.calls),2);self.assertEqual(caught.exception.details['field'],'clarifications[0]')
        self.assertNotIn('public input',str(caught.exception.details))

    def test_authentication_failure_is_not_retried(self):
        model=Model([ServiceError('DEEPSEEK_HTTP_ERROR',status=401)])
        with self.assertRaises(ServiceError):ModelIntentParser(model).parse('public input')
        self.assertEqual(len(model.calls),1)

    def test_bad_json_retries_and_bad_types_do_not_crash(self):
        for error in [ServiceError('DEEPSEEK_INVALID_OUTPUT'),{'city':[]}]:
            model=Model([error,{'interests':[]}]);ModelIntentParser(model).parse('public input')
            self.assertEqual(len(model.calls),2)

    def test_profile_unsupported_activities_and_excess_signals_require_confirmation(self):
        model=Model([{'interests':[{'kind':'tag','query':'movies'}]}])
        intent=ModelIntentParser(model).parse('喜欢：看电影、公园散步、旅行；想尝试：漂流、蹦极、社交活动')
        self.assertTrue(any('3 个兴趣' in x for x in intent.clarifications))
        self.assertTrue(any('漂流、蹦极、社交活动' in x for x in intent.clarifications))
        self.assertEqual(intent.categories,[])

    def test_existing_capability_notice_is_not_duplicated(self):
        messages=['漂流、蹦极和社交活动不在当前MVP支持的范围内。', '最多处理三个兴趣，请选择本轮兴趣。']
        model=Model([{'interests':[], 'clarifications':messages}])
        intent=ModelIntentParser(model).parse('喜欢：看电影、公园散步、旅行；想尝试：漂流、蹦极、社交活动')
        self.assertEqual(intent.clarifications,messages)

    def test_nearby_ui_city_context_does_not_create_city_boundary_constraint(self):
        model=Model([{'interests':[], 'strict_city':True}])
        intent=ModelIntentParser(model).parse('喜欢看电影\n页面上明确选择的探索区域：纽约附近')
        self.assertFalse(intent.strict_city)
        model=Model([{'interests':[], 'strict_city':True}])
        intent=ModelIntentParser(model).parse('必须在纽约市内\n页面上明确选择的探索区域：纽约附近')
        self.assertTrue(intent.strict_city)

    def test_explicit_venue_request_survives_model_omission(self):
        model=Model([{'interests':[], 'categories':[]}])
        intent=ModelIntentParser(model).parse('喜欢 Miles Davis，想看看附近书店，避开咖啡店')
        self.assertEqual(intent.categories,['bookstore'])

    def test_movie_title_is_not_a_venue_request(self):
        model=Model([{'interests':[], 'categories':[]}])
        intent=ModelIntentParser(model).parse('想看电影《Coffee and Cigarettes》，想逛附近书店')
        self.assertEqual(intent.categories,['bookstore'])
