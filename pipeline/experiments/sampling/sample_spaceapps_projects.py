"""Create a reproducible, challenge-stratified Space Apps classification sample."""
import argparse
import csv
import json
import math
import random
import sqlite3
from collections import defaultdict
from pathlib import Path


def allocate(groups, total, minimum):
    """Allocate integer quotas proportional to group sizes, with a floor."""
    keys = sorted(groups)
    sizes = {key: len(groups[key]) for key in keys}
    if total > sum(sizes.values()):
        raise ValueError('Sample size exceeds the number of available projects')
    if len(keys) * minimum > total:
        raise ValueError(f'{len(keys)} challenges x minimum {minimum} exceeds sample size {total}')
    quotas = {key: min(minimum, sizes[key]) for key in keys}
    remaining = total - sum(quotas.values())
    while remaining:
        capacities = {key: sizes[key] - quotas[key] for key in keys}
        available = {key: cap for key, cap in capacities.items() if cap > 0}
        if not available:
            raise ValueError('Insufficient projects to complete allocation')
        denominator = sum(available.values())
        targets = {key: remaining * cap / denominator for key, cap in available.items()}
        grants = {key: min(capacities[key], math.floor(value)) for key, value in targets.items()}
        granted = sum(grants.values())
        if granted == 0:
            # Largest remainder, deterministic tie-breaking.
            key = sorted(available, key=lambda k: (-targets[k], k))[0]
            quotas[key] += 1
            remaining -= 1
        else:
            for key, grant in grants.items():
                quotas[key] += grant
            remaining -= granted
    return quotas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=Path('spaceapps_2026.sqlite'))
    parser.add_argument('--out', type=Path, default=Path('classification_sample'))
    parser.add_argument('--size', type=int, default=300)
    parser.add_argument('--minimum', type=int, default=5)
    parser.add_argument('--seed', type=int, default=2026)
    args = parser.parse_args()

    with sqlite3.connect(f'file:{args.db.resolve()}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute('''
            SELECT p.id AS project_id, p.team_id, t.title AS team_title,
                   t.challenge_id, t.challenge_title,
                   t.location_country, p.name AS project_name,
                   p.summary, p.details_text,
                   p.ai_tools_usage, p.data_references, p.project_references
            FROM projects p JOIN teams t ON t.id = p.team_id
            WHERE t.submitted = 1
            ORDER BY p.id
        ''')]

    groups = defaultdict(list)
    for row in rows:
        key = str(row['challenge_id'] or row['challenge_title'] or 'UNKNOWN')
        groups[key].append(row)
    quotas = allocate(groups, args.size, args.minimum)
    rng = random.Random(args.seed)
    selected = []
    for key in sorted(groups):
        selected.extend(rng.sample(groups[key], quotas[key]))
    selected.sort(key=lambda r: (str(r['challenge_title']), str(r['project_id'])))

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / 'sample_300_review.csv'
    jsonl_path = args.out / 'sample_300_full.jsonl'
    allocation_path = args.out / 'challenge_allocation.csv'
    fields = ['project_id', 'team_id', 'team_title', 'challenge_id',
              'challenge_title', 'location_country', 'project_name', 'summary',
              'details_excerpt', 'primary_category', 'secondary_categories',
              'evidence', 'confidence', 'review_notes']
    with csv_path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in selected:
            writer.writerow({**row, 'details_excerpt': (row['details_text'] or '')[:1200],
                             'primary_category': '', 'secondary_categories': '',
                             'evidence': '', 'confidence': '', 'review_notes': ''})
    with jsonl_path.open('w', encoding='utf-8') as stream:
        for row in selected:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    with allocation_path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['challenge_id', 'challenge_title', 'population', 'sampled'])
        writer.writeheader()
        for key in sorted(groups):
            writer.writerow({'challenge_id': key,
                             'challenge_title': groups[key][0]['challenge_title'],
                             'population': len(groups[key]), 'sampled': quotas[key]})
    print(f'Population: {len(rows):,} projects across {len(groups)} challenges')
    print(f'Sample: {len(selected)} projects (seed={args.seed}, minimum={args.minimum})')
    print(f'Output: {csv_path}, {jsonl_path}, {allocation_path}')


if __name__ == '__main__':
    main()
