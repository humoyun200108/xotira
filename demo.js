/* Xotira demo mode: answers the UI's API calls from demo.json and simulates scans and cleanups.
   Nothing here touches the real disk — it powers the GitHub Pages demo and the README screenshots. */
window.XotiraDemo = (() => {
  let D = null;
  const jobs = {};
  let scanSim = null;
  const TIME_KEYS = new Set(['mtime', 'last_played', 'last_updated', 'ts', 'from_ts', 'to_ts']);

  // demo.json was generated at D.now — shift every timestamp so "3 days ago" stays 3 days ago
  function shift(o, d) {
    if (Array.isArray(o)) { o.forEach(x => shift(x, d)); return; }
    if (!o || typeof o !== 'object') return;
    for (const k of Object.keys(o)) {
      if (TIME_KEYS.has(k) && typeof o[k] === 'number') o[k] += d;
      else if (k === 'samples') o[k].forEach(s => { s[0] += d; });
      else shift(o[k], d);
    }
  }
  const ready = fetch('demo.json').then(r => r.json()).then(j => { D = j; shift(D, Math.round(Date.now() / 1000) - D.now); });
  const clone = x => JSON.parse(JSON.stringify(x));
  const now = () => Date.now() / 1000;
  const drive = () => D.info.drives[0];

  function scanStatus() {
    if (!scanSim) return clone(D.info.scan);
    const k = Math.min(1, (now() - scanSim.t0) / scanSim.dur);
    const st = clone(D.info.scan);
    if (k >= 1) { scanSim = null; return st; }
    const e = 1 - Math.pow(1 - k, 1.6);
    return Object.assign(st, { state: 'running', files: Math.round(st.files * e), dirs: Math.round(st.dirs * e), bytes: Math.round(st.bytes * e),
      elapsed: +(k * scanSim.dur).toFixed(1), rate: 47000 + Math.round(Math.random() * 6000), current: 'C:\\Users\\Aziz\\AppData\\Local\\Packages\\Microsoft.Windows.Photos\\LocalCache' });
  }

  function children(path) {
    const key = path.length === 2 ? path + '\\' : path.replace(/\\+$/, '') || path;
    const k = Object.keys(D.tree).find(p => p.toLowerCase() === key.toLowerCase() || p.toLowerCase() === key.toLowerCase() + '\\');
    const items = clone(D.tree[k] || []);
    const size = items.reduce((a, i) => a + (i.size || 0), 0);
    const parent = key.length <= 3 ? null : (key.slice(0, key.lastIndexOf('\\')) || null);
    return { path: k || key, parent: parent && parent.length === 2 ? parent + '\\' : parent, scanned: true, size,
      files: items.reduce((a, i) => a + (i.files || (i.dir ? 0 : 1)), 0), items, more: 0, more_size: 0, scan_state: scanSim ? 'running' : 'done' };
  }

  function bigFiles(q) {
    const cat = q.get('cat') || '', scope = q.get('scope') || 'user', age = +(q.get('age') || 0), min = +(q.get('min') || 0), text = (q.get('q') || '').toLowerCase();
    const n = now();
    const list = D.big.filter(b => (!cat || b.cat === cat) && (scope === 'all' || !b.sys) && b.size >= min && (!text || b.path.toLowerCase().includes(text)) &&
      (!age || (age > 0 ? b.mtime < n - age * 86400 : b.mtime > n + age * 86400)));
    list.sort((a, b) => b.size - a.size);
    return { items: clone(list.slice(0, +(q.get('limit') || 300))), count: list.length, size: list.reduce((a, b) => a + b.size, 0), scanned: true, state: 'done' };
  }

  function job(kind, steps, finish) {
    const id = Math.random().toString(16).slice(2, 12);
    const j = { id, kind, state: 'running', progress: 0, msg: '', live: {}, result: null, t0: now() };
    jobs[id] = j; j.steps = steps; j.finish = finish;
    return j;
  }
  function tick(j) {
    if (j.state !== 'running') return;
    const el = now() - j.t0;
    j.steps(j, el);
    if (j.progress >= 1) { j.state = 'done'; j.result = j.finish(j); }
  }

  function freeUp(bytes) {
    const d = drive(); d.free += bytes; d.used -= bytes;
    D.breakdown.used -= bytes; D.breakdown.free += bytes;
    D.progress.samples.push([Math.round(now()), d.free, d.used, d.total]);
  }

  function startClean(ids) {
    const plan = ids.map(id => D.smart.items.find(x => x.id === id)).filter(Boolean);
    const before = drive().free;
    const per = 1.6;                                   // seconds per place
    return job('clean', (j, el) => {
      j.live.items = plan.map((t, i) => {
        const k = Math.max(0, Math.min(1, (el - i * per) / per));
        return { id: t.id, title: t.title, size: t.size || 0, freed: Math.round((t.size || 0) * k), state: k >= 1 ? 'done' : k > 0 ? 'run' : 'wait' };
      });
      j.live.freed = j.live.items.reduce((a, x) => a + x.freed, 0);
      const cur = j.live.items.find(x => x.state === 'run');
      j.live.current = cur ? `C:\\Users\\Aziz\\AppData\\Local\\${cur.id}\\cache_${Math.floor(Math.random() * 9e5).toString(16)}.tmp` : '';
      j.progress = Math.min(1, el / (plan.length * per));
    }, j => {
      const freed = plan.reduce((a, t) => a + (t.size || 0), 0);
      plan.forEach(t => { if (t.kind === 'clean' || t.id === 'recycle') { t.size = 0; t.count = 0; } if (t.id === 'recycle') D.info.recycle = { size: 0, count: 0 }; });
      const cache = D.breakdown.buckets.find(b => b.id === 'cache'); if (cache) cache.size = Math.max(0, cache.size - freed);
      freeUp(freed);
      D.info.stats.freed_total += freed; D.progress.freed_total += freed;
      D.progress.events.push({ ts: Math.round(now()), kind: 'clean', title: plan.length === 1 ? plan[0].title : { uz: `Aqlli tozalash · ${plan.length} ta joy`, en: `Smart cleanup · ${plan.length} places` }, bytes: freed });
      return { freed, failed: 0, items: plan.map(t => ({ id: t.id, freed: t.size })), free_before: before, free_after: drive().free };
    });
  }

  function startDelete(paths, mode) {
    const before = drive().free;
    const items = paths.map(p => D.big.find(b => b.path === p) || { path: p, size: 0 });
    return job('delete', (j, el) => {
      const k = Math.min(1, el / Math.max(1.2, items.length * 0.4));
      j.live = { total: items.length, done: Math.floor(items.length * k), bytes: Math.round(items.reduce((a, b) => a + b.size, 0) * k), current: items[Math.min(items.length - 1, Math.floor(items.length * k))]?.path || '' };
      j.progress = k;
    }, () => {
      const total = items.reduce((a, b) => a + b.size, 0);
      D.big = D.big.filter(b => !paths.includes(b.path));
      if (mode === 'permanent') { freeUp(total); D.info.stats.freed_total += total; D.progress.freed_total += total; }
      else { D.info.recycle.size += total; D.info.recycle.count += items.length; }
      D.progress.events.push({ ts: Math.round(now()), kind: mode === 'permanent' ? 'delete' : 'recycle-move', title: { uz: `${items.length} ta fayl`, en: `${items.length} files` }, bytes: total });
      return { ok: items.map(i => ({ path: i.path, size: i.size })), fail: [], bytes: total, mode, free_before: before, free_after: drive().free };
    });
  }

  async function get(u) {
    await ready;
    const url = new URL(u, location.href), p = url.pathname.replace(/^.*?\/api\//, '/api/'), q = url.searchParams;
    switch (p) {
      case '/api/info': return Object.assign(clone(D.info), { scan: scanStatus() });
      case '/api/status': {
        Object.values(jobs).forEach(tick);
        return { scan: scanStatus(), jobs: Object.values(jobs).filter(j => j.state === 'running').map(j => ({ id: j.id, kind: j.kind })), stats: D.info.stats };
      }
      case '/api/smart': return clone(D.smart);
      case '/api/overview': return { breakdown: scanSim ? null : clone(D.breakdown), scan: scanStatus(), admin: false };
      case '/api/games': return { items: clone(D.games), scanned: true };
      case '/api/progress': return clone(D.progress);
      case '/api/children': return children(q.get('path') || 'C:\\');
      case '/api/big': return bigFiles(q);
      case '/api/types': return clone(D.types);
      case '/api/junk': return clone(D.junk);
      case '/api/downloads': return clone(D.downloads);
      case '/api/apps': return clone(D.apps);
      case '/api/job': {
        const j = jobs[q.get('id')]; if (!j) return { error: 'job' };
        tick(j);
        return { id: j.id, kind: j.kind, state: j.state, progress: j.progress, msg: j.msg, live: j.live, result: j.result, elapsed: now() - j.t0 };
      }
    }
    return { error: 'demo' };
  }

  async function post(u, b) {
    await ready;
    const p = new URL(u, location.href).pathname.replace(/^.*?\/api\//, '/api/');
    const view = j => ({ id: j.id, kind: j.kind, state: j.state, progress: j.progress, msg: j.msg, live: j.live, result: null });
    switch (p) {
      case '/api/scan': scanSim = { t0: now(), dur: 9 }; return scanStatus();
      case '/api/scan/cancel': scanSim = null; return { ok: true };
      case '/api/clean': { const j = startClean(b.ids || []); tick(j); return view(j); }
      case '/api/delete': { const j = startDelete(b.paths || [], b.mode); tick(j); return view(j); }
      case '/api/dups': return view(job('dups', (j, el) => { j.progress = Math.min(1, el / 3); j.msg = j.progress < .4 ? { uz: 'Tez solishtirish…', en: 'Quick compare…' } : { uz: 'Tarkibni tekshirish…', en: 'Checking contents…' }; }, () => clone(D.dups)));
    }
    return { ok: true };
  }

  return { ready, get, post };
})();
