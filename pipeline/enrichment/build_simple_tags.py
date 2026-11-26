#!/usr/bin/env python3
"""Read-only, conservative keyword normalization for Space Apps project JSONL.

No inference, category classification, or edits to input. Outputs flat tags and audit.
"""
import argparse, collections, csv, json, pathlib, re, unicodedata

# Only explicitly reviewed, unambiguous aliases. Expand via --aliases CSV.
DEFAULT_ALIASES = {'ai': 'artificial intelligence', 'ml': 'machine learning'}
ACRONYMS = {'nasa', 'modis', 'viirs', 'nisar', 'sar', 'gis', 'iss', 'ai', 'ml', 'gpm', 'landsat', 'sentinel-1', 'nasa power'}

def key(s):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', s).strip()).casefold()

def display(s):
    s = re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', s).strip())
    if key(s) in ACRONYMS:
        return 'NASA POWER' if key(s) == 'nasa power' else s.upper()
    return s

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', required=True, help='Source project metadata JSONL')
    p.add_argument('--out', default='simple_tags')
    p.add_argument('--aliases', help='Optional CSV with alias,canonical columns; overrides defaults')
    p.add_argument('--max-tags', type=int, default=0, help='0 keeps all; positive cap is optional')
    a = p.parse_args()
    if a.max_tags < 0: p.error('--max-tags must be >= 0')
    source = pathlib.Path(a.input)
    out = pathlib.Path(a.out)
    if not source.is_file(): p.error(f'Input missing: {source}')
    if source.resolve() == out.resolve(): p.error('Output must differ from input')
    out.mkdir(parents=True, exist_ok=True)
    aliases = dict(DEFAULT_ALIASES)
    if a.aliases:
        with open(a.aliases, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            if not {'alias','canonical'}.issubset(reader.fieldnames or []): p.error('Alias CSV requires alias,canonical')
            for row in reader:
                if not row['alias'].strip() or not row['canonical'].strip(): continue
                aliases[key(row['alias'])] = key(row['canonical'])
    # Canonical display is derived from a representative original spelling, with common acronyms fixed.
    frequencies = collections.Counter()
    forms = collections.defaultdict(collections.Counter)
    projects = []
    seen_ids = set()
    with source.open(encoding='utf-8') as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip(): continue
            item = json.loads(line)
            pid = item.get('project_id') or item.get('record', {}).get('project_id')
            if not pid or pid in seen_ids: raise ValueError(f'Missing/duplicate project_id at line {line_no}: {pid}')
            seen_ids.add(pid)
            kws = item.get('record', item).get('keywords') or []
            entries = []
            for kw in kws:
                raw = kw.get('term') if isinstance(kw, dict) else kw
                if not isinstance(raw, str) or not raw.strip(): continue
                k = key(raw)
                k = aliases.get(k, k)
                if not k: continue
                entries.append((k, raw))
                forms[k][raw.strip()] += 1
            unique = list(dict.fromkeys(k for k, _ in entries))
            for k in unique: frequencies[k] += 1
            projects.append((pid, unique))
    labels = {}
    for k, options in forms.items():
        if k in ('artificial intelligence', 'machine learning'):
            labels[k] = k
        elif k in ACRONYMS:
            labels[k] = display(k)
        else:
            labels[k] = display(sorted(options.items(), key=lambda x: (-x[1], x[0]))[0][0])
    dist = collections.Counter()
    truncated = 0
    with (out / 'project_tags.jsonl').open('w', encoding='utf-8') as f:
        for pid, keys in projects:
            # Preserve original order unless an explicit cap is requested.
            if a.max_tags and len(keys) > a.max_tags:
                keys = keys[:a.max_tags]
                truncated += 1
            tags = [labels[k] for k in keys]
            dist[len(tags)] += 1
            f.write(json.dumps({'project_id': pid, 'tags': tags}, ensure_ascii=False) + '\n')
    with (out / 'tag_frequencies.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['tag','projects'])
        for k, n in frequencies.most_common(): w.writerow([labels[k], n])
    with (out / 'normalization_audit.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f); w.writerow(['original_term','canonical_tag','mentions','normalization'])
        for k, options in sorted(forms.items()):
            for raw, n in options.most_common():
                kind = 'unchanged' if raw == labels[k] else ('alias_or_case' if key(raw) != k else 'case_or_spacing')
                w.writerow([raw, labels[k], n, kind])
    summary = {'input': str(source), 'projects': len(projects), 'unique_tags': len(frequencies),
               'projects_without_tags': dist[0], 'projects_with_1_or_2_tags': dist[1]+dist[2],
               'projects_with_3_to_7_tags': sum(dist[i] for i in range(3,8)),
               'projects_with_8_plus_tags': sum(v for i,v in dist.items() if i >= 8),
               'tags_per_project_distribution': {str(k): v for k,v in sorted(dist.items())},
               'projects_truncated': truncated, 'max_tags': a.max_tags,
               'note': 'Source unchanged. No semantic merging or unsupported tags added. All source categories ignored.'}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))

if __name__ == '__main__': main()
