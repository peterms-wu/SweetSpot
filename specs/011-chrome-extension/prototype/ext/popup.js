chrome.runtime.sendMessage({type: 'data'}, r => {
  const el = document.getElementById('stamp');
  el.textContent = r && r.ok ? `as_of=${r.data.as_of} games=${(r.data.games || []).length}` : `no data: ${r && r.why}`;
  el.dataset.ok = r && r.ok ? '1' : '0';
});
