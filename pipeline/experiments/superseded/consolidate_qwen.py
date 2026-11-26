#!/usr/bin/env python3
"""Consolidate accepted Space Apps extraction, stage-2 salvage and approved stage-3 ID repairs.
Read-only inputs, no Ollama calls. Standard library only.
"""
import argparse, csv, json, re
from pathlib import Path

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))

def read_jsonl(path):
    with path.open(encoding='utf-8-sig') as f:
        for line in f:
            if line.strip(): yield json.loads(line)

def get_id(row):
    return str(row.get('project_id') or row.get('id') or '')

def rows(obj):
    if isinstance(obj,list): return obj
    if isinstance(obj,dict):
        for k in ('results','projects','items'):
            if isinstance(obj.get(k),list): return obj[k]
    return []

def write_jsonl(path,items):
    with path.open('w',encoding='utf-8') as f:
        for item in items: f.write(json.dumps(item,ensure_ascii=False)+'\n')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--responses',type=Path,default=Path('production_full'))
    p.add_argument('--stage2',type=Path,default=Path('recovery_stage2'))
    p.add_argument('--stage3',type=Path,default=Path('recovery_stage3_audit'))
    p.add_argument('--review',type=Path,default=None,help='Enriched CSV; blank decisions allowed only with --approve-validated')
    p.add_argument('--approve-validated',action='store_true',help='Approve all structurally validated stage-3 candidates (user reviewed)')
    p.add_argument('--out',type=Path,default=Path('consolidated_full'))
    args=p.parse_args()
    source=list(read_jsonl(args.responses/'source_projects.jsonl'))
    source_ids=[get_id(x) for x in source]
    if not all(source_ids) or len(source_ids)!=len(set(source_ids)):
        p.error('Missing or duplicate IDs in source_projects.jsonl')
    expected=set(source_ids)
    batch_size=int(read_json(args.responses/'run_settings.json').get('batch_size',5))
    accepted={}; provenance={}
    for path in sorted(args.responses.glob('response_*.json')):
        match=re.fullmatch(r'response_(\d{6})\.json',path.name)
        if not match: continue
        batch=int(match.group(1)); expected_batch=source_ids[batch*batch_size:(batch+1)*batch_size]
        records=rows(read_json(path))
        ids=[get_id(x) for x in records]
        if len(records)!=len(expected_batch) or ids!=expected_batch:
            p.error(f'Unexpected IDs in accepted response {path.name}; refusing consolidation')
        for record in records:
            ident=get_id(record)
            if ident in accepted: p.error(f'Duplicate accepted ID {ident}')
            accepted[ident]=record
            provenance[ident]={'origin':'production','file':path.name,'batch':batch}
    stage2_count=0
    for wrapper in read_jsonl(args.stage2/'recovered_records.jsonl'):
        record=wrapper.get('record')
        if not isinstance(record,dict): p.error('Stage2 wrapper missing record')
        ident=get_id(record)
        if ident!=get_id(wrapper) or ident not in expected or ident in accepted:
            p.error(f'Stage2 unexpected or duplicate ID: {ident}')
        accepted[ident]=record; stage2_count+=1
        provenance[ident]={'origin':'stage2','batch':wrapper.get('batch'),'file':wrapper.get('source_attempt'),'recovery_status':wrapper.get('recovery_status')}
    review_path=args.review or (args.stage3/'id_repair_review.csv')
    with review_path.open(encoding='utf-8-sig',newline='') as f:
        review=list(csv.DictReader(f))
    approved=set(); rejected=set()
    for row in review:
        ident=row['project_id'].strip(); status=row.get('status','').strip()
        decision=(row.get('review_decision') or '').strip().lower()
        if decision in ('approve','approved','yes','y'):
            if status!='manual_review_candidate': p.error(f'Cannot approve unvalidated candidate {ident}')
            approved.add(ident)
        elif decision in ('reject','rejected','no','n'): rejected.add(ident)
        elif decision:
            p.error(f'Unknown review_decision {decision!r} for {ident}')
        elif args.approve_validated and status=='manual_review_candidate': approved.add(ident)
    if approved & rejected: p.error('Contradictory approval decisions')
    candidates={}
    for wrapper in read_jsonl(args.stage3/'id_repair_candidate_records.jsonl'):
        ident=get_id(wrapper)
        if ident in candidates: p.error(f'Duplicate stage3 candidate ID {ident}')
        candidates[ident]=wrapper
    for ident in approved:
        if ident not in candidates: p.error(f'Approved ID has no candidate record: {ident}')
        wrapper=candidates[ident]; record=wrapper.get('record')
        if not isinstance(record,dict) or get_id(record)!=ident:
            p.error(f'Invalid candidate record ID {ident}')
        if ident not in expected or ident in accepted: p.error(f'Approved ID collision: {ident}')
        accepted[ident]=record
        provenance[ident]={'origin':'stage3_id_repair','batch':wrapper.get('batch'),'file':wrapper.get('source_attempt'),'original_returned_id':wrapper.get('original_returned_id'),'approval':'user_reviewed_validated'}
    missing=[ident for ident in source_ids if ident not in accepted]
    output=args.out
    if output.resolve() in (args.responses.resolve(),args.stage2.resolve(),args.stage3.resolve()):
        p.error('Output must be separate from input directories')
    output.mkdir(parents=True,exist_ok=True)
    write_jsonl(output/'projects_metadata.jsonl',({'project_id':ident,'record':accepted[ident],'provenance':provenance[ident]} for ident in source_ids if ident in accepted))
    write_jsonl(output/'retry_queue.jsonl',({'project_id':ident,'source':source[i],'batch':i//batch_size} for i,ident in enumerate(source_ids) if ident not in accepted))
    with (output/'approved_id_repairs.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=['project_id','batch','source_attempt','original_returned_id'])
        writer.writeheader()
        for ident in sorted(approved):
            x=candidates[ident]; writer.writerow({'project_id':ident,'batch':x.get('batch'),'source_attempt':x.get('source_attempt'),'original_returned_id':x.get('original_returned_id')})
    summary={'source_projects':len(source_ids),'original_accepted':len(accepted)-stage2_count-len(approved),'stage2_recovered':stage2_count,'approved_stage3_repairs':len(approved),'total_covered':len(accepted),'remaining':len(missing),'coverage_pct':round(100*len(accepted)/len(source_ids),4),'output_files':['projects_metadata.jsonl','retry_queue.jsonl','approved_id_repairs.csv']}
    (output/'consolidation_summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
