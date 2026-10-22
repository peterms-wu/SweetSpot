// feature 011: the extension makes no network requests and treats page text as data (tasks T015; FR-004, SC-005).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const EXT = path.join(__dirname, '..', '..', 'extension');
const read = f => fs.readFileSync(path.join(EXT, f), 'utf8');
const PAGE_SCRIPTS = ['content.js', 'lib.js', 'popup.js'];
const ALL = [...PAGE_SCRIPTS, 'sw.js'];
const NETWORK = [/\bfetch\s*\(/, /XMLHttpRequest/, /WebSocket/, /EventSource/, /sendBeacon/, /importScripts\s*\(/,
                 /\bnew\s+Image\b/, /navigator\.connection/];
const ALLOWED_URLS = ['https://store.steampowered.com/app/', 'https://store.steampowered.com/bundle/'];

test('page scripts contain no network API', () => {
  for (const f of PAGE_SCRIPTS) {
    const src = read(f);
    for (const re of NETWORK) assert.doesNotMatch(src, re, `${f}: ${re}`);
  }
});

test('the service worker only fetches its own data file', () => {
  const src = read('sw.js');
  const calls = src.match(/\bfetch\s*\([^)]*/g) || [];
  assert.equal(calls.length, 1);
  assert.match(calls[0], /fetch\s*\(\s*DATA_URL/);
  assert.match(src, /const DATA_URL = chrome\.runtime\.getURL\('data\/sweetspot-extension\.json'\)/);
  assert.deepEqual(src.match(/importScripts\s*\([^)]*\)/g), ["importScripts('lib.js')"]);
});

test('no URLs except links to Steam store pages', () => {
  for (const f of ALL) {
    for (const url of read(f).match(/https?:\/\/[^\s'"`)]+/g) || []) {
      assert.ok(ALLOWED_URLS.some(a => url.startsWith(a)), `${f}: ${url}`);
    }
  }
});

test('only the service worker talks to the local program, one message at a time (015 research R6)', () => {
  for (const f of PAGE_SCRIPTS) assert.doesNotMatch(read(f), /sendNativeMessage|connectNative/, f);
  const sw = read('sw.js');
  assert.equal((sw.match(/sendNativeMessage\s*\(/g) || []).length, 1);
  assert.match(sw, /sendNativeMessage\(SweetSpot\.HOST_NAME, request,/);   // the request relayCheck built
  assert.doesNotMatch(sw, /connectNative/);
});

// feature 016: the pre-016 name, built here so this file does not spell it (scripts/scan_names.py).
const OLD_NAME = ['steam', 'sage'].join('');
const KEPT_FORMAT = new RegExp(OLD_NAME + '\\.extension/1', 'g');   // the data format name stays (016 contracts/names.md §2)

test('only the new name in the extension, except the data format name (016 FR-003)', () => {
  for (const f of [...ALL, 'popup.html', 'popup.css', 'manifest.json']) {
    const src = read(f).replace(KEPT_FORMAT, '');
    assert.ok(!src.toLowerCase().includes(OLD_NAME), f);
  }
  const content = read('content.js');
  const classes = new Set(content.match(/'(?:[a-z]+-)+(?:panel|line|shortcut)'/g));
  assert.deepEqual([...classes].sort(), ["'sweetspot-line'", "'sweetspot-panel'", "'sweetspot-shortcut'"]);
  assert.match(read('lib.js'), /root\.SweetSpot = SweetSpot;/);
  assert.match(read('sw.js'), /self\.sweetspotRefresh = refresh;/);
});

test('no cookies, storage or HTML built from strings', () => {
  for (const f of ALL) {
    const src = read(f);
    assert.doesNotMatch(src, /document\.cookie|chrome\.cookies|chrome\.storage|localStorage|indexedDB/, f);
    assert.doesNotMatch(src, /\.innerHTML\s*=|\.outerHTML\s*=|insertAdjacentHTML|document\.write/, f);
    assert.doesNotMatch(src, /\beval\s*\(|new Function\s*\(/, f);
  }
});
