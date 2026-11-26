#!/usr/bin/env python3
"""Non-destructive SQLite FTS5 index + flat-tag search for Space Apps projects.

Examples:
  python3 spaceapps_search.py inspect --db ~/spaceapps_2026.sqlite
  python3 spaceapps_search.py build --db ~/spaceapps_2026.sqlite --tags project_tags.jsonl \
      --table projects --id-col project_id --title-col title --summary-col summary --description-col description
  python3 spaceapps_search.py search --db ~/spaceapps_2026.sqlite --query 'soil moisture' --tag NISAR

Build creates ONLY spaceapps_search_* tables. It never updates existing tables.
"""
import argparse, base64, json, re, sqlite3, sys
from pathlib import Path

PREFIX = 'spaceapps_search_'
FIELDS = ('title', 'summary', 'description')

def qi(s):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', s):
        raise ValueError(f'Unsafe SQL identifier: {s!r}')
    return '"' + s + '"'

def conn(path):
    db = sqlite3.connect(f'file:{Path(path).expanduser().resolve()}?mode=rw', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=10000')
    return db

def schema(db):
    result = {}
    for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        if row['name'].startswith(PREFIX): continue
        result[row['name']] = [r['name'] for r in db.execute(f'PRAGMA table_info({qi(row["name"])})')]
    return result

def inspect(db):
    for name, cols in schema(db).items():
        print(f'{name}: {", ".join(cols)}')

def detect(db, args):
    tables = schema(db)
    if args.table:
        if args.table not in tables: raise ValueError(f'Table {args.table!r} not found')
        table = args.table
    else:
        candidates = [t for t,c in tables.items() if 'project' in t.lower() and any(x in c for x in ('title','name'))]
        if len(candidates) != 1: raise ValueError(f'Could not uniquely identify projects table ({candidates}); use --table. Run inspect first.')
        table = candidates[0]
    cols = tables[table]
    def pick(explicit, choices, required=False):
        if explicit:
            if explicit not in cols: raise ValueError(f'{explicit!r} is not in {table}: {cols}')
            return explicit
        for x in choices:
            if x in cols: return x
        if required: raise ValueError(f'Cannot identify required column from {cols}; supply explicit option')
        return None
    return (table, pick(args.id_col, ('project_id','id','projectId'), True),
            pick(args.title_col, ('title','name','project_title'), True),
            pick(args.summary_col, ('summary','short_description','abstract','project_summary')),
            pick(args.description_col, ('description','project_description','details','body','content')))

def aliases(value):
    s = str(value).strip()
    result = {s}
    if s.startswith('id:') and s[3:].isdigit(): result.add(s[3:])
    if s.isdigit(): result.add('id:' + s)
    try:
        decoded = base64.b64decode(s, validate=True).decode('utf-8')
        if decoded.startswith('id:') and decoded[3:].isdigit():
            result.add(decoded); result.add(decoded[3:])
    except (ValueError, UnicodeError): pass
    return result

def build(db, args):
    table, idcol, titlecol, sumcol, desccol = detect(db, args)
    print(f'Indexing {table}: id={idcol}, title={titlecol}, summary={sumcol}, description={desccol}')
    if not sumcol and not desccol: print('WARNING: Only title text is available in this table.', file=sys.stderr)
    tags_path = Path(args.tags).expanduser()
    if not tags_path.is_file(): raise ValueError(f'Cannot find tags: {tags_path}')
    # Preload tags, check duplicates and malformed rows before modifying DB.
    tags_by_id = {}
    for line_no, line in enumerate(tags_path.open(encoding='utf-8'), 1):
        if not line.strip(): continue
        item = json.loads(line)
        pid = str(item['project_id'])
        if pid in tags_by_id: raise ValueError(f'Duplicate project_id {pid} at line {line_no}')
        tags = item['tags']
        if not isinstance(tags, list) or not all(isinstance(x,str) for x in tags):
            raise ValueError(f'Invalid tags at line {line_no}')
        tags_by_id[pid] = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
    # In-memory alias lookup, collision-safe: ambiguous aliases are excluded.
    alias_map = {}; ambiguous = set()
    for pid in tags_by_id:
        for a in aliases(pid):
            if a in alias_map and alias_map[a] != pid: ambiguous.add(a)
            else: alias_map[a] = pid
    for a in ambiguous: alias_map.pop(a, None)
    select_expr = [qi(idcol), qi(titlecol), qi(sumcol) if sumcol else "''", qi(desccol) if desccol else "''"]
    sql = f'SELECT {", ".join(select_expr)} FROM {qi(table)}'
    # All writes in a transaction. Existing project data untouched.
    with db:
        db.execute(f'DROP TABLE IF EXISTS {PREFIX}fts')
        db.execute(f'DROP TABLE IF EXISTS {PREFIX}tags')
        db.execute(f'DROP TABLE IF EXISTS {PREFIX}projects')
        db.execute(f'CREATE TABLE {PREFIX}projects (search_id INTEGER PRIMARY KEY, source_id TEXT NOT NULL UNIQUE, source_table TEXT NOT NULL)')
        db.execute(f'CREATE VIRTUAL TABLE {PREFIX}fts USING fts5(title, summary, description, tokenize="unicode61 remove_diacritics 2")')
        db.execute(f'CREATE TABLE {PREFIX}tags (search_id INTEGER NOT NULL, tag TEXT NOT NULL COLLATE NOCASE, PRIMARY KEY(search_id,tag)) WITHOUT ROWID')
        db.execute(f'CREATE INDEX {PREFIX}tags_by_tag ON {PREFIX}tags(tag,search_id)')
        matched = 0; unmatched = 0; rows = 0; tag_count = 0
        used = set()
        for r in db.execute(sql):
            rows += 1
            raw_id = str(r[0]); pid = None
            for a in aliases(raw_id):
                candidate = alias_map.get(a)
                if candidate is not None:
                    if pid is not None and pid != candidate: raise ValueError(f'Ambiguous ID match: {raw_id}')
                    pid = candidate
            if pid is None: unmatched += 1
            else: matched += 1; used.add(pid)
            db.execute(f'INSERT INTO {PREFIX}projects(search_id,source_id,source_table) VALUES (?,?,?)', (rows,raw_id,table))
            db.execute(f'INSERT INTO {PREFIX}fts(rowid,title,summary,description) VALUES (?,?,?,?)',
                       (rows, *(str(x or '') for x in r[1:4])))
            if pid:
                batch = [(rows,tag) for tag in tags_by_id[pid]]
                db.executemany(f'INSERT OR IGNORE INTO {PREFIX}tags(search_id,tag) VALUES (?,?)', batch)
                tag_count += len(batch)
        db.execute(f'CREATE TABLE IF NOT EXISTS {PREFIX}settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        db.execute(f'INSERT OR REPLACE INTO {PREFIX}settings VALUES (?,?)', ('source_table',table))
    print(json.dumps({'indexed_projects':rows,'matched_tag_projects':matched,'unmatched_database_projects':unmatched,
                      'tag_file_projects_not_matched':len(tags_by_id)-len(used),'tag_assignments':tag_count,
                      'source_table':table}, indent=2))
    if len(tags_by_id)-len(used):
        print('WARNING: Some tag IDs did not match database IDs. Check schema and ID formats before proceeding.', file=sys.stderr)

def search(db, args):
    try: db.execute(f'SELECT 1 FROM {PREFIX}projects LIMIT 1')
    except sqlite3.OperationalError: raise ValueError('Search index not found; run build first')
    query = args.query.strip() if args.query else ''
    if not query and not args.tag: raise ValueError('Provide --query and/or at least one --tag')
    # Phrase matching by default; --fts-query allows native FTS5 syntax.
    fts = query if args.fts_query else '"' + query.replace('"','""') + '"'
    filters = []; params = []
    if query:
        filters.append(f'{PREFIX}fts MATCH ?'); params.append(fts)
    for tag in args.tag:
        filters.append(f'EXISTS (SELECT 1 FROM {PREFIX}tags t WHERE t.search_id=p.search_id AND t.tag=?)')
        params.append(tag)
    where = ' AND '.join(filters)
    rank = f'bm25({PREFIX}fts)' if query else 'p.search_id'
    join = f'JOIN {PREFIX}fts ON {PREFIX}fts.rowid=p.search_id' if query else f'LEFT JOIN {PREFIX}fts ON {PREFIX}fts.rowid=p.search_id'
    sql = (f'SELECT p.source_id, f.title, substr(f.summary,1,240) AS summary, '
           f'(SELECT group_concat(tag, ", ") FROM {PREFIX}tags t WHERE t.search_id=p.search_id) AS tags '
           f'FROM {PREFIX}projects p JOIN {PREFIX}fts f ON f.rowid=p.search_id '
           f'WHERE {where} ORDER BY {rank} LIMIT ? OFFSET ?')
    params.extend((args.limit,args.offset))
    try:
        results = [dict(r) for r in db.execute(sql,params)]
    except sqlite3.OperationalError as e:
        raise ValueError(f'Search error ({e}). Try a simpler phrase or use --fts-query for FTS5 operators.') from e
    print(json.dumps(results,indent=2,ensure_ascii=False))

def main():
    p = argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command',required=True)
    for cmd in ('inspect','build','search'):
        s = sub.add_parser(cmd); s.add_argument('--db',required=True)
        if cmd == 'build':
            s.add_argument('--tags',required=True)
            for key in ('table','id-col','title-col','summary-col','description-col'):
                s.add_argument('--'+key)
        if cmd == 'search':
            s.add_argument('--query',default=''); s.add_argument('--tag',action='append',default=[])
            s.add_argument('--limit',type=int,default=20); s.add_argument('--offset',type=int,default=0)
            s.add_argument('--fts-query',action='store_true',help='Interpret query as raw FTS5 syntax')
    args = p.parse_args()
    try:
        db = conn(args.db)
        if args.command=='inspect': inspect(db)
        elif args.command=='build': build(db,args)
        else: search(db,args)
    except (ValueError,sqlite3.Error,OSError,json.JSONDecodeError) as e:
        p.exit(1,f'ERROR: {e}\n')

if __name__ == '__main__': main()
