#!/usr/bin/env python3
"""Read-only map readiness audit for Space Apps GeoNames matching outputs."""
import argparse,csv,json,collections,pathlib

def rows(path):
    with open(path,encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))
def write(path, data, fields):
    with open(path,'w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(data)
def classify(r):
    fc=r['feature_class']; code=r['feature_code'].upper(); name=r['display_name'].casefold()
    if code in {'PCLI','PCL','PCLD','PCLF','PCLH','PCLS','PCLIX','TERR','CONT'} or name in {'earth','world','global','worldwide'}:return 'filter_only','country_or_global'
    if code in {'ADM1','ADM1H','ADM2','ADM2H'}:return 'region','administrative_region'
    if code.startswith('ADM') or code in {'RGN','RGNE','RGNH','AREA','LCTY','ZONE'}:return 'region','broad_or_uncertain_region'
    if code in {'DSRT','DSRTS','PLAT','PLN','MTS','MT','VLC','CRTR','ISL','ISLS','LK','LKS','BAY','GULF','SEA','OCN','PEN','CAPE','GLCR','VAL','VLY','BASN','FRST','RES','PARK','PRK','R','STM','WTRF','DPR','DPRN'}:return 'region','extensive_feature_review_scale'
    if fc=='P':return 'pin','populated_place'
    if fc in {'H','S','T','L','V'}:return 'pin','localized_feature_provisional'
    return 'region','unknown_feature_type_review'
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--accepted',required=True);ap.add_argument('--review',required=True);ap.add_argument('--unmatched',required=True);ap.add_argument('--projects',required=True);ap.add_argument('--out',default='map_readiness');a=ap.parse_args()
    accepted=rows(a.accepted);review=rows(a.review);unmatched=rows(a.unmatched);projects=rows(a.projects);out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=True)
    seen={};result=[]
    for r in accepted:
        key=r['location_key']; status,reason=classify(r); seen[key]=status;result.append({**r,'map_status':status,'map_reason':reason,'review_recommended': 'yes' if reason in {'extensive_feature_review_scale','broad_or_uncertain_region','unknown_feature_type_review'} else 'no'})
    for status,records in [('unresolved',review),('unresolved',unmatched)]:
        for r in records:
            key=r['location_key'];seen[key]=status
    byproject=collections.defaultdict(set)
    for r in projects:
        if r.get('project_id') and r.get('location_key') in seen:byproject[r['project_id']].add(seen[r['location_key']])
    count=collections.Counter(r['map_status'] for r in result)
    project_count={s:sum(s in statuses for statuses in byproject.values()) for s in ['pin','region','filter_only','unresolved']}
    map_projects=sum(bool(statuses & {'pin','region'}) for statuses in byproject.values())
    pin_projects=sum('pin' in statuses for statuses in byproject.values())
    summary={'accepted_locations':len(accepted),'accepted_by_map_status':dict(count),'review_locations':len(review),'unmatched_locations':len(unmatched),'projects_with_any_study_area':len(byproject),'projects_with_pin':pin_projects,'projects_with_pin_or_region':map_projects,'projects_by_status_overlapping':project_count,'map_ready_pct_of_study_area_projects':round(map_projects/len(byproject)*100,2) if byproject else 0,'note':'Classification is provisional; broad physical features may require manual scale review. No files or coordinates were modified.'}
    fields=list(result[0].keys()) if result else ['location_key','map_status'];write(out/'map_candidates.csv',result,fields)
    reviewpriority=[]
    for r in review+unmatched:
        reviewpriority.append({'location_key':r['location_key'],'display_name':r['display_name'],'project_count':r.get('project_count',''),'reason':r.get('reason',''),'candidate_count':r.get('candidate_count',''),'evidence_examples':r.get('evidence_examples','')})
    reviewpriority.sort(key=lambda r:-int(r['project_count'] or 0));write(out/'unresolved_priority.csv',reviewpriority,['location_key','display_name','project_count','reason','candidate_count','evidence_examples'])
    with open(out/'summary.json','w') as f:json.dump(summary,f,indent=2)
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
