// SweetSpot extension: pure functions shared by the service worker, the popup and the content script
// (feature 011; contracts/extension-data.md, contracts/extension-ui.md). No DOM, no network: callers pass plain data.
// Formatting only (spec FR-005): thousands separators, percentages, Taipei time, and the one comparison
// "now - data_time > stale_hours". Numbers and sentences come from the data file written by the report.
(function (root) {
  'use strict';

  const FORMAT = 'steamsage.extension/1';
  const GROUPS = {
    now: {name: '現在買', color: '#1e7d32'},
    soon: {name: '即將到價', color: '#1a73e8'},
    wait: {name: '繼續等', color: '#6b6b70'},
    low: {name: '低信心', color: '#8a4b00'},
    na: {name: '無法預測', color: '#a1261b'},
  };
  const BADGE = {ok: '#1e7d32', stale: '#b06000', error: '#a1261b'};
  const HOUR = 3600 * 1000;

  function money(v) {
    if (v === null || v === undefined) return '未知';
    const s = Math.abs(v).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    return (v < 0 ? '-NT$' : 'NT$') + s;
  }

  function pct(p) {
    return p === null || p === undefined ? '—' : Math.round(p * 100) + '%';
  }

  function off(p) {
    return p ? `-${p}%` : '原價';
  }

  function taipei(stamp) {
    if (!stamp) return '未知';
    const t = new Date(Date.parse(stamp) + 8 * HOUR);
    const two = n => String(n).padStart(2, '0');
    return `${t.getUTCFullYear()}-${two(t.getUTCMonth() + 1)}-${two(t.getUTCDate())} ${two(t.getUTCHours())}:${two(t.getUTCMinutes())}`;
  }

  function isStale(data, now) {
    if (!data.data_time) return true;
    return now - Date.parse(data.data_time) > (data.stale_hours || 26) * HOUR;
  }

  function staleText(data) {
    return `資料超過 ${data.stale_hours || 26} 小時，請先執行更新`;
  }

  function checkData(obj) {
    const bad = {ok: false, why: 'format'};
    if (!obj || typeof obj !== 'object' || Array.isArray(obj) || obj.format !== FORMAT) return bad;
    for (const key of ['games', 'bundles', 'data_time', 'as_of', 'summary']) {
      if (!(key in obj)) return bad;
    }
    if (!Array.isArray(obj.games) || !Array.isArray(obj.bundles)) return bad;
    return {ok: true};
  }

  function nowCount(data) {
    return data.games.filter(g => g.group === 'now').length;
  }

  function badge(result, now) {
    if (!result || !result.ok) return {text: '!', color: BADGE.error};
    const n = nowCount(result.data);
    if (isStale(result.data, now)) return {text: n ? String(n) : '!', color: BADGE.stale};
    return {text: n ? String(n) : '', color: BADGE.ok};
  }

  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  }

  // --- game page panel (FR-012, FR-013, FR-013a) -----------------------------------------------------------------

  const POINT_STATUS = {announced: '官方', estimated: '預估'};

  // blocks: the page's purchase options [{subid, bundleid, priceFinal, text}] as strings read from the page
  function matchOption(blocks, option) {
    if (!option) return {why: '沒有追蹤的購買選項'};
    const key = option.kind === 'bundle' ? 'bundleid' : 'subid';
    const block = blocks.find(b => b[key] !== null && b[key] !== undefined && String(b[key]) === String(option.id));
    if (!block) return {why: '頁面上找不到追蹤的購買選項'};
    if (block.priceFinal === null || block.priceFinal === undefined || !/^\d+$/.test(String(block.priceFinal))) {
      return {why: '頁面上沒有這個選項的價格'};
    }
    if (!/NT\$/.test(block.text || '')) return {why: '頁面不是新台幣，不並列'};
    return {cents: Number(block.priceFinal), text: block.text.trim()};
  }

  // The hover text of every "到價機率" (2026-10-18): the number is the forecast for the sweet point, not about the
  // current price, which a buy-now game has already beaten.
  function probabilityTitle(game) {
    return `到 ${game.point.label}為止，季節特賣打到 -${game.sweet_pct}%（${money(game.sweet_twd)}）以上的機率；跟現價無關`;
  }

  function common(game, data, now) {
    return {
      group: game.group, groupName: GROUPS[game.group].name, color: GROUPS[game.group].color,
      stale: isStale(data, now) ? staleText(data) : null, refreshNote: data.refresh_note || null,
      referenceNotice: data.reference_notice || null,          // feature 014: absent at the target or before 014
    };
  }

  // Per-game fields that a newer report writes. A data file without them was written before this extension version
  // (for example right after a merge, before the next report): say so instead of silently leaving features out.
  // When a feature starts reading a new per-game field, add it here (tests/contract/test_extension_contract.py
  // checks that the report writes every one of them).
  const GAME_FIELDS = ['versions'];
  const OUTDATED_TEXT = '資料檔是舊版，部分功能不會顯示：請執行 更新資料.cmd 重新產生';

  function outdatedText(data) {
    return (data.games || []).some(g => GAME_FIELDS.some(f => !(f in g))) ? OUTDATED_TEXT : null;
  }

  function panelModel(game, live, owned, data, now) {
    const time = taipei(data.data_time);
    const m = {
      ...common(game, data, now), header: `SweetSpot · 資料時間 ${time}（台北）`, tags: game.tags || [],
      cells: [], notes: [], reasons: game.reasons || [], owned: !!owned, outdated: outdatedText(data),
      collapsedText: `你已擁有這款遊戲；以下是購買前（資料時間 ${time}）的建議`,
    };
    if (game.group === 'na') {
      m.notes = [game.status_reason || ''];
      return m;
    }
    const pt = game.point;
    m.cells = [
      ['頁面現價', live && live.cents !== undefined ? live.text : '—'],
      ['甜蜜價', `${money(game.sweet_twd)} -${game.sweet_pct}%`],
      ['甜蜜時點', `${pt.label}（${POINT_STATUS[pt.status] || pt.status}）`],
      ['到價機率', pct(game.probability), probabilityTitle(game)],
      [data.lowest_label, `${money(game.p_min_twd)} -${game.p_min_pct}%`],
    ];
    if (live && live.why) m.notes.push(live.why);
    if (game.version_text) m.notes.push(game.version_text);
    if (game.editions) m.notes.push(`另有 ${game.editions} 個版本`);
    for (const h of game.bundle_hints || []) m.notes.push(h.text);
    for (const r of game.ns_reasons || []) m.notes.push(r);
    return m;
  }

  // --- the user's edition (feature 009) -----------------------------------------------------------------------------

  // option.user is true only when the user chose an edition other than the Steam default (report/extension.py), while
  // Steam's wishlist row shows the default's price: say which edition our numbers are for (2026-10-14).
  const EDITION_TAG = '指定版本';

  function edition(game) {
    const o = game.option;
    if (!o || !o.user) return null;
    return {tag: EDITION_TAG, name: o.name || `${o.kind}/${o.id}`};
  }

  // --- popup (FR-009 to FR-011) ------------------------------------------------------------------------------------

  const APP_URL = 'https://store.steampowered.com/app/';
  const BUNDLE_URL = 'https://store.steampowered.com/bundle/';
  const ERRORS = {
    missing: '還沒有資料：請先執行 更新資料.cmd',
    broken: '資料檔損壞或正在寫入，請稍後再開',
    format: '資料格式不認得（需要 steamsage.extension/1），請更新擴充功能或重新產生報告',
  };
  const OPEN = new Set(['now', 'soon']);

  function popupRow(g) {
    const e = edition(g);
    const base = {appId: g.app_id, name: g.name || `App ${g.app_id}`, url: `${APP_URL}${g.app_id}/`,
                  edition: e && {tag: e.tag, title: `追蹤 ${e.name}（使用者指定）：現價與甜蜜價都是這個版本的價格，不是 Steam 預設版本`}};
    if (g.group === 'na') return {...base, reason: g.status_reason || ''};
    return {...base, price: g.price_twd === null || g.price_twd === undefined ? '未知' : `${money(g.price_twd)} ${off(g.cut_pct)}`,
            sweet: `${money(g.sweet_twd)} -${g.sweet_pct}%`, point: g.point.label, probability: pct(g.probability),
            probabilityTitle: probabilityTitle(g)};
  }

  function popupModel(result, now) {
    if (!result || !result.ok) return {error: ERRORS[result && result.why] || ERRORS.missing};
    const d = result.data;
    const groups = Object.keys(GROUPS).map(key => {
      const rows = d.games.filter(g => g.group === key).map(popupRow);
      return {key, title: `${GROUPS[key].name}（${rows.length}）`, color: GROUPS[key].color, open: OPEN.has(key), rows};
    });
    const bundles = d.bundles.map(b => {
      let text = b.advice_text ? b.advice_text + (b.advice_low ? '（低信心）' : '') : (b.lines[b.lines.length - 1] || '');
      if (b.check_text) text += `（${b.check_text}）`;
      return {name: b.name || `bundle/${b.id}`, url: `${BUNDLE_URL}${b.id}/`, grade: b.grade_text, discount: b.discount_text, text};
    });
    return {header: [`資料時間 ${taipei(d.data_time)}（台北）· 報告 ${taipei(d.as_of)}`],
            stale: isStale(d, now) ? staleText(d) : null, refreshNote: d.refresh_note || null,
            calendarNotices: d.calendar_notices || [],        // feature 012: absent in older data files
            referenceNotice: d.reference_notice || null,      // feature 014 FR-014a
            hint: '買完遊戲後可執行 更新資料.cmd 立即更新', groups, bundles};
  }

  // --- wishlist lines (FR-014 to FR-016; research R0.2) ------------------------------------------------------------

  // links: a row's app links [{childCount, text}]; the name is the one holding only text
  // (the image link holds an <img>, the price link holds <div>s). -1: not found, show nothing.
  function pickNameLink(links) {
    return links.findIndex(l => l.childCount === 0 && (l.text || '').trim() !== '');
  }

  // children: the row grid's children [{gridRowStart}]; the area right under the name is "mid"
  function pickMid(children) {
    return children.findIndex(c => c.gridRowStart === 'mid');
  }

  function rowAction(lineApp, rowApp, inData) {
    if (lineApp === null || lineApp === undefined) return inData ? 'add' : 'none';
    if (lineApp === rowApp) return 'keep';
    return inData ? 'replace' : 'remove';
  }

  function lineModel(game, data, now) {
    const e = edition(game);
    const m = {groupName: GROUPS[game.group].name, color: GROUPS[game.group].color, text: '', bundle: false, title: '',
               stale: isStale(data, now), edition: e && e.tag};
    const note = data.refresh_note ? [data.refresh_note] : [];      // FR-007: the update failure comes first
    if (e) note.push(`追蹤 ${e.name}（使用者指定），不是這一列顯示的版本`);
    if (game.group === 'na') {
      m.text = game.status_reason || '';
      m.title = [...note, m.text].join('\n');
      return m;
    }
    m.text = `甜蜜價 ${money(game.sweet_twd)} -${game.sweet_pct}% · ${game.point.label} · 到價機率 ${pct(game.probability)}` +
             ` · ${data.lowest_label} ${money(game.p_min_twd)} -${game.p_min_pct}%`;
    m.bundle = (game.bundle_hints || []).length > 0;
    m.title = [...note, probabilityTitle(game), ...(game.reasons || []).slice(0, 3)].join('\n');
    return m;
  }

  // --- feature 015: choosing the tracked edition (contracts/extension-ui.md) -------------------------------------
  // The end-to-end check replaces these three constants in its temporary copy of the extension (tasks T021).
  const HOST_NAME = 'com.sweetspot.edition';
  const CONFIRM_MS = 5000;
  const WAIT_MS = 60000;
  const CHECKING_TEXT = '檢查本機程式…';
  // Without the local program: how to install it (the section's guide) and each version's steps by hand (2026-10-14:
  // "安裝本機程式後可在這裡指定" alone said neither how to install nor which file to edit). Texts are segments: strings,
  // and {code} parts (paths, the command) that the panel shows as selectable code. The data file's config_path gives
  // the full path; an older data file without it gets the folder described in words.
  const INSTALL_COMMAND = 'uv run sweetspot host install';
  const UNTIL_THEN = '在那之前，可以照下面各版本的步驟手動指定。';
  const BY_HAND_END = '存檔後執行 更新資料.cmd，再重新整理這一頁。';

  function places(configPath) {
    if (typeof configPath === 'string' && /[\\/]/.test(configPath)) {
      const folder = configPath.replace(/[\\/][^\\/]*$/, '');
      return {where: ['在 ', {code: folder}, ' '], again: ['在 ', {code: folder}, ' '],
              file: ['用記事本打開 ', {code: configPath}]};
    }
    return {where: ['在 SweetSpot 資料夾（extension 資料夾的上一層）'], again: ['在 SweetSpot 資料夾'],
            file: ['用記事本打開 SweetSpot 資料夾的 sweetspot.toml']};
  }

  function segmentsText(segments) {
    return typeof segments === 'string' ? segments : segments.map(s => (typeof s === 'string' ? s : s.code)).join('');
  }

  function installGuide(p) {
    return ['要在這裡直接指定版本：', ...p.where, '開啟命令列，執行 ', {code: INSTALL_COMMAND}, `，然後重新整理這一頁。${UNTIL_THEN}`];
  }

  function unavailableGuide(p, message) {
    return [`本機程式無法使用（Chrome：${message || '未知的錯誤'}）：`, ...p.again, '重新執行 ', {code: INSTALL_COMMAND},
            `（專案資料夾搬家後會這樣），然後重新整理這一頁。${UNTIL_THEN}`];
  }

  function byHand(p, action, app) {
    return action === 'reset'
      ? ['手動改回：', ...p.file, `，在 [purchase_options] 下面找到以「${app} =」開頭的那一行，整行刪掉，${BY_HAND_END}`]
      : ['手動指定：', ...p.file, '，在 [purchase_options] 那一行的下面加上下面這一行（沒有 [purchase_options] 就在檔案最後先加上它），',
         BY_HAND_END];
  }

  const WAIT_TEXT = '報告仍在產生，完成後重新整理頁面即可看到';
  const COMMANDS = new Set(['status', 'choose', 'reset']);

  const ref = v => `${v.kind}/${v.id}`;
  const quoted = name => (/^《.*》$/.test(name) ? name : `《${name}》`);

  function trackedChoice(game) {
    const o = game.option;
    return o && o.user ? `${o.kind}/${o.id}` : null;
  }

  // host: {state: 'unknown' | 'checking' | 'ready' | 'not-installed' | 'unavailable', choice?, message?}
  // configPath: the data file's config_path (the settings file the report ran with), or nothing.
  function versionsModel(game, host, configPath) {
    const versions = game.versions || [];
    if (versions.length < 2) return null;
    const state = host.state;
    const p = places(configPath);
    const rows = versions.map(v => {
      const label = v.tracked ? (v.is_default ? '追蹤中（Steam 預設）' : '追蹤中（使用者指定）') : (v.is_default ? 'Steam 預設' : '');
      const row = {ref: ref(v), name: v.name || ref(v), price: v.price_twd === null || v.price_twd === undefined ? '未知'
                     : `${money(v.price_twd)} ${off(v.cut_pct)}`, label, action: v.action, reason: v.action ? null : v.reason,
                   button: null, help: null, manual: null};
      if (!v.action) return row;
      if (state === 'ready') row.button = {action: v.action, text: v.action === 'reset' ? '改回 Steam 預設' : '追蹤這個版本'};
      else if (state === 'not-installed' || state === 'unavailable') {
        row.help = byHand(p, v.action, game.app_id);
        row.manual = v.action === 'reset' ? null : v.manual;      // the line to add, selectable; nothing to copy for a reset
      } else row.help = CHECKING_TEXT;
      return row;
    });
    const guide = state === 'not-installed' ? installGuide(p)
      : state === 'unavailable' ? unavailableGuide(p, host.message) : null;
    let notice = null;
    // config_ok false: the local program could not read the file, so its choice says nothing (014 T068)
    if (state === 'ready' && host.config_ok !== false && (host.choice || null) !== trackedChoice(game)) {
      const chosen = host.choice && versions.find(v => ref(v) === host.choice && v.action === 'choose');
      if (!host.choice) notice = '設定檔已改回 Steam 預設，報告還沒重新產生';
      else if (chosen) notice = `設定檔已指定 ${chosen.name || ref(chosen)}，報告還沒重新產生`;
    }
    return {title: `版本（${versions.length}）`, guide, notice, rows};
  }

  // state: {phase: 'idle'} | {phase: 'confirm', key, at} | {phase: 'sending', key}
  // event: {type: 'press' | 'elsewhere', trusted, key?} | {type: 'tick'} | {type: 'done'}; only trusted input counts
  function confirmStep(state, event, now) {
    const idle = {phase: 'idle'};
    if (event.type === 'done') return {state: idle, send: false};
    if (state.phase === 'sending') return {state, send: false};
    if (event.type === 'tick') {
      return {state: state.phase === 'confirm' && now - state.at > CONFIRM_MS ? idle : state, send: false};
    }
    if (!event.trusted) return {state, send: false};
    if (event.type === 'elsewhere') return {state: idle, send: false};
    if (state.phase === 'confirm' && state.key === event.key && now - state.at <= CONFIRM_MS) {
      return {state: {phase: 'sending', key: event.key}, send: true};
    }
    return {state: {phase: 'confirm', key: event.key, at: now}, send: false};
  }

  function buttonText(row, state) {
    if (state.phase !== 'confirm' || state.key !== row.ref) return row.button ? row.button.text : '';
    return row.action === 'reset' ? '確定改回 Steam 預設？再按一次' : `確定追蹤${quoted(row.name)}？再按一次`;
  }

  function progressText(cmd, name) {
    return cmd === 'reset' ? '正在改回 Steam 預設並重新產生報告…' : `正在指定${quoted(name)}並重新產生報告…`;
  }

  // The panel's host state from a status reply (content.js). For "unavailable" the message is what Chrome or the
  // program said: unavailableGuide puts it in the sentence once (014 T081; it got replyText's whole sentence before)
  function hostState(reply) {
    if (reply && reply.ok) return {state: 'ready', choice: reply.choice || null, config_ok: reply.config_ok !== false};
    if (reply && reply.code === 'not-installed') return {state: 'not-installed'};
    if (reply && reply.code === 'unavailable') return {state: 'unavailable', message: reply.message || ''};
    return {state: 'unavailable', message: replyText('status', '', reply)};
  }

  function unavailableText(message) {                        // after a failed request: no path at hand, words only
    return segmentsText(unavailableGuide(places(null), message)).replace(UNTIL_THEN, '');
  }

  // reply: the local program's answer as the worker passed it on (or the worker's own refused / not-installed /
  // unavailable). The local program's own message is shown as it is (contracts/native-host.md).
  function replyText(cmd, name, reply) {
    if (!reply) return '本機程式沒有回覆';
    if (reply.ok) {
      if (!reply.changed) return '設定已經是這樣，不需要重新產生報告';
      return cmd === 'reset' ? '已改回 Steam 預設' : `已改為追蹤${quoted(name)}`;
    }
    if (reply.code === 'refused') return '這個請求不符合目前的資料，沒有送出（請重新整理頁面）';
    if (reply.code === 'not-installed') return '找不到本機程式（可能已經移除），沒有改任何設定';
    if (reply.code === 'unavailable') return unavailableText(reply.message);
    return reply.message || `本機程式回覆錯誤（${reply.code}）`;
  }

  // US4: Steam's purchase boxes (blocks as content.js readBlocks reads them, plus hasAction: the box has its
  // purchase button area). A box that is a version the report knows gets a shortcut; when any box cannot be read,
  // none gets one (011 FR-016: do not guess).
  const SHORTCUT = {choose: 'SweetSpot：追蹤這個版本', reset: 'SweetSpot：改回 Steam 預設'};
  const SHORTCUT_TRACKED = 'SweetSpot：追蹤中';
  const SHORTCUT_NO_HOST = '需要安裝本機程式（見 SweetSpot 面板）';
  const filled = value => value !== null && value !== undefined && String(value) !== '';

  function shortcutPlan(blocks, versions) {
    versions = versions || [];
    if (versions.length < 2 || !blocks.length || blocks.some(b => !filled(b.subid) && !filled(b.bundleid))) return [];
    const plan = [];
    blocks.forEach((b, index) => {
      const key = filled(b.subid) ? `sub/${b.subid}` : `bundle/${b.bundleid}`;
      const v = versions.find(x => ref(x) === key);
      if (!v || (!v.tracked && v.action !== 'choose' && v.action !== 'reset')) return;
      const action = v.tracked ? null : v.action;
      plan.push({index, ref: key, action, name: v.name || key, text: action ? SHORTCUT[action] : SHORTCUT_TRACKED});
    });
    return plan.some(s => blocks[s.index].hasAction === false) ? [] : plan;
  }

  function shortcutText(entry, state, host) {
    if (!entry.action) return entry.text;
    if (host.state === 'not-installed' || host.state === 'unavailable') return SHORTCUT_NO_HOST;
    return state.phase === 'confirm' && state.key === entry.ref
      ? `SweetSpot：${buttonText({...entry, button: null}, state)}` : entry.text;
  }

  // The worker's first check before it calls the local program (which checks again against its own data).
  function relayCheck(data, senderUrl, msg) {
    if (!msg || msg.type !== 'host' || !COMMANDS.has(msg.cmd) || !Number.isInteger(msg.app)) return null;
    const m = /^https:\/\/store\.steampowered\.com\/app\/(\d+)(?:[/?#]|$)/.exec(senderUrl || '');
    if (!m || Number(m[1]) !== msg.app) return null;
    const game = ((data && data.games) || []).find(g => g.app_id === msg.app);
    if (!game) return null;
    const versions = game.versions || [];
    if (msg.cmd === 'status') return {v: 1, cmd: 'status', app: msg.app};
    if (msg.cmd === 'reset') return versions.some(v => v.action === 'reset') ? {v: 1, cmd: 'reset', app: msg.app} : null;
    if (typeof msg.option !== 'string') return null;
    const target = versions.find(v => ref(v) === msg.option);
    if (!target || (target.action !== 'choose' && target.action !== 'reset')) return null;
    return {v: 1, cmd: 'choose', app: msg.app, option: msg.option};
  }

  const SweetSpot = {FORMAT, GROUPS, BADGE, money, pct, off, taipei, isStale, staleText, checkData, nowCount, badge, esc,
                     matchOption, GAME_FIELDS, outdatedText, panelModel, popupModel, pickNameLink, pickMid, rowAction, lineModel,
                     HOST_NAME, CONFIRM_MS, WAIT_MS, WAIT_TEXT, versionsModel, confirmStep, buttonText, progressText,
                     replyText, hostState, trackedChoice, relayCheck, shortcutPlan, shortcutText, segmentsText};
  root.SweetSpot = SweetSpot;
  if (typeof module !== 'undefined' && module.exports) module.exports = SweetSpot;
})(typeof globalThis !== 'undefined' ? globalThis : this);
