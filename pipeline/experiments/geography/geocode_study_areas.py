#!/usr/bin/env python3
"""Conservative offline GeoNames matcher for Space Apps study-area inventory.
No network calls, no source modifications. Python standard library only.
"""
import argparse,csv,json,re,unicodedata,zipfile,collections,pathlib

def norm(s):
 s=unicodedata.normalize('NFKD',s or '')
 return ' '.join(''.join(c for c in s if not unicodedata.combining(c)).casefold().replace('’',"'").split())
def readcsv(path):
 with open(path,encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def writecsv(path,rows,cols):
 with open(path,'w',encoding='utf-8',newline='') as f:
  w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)
def geonames(path):
 path=pathlib.Path(path)
 if path.suffix=='.zip':
  z=zipfile.ZipFile(path); names=[n for n in z.namelist() if n.endswith('.txt')]; f=z.open(names[0]); import io; stream=io.TextIOWrapper(f,encoding='utf-8')
 else:stream=open(path,encoding='utf-8')
 try:
  for line in stream:
   p=line.rstrip('\n').split('\t')
   if len(p)<15:continue
   try: lat=float(p[4]);lon=float(p[5]);population=int(p[14] or 0)
   except ValueError:continue
   yield {'id':p[0],'name':p[1],'ascii':p[2],'aliases':p[3].split(',') if p[3] else [],'lat':lat,'lon':lon,'class':p[6],'code':p[7],'country':p[8],'admin1':p[10],'population':population}
 finally:stream.close()
def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--inventory',required=True);ap.add_argument('--projects',required=True);ap.add_argument('--geonames',required=True,help='allCountries.zip or cities15000.zip (cities-only misses countries and physical features)');ap.add_argument('--out',default='geocode_offline');ap.add_argument('--claude-limit',type=int,default=100)
 a=ap.parse_args();out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=True)
 inventory=readcsv(a.inventory);project_rows=readcsv(a.projects)
 # Match primary name or ASCII name only. Aliases deliberately not used for auto acceptance.
 wanted={norm(r['display_name']) for r in inventory}; index=collections.defaultdict(list)
 for g in geonames(a.geonames):
  if g['class'] not in ('A','P','H','L','T','V'):continue
  for n in {norm(g['name']),norm(g['ascii'])}&wanted:index[n].append(g)
 global_names={'earth','world','worldwide','global','the world','planet earth','arctic','antarctic','amazon','africa','asia','europe','north america','south america','oceania','antarctica','pacific ocean','atlantic ocean','indian ocean'}
 accepted=[];review=[];unmatched=[]
 fields=['location_key','display_name','project_count','latitude','longitude','geoname_id','matched_name','feature_class','feature_code','country_code','match_method','coordinate_note','evidence_examples']
 reviewfields=['location_key','display_name','project_count','reason','candidate_count','candidates_json','evidence_examples']
 for r in inventory:
  name=r['display_name'];key=norm(name);count=int(r.get('project_count') or 0)
  base={'location_key':r['location_key'],'display_name':name,'project_count':count,'evidence_examples':r.get('evidence_examples','')}
  if key in global_names:
   review.append({**base,'reason':'global_or_broad_region_no_pin','candidate_count':0,'candidates_json':'[]'});continue
  candidates=index.get(key,[])
  # Explicitly disallow one-word administrative names without a country hint; avoid India/Pakistan Punjab.
  if not candidates:
   unmatched.append({**base,'reason':'no_exact_primary_name_match'});continue
  # Administrative countries only when GeoNames has exactly one PCLI/PCLD etc and no competing names.
  countries=[g for g in candidates if g['code'] in ('PCLI','PCLD','PCLF','PCLIX')]
  choice=None;method=None
  if len(countries)==1 and len({(g['country'],g['code']) for g in countries})==1:
   choice=countries[0];method='unique_country_name'
  elif len(candidates)==1 and candidates[0]['class'] in ('P','T','H','V','L'):
   # Unique geographic feature; no assumptions about area geometry.
   choice=candidates[0];method='unique_exact_feature'
  # Multiple matches are never auto-selected by population, including same-name cities.
  if choice:
   accepted.append({**base,'latitude':choice['lat'],'longitude':choice['lon'],'geoname_id':choice['id'],'matched_name':choice['name'],'feature_class':choice['class'],'feature_code':choice['code'],'country_code':choice['country'],'match_method':method,'coordinate_note':'GeoNames representative coordinate; not a computed polygon centroid'})
  else:
   ranked=sorted(candidates,key=lambda g:(g['class']=='A',g['population']),reverse=True)[:8]
   review.append({**base,'reason':'multiple_exact_matches_or_admin_requires_context','candidate_count':len(candidates),'candidates_json':json.dumps([{k:g[k] for k in ('id','name','country','admin1','class','code','lat','lon','population')} for g in ranked],ensure_ascii=False)})
 writecsv(out/'geocoded_locations.csv',accepted,fields)
 writecsv(out/'geocode_review.csv',review,reviewfields)
 writecsv(out/'geocode_unmatched.csv',unmatched,['location_key','display_name','project_count','reason','evidence_examples'])
 accepted_keys={r['location_key'] for r in accepted};covered={r['project_id'] for r in project_rows if r['location_key'] in accepted_keys}
 all_projects={r['project_id'] for r in project_rows}
 summary={'unique_inventory_names':len(inventory),'accepted_locations':len(accepted),'review_locations':len(review),'unmatched_locations':len(unmatched),'projects_with_study_area':len(all_projects),'projects_with_accepted_coordinate':len(covered),'coverage_of_study_area_projects_pct':round(100*len(covered)/len(all_projects),2) if all_projects else 0,'note':'Offline exact-name matching; coordinates are representative GeoNames points, not boundary centroids. Source files unchanged.'}
 (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
 # Small, evidence-bearing review queue for Claude. Unmatched names included only if high impact.
 queue=sorted(review+unmatched,key=lambda r:-int(r.get('project_count') or 0))[:a.claude_limit]
 writecsv(out/'claude_review_queue.csv',queue,['location_key','display_name','project_count','reason','candidate_count','candidates_json','evidence_examples'])
 print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
