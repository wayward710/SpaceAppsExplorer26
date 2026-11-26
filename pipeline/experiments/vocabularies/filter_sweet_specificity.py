"""Conservative SWEET phrase filtering for Space Apps pilot.
Run: py -3.12 filter_sweet_specificity.py --matches concept_matches.csv --sample sample_300_full.jsonl
No external dependencies.
"""
import argparse,csv,json,re
from collections import Counter,defaultdict
from pathlib import Path

STOP = set('project projects impact impacts future platform power research decision development analysis accuracy important extraordinary plain clear system systems model models data information process processes result results method methods tool tools use user users application applications solution solutions approach approaches design designs mission missions space earth science scientific technology technologies challenge challenges team teams help support provide provides new different example examples based using used work works study studies area areas time times change changes quality high low large small global local environment environmental problem problems resource resources general specific potential level levels value values number numbers part parts type types way ways people community communities history reflection pioneer communication communications'.split())
# Single words must be explicitly approved; expand after reviewing results.
SCIENCE_SINGLE = set('precipitation groundwater irrigation drought flooding flood wildfire wildfires asteroid asteroids spectroscopy microgravity magnetosphere ionosphere thermosphere exoplanet exoplanets orbit orbits orbital salinity evapotranspiration aerosol aerosols albedo radar lidar vegetation biodiversity erosion sediment hydrology geology seismology tectonics photosynthesis methane ozone humidity glacier glaciers permafrost aquifer aquifers radiation climate atmosphere meteorology oceanography satellite satellites telemetry'.split())
# Multiword phrases still need exclusions to avoid generic phrases.
BAD_MULTI = {'data analysis','data science','information system','decision making','machine learning model','research project','future work','power system','space mission','earth science','new technology','web application'}

def clean(x):return re.sub(r'\s+',' ',re.sub(r'[^\w\s-]',' ',x.lower())).strip()
def classify(phrase):
 p=clean(phrase)
 if not p or p in BAD_MULTI:return 'low'
 words=p.split()
 if len(words)==1:return 'medium' if p in SCIENCE_SINGLE else 'low'
 if all(w in STOP for w in words):return 'low'
 if len(p)<7:return 'low'
 return 'high'

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--matches',default='concept_matches.csv');ap.add_argument('--sample',default='sample_300_full.jsonl');ap.add_argument('--out',default='sweet_filtered');a=ap.parse_args()
 projects={}
 with open(a.sample,encoding='utf-8-sig') as f:
  for line in f:
   if line.strip():
    p=json.loads(line);projects[str(p['project_id'])]=p
 out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 rows=[]; seen=set(); counts=Counter(); byproject=defaultdict(lambda:Counter()); terms=defaultdict(set)
 with open(a.matches,encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   pid=str(r['project_id']); phrase=r['matched_phrase']; key=(pid,clean(phrase))
   if pid not in projects or key in seen:continue
   seen.add(key);level=classify(phrase);r['specificity']=level;r['review_note']='multiple concepts' if int(r.get('concept_count') or 1)>1 else ''
   rows.append(r);counts[level]+=1;byproject[pid][level]+=1;terms[clean(phrase)].add(pid)
 fields=['project_id','project_name','challenge_title','matched_phrase','specificity','concept_uris','concept_count','ambiguous','review_note']
 with open(out/'filtered_matches.csv','w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(sorted(rows,key=lambda r:(r['project_id'],{'high':0,'medium':1,'low':2}[r['specificity']],r['matched_phrase'])))
 with open(out/'project_coverage.csv','w',encoding='utf-8-sig',newline='') as f:
  w=csv.writer(f);w.writerow(['project_id','project_name','challenge_title','high_terms','medium_terms','low_terms','high_or_medium','example_specific_terms'])
  for pid,p in projects.items():
   relevant=[r['matched_phrase'] for r in rows if r['project_id']==pid and r['specificity']!='low']
   c=byproject[pid];w.writerow([pid,p.get('project_name',''),p.get('challenge_title',''),c['high'],c['medium'],c['low'],c['high']+c['medium'],' | '.join(sorted(set(relevant))[:20])])
 with open(out/'term_review.csv','w',encoding='utf-8-sig',newline='') as f:
  w=csv.writer(f);w.writerow(['phrase','specificity','projects_matched']);
  for phrase,ids in sorted(terms.items(),key=lambda kv:(-len(kv[1]),kv[0])):w.writerow([phrase,classify(phrase),len(ids)])
 summary={'projects':len(projects),'match_rows_by_level':dict(counts),'projects_with_high':sum(c['high']>0 for c in byproject.values()),'projects_with_high_or_medium':sum(c['high']+c['medium']>0 for c in byproject.values()),'warning':'Heuristic specificity tiers, not validated scientific relevance; inspect term_review.csv.'}
 (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
