#!/usr/bin/env python3
"""Read-only export of a small sample or the full catalog into D1 SQL chunks.
No writes to source SQLite. Export only necessary public project fields.
"""
import argparse, json, sqlite3, pathlib, re

def q(s): return "'" + str(s or '').replace("'", "''") + "'"
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--db',required=True)
    ap.add_argument('--tags',required=True)
    ap.add_argument('--out',default='export')
    ap.add_argument('--limit',type=int,default=200,help='0 means all projects')
    ap.add_argument('--chunk-size',type=int,default=150)
    a=ap.parse_args()
    out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(f'file:{pathlib.Path(a.db).expanduser().resolve()}?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    tags={}
    with open(a.tags,encoding='utf8') as f:
        for line in f:
            if line.strip():
                x=json.loads(line);tags[str(x['project_id'])]=list(dict.fromkeys(str(t).strip() for t in x['tags'] if str(t).strip()))
    schema='''CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, title TEXT NOT NULL, summary TEXT NOT NULL, description TEXT NOT NULL, team TEXT, challenge TEXT, country TEXT, location TEXT, team_url TEXT, project_link TEXT, demo_link TEXT);
CREATE TABLE IF NOT EXISTS project_tags (project_id TEXT NOT NULL, tag TEXT NOT NULL COLLATE NOCASE, PRIMARY KEY(project_id,tag));
CREATE INDEX IF NOT EXISTS tags_lookup ON project_tags(tag,project_id);
CREATE INDEX IF NOT EXISTS projects_country ON projects(country);
CREATE INDEX IF NOT EXISTS projects_challenge ON projects(challenge);
CREATE VIRTUAL TABLE IF NOT EXISTS projects_fts USING fts5(title,summary,description,content='projects',content_rowid='rowid',tokenize='unicode61 remove_diacritics 2');
'''
    # D1 FTS5 content_rowid requires integer rowid; projects is a rowid table despite TEXT primary key.
    (out/'000_schema.sql').write_text(schema,encoding='utf8')
    sql='''SELECT p.id,p.name,p.summary,p.details_text,p.demo_link,p.project_link,
                  t.title team,t.challenge_title challenge,t.location_country country,
                  t.location_title location,t.url team_url
           FROM projects p LEFT JOIN teams t ON p.team_id=t.id ORDER BY p.id'''
    if a.limit>0:sql+=' LIMIT '+str(a.limit)
    cur=conn.execute(sql)
    count=0;files=[];buffer=[];tag_count=0
    def flush():
        if not buffer:return
        name=f'{len(files)+1:03d}_data.sql'
        (out/name).write_text('BEGIN TRANSACTION;\n'+'\n'.join(buffer)+'\nCOMMIT;\n',encoding='utf8')
        files.append(name);buffer.clear()
    for r in cur:
        pid=r['id']; vals=[pid,r['name'],r['summary'],r['details_text'],r['team'],r['challenge'],r['country'],r['location'],r['team_url'],r['project_link'],r['demo_link']]
        buffer.append('INSERT INTO projects(id,title,summary,description,team,challenge,country,location,team_url,project_link,demo_link) VALUES ('+','.join(q(x) for x in vals)+');')
        buffer.append('INSERT INTO projects_fts(rowid,title,summary,description) SELECT rowid,title,summary,description FROM projects WHERE id='+q(pid)+';')
        for tag in tags.get(pid,[]):
            buffer.append('INSERT OR IGNORE INTO project_tags(project_id,tag) VALUES ('+q(pid)+','+q(tag)+');');tag_count+=1
        count+=1
        if count%a.chunk_size==0:flush()
    flush()
    (out/'manifest.json').write_text(json.dumps({'projects':count,'tag_assignments':tag_count,'files':files},indent=2),encoding='utf8')
    print(json.dumps({'projects':count,'tag_assignments':tag_count,'sql_files':len(files),'out':str(out)},indent=2))
if __name__=='__main__':main()
