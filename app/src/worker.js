const json = (data, status=200) => new Response(JSON.stringify(data), {status, headers:{'content-type':'application/json; charset=utf-8','cache-control':'public, max-age=30'}});
function phraseQuery(input) {
  // Quote the entire user input to prevent FTS syntax errors and unintended operators.
  return '"' + input.replaceAll('"','""') + '"';
}
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== '/api/search' && url.pathname !== '/api/filters' && url.pathname !== '/api/map-config' && url.pathname !== '/api/map-points' && url.pathname !== '/api/map-projects') return env.ASSETS.fetch(request);
    try {
      if (url.pathname === '/api/map-config') {
        // Browser keys are public by design: restrict this key by HTTP referrer and API in Google Cloud.
        return json({key: env.GOOGLE_MAPS_BROWSER_KEY || ''});
      }
      if (url.pathname === '/api/map-points') {
        const rows = await env.DB.prepare(`SELECT l.location_key key,l.display_name name,l.latitude lat,l.longitude lng,
          COUNT(pl.project_id) n FROM study_locations l
          JOIN project_study_locations pl ON pl.location_key=l.location_key
          JOIN projects p ON p.id=pl.project_id
          WHERE l.map_status='pin'
          GROUP BY l.location_key,l.display_name,l.latitude,l.longitude
          ORDER BY n DESC,l.display_name LIMIT 1000`).all();
        return json({points:rows.results});
      }
      if (url.pathname === '/api/map-projects') {
        const key=(url.searchParams.get('key')||'').slice(0,250);
        const page=Math.min(100,Math.max(1,parseInt(url.searchParams.get('page')||'1',10)||1));
        if (!key) return json({error:'Missing location key'},400);
        const count=await env.DB.prepare(`SELECT COUNT(*) n FROM project_study_locations pl JOIN projects p ON p.id=pl.project_id WHERE pl.location_key=?`).bind(key).first();
        const rows=await env.DB.prepare(`SELECT p.id,p.title,p.summary,p.project_link,p.challenge,p.team FROM project_study_locations pl JOIN projects p ON p.id=pl.project_id WHERE pl.location_key=? ORDER BY p.title COLLATE NOCASE LIMIT 12 OFFSET ?`).bind(key,(page-1)*12).all();
        return json({total:count.n,page,pageSize:12,results:rows.results});
      }
      if (url.pathname === '/api/filters') {
        const [challenges,countries,tags] = await Promise.all([
          env.DB.prepare("SELECT challenge value,COUNT(*) n FROM projects WHERE challenge IS NOT NULL AND challenge<>'' GROUP BY challenge ORDER BY n DESC LIMIT 100").all(),
          env.DB.prepare("SELECT country value,COUNT(*) n FROM projects WHERE country IS NOT NULL AND country<>'' GROUP BY country ORDER BY n DESC LIMIT 200").all(),
          env.DB.prepare('SELECT tag value,COUNT(*) n FROM project_tags GROUP BY tag ORDER BY n DESC LIMIT 35').all()
        ]);
        return json({challenges:challenges.results,countries:countries.results,tags:tags.results});
      }
      const q=(url.searchParams.get('q')||'').trim().slice(0,150);
      const tag=(url.searchParams.get('tag')||'').trim().slice(0,150);
      const country=(url.searchParams.get('country')||'').trim().slice(0,100);
      const challenge=(url.searchParams.get('challenge')||'').trim().slice(0,200);
      const study=(url.searchParams.get('study')||'').trim().slice(0,150);
      const page=Math.min(1000,Math.max(1,Number.parseInt(url.searchParams.get('page')||'1',10)||1));
      const pageSize=12;
      const conditions=[], params=[];
      if(q){conditions.push('p.rowid IN (SELECT rowid FROM projects_fts WHERE projects_fts MATCH ?)');params.push(phraseQuery(q));}
      if(tag){conditions.push('EXISTS (SELECT 1 FROM project_tags pt WHERE pt.project_id=p.id AND pt.tag=?)');params.push(tag);}
      if(country){conditions.push('p.country=?');params.push(country);}
      if(challenge){conditions.push('p.challenge=?');params.push(challenge);}
      if(study){conditions.push("EXISTS (SELECT 1 FROM project_study_areas psa JOIN study_areas sa ON sa.location_key=psa.location_key WHERE psa.project_id=p.id AND instr(sa.location_key,lower(?))>0)");params.push(study);}
      const where=conditions.length?' WHERE '+conditions.join(' AND '):'';
      const count=await env.DB.prepare('SELECT COUNT(*) n FROM projects p'+where).bind(...params).first();
      // FTS ranking is only needed for text searches; otherwise use a stable title ordering.
      const order=q?'ORDER BY (SELECT bm25(projects_fts) FROM projects_fts WHERE projects_fts.rowid=p.rowid) ASC,p.title ASC':'ORDER BY p.title COLLATE NOCASE ASC,p.id ASC';
      const result=await env.DB.prepare(`SELECT p.id,p.title,substr(p.summary,1,350) summary,p.team,p.challenge,p.country,p.location,p.team_url,p.project_link,p.demo_link FROM projects p${where} ${order} LIMIT ? OFFSET ?`).bind(...params,pageSize,(page-1)*pageSize).all();
      const ids=result.results.map(x=>x.id);
      let tagRows=[];
      if(ids.length) tagRows=(await env.DB.prepare('SELECT project_id,tag FROM project_tags WHERE project_id IN ('+ids.map(()=>'?').join(',')+') ORDER BY tag').bind(...ids).all()).results;
      let areaRows=[];
      if(ids.length) areaRows=(await env.DB.prepare('SELECT psa.project_id,sa.display_name,sa.location_key FROM project_study_areas psa JOIN study_areas sa ON sa.location_key=psa.location_key WHERE psa.project_id IN ('+ids.map(()=>'?').join(',')+') ORDER BY sa.display_name COLLATE NOCASE').bind(...ids).all()).results;
      const areasById={};for(const r of areaRows)(areasById[r.project_id]??=[]).push({name:r.display_name,key:r.location_key});
      const byId={};for(const r of tagRows)(byId[r.project_id]??=[]).push(r.tag);
      return json({total:count.n,page,pageSize,results:result.results.map(x=>({...x,tags:byId[x.id]||[],study_areas:areasById[x.id]||[]}))});
    } catch(e) {return json({error:'Search unavailable',detail:String(e.message||e)},500);}
  }
};
