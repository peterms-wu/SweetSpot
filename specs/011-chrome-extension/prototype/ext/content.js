// Prototype content script (plan research R0.2). Asks the service worker for the data (no web_accessible_resources,
// no network), then: game page -> a panel right above the purchase area; wishlist -> one line under each name.
// Everything is inside try/catch and shadow roots, so a failure or a Steam restyle only affects our own nodes.
(() => {
  const GROUPS = {now: '現在買', soon: '即將到價', wait: '繼續等', low: '低信心', na: '無法預測'};
  const COLORS = {now: '#1e7d32', soon: '#1a73e8', wait: '#6b6b70', low: '#8a4b00', na: '#a1261b'};
  const money = v => v == null ? '未知' : 'NT$' + v.toLocaleString('en-US');
  const pct = p => p == null ? '—' : Math.round(p * 100) + '%';
  const off = p => p ? `-${p}%` : '原價';
  const probe = {};                       // read by the Playwright probe (content scripts run in an isolated world)
  const mark = document.createElement('div');
  mark.id = 'steamsage-probe';
  mark.hidden = true;
  const save = () => { mark.dataset.probe = JSON.stringify(probe); };

  function host(tag, cls) {
    const el = document.createElement(tag);
    el.className = cls;
    return [el, el.attachShadow({mode: 'open'})];
  }

  // --- game page -----------------------------------------------------------------------------------------------
  function pagePrice(g) {
    if (!g.option) return {why: '沒有追蹤的購買選項'};
    const key = g.option.kind === 'bundle' ? 'bundleid' : 'subid';
    const input = document.querySelector(`#game_area_purchase form input[name="${key}"][value="${g.option.id}"]`);
    const block = input && input.closest('.game_area_purchase_game');
    if (!block) return {why: '頁面上找不到追蹤的購買選項'};
    const priced = block.querySelector('[data-price-final]');
    const shown = block.querySelector('.discount_final_price, .game_purchase_price');
    if (!priced || !shown) return {why: '頁面上沒有這個選項的價格'};
    if (!/NT\$/.test(shown.textContent)) return {why: '頁面不是新台幣，不並列'};
    return {cents: Number(priced.getAttribute('data-price-final')), text: shown.textContent.trim()};
  }

  function gamePanel(data, appId) {
    const g = data.games.find(x => x.app_id === appId);
    probe.game = {inData: !!g};
    if (!g) return;
    const area = document.querySelector('#game_area_purchase');
    probe.game.area = !!area;
    if (!area) return;                     // no purchase area: do not guess a position
    const [el, root] = host('div', 'steamsage-panel');
    const live = g.group === 'na' ? null : pagePrice(g);
    const owned = !!document.querySelector('.game_area_already_owned');
    const rows = g.group === 'na' ? `<p>${esc(g.status_reason)}</p>` : `
      <div class="grid">
        <div><small>頁面現價</small>${live.cents != null ? esc(live.text) : '—'}</div>
        <div class="sweet"><small>甜蜜價</small>${money(g.sweet_twd)} -${g.sweet_pct}%</div>
        <div><small>甜蜜時點</small>${esc(g.point.label)}</div>
        <div><small>到價機率</small>${pct(g.probability)}</div>
        <div><small>12 個月內最低</small>${money(g.p_min_twd)} -${g.p_min_pct}%</div>
      </div>
      ${live.cents == null ? `<p class="muted">${esc(live.why)}</p>` : ''}
      ${g.option && g.option.user ? `<p class="muted">追蹤 ${esc(g.option.name)}（使用者指定）</p>` : ''}
      <details><summary>原因（${g.reasons.length}）</summary><ul>${g.reasons.map(r => `<li>${esc(r)}</li>`).join('')}</ul></details>`;
    root.innerHTML = `<style>
      :host { all: initial; display:block; margin: 0 0 12px; font: 13px/1.5 "Segoe UI","Microsoft JhengHei",sans-serif; }
      .box { background:#1f2a38; color:#dfe3e6; border-left:4px solid ${COLORS[g.group]}; padding:10px 14px; border-radius:4px; }
      .grid { display:grid; grid-template-columns: repeat(5, 1fr); gap: 4px 12px; }
      small { display:block; color:#8f98a0; font-size:11px; } .sweet { color:#a4d007; font-weight:600; }
      .muted { color:#8f98a0; margin:6px 0 0; } h3 { margin:0 0 6px; font-size:14px; color:#fff; }
      .tag { background:${COLORS[g.group]}; color:#fff; border-radius:3px; padding:0 6px; margin-right:6px; }
      summary { cursor:pointer; color:#66c0f4; margin-top:6px; }</style>
      <div class="box"><h3><span class="tag">${GROUPS[g.group]}</span>SteamSage2 · 資料時間 ${esc(data.data_time)}</h3>
      ${owned ? '<p>你已擁有這款遊戲；以下是購買前的建議</p>' : ''}${rows}</div>`;
    area.before(el);
    probe.game.inserted = true;
    const nav = performance.getEntriesByType('navigation')[0];
    probe.game.ms_after_dcl = nav ? Math.round(performance.now() - nav.domContentLoadedEventEnd) : null;
    probe.game.live = live;
    save();
  }

  // --- wishlist ------------------------------------------------------------------------------------------------
  function nameLink(row) {
    // the name is the app link that holds only text (the image link holds an <img>, the price link holds divs)
    return [...row.querySelectorAll('a[href*="/app/"]')].find(a => a.children.length === 0 && a.textContent.trim());
  }

  function wishLine(g) {
    const [el, root] = host('span', 'steamsage-line');
    el.dataset.app = g.app_id;
    const body = g.group === 'na' ? esc(g.status_reason || '') :
      `甜蜜價 ${money(g.sweet_twd)} -${g.sweet_pct}% · ${esc(g.point.label)} · ${pct(g.probability)}`;
    el.title = g.reasons.slice(0, 3).join('\n') || (g.status_reason || '');
    root.innerHTML = `<style>:host { all: initial; display:block; font: 12px/1.6 "Segoe UI","Microsoft JhengHei",sans-serif;
      color:#c7d5e0; } b { color:#fff; background:${COLORS[g.group]}; border-radius:3px; padding:0 5px; margin-right:6px;
      font-weight:600; } i { font-style:normal; border:1px solid #8f98a0; border-radius:3px; padding:0 4px; margin-left:6px; }</style>
      <b>${GROUPS[g.group]}</b>${body}${g.bundles.length ? '<i>組合包</i>' : ''}`;
    return el;
  }

  function wishlist(data) {
    const byId = new Map(data.games.map(g => [g.app_id, g]));
    probe.wish = {processed: 0, skippedNoName: 0};
    const handle = () => {
      for (const row of document.querySelectorAll('[data-index]')) {
        try {
          const link = nameLink(row);
          const any = row.querySelector('a[href*="/app/"]');
          const id = any && Number((any.href.match(/\/app\/(\d+)/) || [])[1]);
          const old = row.querySelector('.steamsage-line');
          if (old && Number(old.dataset.app) === id) continue;       // already done for this game
          if (old) old.remove();                                      // the row was reused for another game
          const g = byId.get(id);
          if (!g) continue;
          if (!link) { probe.wish.skippedNoName++; continue; }        // structure changed: do not guess
          // the row is a grid whose area right under the name ("title") is "mid"; put the line at the start of
          // the element placed there, without touching Steam's own styles. No such area: do not guess.
          const grid = link.parentElement && link.parentElement.parentElement;
          const mid = grid && [...grid.children].find(c => getComputedStyle(c).gridRowStart === 'mid');
          if (!mid) { probe.wish.skippedNoMid = (probe.wish.skippedNoMid || 0) + 1; continue; }
          mid.prepend(wishLine(g));
          probe.wish.processed++;
        } catch (e) { probe.wish.error = String(e); }
      }
      save();
    };
    handle();
    let queued = false;
    new MutationObserver(() => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => { queued = false; handle(); });
    }).observe(document.body, {childList: true, subtree: true});
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  }

  chrome.runtime.sendMessage({type: 'data'}, r => {
    try {
      probe.ok = !!(r && r.ok);
      mark.textContent = r && r.ok ? `as_of=${r.data.as_of}` : `no data: ${r && r.why}`;
      document.body.append(mark);
      if (!r || !r.ok) return;
      const m = location.pathname.match(/^\/app\/(\d+)/);
      if (m) gamePanel(r.data, Number(m[1]));
      else if (location.pathname.startsWith('/wishlist/')) wishlist(r.data);
    } catch (e) { probe.error = String(e); }
    save();
  });
})();
