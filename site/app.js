/* League Record Book */

let D = null, F = {}, activeSeason = null, ledgerScope = 'active',
    activeMgr = null, chartFocus = null, weeksKind = 'best';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const pct = n => Math.round(n * 100) + '%';
const mgr = id => F[id]?.manager ?? 'Unknown';
const team = id => F[id]?.team_name ?? 'Unknown';
const rec = f => `${f.wins}-${f.losses}` + (f.ties ? `-${f.ties}` : '');
const sgn = n => (n > 0 ? '+' : '') + n.toFixed(1);
const wk = w => `${w.year} W${w.week}`;

/* ---------------------------------------------------------------- boot */

async function boot() {
  try {
    const r = await fetch('data/league.json', { cache: 'no-store' });
    if (!r.ok) throw new Error(r.status);
    D = await r.json();
  } catch (e) {
    $('#loading').innerHTML = 'No league data. Run <code class="mono">python3 fetch_data.py</code> first.';
    return;
  }
  D.franchises.forEach(f => { F[f.id] = f; });
  $('#loading').hidden = true;

  const L = D.league;
  $('#league-name').textContent = L.name;
  $('#ident-mark').textContent = `${L.first_season}\u2013${String(L.latest_season).slice(2)}`;
  $('#league-sub').textContent =
    `${L.years} seasons \u00b7 ${(D.total_games || 0).toLocaleString()} games \u00b7 ${D.franchises.length} franchises`;
  $('#since-year').textContent = L.first_season;
  document.title = `${L.name} \u2014 Record Book`;

  $('#foot-line').textContent = `Pulled from ESPN ${new Date(D.generated_at).toLocaleString()}`;
  $('#foot-model').textContent =
    `Win probability = ${pct(D.model.espn_weight)} ESPN projection, ${pct(1 - D.model.espn_weight)} Elo. ` +
    `Elo K=${D.model.elo_k}, ${pct(D.model.regression)} regression between seasons. Margin sigma ${D.model.margin_sigma}.`;

  renderWeek(); renderTrophy(); renderAllTime(); renderManagers(); renderSeasons(); renderRecords();

  $$('#tabs .tab').forEach(t => t.addEventListener('click', () => show(t.dataset.view)));
  show('week');
}

function show(view) {
  $$('#tabs .tab').forEach(t => t.classList.toggle('is-active', t.dataset.view === view));
  $$('.view').forEach(v => { v.hidden = v.id !== `view-${view}`; });
  if (view === 'week') requestAnimationFrame(fillBars);
  window.scrollTo({ top: 0, behavior: 'auto' });
}
const fillBars = () => $$('.mu-bar span').forEach(b => { b.style.width = b.dataset.w; });

function goManager(id) {
  activeMgr = id;
  show('managers');
  renderMgrDetail();
  $$('#mgr-list .mgr-btn').forEach(b => b.classList.toggle('is-on', b.dataset.id === id));
}

/* ------------------------------------------------------------ this week */

function h2hLine(a, b) {
  const r = D.head_to_head?.[a]?.[b];
  if (!r || !(r.w + r.l + r.t)) return 'First ever meeting';
  return `All-time <b>${esc(mgr(a))} ${r.w}-${r.l}${r.t ? '-' + r.t : ''}</b>`;
}

function renderWeek() {
  const C = D.current;

  $('#week-eyebrow').textContent =
    C.state === 'playoffs' ? `${C.year} Playoffs` :
    C.state === 'preseason' ? `${C.year} Preseason` :
    C.state === 'offseason' ? 'Offseason' : `${C.year} \u00b7 Week ${C.week}`;
  $('#week-title').textContent = C.state === 'offseason' ? 'No games scheduled' : 'Projected Winners';
  $('#week-note').textContent = C.note || '';

  const box = $('#matchups');
  if (!C.matchups.length) {
    box.innerHTML = `<p class="view-note">Nothing scheduled yet. Rerun the fetch once ESPN opens the season.</p>`;
  } else {
    box.innerHTML = C.matchups.map(m => {
      const hf = m.home_wp >= m.away_wp;
      const side = (fid, proj, wp, fav) => {
        const f = F[fid] || {};
        return `<div class="mu-side ${fav ? 'mu-fav' : ''}">
          <div class="mu-name">
            <div class="mu-team">${esc(team(fid))}</div>
            <div class="mu-mgr">${esc(mgr(fid))}<span class="rec"> ${f.wins != null ? rec(f) : ''} all-time</span></div>
          </div>
          <div class="mu-proj">${proj == null ? '\u2014' : proj.toFixed(1)}</div>
          <div class="mu-wp">${pct(wp)}</div>
        </div>`;
      };
      const margin = (m.home_proj != null && m.away_proj != null)
        ? Math.abs(m.home_proj - m.away_proj).toFixed(1) : null;
      const fav = hf ? mgr(m.home) : mgr(m.away);
      return `<article class="matchup ${m.playoff ? 'matchup--playoff' : ''}">
        ${side(m.away, m.away_proj, m.away_wp, !hf)}
        <div class="mu-bar"><span data-w="${(m.home_wp * 100).toFixed(1)}%"></span></div>
        ${side(m.home, m.home_proj, m.home_wp, hf)}
        <div class="mu-foot">
          <span>${margin ? `<b>${esc(fav)}</b> by ${margin} projected` : `<b>${esc(fav)}</b> favored on rating`}</span>
          <span>${h2hLine(m.home, m.away)}</span>
        </div>
      </article>`;
    }).join('');
  }

  $('#power').innerHTML = (C.power || []).map(p =>
    `<li class="${p.rank <= 3 ? 'top' : ''}" onclick="goManager('${p.franchise}')">
      <span class="rk">${p.rank}</span><span class="nm">${esc(mgr(p.franchise))}</span>
      <span class="el">${p.elo.toFixed(0)}</span></li>`).join('');

  $('#cur-standings').innerHTML = (C.standings || []).map(s =>
    `<tr onclick="goManager('${s.franchise}')"><td class="p">${s.place}</td>
      <td>${esc(mgr(s.franchise))}</td>
      <td class="r">${s.wins}-${s.losses}${s.ties ? '-' + s.ties : ''}</td></tr>`).join('')
    || '<tr><td class="p">\u2014</td><td>No standings yet</td></tr>';

  requestAnimationFrame(fillBars);
}

/* --------------------------------------------------------- trophy case */

function renderTrophy() {
  const T = D.trophy_case;
  if (!T?.cabinet?.length) return;

  $('#cabinet').innerHTML = T.cabinet.map(c => {
    const f = F[c.franchise] || {};
    const gold = '\u25c6'.repeat(c.titles.length);
    const silver = '\u25b2'.repeat(c.crowns.length);
    const bare = !c.titles.length && !c.crowns.length;
    return `<article class="cab ${c.titles.length ? 'cab--champ' : ''}" onclick="goManager('${c.franchise}')">
      <div class="cab-hw">
        ${gold ? `<span class="tk tk-gold">${gold}</span>` : ''}
        ${silver ? `<span class="tk tk-silver">${silver}</span>` : ''}
        ${bare ? '<span class="tk tk-none">empty shelf</span>' : ''}
      </div>
      <h3 class="cab-name">${esc(mgr(c.franchise))}</h3>
      <p class="cab-team">${esc(team(c.franchise))}</p>
      <dl class="cab-rows">
        <div><dt>Titles</dt><dd class="${c.titles.length ? 'gold' : 'nil'}">${c.titles.length
          ? c.titles.join(', ') : '\u2013'}</dd></div>
        <div><dt>Scoring crowns</dt><dd class="${c.crowns.length ? 'silver' : 'nil'}">${c.crowns.length
          ? c.crowns.join(', ') : '\u2013'}</dd></div>
        <div><dt>Runner-up</dt><dd class="${c.runner_ups.length ? '' : 'nil'}">${c.runner_ups.length
          ? c.runner_ups.join(', ') : '\u2013'}</dd></div>
        ${c.doubles.length ? `<div><dt>Doubles</dt><dd class="dbl">${c.doubles.join(', ')}</dd></div>` : ''}
      </dl>
    </article>`;
  }).join('');

  const doubles = T.years.filter(y => y.double);
  $('#double-count').textContent = doubles.length
    ? `${doubles.length} double${doubles.length === 1 ? '' : 's'} in ${T.years.length} seasons`
    : `No one has ever pulled off the double in ${T.years.length} seasons`;

  $('#trophy-years').innerHTML =
    `<thead><tr><th>Year</th><th>Champion</th><th>Runner-up</th><th>Scoring crown</th>
      <th>Points</th><th>By</th><th>Champ finished</th></tr></thead>
     <tbody>${T.years.map(y => `<tr class="${y.double ? 'is-double' : ''}">
       <td class="rank">${y.year}${y.double ? ' <span class="dbl-tag">double</span>' : ''}</td>
       <td class="who" onclick="goManager('${y.champion}')">
         <div class="who-mgr gold">${y.champion ? esc(mgr(y.champion)) : '\u2013'}</div></td>
       <td class="who">${y.runner_up ? esc(mgr(y.runner_up)) : '\u2013'}</td>
       <td class="who" onclick="goManager('${y.crown}')">
         <div class="who-mgr silver">${esc(mgr(y.crown))}</div></td>
       <td>${y.crown_points.toLocaleString()}</td>
       <td class="${y.crown_margin > 0 ? '' : 'nil'}">${y.crown_margin > 0
         ? '+' + y.crown_margin.toFixed(1) : '\u2013'}</td>
       <td>${y.champion_rank ? `${y.champion_rank}${y.champion_rank === 1 ? 'st' :
         y.champion_rank === 2 ? 'nd' : y.champion_rank === 3 ? 'rd' : 'th'} in scoring` : '\u2013'}</td>
     </tr>`).join('')}</tbody>`;
}

/* -------------------------------------------------------------- all time */

function ledgerRows() {
  return D.franchises.filter(f => ledgerScope === 'all' || f.active);
}

function renderLedger() {
  const cols = ['', 'Franchise', 'Titles', 'W', 'L', 'Win%', 'All-Play', 'Luck', 'PF', 'PPG', 'Best', 'Elo', 'Yrs'];
  const rows = ledgerRows().map((f, i) => {
    const lk = f.luck ?? 0;
    const lc = lk > 2 ? 'lk-up' : lk < -2 ? 'lk-dn' : '';
    return `<tr onclick="goManager('${f.id}')">
      <td class="rank">${i + 1}</td>
      <td class="who"><div class="who-mgr">${esc(f.manager)}</div>
        <div class="who-team">${esc(f.team_name)}${f.active ? '' : ' \u00b7 inactive'}</div></td>
      <td><span class="rings ${f.titles ? '' : 'none'}">${f.titles ? '\u25c6'.repeat(Math.min(f.titles, 8)) : '\u2013'}</span> ${f.titles || ''}</td>
      <td>${f.wins}</td><td>${f.losses}</td>
      <td class="pct">${f.win_pct.toFixed(3).replace(/^0/, '')}</td>
      <td>${f.all_play_pct != null ? f.all_play_pct.toFixed(3).replace(/^0/, '') : '\u2013'}</td>
      <td class="${lc}">${f.luck != null ? sgn(f.luck) : '\u2013'}</td>
      <td>${Math.round(f.points_for).toLocaleString()}</td>
      <td>${f.ppg.toFixed(1)}</td>
      <td>${f.best_finish ?? '\u2013'}</td>
      <td>${f.elo.toFixed(0)}</td>
      <td>${f.seasons}</td></tr>`;
  }).join('');
  $('#ledger').innerHTML =
    `<thead><tr>${cols.map(c => `<th>${c}</th>`).join('')}</tr></thead><tbody>${rows}</tbody>`;
}

function renderAllTime() {
  renderLedger();
  $$('#active-toggle .tgl').forEach(b => b.addEventListener('click', () => {
    ledgerScope = b.dataset.scope;
    $$('#active-toggle .tgl').forEach(x => x.classList.toggle('is-on', x === b));
    renderLedger();
  }));
  renderEloChart();
  renderMatrix();
  renderRivalries();
}

/* Elo arc: 20 seasons, every franchise, one SVG. */
const PAL = ['#d0a045', '#4e9c6b', '#c0584b', '#5b8fd0', '#b07cc6', '#4fb0a5',
             '#d97f4a', '#8fa63f', '#c85f92', '#6f7fd0', '#a3894f', '#59a8c9'];

function renderEloChart() {
  const E = D.elo_by_season || {};
  const fs = D.franchises.filter(f => (E[f.id] || []).length >= 3);
  if (!fs.length) { $('#chart-wrap')?.remove(); return; }

  const years = [...new Set(Object.values(E).flat().map(p => p.year))].sort((a, b) => a - b);
  const vals = Object.values(E).flat().map(p => p.elo);
  const y0 = Math.floor(Math.min(...vals) / 25) * 25, y1 = Math.ceil(Math.max(...vals) / 25) * 25;
  const W = 1000, H = 340, mL = 42, mR = 12, mT = 12, mB = 26;
  const x = yr => mL + (years.indexOf(yr) / Math.max(years.length - 1, 1)) * (W - mL - mR);
  const y = v => mT + (1 - (v - y0) / (y1 - y0)) * (H - mT - mB);

  const grid = [];
  for (let v = y0; v <= y1; v += 50) {
    grid.push(`<line x1="${mL}" x2="${W - mR}" y1="${y(v)}" y2="${y(v)}" class="gl"/>
      <text x="${mL - 8}" y="${y(v) + 3}" class="gt" text-anchor="end">${v}</text>`);
  }
  years.forEach((yr, i) => {
    if (i % Math.ceil(years.length / 10) === 0 || i === years.length - 1)
      grid.push(`<text x="${x(yr)}" y="${H - 8}" class="gt" text-anchor="middle">${String(yr).slice(2)}</text>`);
  });

  const lines = fs.map((f, i) => {
    const pts = (E[f.id] || []).map(p => `${x(p.year).toFixed(1)},${y(p.elo).toFixed(1)}`).join(' ');
    const dim = chartFocus && chartFocus !== f.id;
    return `<polyline points="${pts}" fill="none" stroke="${PAL[i % PAL.length]}"
      stroke-width="${chartFocus === f.id ? 2.6 : 1.5}" stroke-linejoin="round" stroke-linecap="round"
      opacity="${dim ? .12 : (chartFocus === f.id ? 1 : .78)}"/>`;
  }).join('');

  $('#elo-chart').innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="chart" preserveAspectRatio="xMidYMid meet">
    <line x1="${mL}" x2="${W - mR}" y1="${y(1500)}" y2="${y(1500)}" class="gl gl--mid"/>
    ${grid.join('')}${lines}</svg>`;

  $('#chart-key').innerHTML = fs.map((f, i) =>
    `<button class="ck ${chartFocus === f.id ? 'is-on' : ''}" data-id="${f.id}">
      <i style="background:${PAL[i % PAL.length]}"></i>${esc(f.manager)}</button>`).join('');
  $$('#chart-key .ck').forEach(b => b.addEventListener('click', () => {
    chartFocus = chartFocus === b.dataset.id ? null : b.dataset.id;
    renderEloChart();
  }));
}

function h2hColor(p, games) {
  const conf = Math.min(games / 12, 1), t = (p - .5) * 2;
  const tgt = t >= 0 ? [78, 156, 107] : [192, 88, 75], base = [35, 48, 60];
  const k = Math.abs(t) * .85 * conf;
  return `rgb(${base.map((b, i) => Math.round(b + (tgt[i] - b) * k)).join(',')})`;
}

function renderMatrix() {
  const fs = D.franchises.filter(f => f.active).sort((a, b) => b.win_pct - a.win_pct);
  const head = `<thead><tr><th class="corner">vs \u2192</th>${
    fs.map(f => `<th>${esc(f.manager.slice(0, 4))}</th>`).join('')}</tr></thead>`;
  const rows = fs.map(a => {
    const cells = fs.map(b => {
      if (a.id === b.id) return '<td class="self"></td>';
      const r = D.head_to_head?.[a.id]?.[b.id];
      const g = r ? r.w + r.l + r.t : 0;
      if (!g) return '<td class="cell empty">\u2013</td>';
      const p = (r.w + .5 * r.t) / g;
      const lbl = `${r.w}-${r.l}${r.t ? '-' + r.t : ''}`;
      const tip = `${a.manager} vs ${b.manager}: ${lbl}, averaging ${(r.pf / g).toFixed(1)} to ${(r.pa / g).toFixed(1)}`;
      return `<td class="cell" style="background:${h2hColor(p, g)}" title="${esc(tip)}">${lbl}</td>`;
    }).join('');
    return `<tr><td class="row-lbl" onclick="goManager('${a.id}')">${esc(a.manager)}</td>${cells}</tr>`;
  }).join('');
  $('#matrix').innerHTML = head + `<tbody>${rows}</tbody>`;
}

function renderRivalries() {
  const R = D.rivalries;
  if (!R) return;
  const card = (title, hint, list, fmt) => `<div class="panel">
    <h3 class="panel-title">${title}</h3><p class="panel-hint">${hint}</p>
    ${list.map(p => `<div class="riv" onclick="goManager('${p.a}')">
      <div class="riv-n">${esc(mgr(p.a))} <span class="riv-v">v</span> ${esc(mgr(p.b))}</div>
      <div class="riv-s">${fmt(p)}</div></div>`).join('') || '<p class="panel-hint">Not enough games.</p>'}
  </div>`;

  $('#rivalries').innerHTML =
    card('Dead Even', 'The series nobody owns', R.deadlocked,
      p => `${p.a_wins}-${p.b_wins}${p.ties ? '-' + p.ties : ''} \u00b7 ${p.games} games`) +
    card('Owned', 'One-sided beyond argument', R.lopsided,
      p => `${p.a_wins}-${p.b_wins}${p.ties ? '-' + p.ties : ''} \u00b7 ${p.games} games`) +
    card('Most Played', 'The matchups you cannot escape', R.most_played,
      p => `${p.games} games \u00b7 ${p.a_wins}-${p.b_wins}`);
}

/* ------------------------------------------------------------- managers */

function renderManagers() {
  const dupes = D.suspected_duplicates || [];
  if (dupes.length) {
    $('#dupe-note').hidden = false;
    $('#dupe-note').innerHTML =
      `<b>Possibly the same person.</b> The script merges identical names and common nicknames
       automatically, but these were too close to call. If any pair is one human, add them to
       <code>aliases.json</code> and rerun the fetch.
       <ul>${dupes.map(d => `<li><span class="mono">["${esc(d.a)}", "${esc(d.b)}"]</span>
         <span class="dn-why">${esc(d.reason)}</span></li>`).join('')}</ul>`;
  }
  const fs = [...D.franchises].sort((a, b) =>
    (b.active - a.active) || (b.seasons - a.seasons) || (b.titles - a.titles));
  $('#mgr-list').innerHTML = fs.map(f =>
    `<button class="mgr-btn" data-id="${f.id}">
      <span class="mb-n">${esc(f.manager)}</span>
      <span class="mb-m">${f.seasons} yr${f.seasons === 1 ? '' : 's'}${f.titles ? ` \u00b7 ${f.titles}\u25c6` : ''}${f.active ? '' : ' \u00b7 gone'}</span>
    </button>`).join('');
  $$('#mgr-list .mgr-btn').forEach(b =>
    b.addEventListener('click', () => goManager(b.dataset.id)));
  activeMgr = fs[0]?.id;
  renderMgrDetail();
  $$('#mgr-list .mgr-btn').forEach(b => b.classList.toggle('is-on', b.dataset.id === activeMgr));
}

function renderMgrDetail() {
  const f = F[activeMgr];
  if (!f) return;
  const cab = (D.trophy_case?.cabinet || []).find(c => c.franchise === f.id) || {};
  const crowns = cab.crowns || [];

  const seasonRows = D.seasons.filter(s => s.standings.some(t => t.franchise === f.id))
    .sort((a, b) => b.year - a.year).map(s => {
      const t = s.standings.find(t => t.franchise === f.id);
      const lk = (f.luck_per_season || []).find(x => x.year === s.year);
      return `<tr>
        <td class="rank">${s.year}</td>
        <td class="who"><span class="mono">${t.wins}-${t.losses}${t.ties ? '-' + t.ties : ''}</span></td>
        <td>${Math.round(t.points_for).toLocaleString()}</td>
        <td class="${lk && lk.luck > 1 ? 'lk-up' : lk && lk.luck < -1 ? 'lk-dn' : ''}">${lk ? sgn(lk.luck) : '\u2013'}</td>
        <td>${t.final === 1 ? '<span class="rings">\u25c6</span> 1st' : t.final === 2 ? '2nd' : t.final + 'th'}</td>
      </tr>`;
    }).join('');

  // best and worst weeks for this manager
  const mine = [];
  D.seasons.forEach(s => s.weeks.forEach(w => w.matchups.forEach(m => {
    if (m.a === f.id) mine.push({ sc: m.a_score, opp: m.b, osc: m.b_score, year: s.year, week: w.week });
    if (m.b === f.id) mine.push({ sc: m.b_score, opp: m.a, osc: m.a_score, year: s.year, week: w.week });
  })));
  mine.sort((a, b) => b.sc - a.sc);
  const hi = mine[0], lo = mine[mine.length - 1];

  const opps = Object.entries(D.head_to_head?.[f.id] || {})
    .map(([id, r]) => ({ id, ...r, g: r.w + r.l + r.t }))
    .filter(o => o.g > 0 && F[o.id])
    .sort((a, b) => b.g - a.g);
  const best = [...opps].filter(o => o.g >= 5).sort((a, b) => (b.w / b.g) - (a.w / a.g))[0];
  const worst = [...opps].filter(o => o.g >= 5).sort((a, b) => (a.w / a.g) - (b.w / b.g))[0];
  const sd = f.streak_detail || {};

  $('#mgr-detail').innerHTML = `
    <div class="md-head">
      <div>
        <p class="eyebrow">${f.seasons} seasons \u00b7 ${f.first_season}\u2013${f.last_season}${f.active ? '' : ' \u00b7 no longer in the league'}</p>
        <h3 class="md-name">${esc(f.manager)}</h3>
        <p class="md-team">${esc(f.team_name)}${f.aliases.length > 1 ? ` \u00b7 also known as ${esc(f.aliases.slice(0, 3).filter(a => a !== f.team_name).join(', '))}` : ''}</p>
      </div>
    </div>

    <div class="md-stats">
      <div><span class="md-n">${rec(f)}</span><span class="md-k">all-time record</span></div>
      <div><span class="md-n">${f.titles}</span><span class="md-k">championship${f.titles === 1 ? '' : 's'}</span></div>
      <div><span class="md-n ${f.luck > 2 ? 'lk-up' : f.luck < -2 ? 'lk-dn' : ''}">${f.luck != null ? sgn(f.luck) : '\u2013'}</span><span class="md-k">career luck</span></div>
      <div><span class="md-n">${f.elo.toFixed(0)}</span><span class="md-k">rating (peak ${f.elo_peak.toFixed(0)})</span></div>
      <div><span class="md-n">${f.ppg.toFixed(1)}</span><span class="md-k">points per game</span></div>
      <div><span class="md-n silver">${crowns.length}</span><span class="md-k">scoring crown${crowns.length === 1 ? '' : 's'}</span></div>
      <div><span class="md-n">${f.best_win_streak || 0}</span><span class="md-k">longest win streak</span></div>
      <div><span class="md-n">${f.worst_loss_streak || 0}</span><span class="md-k">longest skid</span></div>
    </div>

    ${f.championships.length ? `<p class="md-titles"><span class="tk tk-gold">${'\u25c6'.repeat(f.championships.length)}</span>
      Champion in ${f.championships.join(', ')}</p>` : ''}
    ${crowns.length ? `<p class="md-titles"><span class="tk tk-silver">${'\u25b2'.repeat(crowns.length)}</span>
      Led the league in scoring in ${crowns.join(', ')}</p>` : ''}

    <div class="md-cols">
      <div class="panel">
        <h3 class="panel-title">Season by Season</h3>
        <div class="table-scroll" style="border:0">
          <table class="ledger" style="min-width:0">
            <thead><tr><th>Year</th><th>Record</th><th>PF</th><th>Luck</th><th>Finish</th></tr></thead>
            <tbody>${seasonRows}</tbody></table>
        </div>
      </div>

      <div class="md-side">
        <div class="panel">
          <h3 class="panel-title">Career Highs and Lows</h3>
          ${hi ? `<div class="riv"><div class="riv-n">Best week ever</div>
            <div class="riv-s">${hi.sc.toFixed(1)} \u00b7 ${hi.year} W${hi.week} vs ${esc(mgr(hi.opp))}</div></div>` : ''}
          ${lo ? `<div class="riv"><div class="riv-n">Worst week ever</div>
            <div class="riv-s">${lo.sc.toFixed(1)} \u00b7 ${lo.year} W${lo.week} vs ${esc(mgr(lo.opp))}</div></div>` : ''}
          ${sd.win ? `<div class="riv"><div class="riv-n">Longest win streak</div>
            <div class="riv-s">${sd.win.n} games \u00b7 from ${wk(sd.win.from)}</div></div>` : ''}
          ${sd.loss ? `<div class="riv"><div class="riv-n">Longest losing streak</div>
            <div class="riv-s">${sd.loss.n} games \u00b7 from ${wk(sd.loss.from)}</div></div>` : ''}
        </div>

        <div class="panel">
          <h3 class="panel-title">Who They Beat, Who Beats Them</h3>
          ${best ? `<div class="riv" onclick="goManager('${best.id}')"><div class="riv-n">Owns ${esc(mgr(best.id))}</div>
            <div class="riv-s lk-up">${best.w}-${best.l}${best.t ? '-' + best.t : ''}</div></div>` : ''}
          ${worst ? `<div class="riv" onclick="goManager('${worst.id}')"><div class="riv-n">Owned by ${esc(mgr(worst.id))}</div>
            <div class="riv-s lk-dn">${worst.w}-${worst.l}${worst.t ? '-' + worst.t : ''}</div></div>` : ''}
        </div>

        <div class="panel">
          <h3 class="panel-title">Full Head-to-Head</h3>
          <table class="mini">${opps.map(o => `<tr onclick="goManager('${o.id}')">
            <td>${esc(mgr(o.id))}</td>
            <td class="r ${o.w > o.l ? 'lk-up' : o.l > o.w ? 'lk-dn' : ''}">${o.w}-${o.l}${o.t ? '-' + o.t : ''}</td>
          </tr>`).join('')}</table>
        </div>
      </div>
    </div>`;
}

/* -------------------------------------------------------------- seasons */

function renderSeasons() {
  const ss = [...D.seasons].reverse();
  $('#ribbon').innerHTML = ss.map(s =>
    `<button class="rib" data-year="${s.year}">
      <div class="rib-yr">${s.year}</div>
      <div class="rib-champ">${s.champion ? esc(mgr(s.champion)) : '\u2013'}</div></button>`).join('');
  $$('#ribbon .rib').forEach(b => b.addEventListener('click', () => selectSeason(+b.dataset.year)));
  selectSeason(D.league.latest_season);
}

function selectSeason(year) {
  activeSeason = year;
  $$('#ribbon .rib').forEach(b => b.classList.toggle('is-active', +b.dataset.year === year));
  const s = D.seasons.find(x => x.year === year);
  if (!s) return;

  const standings = `<div class="panel">
    <h3 class="panel-title">${year} Final Standings</h3>
    <p class="panel-hint">${s.team_count} teams \u00b7 ${s.reg_season_weeks} week regular season</p>
    <div class="table-scroll" style="border:0"><table class="ledger" style="min-width:0">
      <thead><tr><th></th><th>Franchise</th><th>W</th><th>L</th><th>PF</th><th>PA</th></tr></thead>
      <tbody>${s.standings.map(t => `<tr onclick="goManager('${t.franchise}')">
        <td class="rank">${t.final}${t.final === 1 ? ' <span class="rings">\u25c6</span>' : ''}</td>
        <td class="who"><div class="who-mgr">${esc(mgr(t.franchise))}</div>
          <div class="who-team">${esc(t.team_name)}</div></td>
        <td>${t.wins}</td><td>${t.losses}</td>
        <td>${Math.round(t.points_for).toLocaleString()}</td>
        <td>${Math.round(t.points_against).toLocaleString()}</td></tr>`).join('')}</tbody>
    </table></div></div>`;

  const scores = s.weeks.length ? `<div class="scores">${s.weeks.map(w => `
    <div class="wk"><div class="wk-h ${w.playoff ? 'po' : ''}">${w.playoff ? 'Playoffs \u00b7 ' : ''}Week ${w.week}</div>
      ${w.matchups.map(m => {
        const aw = m.a_score > m.b_score, bw = m.b_score > m.a_score;
        return `<div class="gm">
          <span class="t r ${aw ? 'w' : 'l'}">${esc(mgr(m.a))}</span>
          <span class="s"><span class="${aw ? 'w' : 'l'}">${m.a_score.toFixed(1)}</span> &ndash;
            <span class="${bw ? 'w' : 'l'}">${m.b_score.toFixed(1)}</span></span>
          <span class="t ${bw ? 'w' : 'l'}">${esc(mgr(m.b))}</span></div>`;
      }).join('')}</div>`).join('')}</div>`
    : `<div class="panel"><p class="view-note">No weekly box scores for ${year}.</p></div>`;

  $('#season-detail').innerHTML = standings + scores;
}

/* -------------------------------------------------------------- records */

function renderRecords() {
  const R = D.records, cards = [];
  const card = (label, value, who, ctx, fid) => cards.push(
    `<article class="rec-card" ${fid ? `onclick="goManager('${fid}')"` : ''}>
      <p class="rec-label">${esc(label)}</p><p class="rec-value">${esc(value)}</p>
      <p class="rec-who">${esc(who)}</p><p class="rec-ctx">${esc(ctx)}</p></article>`);

  if (R.highest_score) { const r = R.highest_score;
    card('Highest single week', r.score.toFixed(1), mgr(r.franchise),
      `${r.year} Week ${r.week} \u00b7 beat ${mgr(r.opponent)} ${r.opp_score.toFixed(1)}`, r.franchise); }
  if (R.lowest_score) { const r = R.lowest_score;
    card('Lowest single week', r.score.toFixed(1), mgr(r.franchise),
      `${r.year} Week ${r.week} \u00b7 against ${mgr(r.opponent)}`, r.franchise); }
  if (R.biggest_blowout) { const r = R.biggest_blowout;
    card('Biggest blowout', `+${r.margin.toFixed(1)}`, mgr(r.winner),
      `${r.year} Week ${r.week} \u00b7 ${r.score} over ${mgr(r.loser)}`, r.winner); }
  if (R.closest_game) { const r = R.closest_game;
    card('Closest game', r.margin.toFixed(2), mgr(r.winner),
      `${r.year} Week ${r.week} \u00b7 ${r.score} over ${mgr(r.loser)}`, r.winner); }
  if (R.highest_combined) { const r = R.highest_combined;
    card('Highest scoring game', r.total.toFixed(1), `${mgr(r.a)} vs ${mgr(r.b)}`,
      `${r.year} Week ${r.week} \u00b7 ${r.score}`); }
  if (R.best_regular_season) { const r = R.best_regular_season;
    card('Best regular season', r.record, mgr(r.franchise),
      `${r.year} \u00b7 ${Math.round(r.points_for).toLocaleString()} points for`, r.franchise); }

  const most = D.franchises[0];
  if (most?.titles) card('Most championships', String(most.titles), most.manager,
    most.championships.join(', '), most.id);

  const peak = [...D.franchises].sort((a, b) => b.elo_peak - a.elo_peak)[0];
  if (peak) card('Highest peak rating', peak.elo_peak.toFixed(0), peak.manager,
    `Currently ${peak.elo.toFixed(0)}`, peak.id);

  const lucky = [...D.franchises].filter(f => f.luck != null).sort((a, b) => b.luck - a.luck)[0];
  if (lucky) card('Luckiest career', sgn(lucky.luck), lucky.manager,
    `${lucky.wins} actual wins, ${lucky.expected_wins} expected`, lucky.id);

  const cursed = [...D.franchises].filter(f => f.luck != null).sort((a, b) => a.luck - b.luck)[0];
  if (cursed) card('Most robbed by the schedule', sgn(cursed.luck), cursed.manager,
    `${cursed.wins} actual wins, ${cursed.expected_wins} expected`, cursed.id);

  const strk = [...D.franchises].sort((a, b) => (b.best_win_streak || 0) - (a.best_win_streak || 0))[0];
  if (strk?.best_win_streak) card('Longest win streak', `${strk.best_win_streak}`, strk.manager,
    strk.streak_detail?.win ? `From ${wk(strk.streak_detail.win.from)}` : '', strk.id);

  const skid = [...D.franchises].sort((a, b) => (b.worst_loss_streak || 0) - (a.worst_loss_streak || 0))[0];
  if (skid?.worst_loss_streak) card('Longest losing streak', `${skid.worst_loss_streak}`, skid.manager,
    skid.streak_detail?.loss ? `From ${wk(skid.streak_detail.loss.from)}` : '', skid.id);

  const drought = D.franchises.filter(f => f.active && f.seasons >= 5 && !f.titles)
    .sort((a, b) => b.seasons - a.seasons)[0];
  if (drought) card('Longest title drought', `${drought.seasons} yrs`, drought.manager,
    `${drought.wins}-${drought.losses} all-time, still nothing to show for it`, drought.id);

  $('#records').innerHTML = cards.join('');

  renderTopWeeks();
  $$('#weeks-toggle .tgl').forEach(b => b.addEventListener('click', () => {
    weeksKind = b.dataset.kind;
    $$('#weeks-toggle .tgl').forEach(x => x.classList.toggle('is-on', x === b));
    $('#tw-title').textContent = weeksKind === 'best' ? 'Biggest Weeks Ever' : 'Weeks They Want Forgotten';
    renderTopWeeks();
  }));
}

function renderTopWeeks() {
  const list = D.top_weeks?.[weeksKind] || [];
  $('#top-weeks').innerHTML =
    `<thead><tr><th></th><th>Franchise</th><th>Score</th><th>Opponent</th><th>Their score</th><th>When</th></tr></thead>
     <tbody>${list.map((r, i) => `<tr onclick="goManager('${r.franchise}')">
       <td class="rank">${i + 1}</td>
       <td class="who"><div class="who-mgr">${esc(mgr(r.franchise))}</div></td>
       <td class="pct">${r.score.toFixed(1)}</td>
       <td>${esc(mgr(r.opponent))}</td>
       <td>${r.opp_score.toFixed(1)}</td>
       <td>${r.year} W${r.week}${r.playoff ? ' \u00b7 PO' : ''}</td></tr>`).join('')}</tbody>`;
}

boot();
