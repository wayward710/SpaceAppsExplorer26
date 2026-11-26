"""Build an auditable, editable term-quality registry from Space Apps SWEET outputs.

Usage:
 py -3.12 build_term_registry.py --quality term_quality.csv --vocabulary concept_vocabulary.csv --output term_registry.csv

Only a short explicit list is suppressed. Frequency alone never suppresses a term.
"""
import argparse
import csv
import re
from collections import defaultdict
from pathlib import Path

SUPPRESS = {'project','projects','data','impact','future','system','systems','platform','research','development','analysis','work','solution','solutions','application','applications','information','important'}
SUBJECT = {'soil moisture','precipitation','groundwater','evapotranspiration','drought','climate change','space weather','solar radiation','water quality','land cover','radiation','temperature','health','planetary science','astronomy','agriculture','atmosphere'}
METHOD = {'remote sensing','environmental monitoring','time series','machine learning','neural network','optical depth','radar backscatter','data assimilation','spectroscopy','in situ'}
LOCATION = {'earth','moon','mars','south pole','great lakes','arctic','antarctica'}
TECH = {'satellite','radar','l band','solar power'}

def normalize(s):
    return re.sub(r'\s+', ' ', re.sub(r'[^\w]+', ' ', (s or '').casefold())).strip()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--quality',default='term_quality.csv')
    ap.add_argument('--vocabulary',default='concept_vocabulary.csv')
    ap.add_argument('--output',default='term_registry.csv')
    args=ap.parse_args()
    uris=defaultdict(set)
    with open(args.vocabulary,encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            for label in (r['labels'] or '').split('|'):
                key=normalize(label)
                if key: uris[key].add(r['uri'])
    with open(args.quality,encoding='utf-8-sig',newline='') as f:
        quality=list(csv.DictReader(f))
    columns=['term','document_frequency','prevalence','challenges_with_term','max_challenge_prevalence','max_challenge_lift','top_challenge','source','concept_uris','concept_count','facet','treatment','review_priority','rationale','reviewed','notes']
    out=Path(args.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    counts=defaultdict(int)
    with out.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader()
        for r in quality:
            term=r['term']; key=normalize(term); prevalence=float(r['prevalence'])
            if key in SUPPRESS:
                treatment='suppress_standalone';reason='Explicitly seeded generic term; retain inside longer phrases and full-text search'
            else:
                treatment='retain_candidate';reason='No automatic exclusion based on corpus frequency'
            if key in SUBJECT: facet='scientific_subject'
            elif key in METHOD: facet='method'
            elif key in LOCATION: facet='location_or_celestial_body'
            elif key in TECH: facet='technology_or_instrument'
            else: facet='unassigned'
            priority='high' if prevalence>=.25 or (len(uris[key])>1 and prevalence>=.01) else 'normal'
            if key in {'south pole','earth','moon','mars'}: priority='high';reason+='; geographic/planetary disambiguation needed'
            counts[treatment]+=1
            writer.writerow({'term':term,'document_frequency':r['document_frequency'],'prevalence':r['prevalence'],
                'challenges_with_term':r['challenges_with_term'],'max_challenge_prevalence':r['max_challenge_prevalence'],
                'max_challenge_lift':r['max_challenge_lift'],'top_challenge':r['top_challenge'],
                'source':'SWEET','concept_uris':'|'.join(sorted(uris[key])), 'concept_count':len(uris[key]),
                'facet':facet,'treatment':treatment,'review_priority':priority,'rationale':reason,
                'reviewed':'false','notes':''})
    print(f'Wrote {len(quality):,} terms to {out}; treatments: {dict(counts)}')

if __name__=='__main__': main()
