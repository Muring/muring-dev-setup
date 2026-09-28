'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const { hash, prepare, structuralPatch, archive, marker } = require('../../windows/orca-auto/patch-engine.cjs');
const { Controller } = require('../../windows/orca-auto/controller.cjs');
const { fixture, helper, executable } = require('./fixtures.cjs');
function controller(root) {
  return new Controller({ appDir: root, stateDir: path.join(root, 'state'), manifests: [], quiet: true, stableMs: 0 });
}
function install(root, bytes) { fs.mkdirSync(root, { recursive: true }); fs.writeFileSync(path.join(root, 'Orca.exe'), executable()); fs.mkdirSync(path.join(root, 'resources'), { recursive: true }); fs.writeFileSync(path.join(root, 'resources/app.asar'), bytes); }

test('unlisted version and different minifier names pass runtime contract and preserve ASAR layout', async () => {
  const original = fixture(), result = await prepare(original, []);
  assert.equal(result.version, '1.4.999'); assert.equal(result.output.length, original.length);
  assert(archive(result.output).main.data.includes(Buffer.from(marker)));
  assert.deepEqual(archive(result.output).pkg, archive(original).pkg);
});
test('corrupt archives, duplicate targets, and unknown or already patched helpers are refused', async () => {
  const corrupt = fixture(); corrupt[corrupt.length - 1] ^= 1;
  await assert.rejects(prepare(corrupt, []), /integrity mismatch/);
  await assert.rejects(prepare(fixture('9.0', helper + helper), []), /exactly one/);
  await assert.rejects(prepare(fixture('9.0', helper.replace('getAgentEnvResolvers', 'changedEnvironmentAPI')), []), /exactly one/);
  const fixed = await prepare(fixture(), []);
  await assert.rejects(prepare(fixed.output, []), /previously patched/);
});
test('automatic application, receipt recognition, successive update, backup and restore', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'muring-auto-'));
  try {
    const original = fixture(); install(root, original);
    const c = controller(root); assert.equal((await c.tick()).status, 'patched');
    assert.deepEqual(fs.readFileSync(c.last.backup), original);
    assert.equal((await controller(root).tick()).status, 'patched');
    const next = fixture('1.4.1000'); install(root, next);
    assert.equal((await c.tick()).status, 'patched'); assert.equal(c.last.version, '1.4.1000');
    assert.equal(fs.readdirSync(path.join(root, 'state/backups')).length, 2);
    assert.equal(c.restore().status, 'restored'); assert.deepEqual(fs.readFileSync(c.target), next);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
test('pending patch never overwrites a newer update', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'muring-race-'));
  try {
    install(root, fixture()); const c = controller(root);
    c.applyPending = () => c.status({ status: 'waiting-for-file-access' });
    await c.tick(); const oldStage = c.pending.staged;
    const next = fixture('2.0', helper.replace('getAgentEnvResolvers', 'differentAPI'));
    install(root, next); assert.equal((await c.tick()).status, 'needs-review');
    assert(!fs.existsSync(oldStage)); assert.deepEqual(fs.readFileSync(c.target), next);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
test('damaged backups prevent patching and damaged staged files prevent replacement', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'muring-damage-'));
  try {
    const original = fixture(); install(root, original); const c = controller(root);
    fs.writeFileSync(path.join(root, 'state/backups', hash(original) + '.asar'), 'corrupt');
    assert.equal((await c.tick()).status, 'needs-review'); assert.deepEqual(fs.readFileSync(c.target), original);
    fs.unlinkSync(path.join(root, 'state/backups', hash(original) + '.asar'));
    const d = controller(root); const apply = d.applyPending;
    d.applyPending = () => d.status({ status: 'waiting-for-file-access' }); await d.tick();
    fs.appendFileSync(d.pending.staged, 'corrupt');
    d.applyPending = apply; assert.equal(d.applyPending().status, 'needs-review');
    assert.deepEqual(fs.readFileSync(d.target), original);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
module.exports = { fixture };

test('embedded ASAR validation blocks modification instead of disabling the protection', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'muring-fuses-'));
  try {
    const original = fixture(); install(root, original);
    fs.writeFileSync(path.join(root, 'Orca.exe'), executable(true));
    const c = controller(root); assert.equal((await c.tick()).status, 'needs-review');
    assert.deepEqual(fs.readFileSync(c.target), original);
  } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
