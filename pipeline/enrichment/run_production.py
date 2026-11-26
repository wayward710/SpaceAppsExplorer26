#!/usr/bin/env python3
"""Resumable SQLite -> Ollama geography/keyword extraction, Python stdlib only."""
import argparse, hashlib, json, os, sqlite3, sys, time, urllib.request, urllib.error
from pathlib import Path
from pilot_reference import INSTRUCTIONS, validate

def atomic_json(path, value):
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(tmp,path)

def load_projects(db, details_chars, limit):
    conn=sqlite3.connect(f'file:{Path(db).resolve()}?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    rows=conn.execute('SELECT id, summary, details_text FROM projects ORDER BY id'+(' LIMIT ?' if limit else ''), ((limit,) if limit else ()))
    for r in rows:
        summary=r['summary'] or ''
        details=r['details_text'] or ''
        if details.startswith(summary): details=details[len(summary):].lstrip()
        item={'project_id':r['id'],'summary':summary}
        if details_chars: item['details_excerpt']=details[:details_chars]
        yield item
    conn.close()

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db',required=True)
    ap.add_argument('--out',default='production_results')
    ap.add_argument('--url',default='http://localhost:11434')
    ap.add_argument('--model',default='qwen2.5:14b')
    ap.add_argument('--ctx',type=int,default=8192)
    ap.add_argument('--batch-size',type=int,default=5)
    ap.add_argument('--details-chars',type=int,default=0)
    ap.add_argument('--timeout',type=int,default=1200)
    ap.add_argument('--retries',type=int,default=3)
    ap.add_argument('--limit',type=int,default=0,help='Test first N projects; use a separate --out for tests')
    ap.add_argument('--retry-failed',action='store_true',help='Retry batches previously marked failed')
    args=ap.parse_args()
    if args.batch_size<1 or args.details_chars<0 or args.limit<0 or args.retries<1: ap.error('Invalid numeric argument')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    projects=list(load_projects(args.db,args.details_chars,args.limit))
    if not projects: ap.error('No projects in database')
    settings={'model':args.model,'ctx':args.ctx,'batch_size':args.batch_size,'details_chars':args.details_chars,'limit':args.limit,'project_count':len(projects),'project_ids_sha256':hashlib.sha256('\n'.join(p['project_id'] for p in projects).encode()).hexdigest(),'prompt_sha256':hashlib.sha256(INSTRUCTIONS.encode()).hexdigest()}
    sf=out/'run_settings.json'
    if sf.exists() and json.loads(sf.read_text(encoding='utf-8'))!=settings: ap.error('Settings/project set changed; choose another --out to avoid mixing results')
    atomic_json(sf,settings)
    # Source manifest used by cleanup; only input excerpts sent to Qwen are included.
    source=out/'source_projects.jsonl'
    if not source.exists():
        temp=source.with_suffix('.jsonl.tmp')
        with temp.open('w',encoding='utf-8') as f:
            for p in projects:f.write(json.dumps(p,ensure_ascii=False)+'\n')
        os.replace(temp,source)
    done=0; failed=0
    for start in range(0,len(projects),args.batch_size):
        batch=projects[start:start+args.batch_size];n=start//args.batch_size+1
        stem=f'{n:06d}'
        response_file=out/f'response_{stem}.json'; metrics_file=out/f'metrics_{stem}.json'; fail_file=out/f'failed_{stem}.json'
        if response_file.exists(): done+=len(batch);continue
        if fail_file.exists() and not args.retry_failed:failed+=len(batch);continue
        if fail_file.exists():fail_file.unlink()
        prompt=INSTRUCTIONS+'\n\nPROJECTS:\n'+json.dumps(batch,ensure_ascii=False)
        payload=json.dumps({'model':args.model,'prompt':prompt,'stream':False,'format':'json','options':{'temperature':0,'num_ctx':args.ctx}}).encode()
        issues=[];success=False
        for attempt in range(1,args.retries+1):
            start_time=time.perf_counter()
            try:
                request=urllib.request.Request(args.url.rstrip('/')+'/api/generate',data=payload,headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(request,timeout=args.timeout) as r: ollama=json.load(r)
                elapsed=time.perf_counter()-start_time
                raw=ollama.get('response','')
                (out/f'response_{stem}_raw_attempt{attempt}.txt').write_text(raw,encoding='utf-8')
                parsed=json.loads(raw)
                issues,invalid_geo,invalid_kw=validate(parsed,batch)
                if not isinstance(parsed,dict) or not isinstance(parsed.get('results'),list) or [r.get('project_id') if isinstance(r,dict) else None for r in parsed['results']]!=[p['project_id'] for p in batch]:
                    raise ValueError('Missing, extra, duplicated or out-of-order project IDs')
                for result in parsed['results']:
                    pid=result['project_id']
                    result['has_specific_study_location']=any(isinstance(loc,dict) and loc.get('role')=='study_area' and (pid,i) not in invalid_geo for i,loc in enumerate(result.get('locations',[])))
                atomic_json(response_file,parsed)
                atomic_json(metrics_file,{'batch':n,'project_count':len(batch),'attempt':attempt,'elapsed_seconds':round(elapsed,2),'ollama_total_seconds':round(ollama.get('total_duration',0)/1e9,2),'prompt_tokens':ollama.get('prompt_eval_count'),'output_tokens':ollama.get('eval_count'),'issues':issues})
                success=True;done+=len(batch)
                print(f'batch {n}: OK {len(batch)} projects, {elapsed:.1f}s, {len(issues)} validation warnings',flush=True)
                break
            except (ValueError,TypeError,urllib.error.URLError,TimeoutError,OSError) as exc:
                issues.append(f'attempt {attempt}: {type(exc).__name__}: {exc}')
                print(f'batch {n}: {issues[-1]}',file=sys.stderr,flush=True)
                if attempt<args.retries:time.sleep(min(5*attempt,30))
        if not success:
            failed+=len(batch);atomic_json(fail_file,{'batch':n,'project_ids':[p['project_id'] for p in batch],'issues':issues})
        if n%20==0:print(f'progress: {done}/{len(projects)} completed; {failed} failed',flush=True)
    atomic_json(out/'run_summary.json',{'projects':len(projects),'completed':done,'failed':failed,'batch_size':args.batch_size})
    print(f'Finished: {done} completed, {failed} failed; output: {out}',flush=True)

if __name__=='__main__':main()
