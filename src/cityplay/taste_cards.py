"""Explicit cultural-card selection; no model-generated identities or personalities."""
from .engine import result_array, candidate_type, identity_name
from .profile import check_sensitive
from .transport import ServiceError

DOMAINS={'music':'artist','movie':'movie','book':'book'}
# Editorial search prompts, never IDs or claims of user preference.
SEEDS={
 'music':[['Miles Davis','Beyoncé','Björk'],['Taylor Swift','Bob Marley','Ludwig van Beethoven']],
 'movie':[['Spirited Away','The Matrix','Amélie'],['Interstellar','Toy Story','Parasite']],
 'book':[['The Little Prince','Pride and Prejudice','One Hundred Years of Solitude'],['Robinson Crusoe','Dune','The Hobbit']]}


def load_cards(session,payload,secrets=()):
    if set(payload)-{'domain','page','query','existing'}: raise ValueError('Invalid catalog request')
    domain=payload.get('domain','all');page=payload.get('page',0)
    if domain not in {*DOMAINS,'all'} or type(page) is not int or page not in {0,1}: raise ValueError('Invalid domain/page')
    query=payload.get('query','')
    if not isinstance(query,str) or len(query)>100: raise ValueError('Invalid search')
    check_sensitive(query,secrets)
    lookups=[]
    if query.strip():
        lookups=[(query.strip(),DOMAINS[d],'search') for d in (DOMAINS if domain=='all' else [domain])]
    else:
        for d in (DOMAINS if domain=='all' else [domain]):
            lookups.extend((name,DOMAINS[d],'editor') for name in SEEDS[d][page][:2 if domain=='all' else 3])
    existing=payload.get('existing',[])
    if not isinstance(existing,list) or len(existing)>3: raise ValueError('Invalid existing tastes')
    for item in existing:
        if not isinstance(item,dict) or set(item)!={'query','entity_type'} or item['entity_type'] not in DOMAINS.values() or not isinstance(item['query'],str) or not 1<=len(item['query'].strip())<=100: raise ValueError('Invalid existing taste')
        check_sensitive(item['query'],secrets)
        lookups.append((item['query'],item['entity_type'],'existing'))
    session.qloo.max_calls=min(40,session.qloo.calls+12)
    cards={};failures=0
    for name,kind,mode in lookups:
        try:
            rows=result_array(session.qloo.get('/search',{'query':name,'types':'urn:entity:'+kind,'take':5}),'entities')
            rows=[r for r in rows if candidate_type(r)=='urn:entity:'+kind and isinstance(r.get('entity_id'),str) and isinstance(r.get('name'),str) and 1<=len(r['name'].strip())<=100]
            if mode!='search': rows=[r for r in rows if isinstance(r.get('name'),str) and identity_name(r['name'])==identity_name(name)]
            ambiguous=len(rows)>1
            if mode=='editor':
                rows.sort(key=lambda r:r['properties']['publication_year'] if isinstance(r.get('properties'),dict) and type(r['properties'].get('publication_year')) is int else 9999)
                rows=rows[:1]
            for row in rows:
                if candidate_type(row)!='urn:entity:'+kind or not isinstance(row.get('entity_id'),str) or not isinstance(row.get('name'),str) or not 1<=len(row['name'].strip())<=100: continue
                item={'id':row['entity_id'],'name':row['name'].strip(),'entity_type':kind}
                if mode=='editor':item['editorial']=True
                year=(row.get('properties') or {}).get('publication_year' if kind=='book' else 'release_year') if isinstance(row.get('properties'),dict) else None
                if type(year) is int: item['year']=year
                if isinstance(row.get('disambiguation'),str) and row['disambiguation'].strip(): item['detail']=row['disambiguation'][:160]
                aliases=(row.get('properties') or {}).get('akas') if isinstance(row.get('properties'),dict) else None
                if isinstance(aliases,list):
                    item['aliases']=[{'language':a['language'],'value':a['value']} for a in aliases[:10] if isinstance(a,dict) and isinstance(a.get('language'),str) and isinstance(a.get('value'),str) and len(a['language'])<=20 and 0<len(a['value'])<=150]
                if ambiguous: item['ambiguous']=True
                session.taste_catalog[item['id']]=item;cards[item['id']]=item
        except ServiceError as error:
            failures+=1
            if error.code in {'QLOO_AUTH','QLOO_AUTH_MISSING','QLOO_RATE_LIMIT','CALL_BUDGET_EXHAUSTED','MONTHLY_QUOTA_RESERVE','NETWORK_TIMEOUT_OR_UNAVAILABLE','WEB_PROCESS_BUDGET_EXHAUSTED'}:
                if not cards: raise
                break
    return {'status':'cards','cards':list(cards.values()),'partial':bool(failures),'search':bool(query.strip())}


def selected_tastes(session,items):
    """Validate a single exploration subset; this is not a saved-library limit."""
    if not isinstance(items,list) or not 1<=len(items)<=4: raise ValueError('Choose up to three likes and one curiosity')
    likes=[];curious=[];seen=set()
    for item in items:
        if not isinstance(item,dict) or set(item)!={'id','choice'} or not isinstance(item['id'],str) or item['id'] not in session.taste_catalog or item['id'] in seen or item['choice'] not in {'like','curious'}: raise ValueError('Invalid selected card')
        seen.add(item['id']);card=session.taste_catalog[item['id']]
        (likes if item['choice']=='like' else curious).append(card)
    if len(likes)>3 or len(curious)>1: raise ValueError('Choose up to three likes and one curiosity')
    return likes,curious
