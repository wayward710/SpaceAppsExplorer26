#!/usr/bin/env python3
"""Read-only audit of Space Apps Qwen production output. No Ollama calls."""
import argparse, base64, collections, csv, json, re
from pathlib import Path


def load_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError):
        return None


def rows_from(obj):
    if isinstance(obj, list): return obj
    if isinstance(obj, dict):
        for key in ('results', 'projects', 'items'):
            if isinstance(obj.get(key), list): return obj[key]
    return []


def pid(obj):
    if not isinstance(obj, dict): return None
    for k in ('project_id', 'id'):
        if obj.get(k) is not None: return str(obj[k])
    for k in ('project', 'source'):
        if isinstance(obj.get(k), dict):
            result = pid(obj[k])
            if result: return result
    return None


def parse_jsonish(text):
    try: return json.loads(text)
    except ValueError: pass
    # JSON enclosed in Markdown fences, if any
    m = re.search(r'```(?:json)?\s*(.*?)```', text, re.S | re.I)
    if m:
        try: return json.loads(m.group(1))
        except ValueError: pass
    return None


def decoded_id(value):
    try: return base64.b64decode(value, validate=True).decode('utf-8')
    except (ValueError, UnicodeError): return ''


def write_csv(path, rows, columns):
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        w.writeheader(); w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--responses', type=Path, default=Path('production_full'))
    ap.add_argument('--out', type=Path, default=Path('audit_full'))
    args = ap.parse_args()
    src = args.responses
    out = args.out
    if not src.is_dir(): ap.error(f'No directory: {src}')
    settings = load_json(src / 'run_settings.json') or {}
    summary = load_json(src / 'run_summary.json') or {}
    batch_size = int(settings.get('batch_size', 5))
    source_path = src / 'source_projects.jsonl'
    if not source_path.exists(): ap.error('source_projects.jsonl is missing')
    source = []
    with source_path.open(encoding='utf-8') as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip(): continue
            try: obj = json.loads(line)
            except ValueError: ap.error(f'Invalid source JSONL line {lineno}')
            ident = pid(obj)
            if ident is None: ap.error(f'No project ID in source line {lineno}; inspect source format')
            source.append(ident)
    expected_batches = (len(source) + batch_size - 1) // batch_size
    out.mkdir(parents=True, exist_ok=True)
    keyword_counts = collections.Counter()
    keyword_categories = collections.Counter()
    loc_counts = collections.Counter()
    role_counts = collections.Counter()
    activity_counts = collections.Counter()
    issue_counts = collections.Counter()
    missing_keyword_rows, geo_rows, batch_rows, failure_rows, warning_rows = [], [], [], [], []
    accepted_ids = set()
    raw_recoverable_ids = set()
    n_accepted = 0
    n_keywords = n_locations = 0
    for batch in range(1, expected_batches + 1):
        expected = source[(batch-1)*batch_size:batch*batch_size]
        expected_set = set(expected)
        response_file = src / f'response_{batch:06d}.json'
        failed_file = src / f'failed_{batch:06d}.json'
        metrics_file = src / f'metrics_{batch:06d}.json'
        metrics = load_json(metrics_file) or {}
        response = load_json(response_file)
        records = rows_from(response)
        actual = [pid(r) for r in records]
        valid_response = (len(actual) == len(expected) and actual == expected)
        if valid_response:
            n_accepted += len(records)
            accepted_ids.update(actual)
            for rec in records:
                project_id = pid(rec)
                keywords = rec.get('keywords') or []
                locations = rec.get('locations') or []
                if not keywords: missing_keyword_rows.append({'project_id':project_id, 'batch':batch})
                activity_counts[str(rec.get('activity_type') or '(missing)')] += 1
                for kw in keywords:
                    if not isinstance(kw, dict): continue
                    term = str(kw.get('term') or '').strip()
                    cat = str(kw.get('category') or '(missing)').strip()
                    if term:
                        keyword_counts[term.casefold()] += 1
                        keyword_categories[cat] += 1
                        n_keywords += 1
                for loc in locations:
                    if not isinstance(loc, dict): continue
                    name = str(loc.get('name') or '').strip()
                    role = str(loc.get('role') or '(missing)').strip()
                    body = str(loc.get('parent_body') or '(missing)').strip()
                    ltype = str(loc.get('location_type') or '(missing)').strip()
                    n_locations += 1
                    role_counts[role] += 1
                    loc_counts[(name, role, body)] += 1
                    geo_rows.append({'project_id':project_id, 'batch':batch, 'name':name, 'role':role,
                                     'parent_body':body, 'location_type':ltype,
                                     'confidence':loc.get('confidence',''), 'evidence':loc.get('evidence','')})
        elif response_file.exists():
            issue_counts['structured_response_id_mismatch'] += 1
        elif failed_file.exists():
            issue_counts['failed_batch'] += 1
        else:
            issue_counts['missing_response_and_failure_record'] += 1
        if failed_file.exists() and valid_response:
            issue_counts['failure_record_alongside_valid_response'] += 1
        # Independently assess every saved raw attempt. Never infer an ID from position.
        best = None
        attempts = sorted(src.glob(f'response_{batch:06d}_raw_attempt*.txt'))
        for attempt in attempts:
            try: raw = parse_jsonish(attempt.read_text(encoding='utf-8'))
            except (OSError, UnicodeError): raw = None
            rrows = rows_from(raw)
            returned = [pid(r) for r in rrows]
            matched = [x for x in returned if x in expected_set]
            distinct_matched = set(matched)
            missing = [x for x in expected if x not in distinct_matched]
            extras = [x for x in returned if x not in expected_set]
            dupes = len(matched) - len(distinct_matched)
            classification = ('unparseable' if raw is None else
                              'exact' if returned == expected else
                              'reorder_only' if len(returned) == len(expected) and set(returned) == expected_set and not dupes else
                              'partial_exact_matches' if distinct_matched else 'no_exact_matches')
            candidate = {'batch':batch, 'attempt_file':attempt.name, 'classification':classification,
                         'expected_count':len(expected), 'returned_count':len(returned),
                         'exact_matching_ids':len(distinct_matched), 'missing_ids':';'.join(missing),
                         'extra_ids':';'.join(x or '(missing)' for x in extras), 'duplicate_count':dupes,
                         'expected_ids':';'.join(expected), 'returned_ids':';'.join(x or '(missing)' for x in returned),
                         'decoded_extra_ids':';'.join(decoded_id(x) for x in extras if x)}
            if not valid_response:
                failure_rows.append(candidate)
                raw_recoverable_ids.update(distinct_matched)
            score = (len(distinct_matched), int(classification == 'reorder_only'), -len(extras))
            if best is None or score > best[0]: best = (score, candidate)
        batch_rows.append({'batch':batch, 'expected_projects':len(expected),
                           'status':'accepted' if valid_response else 'failed_or_unverified',
                           'response_file':response_file.exists(), 'failure_file':failed_file.exists(),
                           'raw_attempts':len(attempts),
                           'best_raw_classification':best[1]['classification'] if best else 'no_raw_attempt',
                           'best_raw_exact_matches':best[1]['exact_matching_ids'] if best else 0,
                           'metrics_validation_warnings':metrics.get('validation_warnings','')})
        if isinstance(metrics.get('validation_warnings'), list):
            for item in metrics['validation_warnings']:
                warning_rows.append({'batch':batch, 'warning':str(item)})
    unresolved = set(source) - accepted_ids - raw_recoverable_ids
    report = {
        'source_projects':len(source), 'expected_batches':expected_batches,
        'reported_run_summary':summary, 'accepted_projects_verified':n_accepted,
        'accepted_unique_project_ids':len(accepted_ids),
        'not_in_accepted_responses':len(set(source)-accepted_ids),
        'failed_project_ids_with_exact_match_in_raw_attempt':len(raw_recoverable_ids-accepted_ids),
        'unresolved_project_ids_after_exact_raw_matches':len(unresolved),
        'keyword_records_in_accepted_responses':n_keywords,
        'distinct_casefolded_keywords':len(keyword_counts),
        'accepted_projects_without_keywords':len(missing_keyword_rows),
        'keyword_categories':dict(keyword_categories),
        'activity_types':dict(activity_counts),
        'location_records':n_locations,
        'location_roles':dict(role_counts),
        'issues':dict(issue_counts),
        'notes':['Counts are raw, before evidence validation and synonym cleanup.',
                 'Exact raw matches are potential salvage candidates, not yet validated for metadata quality.',
                 'No project IDs were repaired or inferred from record order.',
                 'Geographic study areas are model classifications, not verified geocoded locations.']
    }
    (out/'audit_summary.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    write_csv(out/'batches.csv',batch_rows,['batch','expected_projects','status','response_file','failure_file','raw_attempts','best_raw_classification','best_raw_exact_matches','metrics_validation_warnings'])
    write_csv(out/'failed_attempts.csv',failure_rows,['batch','attempt_file','classification','expected_count','returned_count','exact_matching_ids','missing_ids','extra_ids','duplicate_count','expected_ids','returned_ids','decoded_extra_ids'])
    write_csv(out/'keywords.csv',[{'keyword':k,'count':v} for k,v in keyword_counts.most_common()],['keyword','count'])
    write_csv(out/'projects_without_keywords.csv',missing_keyword_rows,['project_id','batch'])
    write_csv(out/'geographic_mentions.csv',geo_rows,['project_id','batch','name','role','parent_body','location_type','confidence','evidence'])
    write_csv(out/'geographic_frequency.csv',[{'name':k[0],'role':k[1],'parent_body':k[2],'count':v} for k,v in loc_counts.most_common()],['name','role','parent_body','count'])
    write_csv(out/'unresolved_project_ids.csv',[{'project_id':x} for x in source if x in unresolved],['project_id'])
    if warning_rows: write_csv(out/'validation_warnings.csv',warning_rows,['batch','warning'])
    print(json.dumps(report,indent=2,ensure_ascii=False))
    print(f'\nAudit reports written to {out.resolve()}')

if __name__ == '__main__': main()

