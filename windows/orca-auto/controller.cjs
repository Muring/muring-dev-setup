'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const { hash, archive, prepare } = require('./patch-engine.cjs');
const iso = () => new Date().toISOString();
function json(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temp = `${file}.${process.pid}.tmp`;
  try { fs.writeFileSync(temp, JSON.stringify(value, null, 2)); fs.renameSync(temp, file); }
  finally { if (fs.existsSync(temp)) fs.unlinkSync(temp); }
}
function readJson(file) { try { return JSON.parse(fs.readFileSync(file)); } catch { return null; } }
function fileHash(file) {
  const digest = crypto.createHash('sha256'), chunk = Buffer.allocUnsafe(1024 * 1024), fd = fs.openSync(file, 'r');
  try { let count; while ((count = fs.readSync(fd, chunk, 0, chunk.length, null))) digest.update(chunk.subarray(0, count)); }
  finally { fs.closeSync(fd); }
  return digest.digest('hex');
}
function signature(file) { const s = fs.statSync(file); return `${s.size}:${s.mtimeMs}:${s.ctimeMs}`; }
function executablePolicy(file) {
  const bytes = fs.readFileSync(file), sentinel = Buffer.from('dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX');
  const offset = bytes.indexOf(sentinel);
  assert(bytes.subarray(0, 2).toString() === 'MZ' && offset >= 0 && bytes.indexOf(sentinel, offset + 1) < 0, 'Unknown Electron executable');
  const wire = offset + sentinel.length;
  assert(bytes[wire] === 1 && bytes[wire + 1] >= 5 && bytes[wire + 6] === 48, 'Embedded ASAR validation is enabled or unknown; do not alter this app');
  return signature(file);
}
function busy(error) { return ['EPERM', 'EACCES', 'EBUSY'].includes(error.code); }

class Controller {
  constructor(options) {
    Object.assign(this, options);
    this.target = path.join(this.appDir, 'resources', 'app.asar');
    this.executable = path.join(this.appDir, 'Orca.exe');
    this.stateFile = path.join(this.stateDir, 'auto-status.json');
    this.last = readJson(this.stateFile);
    this.notified = this.last?.notifiedHash;
    fs.mkdirSync(path.join(this.stateDir, 'backups'), { recursive: true });
  }
  status(value) {
    const result = { checkedAt: iso(), mode: 'auto-patch-after-unlock', ...value, notifiedHash: this.notified ?? null };
    json(this.stateFile, result); this.last = result;
    return result;
  }
  notify(result) {
    if (this.quiet || result.status !== 'needs-review' || this.notified === result.sha256) return;
    if (process.platform !== 'win32') return;
    const script = path.join(__dirname, 'notify.ps1');
    const child = spawnSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'RemoteSigned', '-STA', '-File', script], { windowsHide: true, timeout: 20000, stdio: 'ignore' });
    if (child.status === 0) { this.notified = result.sha256; this.status(result); }
  }
  async tick() {
    if (!fs.existsSync(this.target)) { this.seen = null; this.pending = null; return this.status({ status: 'not-installed' }); }
    const stamp = signature(this.target);
    if ((this.stableMs ?? 3000) > 0 && Date.now() - fs.statSync(this.target).mtimeMs < (this.stableMs ?? 3000)) return this.status({ status: 'updating' });
    if (this.pending && this.seen !== stamp) { this.discardPending(); this.seen = null; }
    if (this.seen === stamp && !this.pending && this.cached) {
      const result = this.status(this.cached); this.notify(result); return result;
    }
    if (this.pending) return this.applyPending();
    let sourceHash;
    try {
      sourceHash = fileHash(this.target);
      if (signature(this.target) !== stamp) return this.status({ status: 'updating' });
      this.seen = stamp;
      const receipt = readJson(path.join(this.stateDir, 'receipts', sourceHash + '.json'));
      if (receipt?.patchedSha256 === sourceHash) {
        this.cached = { status: 'patched', sha256: sourceHash, version: receipt.version, method: receipt.method };
        return this.status(this.cached);
      }
      const known = this.manifests.find(m => m.patchedSha256 === sourceHash);
      if (known) {
        this.cached = { status: 'patched', sha256: sourceHash, version: known.version, method: 'verified-archive-hash' };
        return this.status(this.cached);
      }
      assert(fs.statSync(this.target).size <= 512 * 1024 ** 2, 'Archive too large');
      const bytes = fs.readFileSync(this.target);
      assert.equal(hash(bytes), sourceHash, 'Archive changed while reading');
      const prepared = await prepare(bytes, this.manifests);
      if (prepared.already) {
        this.cached = { status: 'patched', sha256: sourceHash, version: prepared.version, method: 'verified-archive-hash' };
        return this.status(this.cached);
      }
      const executableStamp = executablePolicy(this.executable);
      assert.equal(signature(this.target), stamp, 'Archive changed during preparation');
      const backup = path.join(this.stateDir, 'backups', sourceHash + '.asar');
      if (fs.existsSync(backup)) assert.equal(fileHash(backup), sourceHash, 'Backup integrity mismatch');
      else {
        const temporary = backup + '.tmp';
        fs.writeFileSync(temporary, bytes); assert.equal(fileHash(temporary), sourceHash);
        fs.renameSync(temporary, backup);
      }
      const patchedHash = hash(prepared.output);
      const staged = path.join(path.dirname(this.target), `app.asar.muring-auto-${sourceHash.slice(0, 16)}.tmp`);
      if (fs.existsSync(staged)) fs.unlinkSync(staged);
      fs.writeFileSync(staged, prepared.output, { flag: 'wx' });
      assert.equal(fileHash(staged), patchedHash);
      const metadata = { originalSha256: sourceHash, patchedSha256: patchedHash, version: prepared.version, method: prepared.method, backup, createdAt: iso() };
      json(path.join(this.stateDir, 'receipts', patchedHash + '.json'), metadata);
      this.pending = { ...metadata, staged, executableStamp };
      return this.applyPending();
    } catch (error) {
      if (busy(error)) { this.seen = null; return this.status({ status: 'waiting-for-file-access', sha256: sourceHash, detail: error.code }); }
      this.cached = { status: 'needs-review', sha256: sourceHash, detail: String(error.message).slice(0, 600) };
      const result = this.status(this.cached); this.notify(result); return result;
    }
  }
  discardPending() {
    if (this.pending?.staged && fs.existsSync(this.pending.staged)) fs.unlinkSync(this.pending.staged);
    this.pending = null;
  }
  applyPending() {
    const p = this.pending;
    try {
      // A read/write probe avoids rehashing a large locked archive on every timer tick.
      const fd = fs.openSync(this.target, 'r+'); fs.closeSync(fd);
      assert.equal(fileHash(this.target), p.originalSha256, 'Archive changed before replacement');
      assert.equal(fileHash(p.staged), p.patchedSha256, 'Staged patch integrity mismatch');
      assert.equal(fileHash(p.backup), p.originalSha256, 'Backup integrity mismatch');
      assert.equal(signature(this.executable), p.executableStamp, 'Executable changed before replacement');
      fs.renameSync(p.staged, this.target);
      assert.equal(fileHash(this.target), p.patchedSha256, 'Installed patch integrity mismatch');
      this.pending = null; this.seen = signature(this.target);
      this.cached = { status: 'patched', sha256: p.patchedSha256, version: p.version, method: p.method, patchedAt: iso(), backup: p.backup };
      this.notified = null;
      return this.status(this.cached);
    } catch (error) {
      if (busy(error)) return this.status({ status: 'waiting-for-file-access', sha256: p.originalSha256, version: p.version, detail: error.code });
      this.discardPending(); this.seen = null;
      const result = this.status({ status: 'needs-review', sha256: p.originalSha256, detail: error.message });
      this.notify(result); return result;
    }
  }
  restore() {
    const current = fileHash(this.target);
    const receipt = readJson(path.join(this.stateDir, 'receipts', current + '.json'));
    assert(receipt && receipt.patchedSha256 === current, 'No verified receipt for current archive');
    const bytes = fs.readFileSync(receipt.backup);
    assert.equal(hash(bytes), receipt.originalSha256, 'Backup integrity mismatch');
    const temp = this.target + '.muring-restore.tmp';
    try {
      fs.writeFileSync(temp, bytes, { flag: 'wx' });
      assert.equal(fileHash(this.target), current, 'Archive changed during restore');
      fs.renameSync(temp, this.target); assert.equal(fileHash(this.target), receipt.originalSha256);
      return this.status({ status: 'restored', sha256: receipt.originalSha256 });
    } finally { if (fs.existsSync(temp)) fs.unlinkSync(temp); }
  }
}
module.exports = { Controller, readJson, json, executablePolicy };
