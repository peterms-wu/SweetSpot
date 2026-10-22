// 015 plan research R0: which clicks reach the content script as real user input (spec FR-006a, SC-008)?
// The host element records one letter per click: T (event.isTrusted) or F. A trusted click on #ask also asks the
// native host (through the worker) and stores the round trip.
(() => {
  const host = document.createElement('div');
  host.id = 'probe-host';
  const root = host.attachShadow({mode: 'open'});        // same mode as the real panel (011)
  const button = document.createElement('button');
  button.id = 'b';
  button.textContent = 'probe';
  const ask = document.createElement('button');
  ask.id = 'ask';
  ask.textContent = 'ask';
  root.append(button, ask);
  host.dataset.clicks = '';
  button.addEventListener('click', e => { host.dataset.clicks += e.isTrusted ? 'T' : 'F'; });
  ask.addEventListener('click', e => {
    if (!e.isTrusted) { host.dataset.native = 'refused: untrusted'; return; }
    chrome.runtime.sendMessage({type: 'native'}, r => { host.dataset.native = JSON.stringify(r); });
  });
  document.body.append(host);
})();
