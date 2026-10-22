// SweetSpot service worker (feature 011; contracts/extension-ui.md; research R0.1).
// Reads the data file in this extension's own folder on every request (no cache), keeps the toolbar badge current,
// and answers the popup and the content script. It makes no other request (CSP connect-src 'self').
importScripts('lib.js');

const DATA_URL = chrome.runtime.getURL('data/sweetspot-extension.json');
const ALARM = 'refresh';

async function readData() {
  let text;
  try {
    const res = await fetch(DATA_URL, {cache: 'no-store'});
    if (!res.ok) return {ok: false, why: 'missing'};
    text = await res.text();
  } catch (e) {
    return {ok: false, why: 'missing'};
  }
  let data;
  try {
    data = JSON.parse(text);
  } catch (e) {
    return {ok: false, why: 'broken'};           // half written or damaged: read again next time
  }
  const check = SweetSpot.checkData(data);
  return check.ok ? {ok: true, data} : check;
}

async function refresh() {
  const result = await readData();
  const b = SweetSpot.badge(result, Date.now());
  try {
    await chrome.action.setBadgeText({text: b.text});
    await chrome.action.setBadgeBackgroundColor({color: b.color});
  } catch (e) {
    // the badge is a hint; never let it break an answer
  }
  if (result.ok) result.stale = SweetSpot.isStale(result.data, Date.now());
  return result;
}

async function ensureAlarm() {
  const existing = await chrome.alarms.get(ALARM);
  if (!existing) await chrome.alarms.create(ALARM, {periodInMinutes: 30});
}

self.sweetspotRefresh = refresh;                  // used by tests/extension/e2e.py to run the alarm's work

// Feature 015 (contracts/extension-ui.md "訊息"): the content script asks for the local program through the worker.
// relayCheck is the first check (the sending tab is this game's page, the version is one the data file offers);
// the local program checks again against its own settings file and database.
const NOT_FOUND = /native messaging host not found/i;

function callHost(request) {
  return new Promise(resolve => {
    try {
      chrome.runtime.sendNativeMessage(SweetSpot.HOST_NAME, request, answer => {
        const err = chrome.runtime.lastError;
        if (err) resolve({ok: false, code: NOT_FOUND.test(err.message || '') ? 'not-installed' : 'unavailable',
                          message: err.message || ''});
        else resolve(answer && typeof answer === 'object' ? answer : {ok: false, code: 'unavailable', message: '沒有回覆'});
      });
    } catch (e) {
      resolve({ok: false, code: 'unavailable', message: String((e && e.message) || e)});
    }
  });
}

async function askHost(message, sender) {
  const data = await readData();
  const request = data.ok ? SweetSpot.relayCheck(data.data, sender && sender.url, message) : null;
  if (!request) return {ok: false, code: 'refused'};
  const answer = await callHost(request);
  if (answer.ok && answer.changed) {
    const fresh = await refresh();                // the report rewrote the data file: show the new numbers (FR-011)
    if (fresh.ok) answer.data = fresh.data;
  }
  return answer;
}

chrome.runtime.onInstalled.addListener(() => { ensureAlarm(); refresh(); });
chrome.runtime.onStartup.addListener(() => { ensureAlarm(); refresh(); });
chrome.alarms.onAlarm.addListener(alarm => { if (alarm.name === ALARM) refresh(); });
chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (message && message.type === 'host') {
    askHost(message, sender).then(reply, () => reply({ok: false, code: 'unavailable', message: ''}));
    return true;
  }
  if (!message || message.type !== 'data') return false;
  refresh().then(reply, () => reply({ok: false, why: 'missing'}));
  return true;                                    // reply asynchronously
});
