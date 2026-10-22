// 015 plan research R0: the probe's service worker. The probe script calls these through Playwright.
const HOST = 'com.sweetspot.prototype';

function lastError() {
  return chrome.runtime.lastError ? chrome.runtime.lastError.message : null;
}

self.probeSend = msg => new Promise(resolve => {
  const t0 = performance.now();
  chrome.runtime.sendNativeMessage(HOST, msg, r => resolve({r, err: lastError(), ms: Math.round(performance.now() - t0)}));
});

self.probeConnect = (msg, disconnectAfterMs) => new Promise(resolve => {
  const t0 = performance.now();
  let done = false;
  const finish = value => { if (!done) { done = true; resolve({...value, ms: Math.round(performance.now() - t0)}); } };
  const port = chrome.runtime.connectNative(HOST);
  port.onMessage.addListener(m => { finish({r: m}); port.disconnect(); });
  port.onDisconnect.addListener(() => finish({err: lastError() || 'disconnected'}));
  port.postMessage(msg);
  if (disconnectAfterMs) setTimeout(() => { port.disconnect(); finish({err: 'we disconnected'}); }, disconnectAfterMs);
});

// the content script asks the worker (content scripts cannot reach native hosts themselves)
chrome.runtime.onMessage.addListener((m, sender, reply) => {
  if (!m || m.type !== 'native') return false;
  self.probeSend({cmd: 'hello'}).then(r => reply({...r, sender: sender.url}));
  return true;
});
