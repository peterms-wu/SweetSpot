// Prototype service worker: read data/steamsage-extension.json from the extension folder, set the badge,
// and answer content scripts. No other network access (connect-src 'self').
const DATA_URL = chrome.runtime.getURL('data/steamsage-extension.json');

async function readData() {
  try {
    const res = await fetch(DATA_URL, {cache: 'no-store'});
    if (!res.ok) return {ok: false, why: 'missing', status: res.status};
    const text = await res.text();
    try { return {ok: true, data: JSON.parse(text), bytes: text.length}; }
    catch (e) { return {ok: false, why: 'broken'}; }
  } catch (e) {
    return {ok: false, why: 'missing', error: String(e)};
  }
}

async function refreshBadge() {
  const r = await readData();
  if (!r.ok) {
    await chrome.action.setBadgeText({text: '!'});
    return r;
  }
  const now = (r.data.games || []).filter(g => g.group === 'now').length;
  await chrome.action.setBadgeText({text: now ? String(now) : ''});
  return r;
}

self.refreshBadge = refreshBadge;   // for the Playwright probe (sw.evaluate)
chrome.runtime.onStartup.addListener(refreshBadge);
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create('refresh', {periodInMinutes: 30});
  refreshBadge();
});
chrome.alarms.onAlarm.addListener(a => { if (a.name === 'refresh') refreshBadge(); });
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg && msg.type === 'data') {
    refreshBadge().then(reply);
    return true;
  }
  return false;
});
