#!/usr/bin/env python3
"""Create a human-readable, read-only review of stage-three ID repair proposals."""
import argparse,csv,json,sqlite3,base64
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--review',required=True);p.add_argument('--candidates',required=True);p.add_argument('--out',default='id_repair_review_enriched.csv');a=p.parse_args()
 rows=list(csv.DictReader(open(a.review,encoding='utf-8-sig',newline='')))
 candidates={}
 for line in open(a.candidates,encoding='utf-8'):
  if line.strip():
   o=json.loads(line);candidates[o['project_id']]=o
 db=sqlite3.connect(a.db)
 output=[]
 for r in rows:
  project=db.execute('SELECT name,summary FROM projects WHERE id=?',(r['project_id'],)).fetchone()
  candidate=candidates.get(r['project_id']);record=(candidate or {}).get('record',{})
  summary=(project[1] or '') if project else ''
  metadata=[]
  for item in record.get('keywords',[]): metadata.append((item.get('term',''),item.get('evidence','')))
  for item in record.get('locations',[]):metadata.append((item.get('name',''),item.get('evidence','')))
  supported=sum(bool(e) and e in summary for _,e in metadata)
  output.append({'batch':r['batch'],'project_id':r['project_id'],'project_title':project[0] if project else '(missing)', 'expected_decoded':r['decoded_expected'],'returned_decoded':r['decoded_returned'],'status':r['decision'],'passing_attempts':r['passing_attempts'],'source_attempt':(candidate or {}).get('source_attempt',''),'summary':summary,'activity_type':record.get('activity_type',''),'keywords':'; '.join(str(x.get('term','')) for x in record.get('keywords',[])),'locations':'; '.join(str(x.get('name',''))+' ('+str(x.get('role',''))+')' for x in record.get('locations',[])),'retained_evidence_verbatim':f'{supported}/{len(metadata)}','removed_metadata_count':len((candidate or {}).get('removed_metadata',[])),'review_decision':'','review_notes':''})
 out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
 with out.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(output[0]));w.writeheader();w.writerows(output)
 print(f'Wrote {len(output)} review rows to {out}; {len(candidates)} candidate records.')
if __name__=='__main__':main()
