// SweetSpot popup (feature 011; contracts/extension-ui.md). Opens only when the toolbar icon is clicked (FR-009).
// Every number and sentence comes from the data file through SweetSpot.popupModel; this file only builds the DOM.
(() => {
  'use strict';
  const S = globalThis.SweetSpot;

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === 'class') node.className = v;
      else if (k === 'text') node.textContent = v;
      else node.setAttribute(k, v);
    }
    for (const c of children) if (c !== null && c !== undefined) node.append(c);
    return node;
  }

  const link = (url, text) => el('a', {href: url, target: '_blank', rel: 'noopener', text});
  const num = (label, value, cls, title) => el('span', {...(cls ? {class: cls} : {}), ...(title ? {title} : {})},
                                               `${label} `, el('b', {text: value}));

  function row(r) {
    const edition = r.edition ? el('span', {class: 'edition', title: r.edition.title, text: r.edition.tag}) : null;
    if (r.reason !== undefined) {
      return el('div', {class: 'row'}, link(r.url, r.name), edition, el('div', {class: 'reason', text: r.reason}));
    }
    return el('div', {class: 'row'}, link(r.url, r.name), edition,
              el('div', {class: 'nums'}, num('現價', r.price), num('甜蜜價', r.sweet, 'sweet'), num('時點', r.point),
                 num('到價機率', r.probability, null, r.probabilityTitle)));
  }

  function render(result) {
    const meta = document.getElementById('meta');
    const notes = document.getElementById('notes');
    const main = document.getElementById('main');
    const m = S.popupModel(result, Date.now());
    meta.dataset.state = result && result.ok ? 'ok' : ((result && result.why) || 'missing');
    if (m.error) {
      meta.textContent = '';
      main.append(el('p', {class: 'error', text: m.error}));
      return;
    }
    meta.textContent = m.header.join(' ');
    if (m.stale) notes.append(el('p', {class: 'warn', text: m.stale}));
    if (m.refreshNote) notes.append(el('p', {class: 'warn', text: m.refreshNote}));
    for (const notice of m.calendarNotices) notes.append(el('p', {class: 'warn', 'data-kind': 'calendar', text: notice}));
    if (m.referenceNotice) notes.append(el('p', {class: 'warn', 'data-kind': 'reference', text: m.referenceNotice}));
    notes.append(el('p', {class: 'hint', text: m.hint}));
    for (const g of m.groups) {
      const dot = el('span', {class: 'dot'});
      dot.style.background = g.color;
      const details = el('details', {class: 'group', 'data-group': g.key}, el('summary', {}, dot, g.title));
      details.open = g.open;
      if (g.rows.length) g.rows.forEach(r => details.append(row(r)));
      else details.append(el('p', {class: 'empty', text: '沒有遊戲'}));
      main.append(details);
    }
    if (m.bundles.length) {
      main.append(el('h2', {text: `組合包（${m.bundles.length}）`}));
      for (const b of m.bundles) {
        main.append(el('div', {class: 'row bundle'}, link(b.url, b.name), el('span', {class: 'tag', text: `${b.grade} · ${b.discount}`}),
                       el('div', {class: 'reason', text: b.text})));
      }
    }
  }

  try {
    chrome.runtime.sendMessage({type: 'data'}, result => render(chrome.runtime.lastError ? null : result));
  } catch (e) {
    render(null);
  }
})();
