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
    # Titles are English fallbacks; the browser localizes via variant keys.
    versions = [{'id':'familiar','variant':'familiar','title':'Familiar me','subtitle':'From the taste you actually chose',
                 'intent':original,'result':familiar,'path':[], 'boundary':'Familiar refers to your input taste; it does not guarantee visited or liked places.'}]
    if session.taste_starting_mode=='curiosity':
        versions[0].update(variant='familiar_curious',title='Curious me',subtitle='From objects you want to learn about',boundary='This is an intent to try, not yet marked as a taste you already love.')
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
            versions.append({'id':'adjacent','variant':'adjacent_bridge','title':'Adjacent me','subtitle':'One step further along cultural associations',
                'intent':values,'result':result,
                'path':[{'from':[x['name'] for x in inputs],'to':bridge['name'],
                         'evidence':recommendation_evidence(bridge,inputs),'provider':'Qloo Insights'}],
                'boundary':'This is a graph-association direction; it does not mean you do not know the artist, and it is not a personality or psychological distance.'})
        else:
            versions.append({'id':'adjacent','variant':'adjacent_none','title':'Adjacent me','subtitle':'No verifiable cultural bridge found this round',
                'intent':original,'result':{'status':'empty','cards':[],'taste_inputs':[]},'path':[],
                'boundary':'Original constraints are kept; no model-invented cultural objects.'})
    except ServiceError as error:
        versions.append({'id':'adjacent','variant':'adjacent_error','title':'Adjacent me','subtitle':'The association query did not finish',
            'intent':original,'result':{'status':'error','cards':[],'error':{'code':error.code,'retryable':error.retryable}},
            'path':[],'boundary':'The familiar version is still available; retry later.'})
    return versions
