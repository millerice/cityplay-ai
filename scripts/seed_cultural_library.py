"""Bounded, explicit editorial seed import; no keys, raw responses or assumed IDs."""
import argparse
from cityplay.config import Settings,ROOT
from cityplay.transport import QlooClient,ServiceError
from cityplay.engine import result_array,candidate_type,identity_name
from cityplay.library import LibraryStore

PLAN={
 'artist':['Miles Davis','Beyoncé','Björk','Taylor Swift','Bob Marley','Ludwig van Beethoven','David Bowie','Nina Simone','Daft Punk','Radiohead','Billie Eilish','Stevie Wonder','John Coltrane','Dolly Parton','Kendrick Lamar','Adele','Ryuichi Sakamoto','Nirvana','ABBA','Steely Dan'],
 'movie':['Spirited Away','The Matrix','Amélie','Interstellar','Toy Story','Parasite','Blade Runner','The Grand Budapest Hotel','In the Mood for Love','Arrival','The Godfather','The Truman Show','Coco','My Neighbor Totoro','Whiplash','Moonlight','Fantastic Mr. Fox','Dune','The Lord of the Rings: The Fellowship of the Ring','Before Sunrise'],
 'book':['The Little Prince','Pride and Prejudice','One Hundred Years of Solitude','Robinson Crusoe','Dune','The Hobbit','1984','The Great Gatsby','To Kill a Mockingbird','The Catcher in the Rye','Jane Eyre','Frankenstein','The Alchemist','Sapiens','Norwegian Wood','The Name of the Rose','Fahrenheit 451','The Road','A Brief History of Time','The Three-Body Problem']}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=60);args=parser.parse_args()
    if not 1<=args.limit<=60:parser.error('limit must be 1..60')
    settings=Settings.load();client=QlooClient(settings.qloo_key,max_calls=70)
    store=LibraryStore(ROOT/'.qloo-private'/'cityplay.sqlite3')
    found=missed=errors=0
    for index,(kind,name) in enumerate([(k,v) for k,values in PLAN.items() for v in values][:args.limit],1):
        try:
            rows=result_array(client.get('/search',{'query':name,'types':'urn:entity:'+kind,'take':5}),'entities')
            rows=[r for r in rows if candidate_type(r)=='urn:entity:'+kind and isinstance(r.get('entity_id'),str) and isinstance(r.get('name'),str) and identity_name(r['name'])==identity_name(name)]
            rows.sort(key=lambda r:r['properties']['publication_year'] if isinstance(r.get('properties'),dict) and type(r['properties'].get('publication_year')) is int else 9999)
            if not rows:missed+=1;continue
            row=rows[0];props=row.get('properties') if isinstance(row.get('properties'),dict) else {}
            card={'id':row['entity_id'],'name':row['name'].strip(),'entity_type':kind,'ambiguous':len(rows)>1}
            year=props.get('publication_year' if kind=='book' else 'release_year')
            if type(year) is int:card['year']=year
            if isinstance(row.get('disambiguation'),str):card['detail']=row['disambiguation'][:160]
            aliases=props.get('akas')
            if isinstance(aliases,list):card['aliases']=[{'language':a['language'],'value':a['value']} for a in aliases[:10] if isinstance(a,dict) and isinstance(a.get('language'),str) and isinstance(a.get('value'),str)]
            store.put_entities([card],source='Qloo /search · editorial seed');found+=1
        except ServiceError as error:
            errors+=1
            if error.code in {'QLOO_AUTH','QLOO_AUTH_MISSING','MONTHLY_QUOTA_RESERVE','CALL_BUDGET_EXHAUSTED','QLOO_RATE_LIMIT'}:break
        finally:
            if index%5==0:print(f'checked={index} imported={found} unmatched={missed} failed={errors}',flush=True)
    print(f'complete imported={found} unmatched={missed} failed={errors} network_attempts={client.calls}',flush=True)

if __name__=='__main__':main()
