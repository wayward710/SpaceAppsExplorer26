"""SWEET concept coverage pilot. Python 3.12; pip install rdflib.

Example:
 py -3.12 match_sweet_pilot.py --sweet-root E:\\sac2026\\sweet-master --sample sample_300_full.jsonl
"""
import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from rdflib import Graph, URIRef
from rdflib.namespace import RDF, RDFS, SKOS, OWL

# Conservative screening only; review matches before using them as tags.
STOP = {'data', 'model', 'models', 'system', 'systems', 'process', 'processes',
        'information', 'value', 'values', 'result', 'results', 'object', 'objects',
        'property', 'properties', 'time', 'space', 'earth', 'science', 'human',
        'water', 'air', 'land', 'field', 'fields', 'point', 'points', 'type',
        'types', 'class', 'classes', 'state', 'states', 'change', 'changes',
        'level', 'levels', 'area', 'areas', 'source', 'sources', 'image', 'images',
        'surface', 'energy', 'temperature', 'mass', 'force', 'motion', 'number',
        'numbers', 'location', 'locations', 'distance', 'direction'}


def normalize(s):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w]+', ' ', s.casefold(), flags=re.UNICODE)).strip()


def label_for_uri(uri):
    fragment = str(uri).rsplit('#', 1)[-1].rsplit('/', 1)[-1]
    return re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', fragment).replace('_', ' ')


def load_sweet(root):
    files = sorted(root.rglob('*.ttl'))
    if not files:
        raise SystemExit(f'No .ttl files under {root}; check --sweet-root')
    g = Graph()
    errors = []
    for idx, path in enumerate(files, 1):
        try:
            g.parse(path.as_posix(), format='turtle')
        except Exception as e:
            errors.append((str(path), str(e)[:240]))
        if idx % 50 == 0:
            print(f'Parsed {idx}/{len(files)} Turtle files... ', flush=True)
    return g, files, errors


def extract(g):
    # Include classes and explicitly named individuals; exclude properties and ontologies.
    concepts = set(g.subjects(RDF.type, OWL.Class)) | set(g.subjects(RDF.type, RDFS.Class))
    concepts |= set(g.subjects(RDF.type, OWL.NamedIndividual))
    concepts = {u for u in concepts if isinstance(u, URIRef)}
    labels = defaultdict(set)
    for u in concepts:
        for predicate in (RDFS.label, SKOS.prefLabel, SKOS.altLabel):
            for val in g.objects(u, predicate):
                if getattr(val, 'language', None) in (None, 'en'):
                    labels[u].add(str(val))
        # SWEET frequently uses local names as labels; record as a fallback.
        if not labels[u]:
            labels[u].add(label_for_uri(u))
    parents = defaultdict(set)
    for child, parent in g.subject_objects(RDFS.subClassOf):
        if child in concepts and parent in concepts:
            parents[child].add(parent)
    return concepts, labels, parents


def make_index(labels):
    index = defaultdict(set)
    excluded = Counter()
    for uri, variants in labels.items():
        for variant in variants:
            term = normalize(variant)
            if not term or term.isdigit():
                continue
            if term in STOP or (len(term.split()) == 1 and len(term) < 5):
                excluded[term] += 1
                continue
            if len(term) > 90:
                continue
            index[term].add(str(uri))
    return index, excluded


def make_patterns(terms, chunk_size=350):
    # Boundaries avoid substring matches (e.g., 'solar' inside 'extrasolar').
    # One regex per chunk avoids quadratic loops over every concept and project.
    ordered = sorted(terms, key=lambda x: (-len(x), x))
    return [re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(t) for t in ordered[i:i+chunk_size]) + r')(?!\w)')
            for i in range(0, len(ordered), chunk_size)]


def write_csv(path, fieldnames, rows):
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sweet-root', type=Path, required=True)
    ap.add_argument('--sample', type=Path, default=Path('sample_300_full.jsonl'))
    ap.add_argument('--out', type=Path, default=Path('sweet_pilot'))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    g, files, errors = load_sweet(args.sweet_root)
    concepts, labels, parents = extract(g)
    index, excluded = make_index(labels)
    patterns = make_patterns(index)
    projects = [json.loads(line) for line in args.sample.open(encoding='utf-8-sig') if line.strip()]
    hits = []
    project_rows = []
    term_counts = Counter()
    for p in projects:
        # Do not include challenge name: it would inflate coverage artificially.
        content = normalize(' '.join(str(p.get(k) or '') for k in ('project_name', 'summary', 'details_text')))
        matched = set()
        for pattern in patterns:
            matched.update(m.group(0) for m in pattern.finditer(content))
        term_counts.update(matched)
        for term in sorted(matched):
            uris = sorted(index[term])
            hits.append({'project_id': p['project_id'], 'project_name': p.get('project_name', ''),
                         'challenge_title': p.get('challenge_title', ''), 'matched_phrase': term,
                         'concept_uris': ' | '.join(uris), 'concept_count': len(uris),
                         'ambiguous': len(uris) > 1})
        project_rows.append({'project_id': p['project_id'], 'project_name': p.get('project_name', ''),
                             'challenge_title': p.get('challenge_title', ''),
                             'matched_terms': len(matched),
                             'matched_concepts': len(set().union(*(index[t] for t in matched))) if matched else 0,
                             'matched_phrases': ' | '.join(sorted(matched))})
    write_csv(args.out / 'project_coverage.csv',
              ['project_id', 'project_name', 'challenge_title', 'matched_terms', 'matched_concepts', 'matched_phrases'], project_rows)
    write_csv(args.out / 'concept_matches.csv',
              ['project_id', 'project_name', 'challenge_title', 'matched_phrase', 'concept_uris', 'concept_count', 'ambiguous'], hits)
    write_csv(args.out / 'frequent_terms.csv', ['term', 'projects'],
              [{'term': t, 'projects': n} for t, n in term_counts.most_common()])
    write_csv(args.out / 'concept_vocabulary.csv', ['uri', 'labels', 'parent_uris'],
              [{'uri': str(u), 'labels': ' | '.join(sorted(labels[u])),
                'parent_uris': ' | '.join(sorted(map(str, parents[u])))} for u in sorted(concepts, key=str)])
    write_csv(args.out / 'parse_errors.csv', ['file', 'error'],
              [{'file': f, 'error': e} for f, e in errors])
    summary = {'ttl_files': len(files), 'parse_errors': len(errors), 'triples': len(g),
               'concepts': len(concepts), 'usable_normalized_phrases': len(index),
               'subclass_edges': sum(map(len, parents.values())), 'projects': len(projects),
               'projects_with_matches': sum(bool(r['matched_terms']) for r in project_rows),
               'projects_without_matches': sum(not r['matched_terms'] for r in project_rows),
               'notes': ['Coverage measures literal phrase recognition, not tag correctness.',
                         'Fallback URI labels and common words can cause false positives.',
                         'Challenge titles and reference links are excluded from matching.',
                         'Broader-class expansion is deliberately not applied.',
                         'Compare against NASA/GCMD only after reviewing match quality.']}
    (args.out / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    print(f'Outputs: {args.out.resolve()}')


if __name__ == '__main__':
    main()
