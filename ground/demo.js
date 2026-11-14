/* Zakarpattia Orbit — static demo (GitHub Pages).
   Replaces the Python ground station: answers the page's /api/* requests in the browser.
   Same logic as ground/mission.py: auto take-off -> fly -> circle the hotspot while the OPERATOR
   watches day/thermal video and decides -> auto return and landing. Data: a real NASA FIRMS day. */
(function () {
  const realFetch = window.fetch.bind(window);
  let D = null, CAL = null, ready = null;
  const results = {}, log = [];
  let mission = null, alarm = null, lastTick = 0;

  const PH = [['takeoff', 'Автозліт', 'Auto take-off'], ['cruise', 'Політ до точки', 'Flying to the hotspot'],
    ['descend', 'Зниження', 'Descent'], ['inspect', 'Оператор дивиться', 'Operator review'],
    ['return', 'Повернення', 'Return'], ['land', 'Автопосадка', 'Auto landing'], ['done', 'На базі', 'At base']];
  const V = {
    fire: {title: 'Лісова пожежа', title_en: 'Forest fire', color: '#E4572E',
      summary: 'Оператор підтвердив горіння в лісі. Потрібен виїзд пожежників.', summary_en: 'The operator confirmed burning in the forest. Firefighters are needed.'},
    field: {title: 'Палять поле', title_en: 'Field burning', color: '#E9A23B',
      summary: 'Горить поле або суха трава, не ліс. Повідомити громаду / поліцію.', summary_en: 'A field or dry grass is burning, not the forest. Notify the community or police.'},
    false: {title: 'Хибна тривога', title_en: 'False alarm', color: '#7FB069',
      summary: 'На місці ознак горіння немає.', summary_en: 'No signs of burning on site.'},
    none: {title: 'Не перевірено', title_en: 'Not reviewed', color: '#9FAA94',
      summary: 'Оператор не встиг відповісти. Дрон повернувся, точку варто перевірити ще раз.', summary_en: 'The operator did not answer in time. The drone returned; check this place again.'}
  };

  const R = 6371;
  const hav = (a, b, c, d) => { const p = Math.PI / 180, x = Math.sin((c - a) * p / 2) ** 2 + Math.cos(a * p) * Math.cos(c * p) * Math.sin((d - b) * p / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(x)); };
  const bearing = (a, b, c, d) => { const p = Math.PI / 180, x = Math.sin((d - b) * p) * Math.cos(c * p), y = Math.cos(a * p) * Math.sin(c * p) - Math.sin(a * p) * Math.cos(c * p) * Math.cos((d - b) * p); return (Math.atan2(x, y) / p + 360) % 360; };
  const lerp = (a, b, f) => [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
  const off = (lat, lon, n, e) => [lat + n / 111320, lon + e / (111320 * Math.cos(lat * Math.PI / 180))];
  let seed = 1; const rnd = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  const gauss = s => s * Math.sqrt(-2 * Math.log(rnd() + 1e-9)) * Math.cos(2 * Math.PI * rnd());
  const hhmm = () => new Date().toTimeString().slice(0, 5);

  function hint(th, hist) {
    const rec = (hist || {}).recurrence;
    const k = th >= 200 ? (rec === 'often' && th < 230 ? 'field' : 'fire') : th >= 80 ? 'field' : 'false';
    return {label: k, title: V[k].title, title_en: V[k].title_en, color: V[k].color};
  }
  function verdict(label, by, th, h, hist) {
    const v = {...V[label], label, by, confidence: by === 'operator' ? 1 : 0}, r = [], e = [];
    if (by === 'operator') { r.push('рішення оператора за відео денної і теплової камер дрона'); e.push("operator decision from the drone's day and thermal video"); }
    r.push(`тепловізор дрона: найгарячіша точка ${Math.round(th)} °C`); e.push(`drone thermal camera: hottest spot ${Math.round(th)} °C`);
    if (h) { r.push(`підказка системи була: ${h.title}`); e.push(`system hint was: ${h.title_en}`); }
    hist = hist || {};
    if (hist.recurrence === 'often') { r.push(`історія NASA: тут горіло ${hist.fire_days} днів за ${hist.years} різних років — типове місце спалювання`); e.push(`NASA history: ${hist.fire_days} fire days in ${hist.years} different years — a typical burning site`); }
    else if (hist.recurrence === 'first') { r.push('історія NASA: з 2001 року тут не було жодної гарячої точки — нетипово'); e.push('NASA history: no hotspot here since 2001 — unusual'); }
    v.reasons = r; v.reasons_en = e; return v;
  }

  function newMission(p) {
    const b = D.bases.find(x => x.id === p.base_id), dr = D.drone;
    seed = Math.abs(Math.round(p.lat * 1e4 + p.lon * 1e3)) % 2147483646 + 1;
    const m = {p, b, home: [b.lat, b.lon], target: [p.lat, p.lon], t: 0, phase: 'takeoff', pos: [b.lat, b.lon], alt: 0, speed: 0,
      battery: 100, leg: 0, inspect_t: 0, thermal: 12, peak: 0, hint: null, verdict: null, track: [[b.lat, b.lon]],
      history: {t: [], thermal: []}, peakT: D.thermal_peak[p.scenario] || 32};
    m.total = hav(b.lat, b.lon, p.lat, p.lon) * 1000; m.heading = bearing(b.lat, b.lon, p.lat, p.lon);
    return m;
  }
  function decide(m, label, by) {
    if (m.phase !== 'inspect' || m.verdict) return false;
    m.verdict = verdict(label, by, m.peak, m.hint, m.p.history); m.phase = 'return'; m.leg = 0; return true;
  }
  function eta(m) {
    const dr = D.drone, v = dr.speed, c = dr.climb, fa = dr.flight_alt, ia = dr.inspect_alt, back = (fa - ia) / c + m.total / v + fa / c;
    return Math.max(0, ({takeoff: (fa - m.alt) / c + m.total / v + (fa - ia) / c + dr.inspect_s + back,
      cruise: (m.total - m.leg) / v + (fa - ia) / c + dr.inspect_s + back, descend: (m.alt - ia) / c + dr.inspect_s + back,
      inspect: Math.max(dr.inspect_s - m.inspect_t, 0) + back, return: (m.total - m.leg) / v + fa / c + Math.max(fa - m.alt, 0) / c,
      land: m.alt / c, done: 0})[m.phase]);
  }
  function step(m, dt) {
    const dr = D.drone, v = dr.speed, c = dr.climb, fa = dr.flight_alt, ia = dr.inspect_alt;
    m.t += dt;
    switch (m.phase) {
      case 'takeoff': m.alt = Math.min(fa, m.alt + c * dt); m.speed = c; if (m.alt >= fa) { m.phase = 'cruise'; m.leg = 0; } break;
      case 'cruise': m.leg = Math.min(m.total, m.leg + v * dt); m.speed = v; m.pos = lerp(m.home, m.target, m.total ? m.leg / m.total : 1);
        m.heading = bearing(...m.home, ...m.target); if (m.leg >= m.total) m.phase = 'descend'; break;
      case 'descend': m.alt = Math.max(ia, m.alt - c * dt); m.speed = c; if (m.alt <= ia) { m.phase = 'inspect'; m.inspect_t = 0; } break;
      case 'inspect': {
        m.inspect_t += dt; m.speed = 6; const a = m.inspect_t / dr.inspect_s * 2 * Math.PI;
        m.pos = off(...m.target, 60 * Math.cos(a), 60 * Math.sin(a)); m.heading = (a * 180 / Math.PI + 90) % 360;
        if (m.inspect_t >= 8 && !m.hint) m.hint = hint(m.peak, m.p.history);
        if (m.inspect_t >= dr.operator_timeout_s) decide(m, 'none', 'timeout');
        break; }
      case 'return':
        if (m.alt < fa) { m.alt = Math.min(fa, m.alt + c * dt); m.speed = c; }
        else { m.leg = Math.min(m.total, m.leg + v * dt); m.speed = v; m.pos = lerp(m.target, m.home, m.total ? m.leg / m.total : 1);
          m.heading = bearing(...m.target, ...m.home); if (m.leg >= m.total) m.phase = 'land'; }
        break;
      case 'land': m.alt = Math.max(0, m.alt - c * dt); m.speed = c; m.pos = m.home; if (m.alt <= 0) { m.phase = 'done'; m.speed = 0; onDone(m); } break;
    }
    if (m.phase !== 'done') m.battery = Math.max(0, m.battery - dt / (dr.endurance_min * 60) * 100);
    const dist = hav(...m.pos, ...m.target) * 1000, vis = 1 / (1 + (Math.hypot(dist, m.alt) / 350) ** 2);
    m.thermal = Math.round((12 + (m.peakT - 12) * vis + gauss(1.2)) * 10) / 10;
    if (m.phase === 'descend' || m.phase === 'inspect') m.peak = Math.max(m.peak, m.thermal);
    m.history.t.push(Math.round(m.t * 10) / 10); m.history.thermal.push(m.thermal);
    if (m.history.t.length > 180) { m.history.t.shift(); m.history.thermal.shift(); }
    const last = m.track[m.track.length - 1];
    if (hav(...last, ...m.pos) > 0.05) m.track.push([+m.pos[0].toFixed(6), +m.pos[1].toFixed(6)]);
  }
  function onDone(m) {
    const v = m.verdict, now = hhmm();
    results[m.p.id] = v;
    if (v && v.label === 'fire') alarm = {place_id: m.p.id, title: v.title, title_en: v.title_en, color: v.color, lat: m.p.lat, lon: m.p.lon,
      base_name: m.b.name, at: now, acknowledged: false, route: m.p.route};
    log.unshift({at: now, place_id: m.p.id, base_name: m.b.name, lat: m.p.lat, lon: m.p.lon, label: v && v.label, by: v && v.by,
      title: v ? v.title : '—', title_en: v ? v.title_en : '—', color: v ? v.color : '#9FAA94',
      flight_min: Math.round(m.t / 6) / 10, battery_end_pct: Math.round(m.battery * 10) / 10});
  }
  function advance() {
    const now = performance.now();
    if (!lastTick) lastTick = now;
    let dt = Math.min(2, (now - lastTick) / 1000); lastTick = now;
    if (!mission || mission.phase === 'done') return;
    const k = mission.phase === 'inspect' ? 1 : D.speedup;
    let left = dt * k; while (left > 0 && mission.phase !== 'done') { const s = Math.min(left, 1); step(mission, s); left -= s; }
  }
  const busy = () => mission && mission.phase !== 'done';
  function dispatch(id) {
    if (busy()) return {ok: false, error: 'Дрон уже в польоті. Дочекайся повернення. / The drone is already flying.'};
    const p = D.places.find(x => x.id === id);
    if (!p) return {ok: false, error: 'Такої точки немає.'};
    if (p.static_source) return {ok: false, error: 'Це відоме промислове джерело тепла (NASA type 2) — дрон не потрібен.'};
    if (!p.base_id) return {ok: false, error: `Точка за ${p.dist_km} км від найближчої бази — поза радіусом.`};
    if (p.battery_ok === false) return {ok: false, error: 'Не вистачить батареї.'};
    mission = newMission(p); return {ok: true};
  }
  let autoAt = 0;
  function autoStart() {          // demo opens straight into a flight: highest-priority reachable hotspot
    if (mission || autoAt < 0) return;
    if (!autoAt) { autoAt = performance.now() + 2500; return; }
    if (performance.now() < autoAt) return;
    autoAt = -1;
    const rank = {high: 0, normal: 1, low: 2};
    const todo = D.places.filter(p => p.base_id && p.battery_ok && !p.static_source && p.scenario === 'fire')
      .sort((a, b) => (rank[a.priority] ?? 1) - (rank[b.priority] ?? 1) || a.dist_km - b.dist_km);
    if (todo.length) mission = newMission(todo[0]);
  }
  function state() {
    autoStart();
    advance();
    const m = mission;
    const places = D.places.map(p => {
      const q = {...p};
      q.status = m && m.p.id === p.id && m.phase !== 'done' ? 'flying' : p.static_source ? 'industrial' : results[p.id] ? 'checked' : p.base_id ? 'new' : 'out_of_range';
      q.verdict = results[p.id] || null; return q;
    });
    const busyBase = busy() ? m.b.id : null;
    let ms = null;
    if (m) {
      const dist = hav(...m.pos, ...m.target) * 1000;
      ms = {place_id: m.p.id, base_id: m.b.id, base_name: m.b.name, phase: m.phase, phase_label: PH.find(x => x[0] === m.phase)[1],
        phases: PH.map(([id, l, le]) => ({id, label: l, label_en: le})), t_sim_s: Math.round(m.t * 10) / 10, eta_s: Math.round(eta(m)),
        lat: m.pos[0], lon: m.pos[1], target: m.target, alt_m: Math.round(m.alt * 10) / 10, speed_ms: m.speed, heading_deg: m.heading,
        battery_pct: Math.round(m.battery * 10) / 10, dist_to_target_m: Math.round(dist), dist_from_base_m: Math.round(hav(...m.pos, ...m.home) * 1000),
        track: m.track.slice(-400), route: [m.home, m.target], scenario: m.p.scenario, thermal_c: m.thermal, thermal_peak_c: m.peak,
        history: m.history, hint: m.hint, waiting_operator: m.phase === 'inspect' && !m.verdict,
        operator_left_s: m.phase === 'inspect' ? Math.max(0, Math.round(D.drone.operator_timeout_s - m.inspect_t)) : null,
        auto_operator: false, verdict: m.verdict};
    }
    return {now: new Date().toISOString().slice(0, 19), source: 'demo', source_note: D.day, updated_at: D.day.split('-').reverse().join('.'),
      speedup: D.speedup, range_km: D.range_km, bases: D.bases.map(b => ({...b, status: b.id === busyBase ? 'busy' : 'ready'})),
      places, mission: ms, alarm, log, season: null, static_sources: D.static_sources, operator_timeout_s: D.drone.operator_timeout_s, demo: true};
  }
  const J = (o, code = 200) => new Response(JSON.stringify(o), {status: code, headers: {'Content-Type': 'application/json'}});
  ready = Promise.all([realFetch('data/demo.json').then(r => r.json()), realFetch('data/calendar.json').then(r => r.json())])
    .then(([d, c]) => { D = d; CAL = c; });

  window.fetch = async function (url, opt) {
    const u = typeof url === 'string' ? url : url.url;
    if (!u.startsWith('/api/')) return realFetch(url, opt);
    await ready;
    const body = opt && opt.body ? JSON.parse(opt.body) : {};
    const route = u.split('?')[0];
    if (route === '/api/state') return J(state());
    if (route === '/api/calendar') return J(CAL);
    if (route === '/api/dispatch') return J(dispatch(String(body.place_id || '')));
    if (route === '/api/decide') { advance(); return J(mission && decide(mission, body.label, 'operator') ? {ok: true} : {ok: false, error: 'Зараз дрон не над точкою.'}); }
    if (route === '/api/alarm/ack') { if (alarm) alarm.acknowledged = true; return J({ok: true}); }
    if (route === '/api/refresh') return J({ok: false, error: 'Демо: записаний день NASA FIRMS. Живі дані — у повній версії (python server.py). / Demo uses a recorded NASA day.'});
    return J({ok: false}, 404);
  };
  window.ZO_DEMO = true;
})();
