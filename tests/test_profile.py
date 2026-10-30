"""Synthetic profile evidence and explicit-consent persistence checks."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from cityplay.profile import GROUPS, confirm, generate, validate_answers, validate_profile
from cityplay.config import Settings
from cityplay.transport import ServiceError
from cityplay.web import Application


def fixture():
    return {'profile_name':'可能的慢生活探索者','summary':'可能喜欢阅读，也愿意尝试创作',
            **{g:[] for g in GROUPS},
            'existing_interests':[{'name':'阅读','source':'user_answer','confidence':'high','reason':'用户明确选择阅读','evidence':{'question_id':'evening','quote':'阅读'}}],
            'potential_interests':[{'name':'陶艺','source':'ai_inference','confidence':'medium','reason':'用户想尝试','evidence':{'question_id':'wish','quote':'陶艺'}}]}


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.answers={'evening':'阅读','wish':'陶艺'}
        self.draft=validate_profile(fixture(),self.answers)

    def payload(self):
        return {'draft_id':'draft','profile_name':'我的画像','summary':'可修改简介','existing_text':'喜欢 Jazz，避免酒店。',
                'items':[{'id':self.draft[g][0]['id'],'group':g,'name':self.draft[g][0]['name']} for g in ('existing_interests','potential_interests')]}

    def test_schema_rejects_fabricated_evidence_probability_and_inferred_existing(self):
        for mutate in [lambda p:p['existing_interests'][0]['evidence'].update(quote='不存在的答案'),
                       lambda p:p['existing_interests'][0].update(probability=.98),
                       lambda p:p['existing_interests'][0].update(source='ai_inference'),
                       lambda p:p['existing_interests'][0]['evidence'].update(question_id='wish',quote='陶艺')]:
            value=fixture();mutate(value)
            with self.assertRaises(ValueError):validate_profile(value,self.answers)

    def test_sensitive_answers_rejected_before_model(self):
        for value in ['secret-key','person@example.com','12345678901']:
            with self.assertRaises(ServiceError):validate_answers({'evening':value},('secret-key',))
        with self.assertRaises(ValueError):validate_answers({})

    def test_weekend_choice_cannot_be_promoted_to_existing_interest(self):
        value=fixture()
        value['existing_interests'][0].update(name='书店', evidence={'question_id':'weekend','quote':'书店'})
        with self.assertRaises(ValueError):
            validate_profile(value, {**self.answers,'weekend':'想逛书店'})
        value['existing_interests']=[]
        value['potential_interests'][0].update(name='逛书店', evidence={'question_id':'weekend','quote':'想逛书店'})
        self.assertEqual(validate_profile(value, {**self.answers,'weekend':'想逛书店'})['potential_interests'][0]['name'],'逛书店')

    def test_merge_preserves_original_and_potential_semantics(self):
        payload=self.payload();profile,merged=confirm(self.draft,payload)
        self.assertTrue(merged.startswith(payload['existing_text']+'\n'))
        self.assertIn('喜欢：阅读',merged);self.assertIn('想尝试：陶艺',merged)
        self.assertNotIn('experience_motivations',merged)
        self.assertTrue(all(x['user_confirmed'] for g in GROUPS for x in profile[g]))
        payload['existing_text']='已经喜欢阅读';_,merged=confirm(self.draft,payload)
        self.assertEqual(merged.count('阅读'),1)

    def test_negative_interest_is_not_silently_deduped_as_positive(self):
        p=self.payload();p['existing_text']='不喜欢阅读';_,merged=confirm(self.draft,p)
        self.assertIn('喜欢：阅读',merged)
        # Keep the user's earlier words; subsequent intent confirmation resolves contradictions.
        self.assertTrue(merged.startswith('不喜欢阅读'))

    def test_client_cannot_promote_inference_or_forge_ids(self):
        p=self.payload();p['items'][1]['group']='existing_interests'
        with self.assertRaises(ValueError):confirm(self.draft,p)
        p=self.payload();p['items'][0]['id']='forged'
        with self.assertRaises(ValueError):confirm(self.draft,p)
        p=self.payload();p['items']=[]
        with self.assertRaises(ValueError):confirm(self.draft,p)

    def test_edit_preserves_attribution_and_unselected_items_absent(self):
        p=self.payload();p['items']=p['items'][:1];p['items'][0]['name']='读诗'
        profile,_=confirm(self.draft,p)
        self.assertEqual(profile['existing_interests'][0]['source'],'user_edit')
        self.assertEqual(profile['potential_interests'],[])

    def test_invalid_generation_retries_once_and_auth_does_not_retry(self):
        class Model:
            calls=0
            def parse_json(self,*args):
                self.calls+=1
                return {} if self.calls==1 else fixture()
        model=Model();generate(model,self.answers);self.assertEqual(model.calls,2)
        class Auth:
            calls=0
            def parse_json(self,*args):
                self.calls+=1;raise ServiceError('DEEPSEEK_HTTP_ERROR',status=401)
        auth=Auth()
        with self.assertRaises(ServiceError):generate(auth,self.answers)
        self.assertEqual(auth.calls,1)

    def test_draft_not_persisted_confirmation_idempotent_regeneration_preserves_saved(self):
        class Model:
            trace=[]
            def parse_json(self,*args):return fixture()
        with tempfile.TemporaryDirectory() as directory:
            app=Application(Settings('qloo-key','model-key'),model_factory=Model,evidence_dir=Path(directory)/'private')
            _,session=app.session(create=True)
            identifier=app.start(session,'guess',{'answers':self.answers})
            for _ in range(200):
                if session.jobs[identifier]['status']!='running':break
                time.sleep(.01)
            self.assertEqual(session.jobs[identifier]['status'],'completed')
            self.assertFalse(list(Path(directory).rglob('*.json')))
            self.draft=session.profile_draft;p=self.payload();p['draft_id']=session.profile_draft_id
            first=app.confirm_profile(session,p);second=app.confirm_profile(session,p)
            self.assertEqual(first,second);self.assertEqual(len(list(Path(directory).rglob('*.profile.json'))),1)
            saved=copy.deepcopy(session.profile_confirmed)
            p['summary']='Changed'
            with self.assertRaises(ServiceError):app.confirm_profile(session,p)
            identifier=app.start(session,'guess',{'answers':self.answers})
            for _ in range(200):
                if session.jobs[identifier]['status']!='running':break
                time.sleep(.01)
            self.assertEqual(saved,session.profile_confirmed)
