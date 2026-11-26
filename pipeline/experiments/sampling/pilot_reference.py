#!/usr/bin/env python3
"""Qwen geography + keyword pilot; standard library only; Python 3.9+.

Reuses the SAME 50 projects and their order from the geography-only pilot.
Outputs are isolated in combined_results/; resumable by batch.
"""
import argparse
import csv
import json
import re
import time
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ROLES = {'study_area', 'setting', 'background_context'}
ACTIVITIES = {'geographic_analysis', 'mission_planning', 'simulation', 'educational_game', 'storytelling', 'other'}
CATEGORIES = {'subject', 'method', 'data_source', 'application', 'technology'}
CONFIDENCES = {'high', 'medium', 'low'}

INSTRUCTIONS = '''You are indexing NASA Space Apps projects for a searchable catalog.
Analyze EACH project independently using ONLY the provided summary and optional details_excerpt.
Return one result for each input project in the same order, JSON only.

GEOGRAPHY:
Extract named terrestrial or extraterrestrial locations that are explicitly supported by the text, including clear adjectival forms (lunar -> Moon, Martian -> Mars). Do not infer locations from mission names (Apollo, Viking, Voyager), generic Earth observation, project challenge, team location, or software names. Do not create a location merely because the project is about Earth science.
Preserve specific names (e.g. Arcadia Planitia; lunar south pole), using parent_body Mars/Moon/Earth where applicable; use JSON null for parentless bodies.
Roles:
- study_area: REAL spatial, environmental, terrain, geographic or site characteristics of a named place are measured, mapped, compared, monitored or used to plan real candidate sites/routes.
- setting: game, narrative, educational exploration, imagined mission or simulation set in a place, without analysis of that place's actual geography.
- background_context: incidental place reference, not a focus.
Do not call Earth itself a specific study_area merely because the project uses Earth-observation data. Avoid extracting vague, incidental planetary references that do not help search.

KEYWORDS:
Extract ZERO TO FIVE high-value keywords per project. Zero, one, or two are perfectly valid. NEVER fill a quota; if no meaningful keywords are supported, return an empty keywords array. Prefer distinctive searchable concepts, not generic terms such as 'NASA', 'space', 'science', 'project', 'innovation', or 'data'. Avoid location names as keywords; geography is extracted separately. Use canonical singular noun phrases in English. No invented algorithms, instruments, datasets or applications. Avoid duplicates and near-synonyms within a project.
Each keyword has one category:
- subject: scientific/technical topic or phenomenon (e.g. soil moisture, orbital debris)
- method: analytic/computational approach (e.g. change detection, machine learning)
- data_source: specifically identified dataset, mission, instrument or provider used as data (e.g. NISAR, MODIS)
- application: practical problem or intended use (e.g. flood risk assessment)
- technology: implemented software, hardware, platform, or interface (e.g. virtual reality, Python)
Each keyword has support 'explicit' when its term or a direct synonym appears in the source, otherwise 'inferred' only when the source strongly supports it. No speculative inference.

EVIDENCE:
Every geographic location and keyword MUST include the SHORTEST useful EXACT verbatim substring (ideally 3-12 words; avoid full sentences) of that project's supplied summary OR details_excerpt. Copy characters literally, including accents and punctuation; NEVER paraphrase or translate evidence. The evidence must support the location/keyword and its role/category. If no evidence supports a proposed item, omit it.
Confidence: high, medium, low. Do not claim high confidence without strong support.
Activity type: geographic_analysis, mission_planning, simulation, educational_game, storytelling, other.

JSON format:
{"results":[{"project_id":"input id","activity_type":"other","locations":[{"name":"lunar south pole","parent_body":"Moon","role":"study_area","location_type":"extraterrestrial","evidence":"exact source quote","confidence":"high"}],"keywords":[{"term":"terrain analysis","category":"method","support":"explicit","evidence":"exact source quote","confidence":"high"}]}]}
Return AT MOST FIVE keywords per project. Do NOT return has_specific_study_location. Return empty arrays when appropriate.'''


def source_text(item):
    return (item.get('summary') or '') + '\n' + (item.get('details_excerpt') or '')


def validate(parsed, batch):
    issues = []
    if not isinstance(parsed, dict) or not isinstance(parsed.get('results'), list):
        return ['Missing results array'], set(), set()
    results = parsed['results']
    expected = [p['project_id'] for p in batch]
    actual = [r.get('project_id') if isinstance(r, dict) else None for r in results]
    if actual != expected:
        issues.append('Project IDs missing, duplicated, or out of order')
    sources = {p['project_id']: source_text(p) for p in batch}
    invalid_geo, invalid_keywords = set(), set()
    for r in results:
        if not isinstance(r, dict):
            issues.append('Non-object project result'); continue
        pid = r.get('project_id')
        if pid not in sources: continue
        if r.get('activity_type') not in ACTIVITIES:
            issues.append(f'{pid}: invalid activity_type')
        for field in ('locations', 'keywords'):
            values = r.get(field)
            if not isinstance(values, list):
                issues.append(f'{pid}: {field} is not a list'); continue
            if field == 'keywords' and len(values) > 5:
                issues.append(f'{pid}: more than five keywords ({len(values)})')
            for idx, val in enumerate(values):
                key = (pid, idx)
                invalid_set = invalid_geo if field == 'locations' else invalid_keywords
                if not isinstance(val, dict):
                    issues.append(f'{pid}: {field}[{idx}] not an object'); invalid_set.add(key); continue
                ev = val.get('evidence')
                if not isinstance(ev, str) or not ev.strip() or ev not in sources[pid]:
                    issues.append(f'{pid}: {field}[{idx}] evidence not verbatim: {ev!r}')
                    invalid_set.add(key)
                if val.get('confidence') not in CONFIDENCES:
                    issues.append(f'{pid}: {field}[{idx}] invalid confidence'); invalid_set.add(key)
                if field == 'locations':
                    if not isinstance(val.get('name'), str) or not val['name'].strip():
                        issues.append(f'{pid}: location missing name'); invalid_set.add(key)
                    if val.get('role') not in ROLES or val.get('location_type') not in {'terrestrial', 'extraterrestrial'}:
                        issues.append(f'{pid}: location invalid role/type'); invalid_set.add(key)
                    if 'parent_body' not in val or val.get('parent_body') == 'null':
                        issues.append(f'{pid}: parent_body missing or string "null"'); invalid_set.add(key)
                else:
                    if not isinstance(val.get('term'), str) or not val['term'].strip():
                        issues.append(f'{pid}: keyword missing term'); invalid_set.add(key)
                    if val.get('category') not in CATEGORIES or val.get('support') not in {'explicit', 'inferred'}:
                        issues.append(f'{pid}: keyword invalid category/support'); invalid_set.add(key)
    return issues, invalid_geo, invalid_keywords


def load_selected(details_chars):
    selected = json.loads((ROOT / 'selected_50.json').read_text(encoding='utf-8'))
    if len(selected) != 20 or len({p['project_id'] for p in selected}) != 20:
        raise ValueError('selected_50.json must contain 20 unique benchmark projects')
    source = {p['project_id']: p for p in (json.loads(line) for line in (ROOT / 'sample_300_full.jsonl').open(encoding='utf-8') if line.strip())}
    result = []
    for p in selected:
        original = source[p['project_id']]
        item = {'project_id': p['project_id'], 'summary': p['summary']}
        if details_chars:
            details = original.get('details_text') or ''
            # Keep original characters for evidence validation. Avoid duplicating summary.
            if details.startswith(p['summary']):
                details = details[len(p['summary']):].lstrip()
            item['details_excerpt'] = details[:details_chars]
        result.append(item)
    return result


def write_review(selected, out):
    source = {p['project_id']: p for p in selected}
    rows, kws = [], []
    for response_path in sorted(out.glob('response_[0-9][0-9].json')):
        data = json.loads(response_path.read_text(encoding='utf-8'))
        for r in data.get('results', []):
            pid = r.get('project_id')
            if pid not in source: continue
            for idx, loc in enumerate(r.get('locations', [])):
                if not isinstance(loc, dict): continue
                rows.append({'project_id':pid, 'activity_type':r.get('activity_type'), 'location_index':idx, **{k:loc.get(k) for k in ['name','parent_body','role','location_type','evidence','confidence']}, 'evidence_valid': bool(loc.get('evidence') and loc['evidence'] in source_text(source[pid]))})
            for idx, kw in enumerate(r.get('keywords', [])):
                if not isinstance(kw, dict): continue
                kws.append({'project_id':pid, 'activity_type':r.get('activity_type'), 'keyword_index':idx, **{k:kw.get(k) for k in ['term','category','support','evidence','confidence']}, 'evidence_valid': bool(kw.get('evidence') and kw['evidence'] in source_text(source[pid]))})
    for filename, records, fields in [('locations_review.csv', rows, ['project_id','activity_type','location_index','name','parent_body','role','location_type','evidence','confidence','evidence_valid']), ('keywords_review.csv', kws, ['project_id','activity_type','keyword_index','term','category','support','evidence','confidence','evidence_valid'])]:
        with (out / filename).open('w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader(); writer.writerows(records)
    summary = {'projects':len(selected),'locations':len(rows),'keywords':len(kws),'invalid_location_evidence':sum(not x['evidence_valid'] for x in rows),'invalid_keyword_evidence':sum(not x['evidence_valid'] for x in kws),'study_area_projects':len({x['project_id'] for x in rows if x['role']=='study_area' and x['evidence_valid']})}
    (out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print('Combined review:',json.dumps(summary))


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--url',default='http://localhost:11434')
    ap.add_argument('--model',default='qwen2.5:14b')
    ap.add_argument('--ctx',type=int,default=8192)
    ap.add_argument('--batch-size',type=int,default=5)
    ap.add_argument('--details-chars',type=int,default=0,help='Optional characters of details per project; 0 (default) keeps geography comparison summary-only')
    ap.add_argument('--timeout',type=int,default=1200)
    ap.add_argument('--force',action='store_true')
    args=ap.parse_args()
    if args.batch_size < 1 or args.details_chars < 0: ap.error('batch-size must be >=1 and details-chars >=0')
    selected=load_selected(args.details_chars)
    out=ROOT/'benchmark_results'; out.mkdir(exist_ok=True)
    settings_file=out/'run_settings.json'
    settings={'model':args.model,'ctx':args.ctx,'batch_size':args.batch_size,'details_chars':args.details_chars}
    if settings_file.exists() and json.loads(settings_file.read_text(encoding='utf-8'))!=settings and not args.force:
        ap.error('Existing benchmark_results uses different settings. Move it aside or use --force to restart.')
    settings_file.write_text(json.dumps(settings,indent=2),encoding='utf-8')
    for start in range(0,len(selected),args.batch_size):
        n=start//args.batch_size+1
        batch=selected[start:start+args.batch_size]
        response_file=out/f'response_{n:02}.json'
        metrics_file=out/f'metrics_{n:02}.json'
        if response_file.exists() and metrics_file.exists() and not args.force:
            print(f'Batch {n}: skipping existing output'); continue
        prompt=INSTRUCTIONS+'\n\nPROJECTS:\n'+json.dumps(batch,ensure_ascii=False)
        payload=json.dumps({'model':args.model,'prompt':prompt,'stream':False,'format':'json','options':{'temperature':0,'num_ctx':args.ctx}}).encode('utf-8')
        request=urllib.request.Request(args.url.rstrip('/')+'/api/generate',data=payload,headers={'Content-Type':'application/json'})
        start_time=time.perf_counter()
        with urllib.request.urlopen(request,timeout=args.timeout) as response:
            ollama=json.load(response)
        elapsed=time.perf_counter()-start_time
        raw=ollama.get('response','')
        (out/f'response_{n:02}_raw.txt').write_text(raw,encoding='utf-8')
        try:
            parsed=json.loads(raw)
            issues,invalid_geo,invalid_kw=validate(parsed,batch)
            if isinstance(parsed,dict) and isinstance(parsed.get('results'),list) and [r.get('project_id') if isinstance(r,dict) else None for r in parsed['results']] == [p['project_id'] for p in batch]:
                for result in parsed['results']:
                    if not isinstance(result,dict):continue
                    pid=result.get('project_id')
                    result['has_specific_study_location']=any(isinstance(loc,dict) and loc.get('role')=='study_area' and (pid,i) not in invalid_geo for i,loc in enumerate(result.get('locations',[])))
                response_file.write_text(json.dumps(parsed,indent=2,ensure_ascii=False),encoding='utf-8')
        except (ValueError,TypeError) as exc:
            issues=[f'JSON parse/validation error: {exc}']
        metrics={'batch':n,'project_count':len(batch),'elapsed_seconds':round(elapsed,2),'ollama_total_seconds':round(ollama.get('total_duration',0)/1e9,2),'prompt_tokens':ollama.get('prompt_eval_count'),'output_tokens':ollama.get('eval_count'),'issues':issues}
        metrics_file.write_text(json.dumps(metrics,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps(metrics,indent=2,ensure_ascii=False))
    write_review(selected,out)

if __name__=='__main__':main()
