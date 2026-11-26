"""Reproducible, offline NASA STI subject-category baseline (no API calls).

pip install scikit-learn
python classify_nasa_sti_pilot.py

This is a lexical retrieval baseline, NOT a validated semantic classifier.
"""
import argparse
import csv
import json
import re
from pathlib import Path
from collections import Counter

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

BASE = Path(__file__).resolve().parent
TOKEN = re.compile(r"\b[\w]+(?:[-'][\w]+)*\b", re.UNICODE)


def normalize(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(s or ""))).strip()


def snippets(text, terms, limit=2):
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    scored = []
    for sentence in sentences:
        if len(sentence.strip()) < 24:
            continue
        low = sentence.lower()
        hits = sum(1 for t in terms if len(t) >= 4 and re.search(r"\b" + re.escape(t) + r"\b", low))
        if hits:
            scored.append((hits, sentence.strip()[:350]))
    scored.sort(key=lambda x: -x[0])
    return " | ".join(s for _, s in scored[:limit])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--projects', type=Path, default=BASE/'sample_300_full.jsonl')
    ap.add_argument('--categories', type=Path, default=BASE/'nasa_sti_categories.csv')
    ap.add_argument('--outdir', type=Path, default=BASE/'classification_pilot')
    ap.add_argument('--top', type=int, default=3)
    args = ap.parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    with args.categories.open(encoding='utf-8-sig', newline='') as f:
        cats = list(csv.DictReader(f))
    with args.projects.open(encoding='utf-8') as f:
        projects = [json.loads(line) for line in f if line.strip()]
    if not cats or not projects:
        raise ValueError('Missing category or project records')

    # NASA guide descriptions are used without challenge titles, so category assignment
    # does not simply echo the challenge. Do not treat references or AI disclosures as subject.
    cat_docs = [normalize(c['category_name'] + '. ' + c['scope_description']) for c in cats]
    project_docs = [normalize(' '.join([p.get('project_name',''),
                      (p.get('summary') or '') * 2, p.get('details_text','')]))[:20000]
                    for p in projects]
    # Two complementary lexical views: phrase-level and robust character ngrams.
    word = TfidfVectorizer(ngram_range=(1,2), stop_words='english', sublinear_tf=True,
                           min_df=1, max_df=0.95, max_features=50000)
    char = TfidfVectorizer(analyzer='char_wb', ngram_range=(3,5), sublinear_tf=True,
                           min_df=1, max_features=80000)
    all_docs = cat_docs + project_docs
    w = word.fit_transform(all_docs)
    c = char.fit_transform(all_docs)
    n = len(cats)
    scores = 0.7 * cosine_similarity(w[n:], w[:n]) + 0.3 * cosine_similarity(c[n:], c[:n])
    output = []
    for i, p in enumerate(projects):
        ranks = sorted(range(n), key=lambda j: (-scores[i,j], cats[j]['category_code']))[:max(3,args.top)]
        best, runner = (float(scores[i,ranks[0]]), float(scores[i,ranks[1]]))
        # A relative margin is only a review heuristic; NOT a probability or accuracy estimate.
        margin = (best-runner)/max(best, 1e-9)
        status = 'review' if best < 0.11 or margin < 0.12 else 'provisional'
        text = normalize(' '.join([p.get('project_name',''), p.get('summary',''), p.get('details_text','')]))
        suggestions = []
        for j in ranks[:args.top]:
            cat = cats[j]
            # Extract non-stopword terms from the category text for a transparent evidence hint.
            terms = set(re.findall(r'[a-z]{4,}', cat['category_name'].lower()))
            terms |= set(re.findall(r'[a-z]{5,}', cat['scope_description'].lower()))
            terms -= {'includes','include','related','information','general','specific','other','studies','research','systems','applications','category','categories','development','technology','techniques','methods','space','earth','science'}
            suggestions.append({'code':cat['category_code'],'name':cat['category_name'],
                                'similarity':round(float(scores[i,j]),4),
                                'evidence_hint':snippets(text, terms)})
        output.append({'project_id':p['project_id'],'project_name':p.get('project_name',''),
                       'challenge_title':p.get('challenge_title',''),
                       'primary_suggestion':suggestions[0]['code'],
                       'primary_name':suggestions[0]['name'],
                       'secondary_suggestions':'|'.join(s['code'] for s in suggestions[1:]),
                       'top_score':round(best,4),'margin':round(margin,4),
                       'review_status':status,
                       'evidence_hint':suggestions[0]['evidence_hint'],
                       'reviewed_primary':'','reviewed_secondary':'',
                       'reviewer_notes':'', 'candidates_json':json.dumps(suggestions,ensure_ascii=False)})

    fields = list(output[0])
    with (args.outdir/'nasa_sti_suggestions.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(output)
    counts=Counter(x['primary_suggestion'] for x in output)
    with (args.outdir/'category_counts.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['category_code','category_name','primary_suggestions'])
        for cat in cats:
            writer.writerow([cat['category_code'],cat['category_name'],counts[cat['category_code']]])
    summary={'projects':len(projects),'categories':len(cats),
             'review_status_counts':dict(Counter(x['review_status'] for x in output)),
             'notes':['Cosine similarity is not a calibrated confidence score.',
                      'Evidence hints are lexical overlaps, not proof of correctness.',
                      'Secondary suggestions are alternatives, not automatically valid secondary subjects.',
                      'Evaluate with manual review across challenges before full-catalog deployment.']}
    (args.outdir/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
    print('Saved to',args.outdir)

if __name__=='__main__':
    main()
