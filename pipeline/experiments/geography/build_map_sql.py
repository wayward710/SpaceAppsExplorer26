#!/usr/bin/env python3
"""Build idempotent D1 import SQL from audited map candidates and project-study CSVs.
Only accepted 'pin' locations are exported by default. No network access or input changes.
"""
import argparse,csv,pathlib

def sql(v):
    return 'NULL' if v is None else "'"+str(v).replace("'","''")+"'"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--candidates',required=True)
    ap.add_argument('--projects',required=True)
    ap.add_argument('--out',default='map_import.sql')
    ap.add_argument('--include-regions',action='store_true')
    args=ap.parse_args()
    statuses={'pin','region'} if args.include_regions else {'pin'}
    with open(args.candidates,encoding='utf-8-sig',newline='') as f:
        rows=[r for r in csv.DictReader(f) if r['map_status'] in statuses and r.get('latitude') and r.get('longitude')]
    keys={r['location_key'] for r in rows}
    with open(args.projects,encoding='utf-8-sig',newline='') as f:
        pairs={(r['project_id'],r['location_key']) for r in csv.DictReader(f) if r['location_key'] in keys}
    out=pathlib.Path(args.out)
    with out.open('w',encoding='utf-8') as f:
        f.write('-- Generated map data; source GeoNames; approximate representative points.\n')
        for r in rows:
            f.write('INSERT OR REPLACE INTO study_locations(location_key,display_name,latitude,longitude,geoname_id,map_status,source) VALUES ('+','.join([sql(r['location_key']),sql(r['display_name']),str(float(r['latitude'])),str(float(r['longitude'])),sql(r['geoname_id']),sql(r['map_status']),sql('GeoNames')])+');\n')
        for pid,key in sorted(pairs):
            f.write(f'INSERT OR IGNORE INTO project_study_locations(project_id,location_key) VALUES ({sql(pid)},{sql(key)});\n')
    print(f'{len(rows)} locations; {len(pairs)} project-location relationships; wrote {out}')
if __name__=='__main__':main()
