// feature 011: pure functions of extension/lib.js (tasks T012, T018, T023, T027, T031). Run: node --test tests/extension/
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const S = require('../../extension/lib.js');

const FIXTURE = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'data.json'), 'utf8'));
const HOUR = 3600 * 1000;
const NOW = Date.parse('2026-09-27T12:00:00Z');
const data = (over = {}) => ({...structuredClone(FIXTURE), data_time: '2026-09-27T05:06:12Z', ...over});
const fresh = () => data({data_time: new Date(NOW - HOUR).toISOString().replace(/\.\d+Z$/, 'Z')});

// --- T012: formatting, staleness, data check, badge ----------------------------------------------------------

test('money, pct, off', () => {
  assert.equal(S.money(1063), 'NT$1,063');
  assert.equal(S.money(790), 'NT$790');
  assert.equal(S.money(0), 'NT$0');
  assert.equal(S.money(null), '未知');
  assert.equal(S.money(undefined), '未知');
  assert.equal(S.pct(0.825835), '83%');
  assert.equal(S.pct(0.535), '54%');
  assert.equal(S.pct(null), '—');
  assert.equal(S.off(0), '原價');
  assert.equal(S.off(null), '原價');
  assert.equal(S.off(20), '-20%');
});

test('taipei time', () => {
  assert.equal(S.taipei('2026-09-27T05:06:12Z'), '2026-09-27 13:06');
  assert.equal(S.taipei('2026-09-27T17:30:00Z'), '2026-09-28 01:30');
  assert.equal(S.taipei(null), '未知');
});

test('isStale at the 26-hour boundary', () => {
  const at = offset => data({data_time: new Date(NOW - offset).toISOString().replace(/\.\d+Z$/, 'Z')});
  assert.equal(S.isStale(at(26 * HOUR), NOW), false);
  assert.equal(S.isStale(at(26 * HOUR + 1000), NOW), true);
  assert.equal(S.isStale(at(HOUR), NOW), false);
  assert.equal(S.isStale(data({data_time: null}), NOW), true);
  assert.equal(S.isStale(data({stale_hours: 48, data_time: at(27 * HOUR).data_time}), NOW), false);
});

test('checkData', () => {
  assert.deepEqual(S.checkData(data()), {ok: true});
  assert.deepEqual(S.checkData({...data(), format: 'steamsage.extension/2'}), {ok: false, why: 'format'});
  const noGames = data();
  delete noGames.games;
  assert.deepEqual(S.checkData(noGames), {ok: false, why: 'format'});
  const noTime = data();
  delete noTime.data_time;
  assert.deepEqual(S.checkData(noTime), {ok: false, why: 'format'});
  assert.deepEqual(S.checkData(null), {ok: false, why: 'format'});
  assert.deepEqual(S.checkData([1, 2]), {ok: false, why: 'format'});
});

test('badge', () => {
  const ok = d => ({ok: true, data: d});
  assert.deepEqual(S.badge(ok(fresh()), NOW), {text: '1', color: '#1e7d32'});
  const none = fresh();
  none.games = none.games.filter(g => g.group !== 'now');
  assert.deepEqual(S.badge(ok(none), NOW), {text: '', color: '#1e7d32'});
  assert.deepEqual(S.badge(ok(data({data_time: '2026-09-20T00:00:00Z'})), NOW), {text: '1', color: '#b06000'});
  const staleNone = data({data_time: '2026-09-20T00:00:00Z'});
  staleNone.games = staleNone.games.filter(g => g.group !== 'now');
  assert.deepEqual(S.badge(ok(staleNone), NOW), {text: '!', color: '#b06000'});
  for (const why of ['missing', 'broken', 'format']) {
    assert.deepEqual(S.badge({ok: false, why}, NOW), {text: '!', color: '#a1261b'});
  }
});

test('esc escapes the five characters', () => {
  assert.equal(S.esc('<a href="x">&\''), '&lt;a href=&quot;x&quot;&gt;&amp;&#39;');
  assert.equal(S.esc(null), '');
});

test('group names and colours', () => {
  assert.deepEqual(Object.keys(S.GROUPS), ['now', 'soon', 'wait', 'low', 'na']);
  assert.equal(S.GROUPS.now.name, '現在買');
  assert.equal(S.GROUPS.na.color, '#a1261b');
});

// --- T018: game page panel (FR-012, FR-013, FR-013a) ------------------------------------------------------------

const BLOCKS = [
  {subid: '685434', bundleid: null, priceFinal: '79000', text: 'NT$ 790'},
  {subid: null, bundleid: '32470', priceFinal: '220600', text: 'NT$ 2,206'},
  {subid: '999', bundleid: null, priceFinal: null, text: ''},
];

test('matchOption finds the tracked purchase option', () => {
  assert.deepEqual(S.matchOption(BLOCKS, {kind: 'sub', id: 685434}), {cents: 79000, text: 'NT$ 790'});
  assert.deepEqual(S.matchOption(BLOCKS, {kind: 'bundle', id: 32470}), {cents: 220600, text: 'NT$ 2,206'});
  assert.deepEqual(S.matchOption(BLOCKS, {kind: 'bundle', id: 685434}), {why: '頁面上找不到追蹤的購買選項'});
  assert.deepEqual(S.matchOption(BLOCKS, {kind: 'sub', id: 999}), {why: '頁面上沒有這個選項的價格'});
  assert.deepEqual(S.matchOption([{subid: '1', priceFinal: '2999', text: '$29.99'}], {kind: 'sub', id: 1}),
                   {why: '頁面不是新台幣，不並列'});
  assert.deepEqual(S.matchOption(BLOCKS, null), {why: '沒有追蹤的購買選項'});
  assert.deepEqual(S.matchOption([], {kind: 'sub', id: 1}), {why: '頁面上找不到追蹤的購買選項'});
});

// The hover text of every 到價機率 (2026-10-18): what the number forecasts, and that the current price is not part of it.
const PROBABILITY_TITLE = '到 2026 秋特為止，季節特賣打到 -20%（NT$790）以上的機率；跟現價無關';

test('panelModel for a buy-now game', () => {
  const d = fresh();
  const g = d.games[0];
  const m = S.panelModel(g, {cents: 79000, text: 'NT$ 790'}, false, d, NOW);
  assert.equal(m.groupName, '現在買');
  assert.equal(m.color, '#1e7d32');
  assert.equal(m.header, `SweetSpot · 資料時間 ${S.taipei(d.data_time)}（台北）`);
  assert.equal(m.stale, null);
  assert.equal(m.refreshNote, null);
  assert.deepEqual(m.cells, [['頁面現價', 'NT$ 790'], ['甜蜜價', 'NT$790 -20%'], ['甜蜜時點', '2026 秋特（官方）'],
                             ['到價機率', '83%', PROBABILITY_TITLE], ['12 個月內最低', 'NT$692 -30%']]);
  assert.deepEqual(m.notes, ['另有 1 個版本', '可和 Dispatch 超英派遣中心 一起買：組合包 −10%', '季節特賣以外降到甜蜜價以下的機率：30 天內 5%']);
  assert.deepEqual(m.reasons, g.reasons);
  assert.equal(m.owned, false);
});

test('panelModel with the page price missing, a chosen edition and the lowest label from the data', () => {
  const d = fresh();
  d.lowest_label = '長期最低';
  const g = d.games[1];
  const m = S.panelModel(g, {why: '頁面上找不到追蹤的購買選項'}, false, d, NOW);
  assert.deepEqual(m.cells[0], ['頁面現價', '—']);
  assert.deepEqual(m.cells[4], ['長期最低', 'NT$772 -65%']);
  assert.deepEqual(m.notes.slice(0, 2), ['頁面上找不到追蹤的購買選項', g.version_text]);
  assert.deepEqual(m.tags, ['上限生效']);
  const estimated = structuredClone(g);
  estimated.point.status = 'estimated';
  assert.equal(S.panelModel(estimated, {why: 'x'}, false, d, NOW).cells[2][1], '2027 春特（預估）');
});

test('panelModel for an unpredictable game shows only the reason', () => {
  const d = fresh();
  const m = S.panelModel(d.games[2], null, false, d, NOW);
  assert.equal(m.groupName, '無法預測');
  assert.deepEqual(m.cells, []);
  assert.deepEqual(m.notes, ['尚未發行（預定 2026-11-20）']);
});

test('panelModel for an owned game is collapsed', () => {
  const d = fresh();
  const m = S.panelModel(d.games[0], {cents: 79000, text: 'NT$ 790'}, true, d, NOW);
  assert.equal(m.owned, true);
  assert.equal(m.collapsedText, `你已擁有這款遊戲；以下是購買前（資料時間 ${S.taipei(d.data_time)}）的建議`);
});

test('panelModel carries the stale warning and the update-failure note', () => {
  const d = data({data_time: '2026-09-25T00:00:00Z', refresh_note: '本次資料更新失敗，使用既有資料'});
  const m = S.panelModel(d.games[0], {cents: 79000, text: 'NT$ 790'}, false, d, NOW);
  assert.equal(m.stale, '資料超過 26 小時，請先執行更新');
  assert.equal(m.refreshNote, '本次資料更新失敗，使用既有資料');
});

// --- T023: popup (FR-009 to FR-011) ------------------------------------------------------------------------------

test('popupModel lists the five groups in the data order', () => {
  const d = fresh();
  const m = S.popupModel({ok: true, data: d}, NOW);
  assert.deepEqual(m.header, [`資料時間 ${S.taipei(d.data_time)}（台北）· 報告 ${S.taipei(d.as_of)}`]);
  assert.equal(m.stale, null);
  assert.equal(m.refreshNote, null);
  assert.equal(m.hint, '買完遊戲後可執行 更新資料.cmd 立即更新');
  assert.deepEqual(m.groups.map(g => [g.key, g.title, g.open, g.rows.length]),
                   [['now', '現在買（1）', true, 1], ['soon', '即將到價（0）', true, 0], ['wait', '繼續等（1）', false, 1],
                    ['low', '低信心（0）', false, 0], ['na', '無法預測（1）', false, 1]]);
  assert.deepEqual(m.groups[0].rows[0], {appId: 1903340, name: '光與影：33號遠征隊', url: 'https://store.steampowered.com/app/1903340/',
                                         edition: null, price: 'NT$790 -20%', sweet: 'NT$790 -20%', point: '2026 秋特',
                                         probability: '83%', probabilityTitle: PROBABILITY_TITLE});
  assert.equal(m.groups[2].rows[0].price, 'NT$2,206 原價');
  assert.deepEqual(m.groups[4].rows[0], {appId: 9500013, name: '範例未發行遊戲', url: 'https://store.steampowered.com/app/9500013/',
                                         edition: null, reason: '尚未發行（預定 2026-11-20）'});
  assert.equal(m.error, undefined);
});

test('popupModel carries the calendar notices (feature 012, plan D1)', () => {
  const notice = '官方特賣頁面已 8 天沒有成功讀取（最後一次 2026-09-28 20:00 台北）';
  assert.deepEqual(S.popupModel({ok: true, data: {...fresh(), calendar_notices: [notice]}}, NOW).calendarNotices,
                   [notice]);
  const old = fresh();
  delete old.calendar_notices;                                   // a data file written before feature 012
  assert.deepEqual(S.popupModel({ok: true, data: old}, NOW).calendarNotices, []);
});

test('the small reference dataset notice reaches the popup and the panel as written (014 FR-014a)', () => {
  const text = '參考資料集目前 340 款（建議至少 2,000 款），預測的依據還不完整。';
  const d = {...fresh(), reference_notice: text};
  assert.equal(S.popupModel({ok: true, data: d}, NOW).referenceNotice, text);
  assert.equal(S.panelModel(d.games[0], {cents: 79000, text: 'NT$ 790'}, false, d, NOW).referenceNotice, text);
  const old = fresh();                                          // above the threshold, or written before 014
  assert.equal(S.popupModel({ok: true, data: old}, NOW).referenceNotice, null);
  assert.equal(S.panelModel(old.games[0], {cents: 79000, text: 'NT$ 790'}, false, old, NOW).referenceNotice, null);
});

test('popupModel keeps the data order within a group and shows unknown prices', () => {
  const d = fresh();
  const extra = structuredClone(d.games[0]);
  Object.assign(extra, {app_id: 1, name: 'Second', price_twd: null, cut_pct: null});
  d.games.splice(1, 0, extra);
  const rows = S.popupModel({ok: true, data: d}, NOW).groups[0].rows;
  assert.deepEqual(rows.map(r => r.appId), [1903340, 1]);
  assert.equal(rows[1].price, '未知');
});

test('popupModel bundles', () => {
  const d = fresh();
  const m = S.popupModel({ok: true, data: d}, NOW);
  assert.deepEqual(m.bundles, [{name: 'Clair Obscur: Expedition 33 x Dispatch', url: 'https://store.steampowered.com/bundle/74895/',
                                grade: '只含願望清單遊戲', discount: '組合包 −10%',
                                text: '兩款都要買的話，2026 秋特買組合包：約 NT$1,063'}]);
  d.bundles[0].advice_low = true;
  assert.equal(S.popupModel({ok: true, data: d}, NOW).bundles[0].text, '兩款都要買的話，2026 秋特買組合包：約 NT$1,063（低信心）');
  d.bundles[0].advice_text = null;
  assert.equal(S.popupModel({ok: true, data: d}, NOW).bundles[0].text, '任何一場季節特賣（最早 2026 秋特）：約 NT$1,063，同時到價 73%');
});

test('popupModel explains why there is no data', () => {
  assert.deepEqual(S.popupModel({ok: false, why: 'missing'}, NOW), {error: '還沒有資料：請先執行 更新資料.cmd'});
  assert.deepEqual(S.popupModel({ok: false, why: 'broken'}, NOW), {error: '資料檔損壞或正在寫入，請稍後再開'});
  assert.deepEqual(S.popupModel({ok: false, why: 'format'}, NOW),
                   {error: '資料格式不認得（需要 steamsage.extension/1），請更新擴充功能或重新產生報告'});
  assert.deepEqual(S.popupModel(null, NOW), {error: '還沒有資料：請先執行 更新資料.cmd'});
});

// --- T027: wishlist lines (FR-014 to FR-016) ---------------------------------------------------------------------

test('pickNameLink chooses the text-only app link', () => {
  const image = {childCount: 1, text: ''};
  const name = {childCount: 0, text: 'NEKOPARA After'};
  const price = {childCount: 2, text: 'NT$ 188.00'};
  assert.equal(S.pickNameLink([image, name, price]), 1);
  assert.equal(S.pickNameLink([image, {childCount: 1, text: 'NEKOPARA After'}, price]), -1);   // restyled: name has a span
  assert.equal(S.pickNameLink([{childCount: 0, text: '   '}]), -1);
  assert.equal(S.pickNameLink([]), -1);
});

test('pickMid chooses the grid area under the name', () => {
  assert.equal(S.pickMid([{gridRowStart: 'capsule'}, {gridRowStart: 'title'}, {gridRowStart: 'mid'}, {gridRowStart: 'lower'}]), 2);
  assert.equal(S.pickMid([{gridRowStart: 'auto'}, {gridRowStart: 'title'}]), -1);
});

test('rowAction keeps, adds, replaces or removes the line', () => {
  assert.equal(S.rowAction(1903340, 1903340, true), 'keep');
  assert.equal(S.rowAction(1091500, 1903340, true), 'replace');
  assert.equal(S.rowAction(1091500, 730, false), 'remove');
  assert.equal(S.rowAction(null, 1903340, true), 'add');
  assert.equal(S.rowAction(null, 730, false), 'none');
});

test('lineModel for a game and an unpredictable game', () => {
  const d = fresh();
  const m = S.lineModel(d.games[0], d, NOW);
  assert.deepEqual(m, {groupName: '現在買', color: '#1e7d32', text: '甜蜜價 NT$790 -20% · 2026 秋特 · 到價機率 83% · 12 個月內最低 NT$692 -30%', bundle: true,
                       title: `${PROBABILITY_TITLE}\n第 1 個原因\n第 2 個原因\n第 3 個原因`, stale: false, edition: null});
  assert.equal(S.lineModel(d.games[1], d, NOW).bundle, false);
  const na = S.lineModel(d.games[2], d, NOW);
  assert.equal(na.text, '尚未發行（預定 2026-11-20）');
  assert.equal(na.title, '尚未發行（預定 2026-11-20）');
});

// --- the user's edition (2026-10-14): Steam's rows show the default's price, our numbers are for the chosen edition --

const ULTIMATE = {kind: 'bundle', id: 32470, name: '《電馭叛客 2077：終極版》', user: true};

test('a user-chosen edition is tagged on the wishlist line, with its name first in the tooltip', () => {
  const d = fresh();
  d.games[0].option = ULTIMATE;
  const m = S.lineModel(d.games[0], d, NOW);
  assert.equal(m.edition, '指定版本');
  assert.equal(m.title, `追蹤 《電馭叛客 2077：終極版》（使用者指定），不是這一列顯示的版本\n${PROBABILITY_TITLE}\n第 1 個原因\n第 2 個原因\n第 3 個原因`);
  d.refresh_note = '上次更新失敗';
  assert.match(S.lineModel(d.games[0], d, NOW).title, /^上次更新失敗\n追蹤 /);    // FR-007: the update failure stays first
  const na = S.lineModel({...d.games[2], option: ULTIMATE}, d, NOW);
  assert.equal(na.edition, '指定版本');
});

test('the Steam default, or a choice equal to it, is not tagged', () => {
  const d = fresh();
  for (const option of [undefined, null, {...ULTIMATE, user: false}]) {
    d.games[0].option = option;
    assert.equal(S.lineModel(d.games[0], d, NOW).edition, null);
    assert.equal(S.popupModel({ok: true, data: d}, NOW).groups[0].rows[0].edition, null);
  }
});

test('a user-chosen edition is tagged in the popup, saying the prices are that edition\'s', () => {
  const d = fresh();
  d.games[0].option = ULTIMATE;
  d.games[2].option = {kind: 'sub', id: 5, name: null, user: true};
  const rows = S.popupModel({ok: true, data: d}, NOW).groups.flatMap(g => g.rows);
  assert.deepEqual(rows.find(r => r.appId === d.games[0].app_id).edition,
                   {tag: '指定版本', title: '追蹤 《電馭叛客 2077：終極版》（使用者指定）：現價與甜蜜價都是這個版本的價格，不是 Steam 預設版本'});
  assert.equal(rows.find(r => r.appId === d.games[2].app_id).edition.title.startsWith('追蹤 sub/5（使用者指定）'), true);
});

// --- T031: stale data and update failures in all three places (FR-007) ------------------------------------------

test('stale warning in the popup, the panel and the wishlist line', () => {
  const at = h => data({data_time: new Date(NOW - h * HOUR).toISOString().replace(/\.\d+Z$/, 'Z')});
  const old = at(27);
  const recent = at(25);
  assert.equal(S.popupModel({ok: true, data: old}, NOW).stale, '資料超過 26 小時，請先執行更新');
  assert.equal(S.panelModel(old.games[0], null, false, old, NOW).stale, '資料超過 26 小時，請先執行更新');
  assert.equal(S.lineModel(old.games[0], old, NOW).stale, true);
  assert.equal(S.popupModel({ok: true, data: recent}, NOW).stale, null);
  assert.equal(S.panelModel(recent.games[0], null, false, recent, NOW).stale, null);
  assert.equal(S.lineModel(recent.games[0], recent, NOW).stale, false);
});

test('update failure note in the popup, the panel and first in the line tooltip', () => {
  const d = {...fresh(), refresh_note: '本次資料更新失敗，使用既有資料'};
  assert.equal(S.popupModel({ok: true, data: d}, NOW).refreshNote, '本次資料更新失敗，使用既有資料');
  assert.equal(S.panelModel(d.games[0], null, false, d, NOW).refreshNote, '本次資料更新失敗，使用既有資料');
  assert.equal(S.lineModel(d.games[0], d, NOW).title.split('\n')[0], '本次資料更新失敗，使用既有資料');
  assert.equal(S.lineModel(d.games[2], d, NOW).title, '本次資料更新失敗，使用既有資料\n尚未發行（預定 2026-11-20）');
});

// --- feature 015: the version section, two-click confirm, the worker's relay check (tasks T009) ---------------

const ULT = {kind: 'bundle', id: 32470, name: '《電馭叛客 2077：終極版》', price_twd: 882, cut_pct: 60, is_default: false,
             tracked: true, action: null, reason: null, manual: null};
const BASE = {kind: 'sub', id: 367653, name: 'Cyberpunk 2077', price_twd: 479, cut_pct: 70, is_default: true,
              tracked: false, action: 'reset', reason: null, manual: '刪掉設定檔 [purchase_options] 中 1091500 那一行'};
const DLX = {kind: 'sub', id: 9, name: 'Deluxe', price_twd: null, cut_pct: null, is_default: false, tracked: false,
             action: 'choose', reason: null, manual: '1091500 = "sub/9"'};
const BAD = {kind: 'sub', id: 5, name: null, price_twd: 900, cut_pct: 10, is_default: false, tracked: false,
             action: null, reason: '沒有 ITAD 的價格歷史，不能指定', manual: null};
const cyber = (versions = [ULT, BASE, DLX, BAD]) => ({app_id: 1091500, name: 'Cyberpunk 2077', group: 'wait',
  option: {kind: 'bundle', id: 32470, name: ULT.name, user: true}, versions});
const ready = (choice = 'bundle/32470') => ({state: 'ready', choice});

test('constants the end-to-end check replaces in its copy', () => {
  assert.equal(S.HOST_NAME, 'com.sweetspot.edition');
  assert.equal(S.CONFIRM_MS, 5000);
  assert.equal(S.WAIT_MS, 60000);
});

test('no version section for one option or none', () => {
  assert.equal(S.versionsModel(cyber([ULT]), ready()), null);
  assert.equal(S.versionsModel(cyber([]), ready()), null);
  assert.equal(S.versionsModel({...cyber(), versions: undefined}, ready()), null);   // an older data file
});

test('the version rows when the local program is ready', () => {
  const m = S.versionsModel(cyber(), ready());
  assert.equal(m.title, '版本（4）');
  assert.equal(m.notice, null);
  assert.deepEqual(m.rows.map(r => [r.ref, r.name, r.price, r.label]), [
    ['bundle/32470', '《電馭叛客 2077：終極版》', 'NT$882 -60%', '追蹤中（使用者指定）'],
    ['sub/367653', 'Cyberpunk 2077', 'NT$479 -70%', 'Steam 預設'],
    ['sub/9', 'Deluxe', '未知', ''],
    ['sub/5', 'sub/5', 'NT$900 -10%', ''],
  ]);
  assert.deepEqual(m.rows.map(r => r.button && [r.button.action, r.button.text]),
                   [null, ['reset', '改回 Steam 預設'], ['choose', '追蹤這個版本'], null]);
  assert.deepEqual(m.rows.map(r => r.help), [null, null, null, null]);
  assert.deepEqual(m.rows.map(r => r.manual), [null, null, null, null]);
  assert.equal(m.rows[3].reason, '沒有 ITAD 的價格歷史，不能指定');
  const steam = S.versionsModel(cyber([{...BASE, tracked: true, action: null, manual: null},
                                       {...ULT, tracked: false, action: 'choose', manual: '1091500 = "bundle/32470"'}]),
                                ready(null));
  assert.equal(steam.rows[0].label, '追蹤中（Steam 預設）');
});

test('while checking, and before the check, the buttons wait', () => {
  for (const host of [{state: 'checking'}, {state: 'unknown'}]) {
    const m = S.versionsModel(cyber(), host);
    assert.deepEqual(m.rows.map(r => r.help), [null, '檢查本機程式…', '檢查本機程式…', null]);
    assert.ok(m.rows.every(r => r.button === null));
  }
});

const INSTALL = '要在這裡直接指定版本：在 SweetSpot 資料夾（extension 資料夾的上一層）開啟命令列，執行 ' +
                'uv run sweetspot host install，然後重新整理這一頁。在那之前，可以照下面各版本的步驟手動指定。';
const BY_HAND_CHOOSE = '手動指定：用記事本打開 SweetSpot 資料夾的 sweetspot.toml，在 [purchase_options] 那一行的下面加上' +
                       '下面這一行（沒有 [purchase_options] 就在檔案最後先加上它），存檔後執行 更新資料.cmd，再重新整理這一頁。';
const BY_HAND_RESET = '手動改回：用記事本打開 SweetSpot 資料夾的 sweetspot.toml，在 [purchase_options] 下面找到以「1091500 =」' +
                      '開頭的那一行，整行刪掉，存檔後執行 更新資料.cmd，再重新整理這一頁。';
const text = segments => (segments === null ? null : S.segmentsText(segments));
const codes = segments => (segments || []).filter(s => typeof s !== 'string').map(s => s.code);

test('without the local program: how to install it, and each version\'s steps by hand (feature 015 US2)', () => {
  const none = S.versionsModel(cyber(), {state: 'not-installed'});
  assert.equal(text(none.guide), INSTALL);
  assert.deepEqual(codes(none.guide), ['uv run sweetspot host install']);          // the command can be copied
  assert.deepEqual(none.rows.map(r => text(r.help)), [null, BY_HAND_RESET, BY_HAND_CHOOSE, null]);
  assert.deepEqual(none.rows.map(r => r.manual), [null, null, DLX.manual, null]);   // only a line to add is copied
  const moved = S.versionsModel(cyber(), {state: 'unavailable', message: 'Native host has exited.'});   // folder moved
  assert.equal(text(moved.guide), '本機程式無法使用（Chrome：Native host has exited.）：在 SweetSpot 資料夾重新執行 ' +
               'uv run sweetspot host install（專案資料夾搬家後會這樣），然後重新整理這一頁。在那之前，可以照下面各版本的步驟手動指定。');
  assert.deepEqual(moved.rows.map(r => text(r.help)), [null, BY_HAND_RESET, BY_HAND_CHOOSE, null]);
  assert.deepEqual(moved.rows.map(r => r.manual), [null, null, DLX.manual, null]);
  for (const m of [none, moved]) {
    assert.ok(m.rows.every(r => r.button === null));
    assert.deepEqual(m.rows.map(r => r.reason), [null, null, null, BAD.reason]);   // action null: only the reason
    assert.equal(m.notice, null);
  }
  assert.match(text(S.versionsModel(cyber(), {state: 'unavailable'}).guide), /^本機程式無法使用（Chrome：未知的錯誤）：/);
  for (const host of [ready(), {state: 'checking'}, {state: 'unknown'}]) {
    assert.equal(S.versionsModel(cyber(), host).guide, null);
  }
});

test('with the settings file\'s path from the data file, the steps name it in full (2026-10-14)', () => {
  const path = 'D:\\Tools\\SweetSpot\\sweetspot.toml';
  const none = S.versionsModel(cyber(), {state: 'not-installed'}, path);
  assert.equal(text(none.guide), '要在這裡直接指定版本：在 D:\\Tools\\SweetSpot 開啟命令列，執行 ' +
               'uv run sweetspot host install，然後重新整理這一頁。在那之前，可以照下面各版本的步驟手動指定。');
  assert.deepEqual(codes(none.guide), ['D:\\Tools\\SweetSpot', 'uv run sweetspot host install']);
  const [, reset, choose] = none.rows;
  assert.equal(text(choose.help), '手動指定：用記事本打開 D:\\Tools\\SweetSpot\\sweetspot.toml，在 [purchase_options] ' +
               '那一行的下面加上下面這一行（沒有 [purchase_options] 就在檔案最後先加上它），存檔後執行 更新資料.cmd，再重新整理這一頁。');
  assert.equal(text(reset.help), '手動改回：用記事本打開 D:\\Tools\\SweetSpot\\sweetspot.toml，在 [purchase_options] ' +
               '下面找到以「1091500 =」開頭的那一行，整行刪掉，存檔後執行 更新資料.cmd，再重新整理這一頁。');
  assert.deepEqual(codes(choose.help), [path]);
  const moved = S.versionsModel(cyber(), {state: 'unavailable', message: 'x'}, path);
  assert.match(text(moved.guide), /：在 D:\\Tools\\SweetSpot 重新執行 uv run sweetspot host install（/);
  assert.equal(text(S.versionsModel(cyber(), {state: 'not-installed'}, '/home/me/SweetSpot/sweetspot.toml').guide)
    .startsWith('要在這裡直接指定版本：在 /home/me/SweetSpot 開啟命令列'), true);
  for (const bad of [null, undefined, '', 42]) {                                   // an older data file, or junk
    assert.equal(text(S.versionsModel(cyber(), {state: 'not-installed'}, bad).guide), INSTALL);
  }
  assert.equal(S.segmentsText(['a', {code: 'b'}, 'c']), 'abc');
  assert.equal(S.segmentsText('plain'), 'plain');
});

test('a settings file that changed after the report is pointed out', () => {
  assert.equal(S.versionsModel(cyber(), ready('sub/9')).notice, '設定檔已指定 Deluxe，報告還沒重新產生');
  assert.equal(S.versionsModel(cyber(), ready(null)).notice, '設定檔已改回 Steam 預設，報告還沒重新產生');
  assert.equal(S.versionsModel(cyber(), ready('sub/777')).notice, null);    // not choosable: the report explains it
  assert.equal(S.versionsModel(cyber(), {state: 'not-installed'}).notice, null);
});

test('an unavailable local program is explained once (014 T081)', () => {
  // content.js kept replyText's whole sentence as the message, and the versions section wrapped it again
  const host = S.hostState({ok: false, code: 'unavailable', message: 'Native host has exited.'});
  const text = S.segmentsText(S.versionsModel(cyber(), host).guide);
  assert.equal(text.split('本機程式無法使用').length - 1, 1, text);
  assert.ok(text.includes('（Chrome：Native host has exited.）'), text);
  assert.deepEqual(S.hostState({ok: true, choice: 'sub/9', config_ok: false}), {state: 'ready', choice: 'sub/9', config_ok: false});
  assert.deepEqual(S.hostState({ok: false, code: 'not-installed'}), {state: 'not-installed'});
  assert.equal(S.hostState(null).state, 'unavailable');
});

test('a settings file that cannot be read says nothing about what it holds (014 T068)', () => {
  // config_ok false: the local program could not read the choice, so its choice is null, not "back to the default"
  assert.equal(S.versionsModel(cyber(), {state: 'ready', choice: null, config_ok: false}).notice, null);
  assert.equal(S.versionsModel(cyber(), {state: 'ready', choice: null, config_ok: true}).notice,
    '設定檔已改回 Steam 預設，報告還沒重新產生');
});

test('two clicks within five seconds send; anything else does not', () => {
  const T = 1_000_000;
  const press = (key, trusted = true) => ({type: 'press', key, trusted});
  let r = S.confirmStep({phase: 'idle'}, press('sub/9'), T);
  assert.deepEqual(r, {state: {phase: 'confirm', key: 'sub/9', at: T}, send: false});
  assert.deepEqual(S.confirmStep(r.state, press('sub/9'), T + 5000), {state: {phase: 'sending', key: 'sub/9'}, send: true});
  assert.deepEqual(S.confirmStep(r.state, press('sub/9'), T + 5001).send, false);           // too late: asks again
  assert.deepEqual(S.confirmStep(r.state, press('sub/9'), T + 5001).state, {phase: 'confirm', key: 'sub/9', at: T + 5001});
  assert.deepEqual(S.confirmStep(r.state, {type: 'tick'}, T + 4999).state, r.state);
  assert.deepEqual(S.confirmStep(r.state, {type: 'tick'}, T + 5001).state, {phase: 'idle'});
  assert.deepEqual(S.confirmStep(r.state, {type: 'elsewhere', trusted: true}, T + 10).state, {phase: 'idle'});
  const other = S.confirmStep(r.state, press('sub/367653'), T + 10);                        // another button
  assert.deepEqual(other, {state: {phase: 'confirm', key: 'sub/367653', at: T + 10}, send: false});
  assert.deepEqual(S.confirmStep(r.state, press('sub/9', false), T + 10), {state: r.state, send: false});
  assert.deepEqual(S.confirmStep({phase: 'idle'}, press('sub/9', false), T), {state: {phase: 'idle'}, send: false});
  const sending = {phase: 'sending', key: 'sub/9'};
  assert.deepEqual(S.confirmStep(sending, press('sub/9'), T), {state: sending, send: false});
  assert.deepEqual(S.confirmStep(sending, {type: 'done'}, T).state, {phase: 'idle'});
});

test('button texts for each step', () => {
  const [, base, dlx] = S.versionsModel(cyber(), ready()).rows;
  assert.equal(S.buttonText(dlx, {phase: 'idle'}), '追蹤這個版本');
  assert.equal(S.buttonText(dlx, {phase: 'confirm', key: 'sub/9'}), '確定追蹤《Deluxe》？再按一次');
  assert.equal(S.buttonText(base, {phase: 'confirm', key: 'sub/367653'}), '確定改回 Steam 預設？再按一次');
  assert.equal(S.buttonText(dlx, {phase: 'confirm', key: 'sub/367653'}), '追蹤這個版本');
  assert.equal(S.progressText('choose', '《電馭叛客 2077：終極版》'), '正在指定《電馭叛客 2077：終極版》並重新產生報告…');
  assert.equal(S.progressText('reset', 'Cyberpunk 2077'), '正在改回 Steam 預設並重新產生報告…');
  assert.equal(S.WAIT_TEXT, '報告仍在產生，完成後重新整理頁面即可看到');
});

test('what the panel says after the reply', () => {
  assert.equal(S.replyText('choose', '《電馭叛客 2077：終極版》', {ok: true, changed: true}), '已改為追蹤《電馭叛客 2077：終極版》');
  assert.equal(S.replyText('reset', 'Cyberpunk 2077', {ok: true, changed: true}), '已改回 Steam 預設');
  assert.equal(S.replyText('choose', 'X', {ok: true, changed: false}), '設定已經是這樣，不需要重新產生報告');
  assert.equal(S.replyText('choose', 'X', {ok: false, code: 'busy-update', message: '背景更新進行中，請稍後再試'}),
               '背景更新進行中，請稍後再試');
  assert.equal(S.replyText('choose', 'X', {ok: false, code: 'refused'}), '這個請求不符合目前的資料，沒有送出（請重新整理頁面）');
  assert.equal(S.replyText('choose', 'X', {ok: false, code: 'not-installed', message: 'Specified native messaging host not found.'}),
               '找不到本機程式（可能已經移除），沒有改任何設定');
  assert.equal(S.replyText('choose', 'X', {ok: false, code: 'unavailable', message: 'Native host has exited.'}),
               '本機程式無法使用（Chrome：Native host has exited.）：在 SweetSpot 資料夾重新執行 ' +
               'uv run sweetspot host install（專案資料夾搬家後會這樣），然後重新整理這一頁。');
  assert.equal(S.replyText('choose', 'X', null), '本機程式沒有回覆');
});

test('the choice the data file was made with', () => {
  assert.equal(S.trackedChoice(cyber()), 'bundle/32470');
  assert.equal(S.trackedChoice({option: {kind: 'sub', id: 1, user: false}}), null);
  assert.equal(S.trackedChoice({option: null}), null);
});

const GAME_URL = 'https://store.steampowered.com/app/1091500/Cyberpunk_2077/';
const relayData = () => ({games: [cyber()]});

test('the worker forwards only well-formed requests for the game on the sending tab', () => {
  assert.deepEqual(S.relayCheck(relayData(), GAME_URL, {type: 'host', cmd: 'status', app: 1091500}),
                   {v: 1, cmd: 'status', app: 1091500});
  assert.deepEqual(S.relayCheck(relayData(), GAME_URL, {type: 'host', cmd: 'choose', app: 1091500, option: 'sub/9'}),
                   {v: 1, cmd: 'choose', app: 1091500, option: 'sub/9'});
  assert.deepEqual(S.relayCheck(relayData(), GAME_URL, {type: 'host', cmd: 'choose', app: 1091500, option: 'sub/367653'}),
                   {v: 1, cmd: 'choose', app: 1091500, option: 'sub/367653'});         // the default: same as reset
  assert.deepEqual(S.relayCheck(relayData(), 'https://store.steampowered.com/app/1091500', {type: 'host', cmd: 'reset', app: 1091500}),
                   {v: 1, cmd: 'reset', app: 1091500});
});

test('the worker refuses everything else (feature 015 US3, tasks T028)', () => {
  const ok = {type: 'host', cmd: 'choose', app: 1091500, option: 'sub/9'};
  const cases = [
    ['another game page', relayData(), 'https://store.steampowered.com/app/730/', ok],
    ['another site', relayData(), 'https://evil.example/app/1091500/', ok],
    ['a look-alike host', relayData(), 'https://store.steampowered.com.evil.example/app/1091500/', ok],
    ['plain http', relayData(), 'http://store.steampowered.com/app/1091500/', ok],
    ['the app id only as a prefix', relayData(), 'https://store.steampowered.com/app/10915000/', ok],
    ['the wishlist page', relayData(), 'https://store.steampowered.com/wishlist/profiles/1/', ok],
    ['no tab address (the popup)', relayData(), undefined, ok],
    ['an empty tab address', relayData(), '', ok],
    ['app different from the address', relayData(), 'https://store.steampowered.com/app/1091500/', {...ok, app: 730}],
    ['a game not in the data', {games: [{...cyber(), app_id: 730}]}, 'https://store.steampowered.com/app/1091500/', ok],
    ['no data file', null, GAME_URL, ok],
    ['a version not in versions', relayData(), GAME_URL, {...ok, option: 'sub/12345'}],
    ['a version with action null (tracked)', relayData(), GAME_URL, {...ok, option: 'bundle/32470'}],
    ['a version with action null (refused)', relayData(), GAME_URL, {...ok, option: 'sub/5'}],
    ['reset with nothing to go back from', {games: [cyber([{...BASE, tracked: true, action: null}, DLX])]}, GAME_URL,
     {type: 'host', cmd: 'reset', app: 1091500}],
    ['choose without an option', relayData(), GAME_URL, {type: 'host', cmd: 'choose', app: 1091500}],
    ['option not a string', relayData(), GAME_URL, {...ok, option: 9}],
    ['an unknown command', relayData(), GAME_URL, {...ok, cmd: 'update'}],
    ['a data request', relayData(), GAME_URL, {type: 'data'}],
    ['app as a string', relayData(), GAME_URL, {...ok, app: '1091500'}],
    ['app as a fraction', relayData(), GAME_URL, {...ok, app: 1091500.5}],
    ['no message', relayData(), GAME_URL, null],
  ];
  for (const [label, data, url, msg] of cases) assert.equal(S.relayCheck(data, url, msg), null, label);
  const extra = S.relayCheck(relayData(), GAME_URL, {...ok, path: 'C:/x', args: ['--as-of'], v: 2, type: 'host'});
  assert.deepEqual(extra, {v: 1, cmd: 'choose', app: 1091500, option: 'sub/9'});      // only the allowed fields go on
  assert.deepEqual(S.relayCheck(relayData(), GAME_URL, {type: 'host', cmd: 'status', app: 1091500, option: 'sub/9'}),
                   {v: 1, cmd: 'status', app: 1091500});
});

// --- feature 015 US4: shortcuts in Steam's own purchase boxes (tasks T030) -----------------------------------

const box = (ids, hasAction = true) => ({subid: null, bundleid: null, priceFinal: '100', text: 'NT$ 1', hasAction, ...ids});

test('a shortcut for each purchase box that is a version the report knows', () => {
  const blocks = [box({subid: '367653'}), box({bundleid: '32470'}), box({subid: '999001'}), box({subid: '9'})];
  assert.deepEqual(S.shortcutPlan(blocks, cyber().versions), [
    {index: 0, ref: 'sub/367653', action: 'reset', name: 'Cyberpunk 2077', text: 'SweetSpot：改回 Steam 預設'},
    {index: 1, ref: 'bundle/32470', action: null, name: '《電馭叛客 2077：終極版》', text: 'SweetSpot：追蹤中'},
    {index: 3, ref: 'sub/9', action: 'choose', name: 'Deluxe', text: 'SweetSpot：追蹤這個版本'},
  ]);                                                       // the soundtrack (999001) is not a version: no shortcut
  const refused = S.shortcutPlan([box({subid: '5'}), box({subid: '367653'})], cyber().versions);
  assert.deepEqual(refused.map(s => s.ref), ['sub/367653']);           // action null and not tracked: nothing
});

test('a sub and a bundle with the same number are told apart', () => {
  const versions = [{...ULT, kind: 'bundle', id: 9}, {...DLX, kind: 'sub', id: 9}];
  assert.deepEqual(S.shortcutPlan([box({subid: '9'}), box({bundleid: '9'})], versions).map(s => [s.index, s.ref]),
                   [[0, 'sub/9'], [1, 'bundle/9']]);
});

test('no shortcut at all when the boxes cannot be read (do not guess, 011 FR-016)', () => {
  const v = cyber().versions;
  assert.deepEqual(S.shortcutPlan([box({subid: '367653'}), box({})], v), []);           // one box without ids
  assert.deepEqual(S.shortcutPlan([box({subid: '367653'}), box({subid: ''})], v), []);
  assert.deepEqual(S.shortcutPlan([box({subid: '367653'}, false)], v), []);             // no purchase button area
  assert.deepEqual(S.shortcutPlan([], v), []);
  assert.deepEqual(S.shortcutPlan([box({subid: '367653'})], [BASE]), []);              // one version: no choice
  assert.deepEqual(S.shortcutPlan([box({subid: '367653'})], undefined), []);           // an older data file
});

test('shortcut texts while confirming and without the local program', () => {
  const [base, , dlx] = S.shortcutPlan([box({subid: '367653'}), box({bundleid: '32470'}), box({subid: '9'})],
                                       cyber().versions);
  const idle = {phase: 'idle'};
  assert.equal(S.shortcutText(dlx, idle, {state: 'unknown'}), 'SweetSpot：追蹤這個版本');
  assert.equal(S.shortcutText(dlx, idle, ready()), 'SweetSpot：追蹤這個版本');
  assert.equal(S.shortcutText(dlx, {phase: 'confirm', key: 'sub/9'}, {state: 'checking'}), 'SweetSpot：確定追蹤《Deluxe》？再按一次');
  assert.equal(S.shortcutText(base, {phase: 'confirm', key: 'sub/367653'}, ready()), 'SweetSpot：確定改回 Steam 預設？再按一次');
  assert.equal(S.shortcutText(dlx, {phase: 'confirm', key: 'sub/367653'}, ready()), 'SweetSpot：追蹤這個版本');
  for (const host of [{state: 'not-installed'}, {state: 'unavailable', message: 'x'}]) {
    assert.equal(S.shortcutText(dlx, idle, host), '需要安裝本機程式（見 SweetSpot 面板）');
    assert.equal(S.shortcutText(base, idle, host), '需要安裝本機程式（見 SweetSpot 面板）');
  }
});

// --- a data file written before this extension version (2026-10-14, after merging 015) ------------------------

test('a data file without the fields this version reads says so in the panel', () => {
  const d = fresh();
  assert.equal(S.outdatedText(d), null);
  assert.equal(S.panelModel(d.games[0], null, false, d, NOW).outdated, null);
  const old = fresh();
  for (const g of old.games) delete g.versions;                     // what the report wrote before 015
  const text = '資料檔是舊版，部分功能不會顯示：請執行 更新資料.cmd 重新產生';
  assert.equal(S.outdatedText(old), text);
  assert.equal(S.panelModel(old.games[0], null, false, old, NOW).outdated, text);
  assert.equal(S.panelModel(old.games[2], null, false, old, NOW).outdated, text);   // also for an unpredictable game
  const one = fresh();
  delete one.games[1].versions;
  assert.equal(S.outdatedText(one), text);
  assert.equal(S.outdatedText({...fresh(), games: []}), null);
  assert.ok(S.GAME_FIELDS.includes('versions'));
});
