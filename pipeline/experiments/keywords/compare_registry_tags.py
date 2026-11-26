#!/usr/bin/env python3
"""Compare SWEET pilot tags before/after registry standalone suppression.

Uses existing concept_matches.csv (baseline), filtered_matches.csv (specificity),
and term_registry.csv. No re-matching or ontology parsing required.
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def read_csv(path):
    with open(path, encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def write_csv(path, rows, columns):
    with open(path, 'w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--matches', default='concept_matches.csv')
    parser.add_argument('--filtered', default='filtered_matches.csv')
    parser.add_argument('--registry', default='term_registry.csv')
    parser.add_argument('--sample', default='sample_300_full.jsonl')
    parser.add_argument('--output', default='registry_comparison')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    registry = {r['term'].strip().casefold(): r for r in read_csv(args.registry)}
    baseline = read_csv(args.matches)
    specific = read_csv(args.filtered)
    with open(args.sample, encoding='utf-8') as handle:
        projects = {p['project_id']: p for line in handle if (p := json.loads(line))}
    suppressed = {term for term, row in registry.items() if row['treatment'].strip().lower() == 'suppress_standalone'}

    # A term is evaluated on its own: suppressing 'data' does not suppress 'data assimilation'.
    # Deduplicate repeated rows by (project, normalized phrase).
    def unique(rows):
        return {(r['project_id'], r['matched_phrase'].strip().casefold()): r for r in rows}

    base = unique(baseline)
    filtered = unique(specific)
    kept = {k: v for k, v in base.items() if k[1] not in suppressed}
    high_medium = {k: v for k, v in filtered.items() if v['specificity'].lower() in ('high', 'medium')}
    final = {k: v for k, v in high_medium.items() if k[1] not in suppressed}

    groups = {'baseline': base, 'registry_only': kept, 'specificity_only': high_medium, 'specificity_plus_registry': final}
    per_project = {name: Counter(pid for pid, _ in group) for name, group in groups.items()}
    review = []
    for pid, p in projects.items():
        row = {'project_id': pid, 'project_name': p.get('project_name',''), 'challenge_title': p.get('challenge_title','')}
        for name in groups:
            row[name + '_tags'] = per_project[name][pid]
        row['suppressed_terms'] = '; '.join(sorted(term for proj, term in base if proj == pid and term in suppressed))
        row['retained_specific_terms'] = '; '.join(sorted(term for proj, term in final if proj == pid))
        review.append(row)
    review.sort(key=lambda r: (r['challenge_title'], r['project_name']))
    write_csv(output/'project_comparison.csv', review, list(review[0]))

    term_counts = Counter(term for _, term in base)
    term_rows = []
    for term, count in term_counts.most_common():
        reg = registry.get(term, {})
        term_rows.append({'term':term, 'sample_projects':count, 'catalog_document_frequency':reg.get('document_frequency',''), 'catalog_prevalence':reg.get('prevalence',''), 'treatment':reg.get('treatment','unregistered'), 'facet':reg.get('facet',''), 'specificity':next((v['specificity'] for (pid,t),v in filtered.items() if t == term), 'low_or_unmatched'), 'removed_by_registry':term in suppressed})
    write_csv(output/'term_impact.csv', term_rows, list(term_rows[0]))

    summary = {'sample_projects':len(projects), 'registry_terms':len(registry), 'suppressed_terms_in_registry':len(suppressed), 'stages':{}}
    for name, group in groups.items():
        count = per_project[name]
        summary['stages'][name] = {'project_term_pairs':len(group), 'distinct_terms':len({t for _,t in group}), 'projects_with_tags':sum(count[p] > 0 for p in projects), 'projects_without_tags':sum(count[p] == 0 for p in projects)}
    summary['registry_only_removed_pairs'] = len(base)-len(kept)
    summary['specificity_plus_registry_removed_pairs'] = len(high_medium)-len(final)
    summary['notes'] = ['Tags are lexical candidate matches, not verified scientific relevance.', 'Registry suppressions only remove exact standalone phrases.', 'Specificity filtering is a separate heuristic and should not be conflated with registry suppression.']
    (output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
