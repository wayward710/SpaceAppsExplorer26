#!/usr/bin/env python3
"""Conservative, read-only salvage of failed Space Apps Qwen batches.

No Ollama calls, no project-ID repair, no modification of production output.
Only unique, exact expected project IDs are candidates. Conflicting or malformed
records go to review, not the auto-salvage file.
"""
import argparse
import collections
import csv
import hashlib
import json
import re
from pathlib import Path

ACTIVITIES = {'educational_game', 'simulation', 'geographic_analysis', 'storytelling', 'mission_planning', 'other'}
ROLES = {'study_area', 'setting', 'background_context'}
CATEGORIES = {'subject', 'method', 'data_source', 'application', 'technology'}
CONFIDENCES = {'high', 'medium', 'low'}


def load(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError):
        return None


def parse_raw(path):
    try:
        txt = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError):
        return None
    try:
        return json.loads(txt)
    except ValueError:
        m = re.search(r'```(?:json)?\s*(.*?)```', txt, re.I | re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except ValueError:
                pass
    return None


def rows(obj):
    if isinstance(obj, dict) and isinstance(obj.get('results'), list):
        return obj['results']
    return []


def pid(rec):
    return rec.get('project_id') if isinstance(rec, dict) else None


def issues_for(rec, source):
    problems = []
    if rec.get('activity_type') not in ACTIVITIES:
        problems.append('invalid_activity_type')
    for field in ('locations', 'keywords'):
        vals = rec.get(field)
        if not isinstance(vals, list):
            problems.append(field + '_not_list')
            continue
        if field == 'keywords' and len(vals) > 5:
            problems.append('too_many_keywords')
        for i, v in enumerate(vals):
            tag = f'{field}[{i}]'
            if not isinstance(v, dict):
                problems.append(tag + '_not_object')
                continue
            ev = v.get('evidence')
            if not isinstance(ev, str) or not ev.strip() or ev not in source:
                problems.append(tag + '_evidence_not_verbatim')
            if v.get('confidence') not in CONFIDENCES:
                problems.append(tag + '_invalid_confidence')
            if field == 'keywords':
                if not isinstance(v.get('term'), str) or not v['term'].strip():
                    problems.append(tag + '_missing_term')
                if v.get('category') not in CATEGORIES or v.get('support') not in ('explicit', 'inferred'):
                    problems.append(tag + '_invalid_category_or_support')
            else:
                if not isinstance(v.get('name'), str) or not v['name'].strip():
                    problems.append(tag + '_missing_name')
                if v.get('role') not in ROLES or v.get('location_type') not in ('terrestrial', 'extraterrestrial'):
                    problems.append(tag + '_invalid_role_or_type')
                if 'parent_body' not in v or v.get('parent_body') == 'null':
                    problems.append(tag + '_invalid_parent_body')
    return problems


def canonical(obj):
    # Ignore only runner-derived field, which may not be present in raw responses.
    x = {k: v for k, v in obj.items() if k != 'has_specific_study_location'}
    return json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def write_csv(path, items, fields):
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(items)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--responses', type=Path, default=Path('production_full'))
    ap.add_argument('--out', type=Path, default=Path('salvage_full'))
    args = ap.parse_args()
    src, out = args.responses, args.out
    if not src.is_dir() or not (src/'source_projects.jsonl').exists():
        ap.error('Missing production directory or source_projects.jsonl')
    if src.resolve() == out.resolve() or src.resolve() in out.resolve().parents:
        ap.error('Output must be outside production directory')
    settings = load(src/'run_settings.json') or {}
    bs = settings.get('batch_size')
    if not isinstance(bs, int) or bs < 1:
        ap.error('Invalid batch size in run_settings.json')
    source = []
    with (src/'source_projects.jsonl').open(encoding='utf-8') as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                if not isinstance(item.get('project_id'), str):
                    ap.error('Invalid source project_id')
                source.append(item)
    ids = [p['project_id'] for p in source]
    if len(ids) != len(set(ids)):
        ap.error('Duplicate project IDs in source manifest')
    expected_hash = settings.get('project_ids_sha256')
    actual_hash = hashlib.sha256('\n'.join(ids).encode()).hexdigest()
    if expected_hash and expected_hash != actual_hash:
        ap.error('Source project IDs do not match run_settings hash')
    out.mkdir(parents=True, exist_ok=True)
    recovered, review, retry, batches = [], [], [], []
    counters = collections.Counter()
    for offset in range(0, len(source), bs):
        batch = offset // bs + 1
        batch_source = source[offset:offset+bs]
        expected = [p['project_id'] for p in batch_source]
        expected_set = set(expected)
        structured = src/f'response_{batch:06d}.json'
        obj = load(structured)
        if [pid(x) for x in rows(obj)] == expected:
            counters['already_accepted'] += len(expected)
            continue
        attempts = sorted(src.glob(f'response_{batch:06d}_raw_attempt*.txt'))
        candidate_map = collections.defaultdict(list)
        for attempt in attempts:
            raw = parse_raw(attempt)
            result = rows(raw)
            counts = collections.Counter(pid(r) for r in result if isinstance(r, dict))
            for r in result:
                key = pid(r)
                if not isinstance(key, str) or key not in expected_set:
                    continue
                if counts[key] != 1:
                    counters['duplicate_id_occurrences_skipped'] += 1
                    continue
                candidate_map[key].append((attempt.name, r))
        for p in batch_source:
            key = p['project_id']
            options = candidate_map.get(key, [])
            if not options:
                retry.append({'project_id':key,'batch':batch,'reason':'no_unique_exact_id_record'})
                continue
            valid = []
            for filename, record in options:
                problems = issues_for(record, (p.get('summary') or '')+'\n'+(p.get('details_excerpt') or ''))
                valid.append((filename, record, problems))
            clean = [(fn, r) for fn, r, probs in valid if not probs]
            clean_variants = collections.defaultdict(list)
            for fn, r in clean:
                clean_variants[canonical(r)].append((fn, r))
            # Strict policy: any divergent clean candidate or invalid attempt requires review.
            all_variants = {canonical(r) for _, r, _ in valid}
            if len(clean_variants) == 1 and len(all_variants) == 1:
                filename, record = clean[0]
                recovered.append({'project_id':key,'batch':batch,'source_attempt':filename,'record':record})
            else:
                reason = ('conflicting_attempt_records' if len(all_variants) > 1 else
                          'validation_issues' if not clean else 'conflicting_clean_records')
                review.append({'project_id':key,'batch':batch,'reason':reason,
                               'attempts':';'.join(fn for fn, _, _ in valid),
                               'validation_issues':json.dumps({fn:probs for fn,_,probs in valid},ensure_ascii=False),
                               'clean_candidate_count':len(clean),'variant_count':len(all_variants)})
        batches.append({'batch':batch,'expected':len(expected),'raw_attempts':len(attempts)})
    with (out/'recovered_records.jsonl').open('w', encoding='utf-8') as f:
        for r in recovered:
            f.write(json.dumps(r, ensure_ascii=False)+'\n')
    write_csv(out/'review_candidates.csv', review,
              ['project_id','batch','reason','attempts','validation_issues','clean_candidate_count','variant_count'])
    write_csv(out/'retry_queue.csv', retry, ['project_id','batch','reason'])
    write_csv(out/'failed_batches.csv', batches, ['batch','expected','raw_attempts'])
    report = {'source_projects':len(source),'already_accepted':counters['already_accepted'],
              'failed_projects':len(source)-counters['already_accepted'],
              'auto_salvaged':len(recovered),'review_needed':len(review),
              'no_unique_exact_id_candidate':len(retry),
              'duplicate_id_occurrences_skipped':counters['duplicate_id_occurrences_skipped'],
              'failed_batches':len(batches),
              'policy':'Auto-salvage only when all unique exact-ID attempts agree and pass schema/verbatim-evidence checks; no ID repair.',
              'note':'Review and retry records remain unresolved; no Ollama calls or source modifications.'}
    assert report['failed_projects'] == len(recovered)+len(review)+len(retry)
    (out/'salvage_summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
    print('Reports:',out.resolve())

if __name__ == '__main__':
    main()
