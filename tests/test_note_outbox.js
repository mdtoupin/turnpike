// Exercise the real browser storage functions in two independent window scopes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../ui/index.html'), 'utf8');
const source = html.slice(html.indexOf('function readOutbox(){'), html.indexOf('function restoreOutbox(slug){'));
const saved = new Map();
let interleave;
const storage = {
  get length() { return saved.size; },
  key(i) { return [...saved.keys()][i] ?? null; },
  getItem(key) { return saved.get(key) ?? null; },
  setItem(key, value) { const f = interleave; interleave = null; if (f) f(); saved.set(key, value); },
  removeItem(key) { const f = interleave; interleave = null; if (f) f(); saved.delete(key); },
};
const makeWindow = () => {
  const scope = vm.createContext({localStorage: storage, toast() {}});
  vm.runInContext(source, scope);
  return scope;
};
const first = makeWindow(), second = makeWindow();
const a = {client_id: 'note-a', slug: 'room', attachments: []};
const b = {client_id: 'note-b', slug: 'room', attachments: []};
interleave = () => second.rememberOutbox(b);
assert.equal(first.rememberOutbox(a), true);
assert.deepEqual(Object.keys(first.readOutbox()).sort(), ['note-a', 'note-b']);
saved.clear();
first.rememberOutbox(a);
interleave = () => second.rememberOutbox(b);
first.forgetOutbox(a.client_id);
assert.deepEqual(Object.keys(second.readOutbox()), ['note-b']);
assert.equal(second.pendingPosts('room').length, 1);
assert.equal(first.pendingPosts('another-room').length, 0);
console.log('Outbox interleaved save/save and confirmation/save checks passed.');
