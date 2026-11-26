import csv,re,unicodedata
from pathlib import Path
import fitz
SOURCE=Path(__file__).with_name('20000025197.pdf')
OUTPUT=Path(__file__).with_name('nasa_sti_categories.csv')
doc=fitz.open(SOURCE)
starts=[]
for page_index in range(8,116):
    lines=doc[page_index].get_text().splitlines()
    for j,line in enumerate(lines[:-1]):
        if re.fullmatch(r'(0[1-9]|[1-9][0-9])',line.strip()) and j+1<len(lines):
            name=lines[j+1].strip()
            if name and not name.isdigit() and not name.startswith('•'):
                starts.append((int(line),name,page_index,j,lines))
print('Detected:',len(starts), 'unique:',len(set(x[0] for x in starts)))
print([(x[0],x[1]) for x in starts])
DIVISIONS=[(1,9,'Aeronautics'),(12,20,'Astronautics'),(23,29,'Chemistry and Materials'),(31,39,'Engineering'),(42,48,'Geosciences'),(51,55,'Life Sciences'),(59,67,'Mathematical and Computer Sciences'),(70,77,'Physics'),(80,85,'Social and Information Sciences'),(88,93,'Space Sciences'),(99,99,'General')]
rows=[]
for k,(number,name,page,j,lines) in enumerate(starts):
    next_page=starts[k+1][2] if k+1<len(starts) else 116
    next_j=starts[k+1][3] if k+1<len(starts) else 0
    block=lines[j+2:]
    for pg in range(page+1,next_page+1):
        if pg>=len(doc):break
        block+=doc[pg].get_text().splitlines()[:next_j if pg==next_page else None]
    if number==17 and block and block[0].strip()=='Tracking':
        name+=' Tracking';block=block[1:]
    # The initial 'Includes...' paragraph is the category's scope; stop at Definition or NASA Interest.
    scope=[]
    for line in block:
        if line.strip().replace('ﬁ','fi') in ('Definition','NASA Interest','Input Subjects of Specific Interest'):break
        if re.fullmatch(r'\s*\d{1,3}\s*',line):break
        if line.strip():scope.append(line.strip())
    description=' '.join(scope).replace('ﬁ','fi').replace('ﬂ','fl')
    division=next(d for lo,hi,d in DIVISIONS if lo<=number<=hi)
    rows.append(dict(category_code=f'{number:02d}',category_name=name,division=division,scope_description=description,source_pdf_page=page+1))
with OUTPUT.open('w',newline='',encoding='utf-8-sig') as f:
    writer=csv.DictWriter(f,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
print('Wrote',OUTPUT)
for code in ('17','43','63','99'):
    r=next(r for r in rows if r['category_code']==code)
    print(code,r['category_name'],repr(r['scope_description'][:240]))
