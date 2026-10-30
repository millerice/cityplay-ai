"""Bounded live category probe; credentials and raw records remain private."""
import json
from collections import Counter
from cityplay.config import Settings, ROOT
from cityplay.transport import QlooClient, ServiceError
from cityplay.engine import result_array, distance_m, candidate_type
from cityplay.intent import Area
from cityplay.__main__ import save_private

DEFINITIONS = {
 'restaurant':('restaurant','Restaurant','urn:tag:genre:place'),
 'bakery':('bakery','Bakery','urn:tag:cuisine:qloo'),
 'gallery':('art gallery','Art gallery','urn:tag:category:place'),
 'cinema':('movie theater','Movie theater','urn:tag:category:place'),
 'theater':('performing arts theater','Performing arts theater','urn:tag:category:place'),
 'record_store':('record store','Record store','urn:tag:category:place'),
 'clothing':('clothing store','Clothing store','urn:tag:category:place'),
 'garden':('garden','Garden','urn:tag:category:place'),
}

def main():
 s=Settings.load();c=QlooClient(s.qloo_key,max_calls=35);root=ROOT/'.qloo-private/category-validation';rows=[]
 artists=result_array(c.get('/search',{'query':'Miles Davis','types':'urn:entity:artist','take':5}),'entities')
 exact=[x for x in artists if x.get('name')=='Miles Davis' and candidate_type(x)=='urn:entity:artist']
 if len(exact)!=1:raise RuntimeError('Cultural anchor ambiguous')
 signal=exact[0]['entity_id']
 for key,(q,name,kind) in DEFINITIONS.items():
  try:
   tags=result_array(c.get('/v2/tags',{'filter.query':q,'feature.semantic_search':True,'take':10}),'tags')
   matches=[x for x in tags if x.get('name')==name and x.get('type')==kind]
   if len(matches)!=1:rows.append({'category':key,'error':'TAG_NOT_UNIQUE'});print(key,'TAG_NOT_UNIQUE',flush=True);continue
   for city,lat,lon in [('new_york',40.722668,-73.99823),('shanghai',31+14/60,121+29/60)]:
    params={'filter.type':'urn:entity:place','filter.tags':matches[0]['id'],'filter.location':f'POINT({lon} {lat})','filter.location.radius':10000,'signal.interests.entities':signal,'feature.explainability':True,'take':10}
    data=c.get('/v2/insights',params);save_private(root/f'{key}-{city}.json',{'params':params,'response':data},s)
    values=result_array(data,'entities');valid=[x for x in values if x.get('subtype')=='urn:entity:place' and isinstance(x.get('properties'),dict) and x['properties'].get('is_closed') is not True and isinstance(x['properties'].get('address'),str) and x['properties']['address'].strip() and distance_m(Area(lat,lon,10000),x.get('location')) is not None and distance_m(Area(lat,lon,10000),x.get('location'))<=10000]
    row={'category':key,'city':city,'returned':len(values),'address_coordinates_not_closed':len(valid),'genres':dict(Counter((x.get('properties',{}).get('primary_genre') or {}).get('name','unknown') for x in valid))};rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
  except ServiceError as e:rows.append({'category':key,'error':e.code});print(key,e.code,flush=True)
 save_private(root/'venue-summary.json',{'attempts':c.calls,'rows':rows},s)
 print('ATTEMPTS',c.calls,flush=True)
if __name__=='__main__':main()
