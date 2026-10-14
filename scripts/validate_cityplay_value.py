"""Bounded live Qloo comparison. Raw data stays private; public report is aggregate."""
import json
import math
import re
import uuid
from collections import Counter
from pathlib import Path
from cityplay.config import Settings, ROOT
from cityplay.transport import QlooClient, ServiceError
from cityplay.__main__ import save_private
from cityplay.engine import result_array, candidate_type, PUBLIC_CATEGORIES, distance_m
from cityplay.intent import Area


def main():
    settings = Settings.load()
    client = QlooClient(settings.qloo_key, max_calls=30)
    run = ROOT / '.qloo-private' / 'value-validation' / str(uuid.uuid4())
    def request(label, path, params):
        value = client.get(path, params)
        save_private(run / (label+'.json'), {'path':path,'params':params,'response':value}, settings)
        return value
    def tag(query, name, kind):
        tags = result_array(request('tag-'+query.replace(' ','-'), '/v2/tags', {'filter.query':query,'feature.semantic_search':True,'take':10}), 'tags')
        matches = [x for x in tags if str(x.get('name','')).strip()==name and x.get('type')==kind]
        if len(matches)!=1: raise ValueError('Tag resolution not unique')
        return matches[0]['id']
    def entity(query, kind, year=None):
        values = result_array(request('entity-'+query.replace(' ','-'), '/search', {'query':query,'types':'urn:entity:'+kind,'take':10}), 'entities')
        matches = [x for x in values if x.get('name')==query and candidate_type(x)=='urn:entity:'+kind and (year is None or (x.get('properties') or {}).get('release_year')==year)]
        if len(matches)!=1: raise ValueError('Entity resolution not unique')
        return matches[0]['entity_id']
    signals={}
    definitions=[('miles',lambda: {'signal.interests.entities':entity('Miles Davis','artist')}),
                 ('blade',lambda: {'signal.interests.entities':entity('Blade Runner','movie',1982)}),
                 ('jazz',lambda: {'signal.interests.tags':tag('jazz','Jazz','urn:tag:genre:music')}),
                 ('book_interest',lambda: {'signal.interests.tags':tag('bookstore','Book store','urn:tag:category:place')}),
                 ('coffee_interest',lambda: {'signal.interests.tags':tag('coffee','Coffee','urn:tag:cuisine:qloo')})]
    resolution_errors={}
    for label, resolve in definitions:
        try:signals[label]=resolve()
        except (ServiceError,ValueError,KeyError) as error:resolution_errors[label]=error.code if isinstance(error,ServiceError) else 'RESOLUTION_NOT_UNIQUE_OR_SCHEMA'
    cases={'baseline':{},**signals}
    if 'book_interest' in signals:cases['book_filter']={'filter.tags':signals['book_interest']['signal.interests.tags']}
    if 'coffee_interest' in signals:cases['coffee_filter']={'filter.tags':signals['coffee_interest']['signal.interests.tags']}
    if 'miles' in signals and 'book_filter' in cases:cases['miles_books']={**signals['miles'],**cases['book_filter']}
    if 'blade' in signals and 'coffee_filter' in cases:cases['blade_coffee']={**signals['blade'],**cases['coffee_filter']}
    rows=[]; private_ids={}; unique={}
    allowed=set().union(*PUBLIC_CATEGORIES.values())
    for city,lat,lon in [('Shanghai',31+14/60,121+29/60),('NewYork',40.722668,-73.99823)]:
        area=Area(lat,lon,10000);unique[city]={}
        for label, extra in cases.items():
            params={'filter.type':'urn:entity:place','filter.location':f'POINT({lon} {lat})','filter.location.radius':10000,'take':10,**extra}
            try:
                values=result_array(request(city+'-'+label,'/v2/insights',params),'entities')
                ids=[x.get('entity_id') for x in values]
                private_ids[(city,label)]=ids
                genres=Counter(); counts=Counter(); keys=Counter()
                for item in values:
                    props=item.get('properties') or {};keys.update(props.keys())
                    genre=(props.get('primary_genre') or {}).get('name','unknown')
                    genres[genre]+=1
                    delta=distance_m(area,item.get('location'))
                    coordinates=delta is not None and delta<=10000
                    address=isinstance(props.get('address'),str) and bool(props['address'].strip())
                    counts['coordinates_in_radius']+=coordinates
                    counts['address']+=address
                    counts['address_coordinates']+=coordinates and address
                    counts['mvp_category']+=str(genre).strip().casefold() in allowed and props.get('is_closed') is not True and coordinates and address
                    counts['website_present']+=bool(props.get('website'))
                    counts['hours_nonempty']+=bool(props.get('hours'))
                    price=props.get('price_range') or {}
                    counts['numeric_price_bound']+=isinstance(price,dict) and any(type(price.get(k)) in {int,float} and math.isfinite(price[k]) for k in ['from','to'])
                    if item.get('entity_id'):unique[city][item['entity_id']]=item
                target = PUBLIC_CATEGORIES['bookstore'] if label in {'book_filter','miles_books'} else PUBLIC_CATEGORIES['coffee'] if label in {'coffee_filter','blade_coffee'} else allowed
                counts['target_category'] = sum(str((x.get('properties',{}).get('primary_genre') or {}).get('name','')).strip().casefold() in target and x.get('properties',{}).get('is_closed') is not True and distance_m(area,x.get('location')) is not None and distance_m(area,x.get('location'))<=10000 and bool(x.get('properties',{}).get('address')) for x in values)
                rows.append({'city':city,'case':label,'returned':len(values),'genres':dict(genres),'fields':dict(counts),'property_keys':dict(keys)})
                print(city,label,'returned',len(values),'mvp_category',counts['mvp_category'],flush=True)
            except ServiceError as error:rows.append({'city':city,'case':label,'error':error.code});print(city,label,error.code,flush=True)
    for row in rows:
        city,label=row['city'],row['case']
        if 'error' in row:continue
        baseline=private_ids.get((city,'baseline'),[]);ids=private_ids[(city,label)]
        row['shared_with_baseline']=len(set(ids)&set(baseline))
        row['order_changed_vs_baseline']=ids!=baseline
        if label in {'miles_books','blade_coffee'}:
            control = private_ids.get((city,'book_filter' if label=='miles_books' else 'coffee_filter'),[])
            row['shared_with_category_control']=len(set(ids)&set(control))
            row['order_changed_vs_category_control']=ids!=control
    save_private(run/'summary.json',{'rows':rows,'resolution_errors':resolution_errors,'calls':client.calls,'trace':client.trace,'unique_by_city':{k:len(v) for k,v in unique.items()}},settings)
    public={'rows':rows,'resolution_errors':resolution_errors,'calls':client.calls,'unique_by_city':{k:len(v) for k,v in unique.items()}}
    # Aggregate-only intermediate; no entity IDs, response records or key values.
    Path('/tmp/cityplay-value-summary.json').write_text(json.dumps(public,ensure_ascii=False,indent=2))
    print('Completed attempts:',client.calls,'resolution errors:',resolution_errors,flush=True)

if __name__=='__main__':main()
