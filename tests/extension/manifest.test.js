// feature 011: extension/manifest.json matches contracts/extension-ui.md (tasks T014).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const EXT = path.join(__dirname, '..', '..', 'extension');
const m = JSON.parse(fs.readFileSync(path.join(EXT, 'manifest.json'), 'utf8'));
const CSP = "default-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self'; style-src 'self'; object-src 'none'";

test('MV3 with only the alarms and native messaging permissions (015 FR-021)', () => {
  assert.equal(m.manifest_version, 3);
  assert.deepEqual(m.permissions, ['alarms', 'nativeMessaging']);
  for (const key of ['host_permissions', 'optional_permissions', 'optional_host_permissions', 'web_accessible_resources',
                     'externally_connectable']) {
    assert.equal(m[key], undefined, key);
  }
});

test('a public key fixes the extension id (015 plan D1); 1.2.0 is the renamed extension (016 research R9)', () => {
  assert.equal(m.version, '1.2.4');                       // 1.2.4: the unavailable notice is said once (014 T081)
  assert.match(m.key, /^[A-Za-z0-9+/]+={0,2}$/);
  const der = Buffer.from(m.key, 'base64');
  assert.equal(der.toString('base64'), m.key);            // valid base64, no stray characters
  assert.ok(der.length > 250 && der[0] === 0x30, 'an RSA SubjectPublicKeyInfo (DER sequence)');
});

test('extension pages cannot connect anywhere else', () => {
  assert.equal(m.content_security_policy.extension_pages, CSP);
});

test('content scripts only on Steam game and wishlist pages', () => {
  assert.equal(m.content_scripts.length, 1);
  const cs = m.content_scripts[0];
  assert.deepEqual(cs.matches, ['https://store.steampowered.com/app/*', 'https://store.steampowered.com/wishlist/*']);
  assert.deepEqual(cs.js, ['lib.js', 'content.js']);
  assert.equal(cs.run_at, 'document_idle');
  assert.equal(cs.all_frames, undefined);
});

test('popup, service worker and icons', () => {
  assert.equal(m.action.default_popup, 'popup.html');
  assert.equal(m.background.service_worker, 'sw.js');
  assert.equal(m.background.type, undefined);            // classic worker: importScripts('lib.js')
  for (const size of ['16', '32', '48', '128']) {
    assert.equal(m.icons[size], `icons/icon-${size}.png`);
    assert.ok(fs.existsSync(path.join(EXT, m.icons[size])), size);
  }
  for (const file of ['popup.html', 'popup.js', 'popup.css', 'sw.js', 'lib.js', 'content.js']) {
    assert.ok(fs.existsSync(path.join(EXT, file)), file);
  }
});
