#!/usr/bin/env python3
"""Offline, rerunnable validation of Qwen project extraction. Python 3.9+, stdlib only."""
import argparse, csv, json, re, unicodedata
from collections import Counter
from pathlib import Path

ROLES={'study_area','setting','background_context'}
TYPES={'terrestrial','extraterrestrial'}
CATS={'subject','method','data_source','application','technology'}
CONF={'high','medium','low'}
ALIASES={'lunar':'Moon','martian':'Mars','the moon':'Moon','earth':'Earth','mars':'Mars',
         'synthetic aperture radar':'SAR','ground sinking':'land subsidence',
         'mann kendall test':'Mann–Kendall test','crop rotation strategies':'crop rotation'}
# Strongly identifiable non-places; deliberately conservative, extend via JSON rules.
NOT_PLACES={'apollo 11','surveyor 1','viking','voyager','iss','international space station',
            'lunar habitat','mars rover','insight','nisar','modis','viirs'}
GENERIC={'web application','interactive web app','space exploration','nasa','science','data','project'}
BODY={'moon':'Moon','mars':'Mars','earth':'Earth'}
SPECIFIC_RE=re.compile(r'\b(south pole|north pole|planitia|crater|basin|valley|region|province|city)\b',re.I)

def normkey(s):
    return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',str(s)).strip()).casefold()

def load_source(path):
    if not path:return {}
    p=Path(path); rows=[]
    if p.suffix.lower()=='.jsonl':
        with p.open(encoding='utf-8-sig') as f:
            for line in f:
                if line.strip():rows.append(json.loads(line))
    else:
        x=json.loads(p.read_text(encoding='utf-8-sig'))
        rows=x if isinstance(x,list) else x.get('projects',x.get('results',[]))
    return {str(r['project_id']): '\n'.join(str(r.get(k) or '') for k in ('summary','details_excerpt')) for r in rows if isinstance(r,dict) and 'project_id' in r}

def load_responses(paths):
    for p in paths:
        obj=json.loads(p.read_text(encoding='utf-8-sig'))
        for r in obj.get('results',[]):
            if isinstance(r,dict):yield p.name,r

def write_csv(path,rows,cols):
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--responses',required=True,help='Directory of response_*.json files')
    ap.add_argument('--source',help='selected_50.json or full project JSONL with project_id and summary')
    ap.add_argument('--out',default='cleaned_results')
    ap.add_argument('--rules',help='Optional JSON with not_places, generic_keywords, keyword_aliases, location_aliases')
    a=ap.parse_args();out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    src=load_source(a.source)
    rules=json.loads(Path(a.rules).read_text(encoding='utf-8')) if a.rules else {}
    not_places=NOT_PLACES|{normkey(x) for x in rules.get('not_places',[])}
    generic=GENERIC|{normkey(x) for x in rules.get('generic_keywords',[])}
    ka={k:v for k,v in ALIASES.items() if k not in {'lunar','martian','the moon','earth','mars'}}
    ka.update({normkey(k):v for k,v in rules.get('keyword_aliases',{}).items()})
    la={k:v for k,v in ALIASES.items() if k in {'lunar','martian','the moon','earth','mars'}}
    la.update({normkey(k):v for k,v in rules.get('location_aliases',{}).items()})
    paths=sorted(Path(a.responses).glob('response_*.json'))
    if not paths:ap.error('No response_*.json files found')
    locations=[];keywords=[];reviews=[];raw=[];counts=Counter();seen_projects=set()
    for filename,r in load_responses(paths):
        pid=str(r.get('project_id',''));raw.append({'file':filename,'result':r});counts['projects']+=1
        if pid in seen_projects:reviews.append({'project_id':pid,'field':'project','value':pid,'status':'review','reason':'duplicate project across response files'})
        seen_projects.add(pid)
        text=src.get(pid)
        for kind in ('locations','keywords'):
            values=r.get(kind,[])
            if not isinstance(values,list):
                reviews.append({'project_id':pid,'field':kind,'value':'','status':'rejected','reason':'not a list'});continue
            for idx,item in enumerate(values):
                counts['raw_'+kind]+=1
                if not isinstance(item,dict):
                    reviews.append({'project_id':pid,'field':kind,'value':str(item),'status':'rejected','reason':'not an object'});continue
                name=str(item.get('name' if kind=='locations' else 'term') or '').strip()
                key=normkey(name); ev=item.get('evidence','')
                issues=[];status='accepted'
                def flag(level,reason):
                    nonlocal_status[0]='rejected' if level=='rejected' else ('review' if nonlocal_status[0]=='accepted' else nonlocal_status[0]);issues.append(reason)
                nonlocal_status=[status]
                if not name:flag('rejected','missing name/term')
                if item.get('confidence') not in CONF:flag('review','invalid confidence')
                if not isinstance(ev,str) or not ev.strip():flag('rejected','missing evidence')
                elif text is None:flag('review','source unavailable: evidence not verified')
                elif ev not in text:flag('review','evidence not verbatim')
                if kind=='locations':
                    canonical=la.get(key,name)
                    if item.get('role') not in ROLES or item.get('location_type') not in TYPES:flag('rejected','invalid geographic role/type')
                    if key in not_places:flag('rejected','known non-geographic entity')
                    if key in {'lunar south pole','martian south pole','mars south pole'} and text is not None and normkey(name) not in normkey(text):
                        flag('review','specific geographic name not present in source')
                    if SPECIFIC_RE.search(name) and text is not None and normkey(name) not in normkey(text):
                        flag('review','specific geographic name not present in source')
                    parent=item.get('parent_body')
                    if isinstance(parent,str) and normkey(parent) in BODY:parent=BODY[normkey(parent)]
                    if canonical in BODY.values() and parent is None:parent=canonical
                    if canonical=='Moon' and parent not in (None,'Moon'):flag('review','inconsistent parent body')
                    if canonical=='Mars' and parent not in (None,'Mars'):flag('review','inconsistent parent body')
                    row={'project_id':pid,'source_file':filename,'index':idx,'original_name':name,'name':canonical,
                         'role':item.get('role'),'location_type':item.get('location_type'),'parent_body':parent,
                         'confidence':item.get('confidence'),'evidence':ev,'status':nonlocal_status[0],'reasons':'; '.join(issues)}
                    locations.append(row)
                else:
                    canonical=ka.get(key,name)
                    if item.get('category') not in CATS:flag('rejected','invalid keyword category')
                    if idx>=5:flag('rejected','exceeds five keyword maximum')
                    if key in generic:flag('review','generic keyword: consider suppressing from facets')
                    if item.get('support') not in {'explicit','inferred'}:flag('review','invalid support label')
                    if key in {'nisar','modis','viirs','insight','donki'} and text is not None and key not in normkey(text):
                        flag('review','named instrument/dataset not present in source')
                    if key=='virtual reality' and text is not None and not any(x in normkey(text) for x in ('virtual reality','vr headset','vr experience')):
                        flag('review','VR inferred without explicit VR terminology')
                    row={'project_id':pid,'source_file':filename,'index':idx,'original_term':name,'term':canonical,
                         'category':item.get('category'),'support':item.get('support'),'confidence':item.get('confidence'),
                         'evidence':ev,'status':nonlocal_status[0],'reasons':'; '.join(issues)}
                    keywords.append(row)
                counts[kind+'_'+nonlocal_status[0]]+=1
                if nonlocal_status[0]!='accepted':reviews.append({'project_id':pid,'field':kind,'value':name,'status':nonlocal_status[0],'reason':'; '.join(issues)})
    write_csv(out/'locations_all.csv',locations,['project_id','source_file','index','original_name','name','role','location_type','parent_body','confidence','evidence','status','reasons'])
    write_csv(out/'keywords_all.csv',keywords,['project_id','source_file','index','original_term','term','category','support','confidence','evidence','status','reasons'])
    write_csv(out/'review_queue.csv',reviews,['project_id','field','value','status','reason'])
    write_csv(out/'locations_accepted.csv',[x for x in locations if x['status']=='accepted'],list(locations[0]) if locations else ['project_id'])
    write_csv(out/'keywords_accepted.csv',[x for x in keywords if x['status']=='accepted'],list(keywords[0]) if keywords else ['project_id'])
    (out/'raw_extractions.json').write_text(json.dumps(raw,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'summary.json').write_text(json.dumps(dict(counts),indent=2),encoding='utf-8')
    print(json.dumps(dict(counts),indent=2));print('Wrote:',out.resolve())
if __name__=='__main__':main()
