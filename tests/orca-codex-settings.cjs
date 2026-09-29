'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { DatabaseSync } = require('node:sqlite');
const { configure, hash, ActionRequired } = require('../windows/orca-codex-settings.cjs');
function fixture(t, { sqlite = true, command, wal = false } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'orca-codex-'));
  t.after(() => { if (db) db.close(); fs.rmSync(root, { recursive: true, force: true }); });
  fs.writeFileSync(path.join(root, 'orca-profile-index.json'), JSON.stringify({ schemaVersion: 1, activeProfileId: 'local-default', profiles: [{ id: 'local-default' }] }));
  const directory = path.join(root, 'profiles', 'local-default');
  fs.mkdirSync(directory, { recursive: true });
  const settings = { theme: 'dark', agentCmdOverrides: { claude: 'custom-claude', ...(command === undefined ? {} : { codex: command }) }, agentDefaultArgs: { codex: '--dangerously-bypass-approvals-and-sandbox' }, agentDefaultEnv: { codex: { PRESERVED: 'yes' } } };
  const json = path.join(directory, 'orca-data.json');
  const data = { settings, worktrees: [{ id: 'existing-session', pendingFirstAgentMessageRename: true }] };
  fs.writeFileSync(json, JSON.stringify(data));
  const database = path.join(directory, 'profile-state.db');
  let db;
  if (sqlite) {
    db = new DatabaseSync(database);
    db.exec(`PRAGMA user_version = 3;
      CREATE TABLE profile_state_meta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
      CREATE TABLE profile_state_documents (domain TEXT PRIMARY KEY NOT NULL, payload TEXT NOT NULL, domain_version INTEGER NOT NULL, revision INTEGER NOT NULL, updated_at INTEGER NOT NULL, content_hash TEXT NOT NULL);`);
    for (const [key, value] of Object.entries({ profile_id: 'local-default', revision: '7', legacy_json_acceptance: JSON.stringify({ jsonHash: hash(fs.readFileSync(json)), acceptedRevision: 7 }) })) db.prepare('INSERT INTO profile_state_meta VALUES (?,?)').run(key, value);
    for (const [key, value] of Object.entries(data)) {
      const payload = JSON.stringify(value);
      db.prepare('INSERT INTO profile_state_documents VALUES (?,?,1,7,100,?)').run(key, payload, hash(payload));
    }
    if (wal) db.exec('PRAGMA journal_mode = WAL');
  }
  return { root, directory, settings, data, json, database, db };
}
const stopped = () => {};
const backups = f => fs.readdirSync(f.directory).filter(x => x.endsWith('.bak'));
const row = db => db.prepare("SELECT * FROM profile_state_documents WHERE domain='settings'").get();
test('SQLite apply preserves args, env, other agents and sessions; backup and rerun are valid', t => {
  const f = fixture(t, { wal: true });
  const untouched = f.db.prepare("SELECT * FROM profile_state_documents WHERE domain='worktrees'").get();
  const beforeJson = fs.readFileSync(f.json, 'utf8');
  assert.equal(configure(f.root, { check: true }).status, 'pending');
  assert.equal(backups(f).length, 0);
  const result = configure(f.root, { stopped });
  assert.equal(result.status, 'applied');
  const actual = JSON.parse(row(f.db).payload);
  assert.deepEqual(actual, { ...f.settings, agentCmdOverrides: { ...f.settings.agentCmdOverrides, codex: 'codex --no-daemon' } });
  assert.equal(row(f.db).content_hash, hash(row(f.db).payload));
  assert.equal(row(f.db).revision, 8);
  assert.equal(f.db.prepare("SELECT value FROM profile_state_meta WHERE key='revision'").get().value, '8');
  assert.deepEqual(f.db.prepare("SELECT * FROM profile_state_documents WHERE domain='worktrees'").get(), untouched);
  assert.equal(fs.readFileSync(f.json, 'utf8'), beforeJson);
  const backup = new DatabaseSync(result.backup, { readOnly: true });
  assert.deepEqual(JSON.parse(row(backup).payload), f.settings);
  backup.close();
  assert.equal(configure(f.root, { stopped: () => assert.fail('already configured must not require shutdown') }).status, 'already-configured');
  assert.equal(backups(f).length, 1);
});
test('running Orca is refused before any backup or settings write', t => {
  const f = fixture(t);
  const before = row(f.db);
  assert.throws(() => configure(f.root, { stopped: () => { throw new ActionRequired('running'); } }), /running/);
  assert.deepEqual(row(f.db), before);
  assert.equal(backups(f).length, 0);
});
test('Orca starting before commit rolls back DB changes', t => {
  const f = fixture(t);
  const before = row(f.db);
  let calls = 0;
  assert.throws(() => configure(f.root, { stopped: () => { if (++calls === 3) throw new ActionRequired('started'); } }), /started/);
  assert.deepEqual(row(f.db), before);
  assert.equal(f.db.prepare("SELECT value FROM profile_state_meta WHERE key='revision'").get().value, '7');
});
test('concurrent profile revision change is preserved and application refused', t => {
  const f = fixture(t);
  let calls = 0;
  assert.throws(() => configure(f.root, { stopped: () => {
    if (++calls !== 1) return;
    f.db.prepare("UPDATE profile_state_meta SET value='9' WHERE key='revision'").run();
  } }), /locked|변경/);
  assert.deepEqual(JSON.parse(row(f.db).payload), f.settings);
});
for (const command of ['my-wrapper codex', 'codex --model custom', 'codex --no-daemon; another-command']) {
  test(`custom command is never overwritten: ${command}`, t => {
    const f = fixture(t, { command });
    assert.throws(() => configure(f.root, { stopped }), /사용자 지정/);
    assert.equal(backups(f).length, 0);
    assert.deepEqual(JSON.parse(row(f.db).payload), f.settings);
  });
}
for (const mutation of ['schema', 'hash', 'identity', 'json', 'index']) {
  test(`refuses invalid ${mutation} without writing`, t => {
    const f = fixture(t);
    if (mutation === 'schema') f.db.exec('PRAGMA user_version=4');
    if (mutation === 'hash') f.db.exec("UPDATE profile_state_documents SET content_hash='bad' WHERE domain='settings'");
    if (mutation === 'identity') f.db.exec("UPDATE profile_state_meta SET value='other' WHERE key='profile_id'");
    if (mutation === 'json') fs.appendFileSync(f.json, ' ');
    if (mutation === 'index') fs.writeFileSync(path.join(f.root, 'orca-profile-index.json'), JSON.stringify({ schemaVersion: 1, activeProfileId: '../outside', profiles: [{ id: '../outside' }] }));
    assert.throws(() => configure(f.root, { stopped }), ActionRequired);
    assert.equal(backups(f).length, 0);
  });
}
test('legacy JSON backup retains complete original and apply is idempotent', t => {
  const f = fixture(t, { sqlite: false });
  const original = fs.readFileSync(f.json, 'utf8');
  const result = configure(f.root, { stopped });
  assert.equal(fs.readFileSync(result.backup, 'utf8'), original);
  const actual = JSON.parse(fs.readFileSync(f.json, 'utf8'));
  assert.deepEqual(actual.worktrees, f.data.worktrees);
  assert.deepEqual(actual.settings.agentDefaultArgs, f.settings.agentDefaultArgs);
  assert.equal(actual.settings.agentCmdOverrides.codex, 'codex --no-daemon');
  assert.equal(configure(f.root, { check: true }).status, 'already-configured');
});
test('legacy JSON is not overwritten when it changes during backup', t => {
  const f = fixture(t, { sqlite: false });
  let calls = 0;
  assert.throws(() => configure(f.root, { stopped: () => { if (++calls === 2) fs.writeFileSync(f.json, '{"external":true}'); } }), /변경/);
  assert.equal(fs.readFileSync(f.json, 'utf8'), '{"external":true}');
  assert(!fs.readdirSync(f.directory).some(x => x.endsWith('.tmp')));
});
test('orphaned SQLite sidecar must not fall back to JSON', t => {
  const f = fixture(t, { sqlite: false });
  fs.writeFileSync(f.database + '-wal', 'orphan');
  assert.throws(() => configure(f.root, { stopped }), ActionRequired);
  assert.equal(backups(f).length, 0);
});
