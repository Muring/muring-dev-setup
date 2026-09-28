'use strict';
const { archive, hash, prepare: prepareRename } = require('./patch-engine.cjs');
const { prepareTerminal } = require('./terminal-patch.cjs');
const mainHashes = require('./rename-main-hashes.json');
const revision = 2;
async function prepare(bytes, manifests, previousReceipt) {
  const info = archive(bytes);
  const renameVerified = mainHashes[info.integrity.hash] || previousReceipt?.patchedSha256 === hash(bytes);
  const rename = renameVerified ? { already: true, version: info.pkg.version } : await prepareRename(bytes, manifests);
  const terminal = prepareTerminal(rename.output || bytes);
  const features = { wslRename: rename.already ? 'already-fixed' : 'applied', terminalRecovery: terminal.status };
  return { output: terminal.output, already: rename.already && terminal.status === 'already-fixed', version: info.pkg.version, method: 'verified-components-v2', revision, features };
}
module.exports = { prepare, revision };
