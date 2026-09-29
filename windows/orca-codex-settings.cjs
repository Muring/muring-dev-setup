'use strict';
// Offline settings migration. Never close Orca or edit the compatibility JSON beside a database.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const { DatabaseSync } = require('node:sqlite');
const hash = value => crypto.createHash('sha256').update(value).digest('hex');
const object = value => value && typeof value === 'object' && !Array.isArray(value);
class ActionRequired extends Error {}
function requireState(condition, message) {
  if (!condition) throw new ActionRequired(message);
}
function desired(settings) {
  requireState(object(settings), 'Orca 설정 형식을 확인할 수 없습니다.');
  const commands = settings.agentCmdOverrides ?? {};
  requireState(object(commands), 'Orca 실행 명령 형식을 확인할 수 없습니다.');
  const command = commands.codex ?? '';
  requireState(typeof command === 'string', 'Codex 실행 명령 형식을 확인할 수 없습니다.');
  if (command.trim() === 'codex --no-daemon') return null;
  requireState(['', 'codex'].includes(command.trim()),
    '사용자 지정 Codex 명령은 보존했습니다. Orca 설정에서 --no-daemon을 직접 적용하세요.');
  return { ...settings, agentCmdOverrides: { ...commands, codex: 'codex --no-daemon' } };
}
function locate(root) {
  const indexFile = path.join(root, 'orca-profile-index.json');
  const indexText = fs.existsSync(indexFile) ? fs.readFileSync(indexFile, 'utf8') : null;
  let profile = null;
  if (indexText !== null) {
    const index = JSON.parse(indexText);
    profile = index.activeProfileId;
    requireState(index.schemaVersion === 1 && typeof profile === 'string' &&
      /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(profile) &&
      Array.isArray(index.profiles) && index.profiles.some(p => p.id === profile),
    'Orca 활성 프로필을 확인할 수 없습니다. Orca에서 프로필을 먼저 준비하세요.');
  }
  const directory = profile ? path.join(root, 'profiles', profile) : root;
  const database = path.join(directory, 'profile-state.db');
  const json = path.join(directory, 'orca-data.json');
  const databaseExists = ['', '-wal', '-shm', '-journal'].some(s => fs.existsSync(database + s));
  requireState(databaseExists ? fs.existsSync(database) : fs.existsSync(json),
    'Orca를 설치하고 한 번 실행한 뒤 종료하고 재시도하세요.');
  return { profile, database, json, databaseExists, indexFile, indexText };
}
function sameProfile(location) {
  const text = fs.existsSync(location.indexFile) ? fs.readFileSync(location.indexFile, 'utf8') : null;
  requireState(text === location.indexText, 'Orca 프로필이 변경되었습니다. 재시도하세요.');
}
function assertStopped() {
  requireState(process.platform === 'win32', 'Windows에서 실행해야 합니다.');
  const result = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
    "$ErrorActionPreference='Stop'; if (@(Get-Process | Where-Object { $_.ProcessName -eq 'Orca' }).Count -gt 0) { exit 20 }"],
  { windowsHide: true, timeout: 15000, encoding: 'utf8' });
  requireState(result.status === 0,
    'Orca를 완전히 종료한 뒤 Codex 실행 설정을 재시도하세요. 실행 중인 세션은 종료하지 않았습니다.');
}
function readDatabase(db, location) {
  requireState(db.prepare('PRAGMA user_version').get().user_version === 3,
    '지원하지 않는 Orca 설정 DB 버전입니다. 설정 화면에서 직접 적용하세요.');
  const meta = Object.fromEntries(db.prepare('SELECT key, value FROM profile_state_meta').all().map(r => [r.key, r.value]));
  requireState(location.profile !== null && meta.profile_id === location.profile, 'Orca 설정 DB 프로필이 일치하지 않습니다.');
  const revision = Number(meta.revision);
  const row = db.prepare("SELECT * FROM profile_state_documents WHERE domain = 'settings'").get();
  requireState(Number.isSafeInteger(revision) && revision > 0 && revision < Number.MAX_SAFE_INTEGER &&
    row && row.domain_version === 1 && Number.isSafeInteger(row.revision) && row.revision > 0 &&
    row.revision <= revision && hash(row.payload) === row.content_hash, 'Orca 설정 DB 검증에 실패했습니다.');
  if (fs.existsSync(location.json)) {
    const accepted = JSON.parse(meta.legacy_json_acceptance || 'null');
    const jsonHash = hash(fs.readFileSync(location.json));
    requireState(accepted && [accepted, accepted.pending].some(a => a && a.jsonHash === jsonHash &&
      Number.isSafeInteger(a.acceptedRevision) && a.acceptedRevision > 0 && a.acceptedRevision <= revision),
    '아직 반영되지 않은 Orca JSON 설정이 있습니다. Orca를 실행·종료한 뒤 재시도하세요.');
  }
  return { revision, row, settings: JSON.parse(row.payload) };
}
function backupName(file) {
  return `${file}.before-codex-no-daemon.${Date.now()}-${crypto.randomUUID()}.bak`;
}
function configure(root, { check = false, stopped = assertStopped } = {}) {
  const location = locate(root);
  if (!location.databaseExists) {
    const original = fs.readFileSync(location.json, 'utf8');
    const data = JSON.parse(original);
    const next = desired(data.settings);
    if (!next) return { status: 'already-configured' };
    if (check) return { status: 'pending' };
    stopped();
    sameProfile(location);
    const backup = backupName(location.json);
    fs.copyFileSync(location.json, backup, fs.constants.COPYFILE_EXCL);
    requireState(fs.readFileSync(backup, 'utf8') === original, '백업 중 Orca 설정이 변경되었습니다.');
    const temporary = `${backup}.tmp`;
    try {
      fs.writeFileSync(temporary, JSON.stringify({ ...data, settings: next }, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
      stopped();
      sameProfile(location);
      requireState(!fs.existsSync(location.database) && fs.readFileSync(location.json, 'utf8') === original,
        '적용 중 Orca 설정이 변경되었습니다. 재시도하세요.');
      fs.renameSync(temporary, location.json);
      return { status: 'applied', backup };
    } finally {
      if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
    }
  }
  // Open read-only first: checks and the running-app refusal must not modify the DB.
  let db = new DatabaseSync(location.database, { readOnly: true });
  let initial;
  try {
    initial = readDatabase(db, location);
    if (!desired(initial.settings)) return { status: 'already-configured' };
    if (check) return { status: 'pending' };
  } finally { db.close(); }
  stopped();
  sameProfile(location);
  db = new DatabaseSync(location.database);
  let transaction = false;
  try {
    db.exec('PRAGMA busy_timeout = 1000');
    const backup = backupName(location.database);
    // VACUUM INTO creates a consistent, complete backup, including committed WAL data.
    db.prepare('VACUUM INTO ?').run(backup);
    const snapshot = new DatabaseSync(backup, { readOnly: true });
    let saved;
    try { saved = readDatabase(snapshot, location); } finally { snapshot.close(); }
    db.exec('BEGIN IMMEDIATE');
    transaction = true;
    stopped();
    sameProfile(location);
    const current = readDatabase(db, location);
    requireState(current.revision === initial.revision && saved.revision === current.revision &&
      current.row.payload === initial.row.payload && saved.row.payload === current.row.payload,
    '적용 중 Orca 설정이 변경되었습니다. 재시도하세요.');
    const payload = JSON.stringify(desired(current.settings));
    db.prepare("UPDATE profile_state_documents SET payload = ?, revision = ?, updated_at = ?, content_hash = ? WHERE domain = 'settings'")
      .run(payload, current.revision + 1, Date.now(), hash(payload));
    db.prepare("UPDATE profile_state_meta SET value = ? WHERE key = 'revision'").run(String(current.revision + 1));
    readDatabase(db, location);
    stopped();
    sameProfile(location);
    db.exec('COMMIT');
    transaction = false;
    return { status: 'applied', backup };
  } finally {
    if (transaction) db.exec('ROLLBACK');
    db.close();
  }
}
if (require.main === module) {
  try {
    const check = process.argv[2] === '--check';
    requireState(process.argv.length === (check ? 3 : 2), '지원하지 않는 인자입니다.');
    requireState(process.env.APPDATA, 'Windows APPDATA 경로가 없습니다.');
    const result = configure(path.join(process.env.APPDATA, 'orca'), { check });
    console.log(result.status === 'applied' ? `Codex 실행 설정 적용 완료. 백업: ${result.backup}` :
      result.status === 'already-configured' ? 'Codex 실행 설정 확인 완료.' : 'Codex 실행 설정 적용이 필요합니다.');
    process.exitCode = result.status === 'pending' ? 20 : 0;
  } catch (error) {
    // Never print settings, JSON payloads, or database errors containing user data.
    console.error(error instanceof ActionRequired ? error.message : 'Orca 설정을 안전하게 확인하지 못했습니다. 설정 화면에서 확인 후 재시도하세요.');
    process.exitCode = 20;
  }
}
module.exports = { configure, desired, ActionRequired, hash };
