// SweetSpot content script (feature 011; contracts/extension-ui.md; research R0.2).
// Game page: a panel right above the purchase area. Wishlist: one line under each game's name.
// It only adds its own nodes (in shadow roots) and never changes Steam's elements; when the page structure is not
// found it shows nothing (FR-016). Page text is read as data and written with textContent only.
(() => {
  'use strict';
  const S = globalThis.SweetSpot;

  function ask() {
    return new Promise(resolve => {
      try {
        chrome.runtime.sendMessage({type: 'data'}, result => {
          resolve(chrome.runtime.lastError ? null : result);
        });
      } catch (e) {
        resolve(null);                               // extension reloaded while the page was open
      }
    });
  }

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === 'class') node.className = v;
      else if (k === 'text') node.textContent = v;
      else node.setAttribute(k, v);
    }
    for (const c of children) if (c) node.append(c);
    return node;
  }

  function shadowHost(tag, cls, css) {
    const host = document.createElement(tag);
    host.className = cls;
    const root = host.attachShadow({mode: 'open'});
    root.append(el('style', {text: css}));
    return [host, root];
  }

  // --- game page (FR-012, FR-013, FR-013a) -----------------------------------------------------------------------

  const PANEL_CSS = `
    :host { all: initial; display: block; margin: 0 0 16px; font: 13px/1.5 "Segoe UI", "Microsoft JhengHei", Arial, sans-serif; }
    .box { background: #1f2a38; color: #dfe3e6; border-left: 4px solid var(--c); border-radius: 4px; padding: 10px 14px; }
    .head { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 6px; }
    .group { background: var(--c); color: #fff; border-radius: 3px; padding: 0 7px; font-weight: 600; }
    .title { color: #fff; font-weight: 600; }
    .tag { border: 1px solid #56657a; color: #b8c2cc; border-radius: 3px; padding: 0 5px; font-size: 11px; }
    .warn { background: #3a2a12; color: #f6c26b; border-radius: 3px; padding: 2px 8px; margin: 4px 0; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 4px 14px; margin: 4px 0; }
    .cell small { display: block; color: #8f98a0; font-size: 11px; }
    .cell.sweet { color: #a4d007; font-weight: 600; }
    ul { margin: 4px 0; padding-left: 18px; } li { margin: 1px 0; }
    .notes { color: #c7d5e0; }
    details summary { cursor: pointer; color: #66c0f4; margin-top: 4px; }
    button { all: unset; cursor: pointer; color: #66c0f4; margin-left: 8px; }
    button:hover, details summary:hover { text-decoration: underline; }
    .owned { color: #c7d5e0; }
    .versions { margin-top: 6px; border-top: 1px solid #2f3e52; padding-top: 2px; }
    .vstatus { background: #22374d; color: #dfe3e6; border-radius: 3px; padding: 2px 8px; margin: 4px 0; }
    .vguide { background: #22374d; color: #c7d5e0; border-left: 3px solid #66c0f4; border-radius: 3px; padding: 4px 8px; margin: 4px 0; }
    .vrow { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 0 12px; padding: 3px 0; border-bottom: 1px solid #2a3647; }
    .vname { color: #fff; } .vprice { color: #c7d5e0; margin-left: 8px; } .vlabel { color: #a4d007; margin-left: 8px; }
    .vside { display: flex; justify-content: flex-end; align-items: baseline; flex-wrap: wrap; gap: 0 8px; }
    .vside .vlabel, .vside button { margin-left: 0; }
    .vhelp, .vreason { grid-column: 1 / -1; color: #8f98a0; font-size: 12px; }
    .vcode { font: 12px Consolas, monospace; color: #dfe3e6; background: #10161f; padding: 0 4px; border-radius: 3px;
             user-select: all; word-break: break-all; }
    .vmanual { grid-column: 1 / -1; font: 12px Consolas, monospace; color: #dfe3e6; background: #10161f; padding: 1px 6px;
               border-radius: 3px; user-select: all; }
    button.confirm { color: #f6c26b; font-weight: 600; }
    button:disabled { color: #56657a; cursor: default; text-decoration: none; }`;

  const purchaseBoxes = () => [...document.querySelectorAll('#game_area_purchase .game_area_purchase_game')];

  function readBlocks(boxes = purchaseBoxes()) {
    return boxes.map(b => {
      const input = name => b.querySelector(`form input[name="${name}"]`);
      const priced = b.querySelector('[data-price-final]');
      const shown = b.querySelector('.discount_final_price, .game_purchase_price');
      return {subid: input('subid') ? input('subid').value : null, bundleid: input('bundleid') ? input('bundleid').value : null,
              priceFinal: priced ? priced.getAttribute('data-price-final') : null, text: shown ? shown.textContent : '',
              hasAction: !!b.querySelector('.game_purchase_action')};
    });
  }

  // Feature 015 US4: the shortcut inside one of Steam's purchase boxes (contracts/extension-ui.md).
  const SHORTCUT_CSS = `
    :host { all: initial; display: block; margin: 6px 0 0; font: 12px/1.6 "Segoe UI", "Microsoft JhengHei", Arial, sans-serif; }
    button { all: unset; cursor: pointer; color: #66c0f4; } button:hover { text-decoration: underline; }
    button.confirm { color: #f6c26b; font-weight: 600; }
    button:disabled { color: #56657a; cursor: default; text-decoration: none; }
    .tracked { color: #a4d007; } .nohost { color: #8f98a0; }`;

  function panelBody(m) {
    const body = el('div', {class: 'body'});
    if (m.cells.length) {
      body.append(el('div', {class: 'grid'}, ...m.cells.map(([label, value, title], i) =>
        el('div', {class: i === 1 ? 'cell sweet' : 'cell', ...(title ? {title} : {})}, el('small', {text: label}),
           document.createTextNode(value)))));
    }
    if (m.notes.length) body.append(el('ul', {class: 'notes'}, ...m.notes.map(n => el('li', {text: n}))));
    if (m.reasons.length) {
      body.append(el('details', {}, el('summary', {text: `原因（${m.reasons.length}）`}),
                     el('ul', {}, ...m.reasons.map(r => el('li', {text: r})))));
    }
    return body;
  }

  // --- game page: the "versions" section (feature 015; contracts/extension-ui.md) ---------------------------------

  function askHost(appId, message) {
    return new Promise(resolve => {
      try {
        chrome.runtime.sendMessage({type: 'host', app: appId, ...message}, reply => {
          resolve(chrome.runtime.lastError ? {ok: false, code: 'unavailable', message: chrome.runtime.lastError.message}
                                           : reply);
        });
      } catch (e) {
        resolve({ok: false, code: 'unavailable', message: String((e && e.message) || e)});
      }
    });
  }

  // lib.js text segments: strings, and {code} parts (paths, the install command) shown as selectable code.
  function segments(cls, parts) {
    const node = el('div', {class: cls});
    for (const p of typeof parts === 'string' ? [parts] : parts) {
      node.append(typeof p === 'string' ? document.createTextNode(p) : el('code', {class: 'vcode', text: p.code}));
    }
    return node;
  }

  function versionRow(row, button) {
    const side = el('span', {class: 'vside'});
    if (row.label) side.append(el('span', {class: 'vlabel', text: row.label}));
    if (button) side.append(button);
    const line = el('div', {class: 'vrow', 'data-ref': row.ref},
                    el('span', {}, el('span', {class: 'vname', text: row.name}), el('span', {class: 'vprice', text: row.price})),
                    side);
    if (row.help) line.append(segments('vhelp', row.help));
    if (row.manual) line.append(el('code', {class: 'vmanual', text: row.manual}));
    if (row.reason) line.append(el('div', {class: 'vreason', text: row.reason}));
    return line;
  }

  // The section's own state: the local program's status (asked once, when the section is first opened or a
  // shortcut is first pressed; FR-023a), the two-click confirmation (only trusted clicks count; FR-006a) and the
  // request in progress, shared by the panel and the purchase-box shortcuts. `page` gives the current game, takes
  // the regenerated report's data (FR-011), unfolds an owned game's panel and draws everything again.
  function versionsController(appId, page) {
    const v = {host: {state: 'unknown'}, asked: false, open: false, confirm: {phase: 'idle'}, status: null, stuck: false};
    const noHost = () => v.host.state === 'not-installed' || v.host.state === 'unavailable';

    function show() {                                  // progress, results and install hints are in the section
      v.open = true;
      page.reveal();
    }

    function checkHost(fromShortcut = false) {
      if (v.asked) return;
      v.asked = true;
      v.host = {state: 'checking'};
      page.draw();
      askHost(appId, {cmd: 'status'}).then(reply => {
        v.host = S.hostState(reply);
        if (reply && reply.ok && !reply.config_ok) v.status = reply.message;
        if (v.host.state !== 'ready') {
          v.confirm = {phase: 'idle'};                  // a shortcut's first click cannot be confirmed now
          if (fromShortcut) show();
        }
        page.draw();
      });
    }

    function step(event) {
      const r = S.confirmStep(v.confirm, event, Date.now());
      const changed = r.state !== v.confirm;
      v.confirm = r.state;
      return {send: r.send, changed};
    }

    function press(row, event) {
      event.stopPropagation();
      const r = step({type: 'press', key: row.ref, trusted: event.isTrusted});
      if (r.send) send(row);
      else if (r.changed) {
        page.draw();
        setTimeout(() => { if (step({type: 'tick'}).changed) page.draw(); }, S.CONFIRM_MS + 50);
      }
    }

    function pressShortcut(entry, event) {
      event.stopPropagation();
      if (!event.isTrusted) return;                     // a page script does not even start the status query
      if (noHost()) {
        show();
        page.draw();
        return;
      }
      const waiting = v.host.state !== 'ready';
      if (waiting && v.confirm.phase === 'confirm' && v.confirm.key === entry.ref) return;   // status not back yet
      press(entry, event);
      if (waiting) checkHost(true);
    }

    function send(row) {
      const cmd = row.action === 'reset' ? 'reset' : 'choose';
      v.status = S.progressText(cmd, row.name);
      v.stuck = false;
      show();
      page.draw();
      let settled = false;
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        v.status = S.WAIT_TEXT;                         // FR-010: buttons stay off until the page is reloaded
        v.stuck = true;
        page.draw();
      }, S.WAIT_MS);
      askHost(appId, cmd === 'reset' ? {cmd} : {cmd, option: row.ref}).then(reply => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        step({type: 'done'});
        if (reply && reply.ok && reply.data) {
          page.setData(reply.data);
          const g = page.game();
          if (g) v.host = {state: 'ready', choice: S.trackedChoice(g)};
        }
        if (reply && !reply.ok && reply.code === 'not-installed') v.host = {state: 'not-installed'};
        v.status = S.replyText(cmd, row.name, reply);
        page.draw();
      });
    }

    function button(row) {
      const confirming = v.confirm.phase === 'confirm' && v.confirm.key === row.ref;
      const b = el('button', {type: 'button', class: confirming ? 'confirm' : 'choose', 'data-ref': row.ref,
                              text: S.buttonText(row, v.confirm)});
      b.disabled = v.confirm.phase === 'sending' || v.stuck;
      b.addEventListener('click', e => press(row, e));
      return b;
    }

    function section(g) {
      const m = S.versionsModel(g, v.host, page.configPath());
      if (!m) return null;
      const details = el('details', {class: 'versions'});
      details.open = v.open;
      details.addEventListener('toggle', () => {
        v.open = details.open;
        if (v.open) checkHost();
      });
      details.append(el('summary', {text: m.title}));
      if (v.status) details.append(el('div', {class: 'vstatus', text: v.status}));
      if (m.guide) details.append(segments('vguide', m.guide));
      if (m.notice) details.append(el('div', {class: 'warn', text: m.notice}));
      for (const row of m.rows) details.append(versionRow(row, row.button ? button(row) : null));
      return details;
    }

    function shortcut(entry) {
      const [node, root] = shadowHost('div', 'sweetspot-shortcut', SHORTCUT_CSS);
      node.dataset.ref = entry.ref;
      const text = S.shortcutText(entry, v.confirm, v.host);
      if (!entry.action || noHost()) {
        root.append(el('span', {class: entry.action ? 'nohost' : 'tracked', text}));
        return node;
      }
      const confirming = v.confirm.phase === 'confirm' && v.confirm.key === entry.ref;
      const b = el('button', {type: 'button', class: confirming ? 'confirm' : 'choose', text});
      b.disabled = v.confirm.phase === 'sending' || v.stuck;
      b.addEventListener('click', e => pressShortcut(entry, e));
      root.append(b);
      return node;
    }

    // A trusted click anywhere outside the button being confirmed cancels the confirmation (FR-006).
    function elsewhere(event) {
      if (v.confirm.phase === 'confirm' && step({type: 'elsewhere', trusted: event.isTrusted}).changed) page.draw();
    }

    return {section, shortcut, elsewhere};
  }

  function drawShortcuts(versions, g) {
    for (const old of document.querySelectorAll('.sweetspot-shortcut')) old.remove();
    if (!g) return;
    const boxes = purchaseBoxes();
    for (const s of S.shortcutPlan(readBlocks(boxes), g.versions)) {
      boxes[s.index].querySelector('.game_purchase_action').before(versions.shortcut(s));
    }
  }

  // The panel keeps its own data so it can be drawn again after an edition was chosen (feature 015).
  function gamePage(result, appId) {
    const area = document.querySelector('#game_area_purchase');
    if (!area || document.querySelector('.sweetspot-panel')) return;
    const owned = !!document.querySelector('.game_area_already_owned');
    let data = result.data;
    let ownedOpen = false;
    const game = () => data.games.find(g => g.app_id === appId);
    if (!game()) return;

    const [panel, root] = shadowHost('div', 'sweetspot-panel', PANEL_CSS);
    panel.dataset.app = String(appId);
    const versions = versionsController(appId, {game, draw, setData: d => { data = d; }, reveal: () => { ownedOpen = true; },
                                                configPath: () => data.config_path});
    const ours = n => n === panel || (n.classList && n.classList.contains('sweetspot-shortcut'));
    root.addEventListener('click', versions.elsewhere);
    document.addEventListener('click', e => { if (!e.composedPath().some(ours)) versions.elsewhere(e); }, true);

    function draw() {
      const g = game();
      try {
        drawShortcuts(versions, g);
      } catch (e) {
        // 011 FR-008: a shortcut problem never takes the panel with it
      }
      if (!g) {                                         // the regenerated report no longer has this game
        panel.remove();
        return;
      }
      const live = g.group === 'na' ? null : S.matchOption(readBlocks(), g.option);
      const m = S.panelModel(g, live, owned, data, Date.now());
      const box = el('div', {class: 'box'});
      box.style.setProperty('--c', m.color);
      box.append(el('div', {class: 'head'}, el('span', {class: 'group', text: m.groupName}), el('span', {class: 'title', text: m.header}),
                    ...m.tags.map(t => el('span', {class: 'tag', text: t}))));
      if (m.stale) box.append(el('div', {class: 'warn', text: m.stale}));
      if (m.refreshNote) box.append(el('div', {class: 'warn', text: m.refreshNote}));
      if (m.referenceNotice) box.append(el('div', {class: 'warn', 'data-kind': 'reference', text: m.referenceNotice}));
      if (m.outdated) box.append(el('div', {class: 'warn outdated', text: m.outdated}));
      const body = panelBody(m);
      const section = versions.section(g);
      if (section) body.append(section);
      if (m.owned) {
        body.hidden = !ownedOpen;
        const button = el('button', {type: 'button', text: ownedOpen ? '收合' : '展開'});
        button.addEventListener('click', () => {
          ownedOpen = !ownedOpen;
          body.hidden = !ownedOpen;
          button.textContent = ownedOpen ? '收合' : '展開';
        });
        box.append(el('div', {class: 'owned'}, document.createTextNode(m.collapsedText), button));
      }
      box.append(body);
      root.querySelector('.box')?.remove();
      root.append(box);
    }

    draw();
    area.before(panel);
  }

  // --- wishlist (FR-014 to FR-016; research R0.2) -----------------------------------------------------------------

  const LINE_CSS = `
    :host { all: initial; display: block; margin: 2px 0 0; font: 12px/1.6 "Segoe UI", "Microsoft JhengHei", Arial, sans-serif;
      color: #c7d5e0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .group { background: var(--c); color: #fff; border-radius: 3px; padding: 0 6px; margin-right: 6px; font-weight: 600; }
    .bundle { border: 1px solid #8f98a0; border-radius: 3px; padding: 0 4px; margin-left: 6px; }
    .edition { border: 1px solid #f6c26b; color: #f6c26b; border-radius: 3px; padding: 0 4px; margin-right: 6px; }
    .stale { color: #f6c26b; margin-right: 6px; }`;

  function appOf(row) {
    const a = row.querySelector('a[href*="/app/"]');
    const m = a && a.href.match(/\/app\/(\d+)/);
    return m ? Number(m[1]) : null;
  }

  function wishLine(game, data) {
    const m = S.lineModel(game, data, Date.now());
    const [host, root] = shadowHost('span', 'sweetspot-line', LINE_CSS);
    host.dataset.app = String(game.app_id);
    host.title = m.title;
    const group = el('span', {class: 'group', text: m.groupName});
    group.style.setProperty('--c', m.color);
    root.append(...[m.stale ? el('span', {class: 'stale', text: '資料過舊 ·'}) : null, group,
                    m.edition ? el('span', {class: 'edition', text: m.edition}) : null, document.createTextNode(m.text),
                    m.bundle ? el('span', {class: 'bundle', text: '組合包'}) : null].filter(Boolean));
    return host;
  }

  function wishRow(row, byId, data) {
    const app = appOf(row);
    const old = row.querySelector('.sweetspot-line');
    const action = S.rowAction(old ? Number(old.dataset.app) : null, app, byId.has(app));
    if (action === 'keep' || action === 'none') return;
    if (old) old.remove();                              // the row was reused for another game
    if (action === 'remove') return;
    const links = [...row.querySelectorAll('a[href*="/app/"]')];
    const name = links[S.pickNameLink(links.map(a => ({childCount: a.children.length, text: a.textContent})))];
    const grid = name && name.parentElement && name.parentElement.parentElement;
    if (!grid) return;                                  // structure changed: do not guess (FR-016)
    const children = [...grid.children];
    const mid = children[S.pickMid(children.map(c => ({gridRowStart: getComputedStyle(c).gridRowStart})))];
    if (!mid) return;
    mid.prepend(wishLine(byId.get(app), data));
  }

  function wishlistPage(result) {
    const byId = new Map(result.data.games.map(g => [g.app_id, g]));
    const handle = () => {
      for (const row of document.querySelectorAll('[data-index]')) {
        try {
          wishRow(row, byId, result.data);
        } catch (e) {
          // FR-008: skip this row only
        }
      }
    };
    const ours = node => node.nodeType === 1 && node.classList.contains('sweetspot-line');
    let queued = false;
    new MutationObserver(records => {
      if (queued) return;
      if (records.every(r => [...r.addedNodes, ...r.removedNodes].every(ours))) return;   // our own insertions
      queued = true;
      requestAnimationFrame(() => { queued = false; handle(); });                       // at most once per frame
    }).observe(document.body, {childList: true, subtree: true});
    handle();
  }

  // --- start ------------------------------------------------------------------------------------------------------

  async function start() {
    const result = await ask();
    if (!result || !result.ok) return;                  // no data: show nothing on Steam pages (FR-007)
    const m = location.pathname.match(/^\/app\/(\d+)/);
    try {
      if (m) gamePage(result, Number(m[1]));
      else if (location.pathname.startsWith('/wishlist/')) wishlistPage(result);
    } catch (e) {
      // FR-008: an error only affects our own nodes
    }
  }

  start();
})();
