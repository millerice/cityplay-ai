"""Evidence-led parallel lives; graph links are exploration paths, not personalities."""
import copy
from .engine import DiscoveryEngine, result_array, candidate_type, recommendation_evidence
from .intent import Intent, Area
from .transport import ServiceError


def public_result(result):
    allowed={'status','cards','source','error','questions','trace','diagnostics','taste_inputs','recommendation_mode','cache_origin','cached_at'}
    return {key:value for key,value in result.items() if key in allowed}


def build_parallel(session):
    original = copy.deepcopy(session.parallel_versions[0]["intent"] if session.parallel_versions else session.confirmed)
    familiar = copy.deepcopy(session.parallel_versions[0]["result"] if session.parallel_versions else session.parallel_familiar)
    versions = [{'id':'familiar','variant':'familiar','title':'熟悉的我','subtitle':'从你明确选择的口味出发',
                 'intent':original,'result':familiar,'path':[], 'boundary':'熟悉指输入口味，不保证地点曾去过或一定喜欢。'}]
    if session.taste_starting_mode=='curiosity':
        versions[0].update(variant='familiar_curious',title='想尝试的我',subtitle='从你想了解的对象出发',boundary='这是尝试意向，尚未标记为你已经喜欢的口味。')
    inputs = familiar.get('taste_inputs', [])
    entities = [x['id'] for x in inputs if x.get('type','').startswith('urn:entity:')]
    tags = [x['id'] for x in inputs if x.get('type','').startswith('urn:tag:')]
    params = {'filter.type':'urn:entity:artist','take':5,'feature.explainability':True}
    if entities: params['signal.interests.entities'] = ','.join(entities)
    if tags: params['signal.interests.tags'] = ','.join(tags)
    if not entities and not tags: return versions
    try:
        candidates = result_array(session.qloo.get('/v2/insights', params),'entities')
        bridge = next((x for x in candidates if candidate_type(x)=='urn:entity:artist' and isinstance(x.get('entity_id'),str)
                       and isinstance(x.get('name'),str) and x['name'].strip() and len(x['name'])<=100
                       and x['entity_id'] not in {v['id'] for v in inputs}), None)
        if bridge:
            values=copy.deepcopy(original)
            values['interests']=[{'kind':'entity','query':bridge['name'],'entity_type':'artist'}]
            # Resolve the bridge again and validate that the chosen ID exists in lookup results.
            result=DiscoveryEngine(session.qloo,session.verifier).run(Intent.from_dict(values),Area(**session.area),
                selections={'interests.0':bridge['entity_id']},seen_ids=list(session.feedback),
                independent_bookstore=session.independent_bookstore,prefer_nearby=session.prefer_nearby)
            versions.append({'id':'adjacent','variant':'adjacent_bridge','title':'邻近的我','subtitle':'沿文化关联，多走一步',
                'intent':values,'result':result,
                'path':[{'from':[x['name'] for x in inputs],'to':bridge['name'],
                         'evidence':recommendation_evidence(bridge,inputs),'provider':'Qloo Insights'}],
                'boundary':'这是图谱关联方向，不表示你不认识这位音乐人，也不代表人格或心理距离。'})
        else:
            versions.append({'id':'adjacent','variant':'adjacent_none','title':'邻近的我','subtitle':'暂未找到可验证的文化桥梁',
                'intent':original,'result':{'status':'empty','cards':[],'taste_inputs':[]},'path':[],
                'boundary':'保留原有条件，不用模型虚构新的文化对象。'})
    except ServiceError as error:
        versions.append({'id':'adjacent','variant':'adjacent_error','title':'邻近的我','subtitle':'本次文化关联查询未完成',
            'intent':original,'result':{'status':'error','cards':[],'error':{'code':error.code,'retryable':error.retryable}},
            'path':[],'boundary':'熟悉版本仍可查看，可稍后重试。'})
    return versions
