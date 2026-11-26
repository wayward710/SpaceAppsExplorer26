"""Offline pilot geographic mention extraction with spaCy NER.
Install: py -3.12 -m pip install spacy
         py -3.12 -m spacy download en_core_web_sm
Run: py -3.12 extract_project_places.py --sample sample_300_full.jsonl
No geocoding is attempted. Every candidate needs human review.
"""
import argparse,csv,json,re
from pathlib import Path
from collections import Counter
import spacy

# Common nongeographic false positives for Earth/space science projects.
EXCLUDE={'earth','mars','moon','sun','nasa','space apps','space apps challenge','google earth','planet earth','united nations','international space station'}
STUDY=re.compile(r'\b(stud(?:y|ied|ying)|focus(?:es|ed)? on|monitor(?:s|ing|ed)?|map(?:s|ping|ped)?|analy[sz](?:e|es|ed|ing)|flood(?:s|ing)?|drought|wildfire|case study|soil moisture|water quality|crop|region|target area|observ(?:e|ing|ed))\b',re.I)
TEAM=re.compile(r'\b(our team|we are from|team members|based in|our university|our school|our city)\b',re.I)
BACKGROUND=re.compile(r'\b(for example|such as|e\.g\.|similar to|in comparison|previously|according to|source:|references?)\b',re.I)

def role(sentence):
 if TEAM.search(sentence):return 'possible_team_context'
 if BACKGROUND.search(sentence):return 'possible_context'
 if STUDY.search(sentence):return 'possible_study_area'
 return 'unknown'

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--sample',default='sample_300_full.jsonl');ap.add_argument('--out',default='geography_pilot');ap.add_argument('--model',default='en_core_web_sm');a=ap.parse_args()
 try:nlp=spacy.load(a.model,disable=['tagger','parser','lemmatizer','attribute_ruler'])
 except OSError as e:raise SystemExit('Missing spaCy model. Run: py -3.12 -m spacy download en_core_web_sm') from e
 nlp.add_pipe('sentencizer')
 projects=[]
 with open(a.sample,encoding='utf-8-sig') as f:
  for line in f:
   if line.strip():projects.append(json.loads(line))
 texts=[];meta=[]
 for p in projects:
  # Project text only; deliberately exclude challenge name, team location, citations and AI disclosures.
  for field in ('project_name','summary','details_text'):
   t=re.sub(r'<[^>]*>',' ',str(p.get(field) or ''))
   t=re.sub(r'\s+',' ',t).strip()
   if t:texts.append(t[:120000]);meta.append((p,field))
 out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
 rows=[];counts=Counter();unique_projects=set();seen=set()
 for (p,field),doc in zip(meta,nlp.pipe(texts,batch_size=12)):
  for ent in doc.ents:
   if ent.label_ not in ('GPE','LOC','FAC'):continue
   name=ent.text.strip(' \t\r\n.,;:()[]')
   if len(name)<3 or name.lower() in EXCLUDE:continue
   sent=ent.sent.text.strip()[:650]
   key=(p['project_id'],field,name.casefold(),sent)
   if key in seen:continue
   seen.add(key);r=role(sent)
   rows.append({'project_id':p['project_id'],'project_name':p.get('project_name',''),'challenge_title':p.get('challenge_title',''),'source_field':field,'place_mention':name,'ner_label':ent.label_,'proposed_role':r,'sentence':sent,'resolved_place_id':'','review_status':'','review_notes':''})
   counts[r]+=1;unique_projects.add(p['project_id'])
 fields=['project_id','project_name','challenge_title','source_field','place_mention','ner_label','proposed_role','sentence','resolved_place_id','review_status','review_notes']
 with open(out/'place_mentions_review.csv','w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 with open(out/'project_geography_coverage.csv','w',encoding='utf-8-sig',newline='') as f:
  w=csv.writer(f);w.writerow(['project_id','project_name','challenge_title','place_mentions','distinct_place_strings','possible_study_mentions'])
  for p in projects:
   subset=[r for r in rows if r['project_id']==p['project_id']];w.writerow([p['project_id'],p.get('project_name',''),p.get('challenge_title',''),len(subset),len(set(r['place_mention'].casefold() for r in subset)),sum(r['proposed_role']=='possible_study_area' for r in subset)])
 summary={'projects':len(projects),'projects_with_candidates':len(unique_projects),'place_mentions':len(rows),'role_heuristics':dict(counts),'limitations':['NER may miss places or mistake organizations/people for places','Roles are keyword-based suggestions only','No gazetteer resolution or geographic hierarchy yet','Project text only; team location is a separate facet']}
 (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8');print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
