'use strict';
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { archive, hash } = require('./patch-engine.cjs');
const id = '[A-Za-z_$][\\w$]*';
// Match the surrounding baseline/backpressure/drain contract, not just one property name.
function pattern(vulnerable) {
  return new RegExp('let (?<snapshot>' + id + ')=(?<session>' + id + ')\\.' +
    (vulnerable ? 'hiddenOutputRestorePendingOverflow\\?\\k<session>\\.' : '') +
    'hiddenOutputRestoreReplayingSnapshot' + (vulnerable ? ':null' : '') + ';\\s*' +
    '\\k<snapshot>&&\\(\\k<session>\\.setRestoredSnapshotBaseline\\((?<pty>' + id + '),\\k<snapshot>,\\k<snapshot>\\.paintsContent===!0\\),\\k<session>\\.noteHiddenOutputRestoreFloodBackpressure\\(\\)\\),\\k<session>\\.abandonHiddenOutputRestoreAndDrainPendingForeground\\(\\k<pty>,\\{quiet:\\k<snapshot>!==null\\}\\)', 'g');
}
function inspect(bytes) {
  const info = archive(bytes), matches = [];
  function walk(node, prefix) {
    for (const [name, item] of Object.entries(node.files || {})) {
      const file = prefix ? prefix + '/' + name : name;
      if (item.files) walk(item, file);
      else if (file.startsWith('out/renderer/') && file.endsWith('.js') && !item.unpacked && !item.link) {
        const entry = info.entry(file);
        assert(entry.data.length < 32 * 1024 ** 2, 'Renderer script too large');
        const source = entry.data.toString('utf8');
        for (const vulnerable of [true, false]) {
          for (const match of source.matchAll(pattern(vulnerable))) matches.push({ file, entry, source, match, vulnerable });
        }
      }
    }
  }
  walk(info.tree, '');
  assert.equal(matches.length, 1, 'Terminal recovery code missing or ambiguous; review this version');
  const target = matches[0], integrity = target.entry.item.integrity;
  assert(integrity?.algorithm === 'SHA256' && integrity.blockSize === 4194304, 'Unsupported renderer integrity');
  assert.equal(hash(target.entry.data), integrity.hash, 'Renderer integrity mismatch');
  const blocks = [];
  for (let i = 0; i < target.entry.data.length; i += integrity.blockSize) blocks.push(hash(target.entry.data.subarray(i, i + integrity.blockSize)));
  assert.deepEqual(blocks, integrity.blocks, 'Renderer block integrity mismatch');
  return { ...target, info, integrity };
}
function prepareTerminal(bytes) {
  const target = inspect(bytes);
  if (!target.vulnerable) return { output: bytes, status: 'already-fixed' };
  const { session, snapshot } = target.match.groups;
  const old = `let ${snapshot}=${session}.hiddenOutputRestorePendingOverflow?${session}.hiddenOutputRestoreReplayingSnapshot:null;`;
  const replacement = `let ${snapshot}=${session}.hiddenOutputRestoreReplayingSnapshot;`;
  const start = target.match.index;
  const data = Buffer.from(target.source.slice(0, start) + replacement + ' '.repeat(old.length - replacement.length) + target.source.slice(start + old.length));
  assert.equal(data.length, target.entry.data.length);
  // Syntax check only: never execute the renderer bundle.
  const check = spawnSync(process.execPath, ['--input-type=module', '--check'], { input: data, timeout: 30000, windowsHide: true });
  assert.equal(check.status, 0, 'Patched renderer syntax check failed');
  const integrity = { ...target.integrity, hash: hash(data), blocks: [] };
  for (let i = 0; i < data.length; i += integrity.blockSize) integrity.blocks.push(hash(data.subarray(i, i + integrity.blockSize)));
  const oldJson = JSON.stringify(target.integrity), newJson = JSON.stringify(integrity);
  assert.equal(oldJson.length, newJson.length); assert.equal(target.info.header.split(oldJson).length, 2);
  const output = Buffer.from(bytes);
  Buffer.from(target.info.header.replace(oldJson, newJson)).copy(output, 16);
  data.copy(output, target.entry.start);
  assert.equal(inspect(output).vulnerable, false);
  return { output, status: 'applied' };
}
module.exports = { inspect, prepareTerminal };
