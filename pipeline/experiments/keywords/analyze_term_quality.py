"""Corpus-derived vocabulary diagnostics for the Space Apps 2026 catalog.

Example:
  py -3.12 analyze_term_quality.py --db spaceapps_2026.sqlite \
      --vocabulary concept_vocabulary.csv --out term_quality

Requires: scikit-learn. Read-only database access; no automatic stopword deletion.
"""
import argparse
import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from sklearn.feature_extraction.text import CountVectorizer

# These are examples of generic labels, NOT an exhaustive stopword list.
GENERIC = {'project', 'team', 'solution', 'website', 'important', 'future',
           'platform', 'research', 'development', 'analysis', 'application',
           'system', 'data', 'information', 'impact', 'tool', 'tools'}
TOKEN = re.compile(r'(?u)\b\w+\b')


def normalize(s):
    return ' '.join(TOKEN.findall(str(s).casefold().replace('_', ' ')))


def load_vocabulary(path):
    """Read SWEET concept_vocabulary.csv or term_review.csv."""
    terms = defaultdict(set)
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        if 'labels' in reader.fieldnames:
            for row in reader:
                for label in (row.get('labels') or '').split('|'):
                    phrase = normalize(label)
                    if phrase and len(phrase) >= 3:
                        terms[phrase].add(row.get('uri', ''))
        elif 'phrase' in reader.fieldnames:
            for row in reader:
                phrase = normalize(row['phrase'])
                if phrase and len(phrase) >= 3:
                    terms[phrase].add('')
        else:
            raise ValueError('Vocabulary needs a labels or phrase column')
    return terms


def load_projects(db):
    with sqlite3.connect(f'file:{db.resolve()}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('''
            SELECT p.id AS project_id, t.challenge_id AS challenge_id,
                   t.challenge_title AS challenge_title, p.name AS name,
                   p.summary AS summary, p.details_text AS details_text
            FROM projects p JOIN teams t ON t.id=p.team_id
            WHERE t.submitted=1 ORDER BY p.id
        ''').fetchall()
    return [dict(row) for row in rows]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--db', type=Path, default=Path('spaceapps_2026.sqlite'))
    ap.add_argument('--vocabulary', type=Path, default=Path('concept_vocabulary.csv'))
    ap.add_argument('--out', type=Path, default=Path('term_quality'))
    ap.add_argument('--flag-prevalence', type=float, default=0.25)
    ap.add_argument('--batch-size', type=int, default=400)
    args = ap.parse_args()
    if not 0 < args.flag_prevalence <= 1:
        ap.error('--flag-prevalence must be in (0, 1]')

    terms = load_vocabulary(args.vocabulary)
    projects = load_projects(args.db)
    if not projects or not terms:
        raise ValueError('No projects or vocabulary terms found')
    args.out.mkdir(parents=True, exist_ok=True)
    # Fixed tokenization shared by vocabulary and corpus; avoids substring hits.
    vocab = {term: i for i, term in enumerate(sorted(terms))}
    vectorizer = CountVectorizer(vocabulary=vocab, binary=True,
                                lowercase=True, strip_accents='unicode',
                                token_pattern=r'(?u)\b\w+\b', ngram_range=(1, 5))
    overall = [0] * len(vocab)
    by_challenge = defaultdict(Counter)
    challenge_sizes = Counter(str(r['challenge_id'] or r['challenge_title']) for r in projects)
    # Process batches to avoid holding the whole sparse matrix in memory.
    for start in range(0, len(projects), args.batch_size):
        batch = projects[start:start + args.batch_size]
        texts = [' '.join(str(r.get(k) or '') for k in ('name', 'summary', 'details_text')) for r in batch]
        matrix = vectorizer.transform(texts).tocsr()
        for i, row in enumerate(batch):
            key = str(row['challenge_id'] or row['challenge_title'])
            indices = matrix.indices[matrix.indptr[i]:matrix.indptr[i + 1]]
            for index in indices:
                overall[index] += 1
                by_challenge[key][int(index)] += 1
        if start % (args.batch_size * 10) == 0:
            print(f'Processed {min(start + len(batch), len(projects)):,}/{len(projects):,} projects', flush=True)

    n = len(projects)
    reverse = {i: term for term, i in vocab.items()}
    fields = ['term', 'document_frequency', 'prevalence', 'challenges_with_term',
              'max_challenge_prevalence', 'max_challenge_lift', 'top_challenge',
              'concept_count', 'flag', 'suggested_treatment']
    output = args.out / 'term_quality.csv'
    flagged = 0
    with output.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for index in sorted(range(len(vocab)), key=lambda i: (-overall[i], reverse[i])):
            term = reverse[index]
            df = overall[index]
            prevalence = df / n
            occurrences = [(key, counts.get(index, 0)) for key, counts in by_challenge.items()]
            # Exclude tiny challenge groups when measuring concentration.
            relevant = [(key, count) for key, count in occurrences if challenge_sizes[key] >= 10]
            represented = sum(count > 0 for _, count in occurrences)
            top_key, top_count = max(relevant, key=lambda x: (x[1] / challenge_sizes[x[0]], x[1]), default=('', 0))
            max_cp = top_count / challenge_sizes[top_key] if top_key else 0
            lift = max_cp / prevalence if prevalence else 0
            flag = 'review_common' if prevalence >= args.flag_prevalence else ''
            flagged += bool(flag)
            if term in GENERIC:
                treatment = 'review_generic'
            elif flag:
                treatment = 'review_high_frequency_keep_if_scientific'
            elif df == 0:
                treatment = 'not_observed'
            else:
                treatment = 'retain_candidate_verify_context'
            writer.writerow({'term': term, 'document_frequency': df,
                             'prevalence': round(prevalence, 6),
                             'challenges_with_term': represented,
                             'max_challenge_prevalence': round(max_cp, 6),
                             'max_challenge_lift': round(lift, 3),
                             'top_challenge': next((r['challenge_title'] for r in projects if str(r['challenge_id'] or r['challenge_title']) == top_key), ''),
                             'concept_count': len(terms[term]),
                             'flag': flag, 'suggested_treatment': treatment})

    summary = {'projects': n, 'challenges': len(challenge_sizes),
               'vocabulary_phrases': len(vocab), 'phrases_observed': sum(x > 0 for x in overall),
               'common_terms_flagged': flagged, 'flag_prevalence': args.flag_prevalence,
               'method': 'Exact token n-gram matching across title, summary, details; project-level DF',
               'cautions': ['Flags are for review, not automatic exclusion',
                            'Challenge lift is descriptive, not a validated relevance score',
                            'Does not resolve polysemy or recognize inflected forms']}
    (args.out / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    print('Saved:', output)


if __name__ == '__main__':
    main()
