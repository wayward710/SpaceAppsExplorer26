#!/usr/bin/env python3
"""Read-only inventory of Earth study areas from Qwen project metadata JSONL.
No network calls or database writes. Uses only Python standard library.
"""
import argparse, collections, csv, json, pathlib, re, unicodedata

def norm(s):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', s).strip()).casefold()

def write_csv(path, rows, fields):
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); w.writeheader(); w.writerows(rows)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', required=True)
    p.add_argument('--out', default='study_location_audit')
    args=p.parse_args()
    out=pathlib.Path(args.out);out.mkdir(parents=True,exist_ok=True)
    groups={}; project_locs=[]; excluded=collections.Counter(); malformed=[]; projects=set(); eligible_mentions=0
    with open(args.input, encoding='utf-8') as f:
        for line_no,line in enumerate(f,1):
            try: d=json.loads(line)
            except json.JSONDecodeError as e: malformed.append({'line':line_no,'reason':str(e)});continue
            r=d.get('record',d)
            if not isinstance(r,dict): malformed.append({'line':line_no,'reason':'record not object'});continue
            pid=str(d.get('project_id') or r.get('project_id') or '')
            projects.add(pid)
            locations=r.get('locations') or []
            if not isinstance(locations,list): malformed.append({'line':line_no,'reason':'locations not list'});continue
            seen=set()
            for x in locations:
                if not isinstance(x,dict): malformed.append({'line':line_no,'reason':'location not object'});continue
                role=str(x.get('role') or '').casefold();kind=str(x.get('location_type') or '').casefold();body=str(x.get('parent_body') or '').casefold()
                if role!='study_area': excluded['non_study_area']+=1;continue
                if kind!='terrestrial' or body not in ('earth',''):
                    excluded['non_earth_or_unclassified_study_area']+=1;continue
                name=x.get('name')
                if not isinstance(name,str) or not name.strip():malformed.append({'line':line_no,'reason':'missing location name'});continue
                eligible_mentions+=1;key=norm(name)
                if not key:continue
                g=groups.setdefault(key,{'names':collections.Counter(),'projects':set(),'mentions':0,'evidence':[], 'confidence':collections.Counter()})
                g['names'][name.strip()]+=1;g['projects'].add(pid);g['mentions']+=1;g['confidence'][str(x.get('confidence') or '')]+=1
                ev=str(x.get('evidence') or '').replace('\n',' ').strip()
                if ev and len(g['evidence'])<3 and ev not in g['evidence']:g['evidence'].append(ev[:300])
                if key not in seen:
                    project_locs.append({'project_id':pid,'location_key':key,'original_name':name.strip(),'confidence':x.get('confidence') or '', 'evidence':ev[:500]})
                    seen.add(key)
    rows=[]
    for key,g in groups.items():
        display=g['names'].most_common(1)[0][0]
        rows.append({'location_key':key,'display_name':display,'project_count':len(g['projects']),'mentions':g['mentions'],
                     'name_variants':' | '.join(n for n,_ in g['names'].most_common()),
                     'confidence_counts':json.dumps(g['confidence'],ensure_ascii=False,sort_keys=True),
                     'evidence_examples':' | '.join(g['evidence']),
                     'geocode_status':'unresolved','latitude':'','longitude':'','provider':'','match_review':''})
    rows.sort(key=lambda x:(-x['project_count'],x['location_key']))
    write_csv(out/'study_location_inventory.csv',rows,['location_key','display_name','project_count','mentions','name_variants','confidence_counts','evidence_examples','geocode_status','latitude','longitude','provider','match_review'])
    write_csv(out/'project_study_locations.csv',project_locs,['project_id','location_key','original_name','confidence','evidence'])
    write_csv(out/'parse_warnings.csv',malformed,['line','reason'])
    summary={'input':args.input,'projects_seen':len(projects),'eligible_earth_study_area_mentions':eligible_mentions,'unique_earth_study_area_names':len(groups),'projects_with_earth_study_area':len({x['project_id'] for x in project_locs}),'excluded_mentions':dict(excluded),'parse_warnings':len(malformed),'note':'No geocoding attempted. Coordinates remain blank. Source file unchanged.'}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
