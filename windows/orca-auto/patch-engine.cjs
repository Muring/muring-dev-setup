'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const marker = '/*MuRingWslRename:v1*/';

function archive(bytes) {
  assert(bytes.length >= 16 && bytes.length <= 512 * 1024 ** 2, 'Archive size outside supported range');
  const headerSize = bytes.readUInt32LE(4), jsonSize = bytes.readUInt32LE(12);
  assert(bytes.readUInt32LE(0) === 4 && jsonSize > 0 && jsonSize < 16 * 1024 ** 2);
  assert(16 + jsonSize <= 8 + headerSize && 8 + headerSize <= bytes.length);
  const header = bytes.subarray(16, 16 + jsonSize).toString('utf8');
  const tree = JSON.parse(header), base = 8 + headerSize;
  function entry(name) {
    let item = tree;
    for (const part of name.split('/')) item = item.files?.[part];
    assert(item && !item.unpacked && !item.link, `Unsupported archive entry: ${name}`);
    const offset = Number(item.offset), size = item.size;
    assert(Number.isSafeInteger(offset) && offset >= 0 && Number.isSafeInteger(size) && size >= 0);
    assert(base + offset + size <= bytes.length);
    return { item, start: base + offset, data: bytes.subarray(base + offset, base + offset + size) };
  }
  const main = entry('out/main/index.js');
  assert(main.data.length < 32 * 1024 ** 2, 'Main script too large');
  const pkg = JSON.parse(entry('package.json').data);
  assert(pkg.name === 'orca' && typeof pkg.version === 'string', 'Not an Orca archive');
  const integrity = main.item.integrity;
  assert(integrity?.algorithm === 'SHA256' && integrity.blockSize === 4194304, 'Unsupported integrity format');
  assert(hash(main.data) === integrity.hash, 'Main integrity mismatch');
  const blocks = [];
  for (let i = 0; i < main.data.length; i += integrity.blockSize) blocks.push(hash(main.data.subarray(i, i + integrity.blockSize)));
  assert.deepEqual(blocks, integrity.blocks, 'Main block integrity mismatch');
  return { header, main, pkg, integrity };
}

// Exact old helper shape, with minifier names captured rather than version offsets.
const id = '[A-Za-z_$][\\w$]*';
const pattern = new RegExp(
  'async function (?<fn>' + id + ')\\((?<cwd>' + id + '),(?<agent>' + id + '),(?<remote>' + id + '),(?<deps>' + id + ')\\)\\{' +
  'if\\(\\k<remote>\\)return\\{kind:`remote`,cwd:\\k<cwd>,execute:\\((?<a>' + id + '),(?<b>' + id + '),(?<c>' + id + '),(?<d>' + id + ')\\)=>\\k<remote>\\.executeCommitMessagePlan\\(\\k<a>,\\k<b>,\\k<c>,\\k<d>\\),missingBinaryLocation:`remote PATH`\\};' +
  'let (?<env>' + id + ')=await (?<prepare>' + id + ')\\(\\k<agent>,\\k<deps>\\.getAgentEnvResolvers\\(\\)\\);' +
  'return \\k<env>\\.ok\\?\\{kind:`local`,cwd:\\k<cwd>,\\.\\.\\.\\k<env>\\.env\\?\\{env:\\k<env>\\.env\\}:\\{\\}\\}:null\\}', 'g');

async function verifyFunction(source, names) {
  let calls = [], fail = false;
  const context = vm.createContext({ process: { platform: 'win32' }, [names.prepare]: async (...args) => {
    calls.push(args); return fail ? { ok: false } : { ok: true, env: { TEST: 'preserved' } };
  }});
  new vm.Script(source).runInContext(context, { timeout: 1000 });
  const fn = context[names.fn], deps = { getAgentEnvResolvers: () => 'resolvers' };
  for (const [cwd, distro] of [[String.raw`\\wsl.localhost\Ubuntu\home\user\worktree`, 'Ubuntu'], [String.raw`\\wsl$\Debian\home\user\folder space`, 'Debian'], ['//WSL.LOCALHOST/Debian/home/u', 'Debian']]) {
    const result = await fn(cwd, 'codex', null, deps);
    assert.equal(result.wslDistro, distro); assert.equal(result.env.TEST, 'preserved');
    assert.equal(calls.at(-1)[2].runtime, 'wsl'); assert.equal(calls.at(-1)[2].wslDistro, distro);
  }
  for (const [platform, cwd] of [['win32', 'C:\\repo'], ['linux', '/home/user'], ['darwin', '/Users/user'], ['linux', '//wsl.localhost/Ubuntu/home']]) {
    context.process.platform = platform;
    assert.equal((await fn(cwd, 'codex', null, deps)).wslDistro, undefined);
    assert.equal(calls.at(-1)[2], undefined);
  }
  const before = calls.length;
  const target = await fn('/remote', 'codex', { executeCommitMessagePlan: (...args) => args.join(',') }, deps);
  assert.equal(target.kind, 'remote'); assert.equal(target.execute('plan', 'cwd', 10, 'op'), 'plan,cwd,10,op');
  assert.equal(calls.length, before);
  fail = true; context.process.platform = 'win32';
  assert.equal(await fn(String.raw`\\wsl.localhost\Ubuntu\home`, 'codex', null, deps), null);
}

async function structuralPatch(bytes) {
  const info = archive(bytes), source = info.main.data.toString('utf8');
  assert(!source.includes(marker), 'Unrecognized previously patched archive; review its receipt');
  const matches = [...source.matchAll(pattern)];
  assert(matches.length === 1, 'Expected exactly one recognized vulnerable helper; review this version');
  const match = matches[0], n = match.groups, variable = '__w';
  assert(!Object.values(n).includes(variable));
  const oldCall = `let ${n.env}=await ${n.prepare}(${n.agent},${n.deps}.getAgentEnvResolvers());`;
  const newCall = `let ${variable}=process.platform===\`win32\`?${n.cwd}.replace(/\\\\/g,\`/\`).match(/^\\/\\/(?:wsl\\.localhost|wsl\\$)\\/([^/]+)(?:\\/|$)/i)?.[1]:void 0,${n.env}=await ${n.prepare}(${n.agent},${n.deps}.getAgentEnvResolvers(),${variable}?{runtime:\`wsl\`,wslDistro:${variable}}:void 0);`;
  const patchedFunction = match[0].replace(oldCall, marker + newCall).replace(`cwd:${n.cwd},...${n.env}.env`, `cwd:${n.cwd},...${variable}?{wslDistro:${variable}}:{},...${n.env}.env`);
  await verifyFunction(patchedFunction, n);
  // Reclaim only leading whitespace in the known bootstrap prelude, keeping ASAR layout unchanged.
  const end = source.indexOf('\n;(() => {', 10);
  assert(end > 0 && end < 10000 && end < match.index && source.startsWith('\n;(() => {'), 'Unknown bootstrap layout');
  assert(source.slice(0, end).includes('__ORCA_BOOTSTRAP_FATAL_EXIT_GUARD__') && !source.slice(0, end).includes('`'), 'Unknown bootstrap syntax');
  let prefix = source.slice(0, end), remaining = Buffer.byteLength(patchedFunction) - Buffer.byteLength(match[0]);
  for (const spaces of [...prefix.matchAll(/^ +/gm)].reverse()) {
    const take = Math.min(remaining, spaces[0].length);
    prefix = prefix.slice(0, spaces.index) + prefix.slice(spaces.index + take); remaining -= take;
    if (!remaining) break;
  }
  assert.equal(remaining, 0, 'Insufficient safe padding');
  const main = Buffer.from(prefix + source.slice(end, match.index) + patchedFunction + source.slice(match.index + match[0].length));
  assert.equal(main.length, info.main.data.length);
  new vm.Script(main.toString('utf8'), { filename: 'orca-patched-main.js' });
  const integrity = { ...info.integrity, hash: hash(main), blocks: [] };
  for (let i = 0; i < main.length; i += integrity.blockSize) integrity.blocks.push(hash(main.subarray(i, i + integrity.blockSize)));
  const oldJson = JSON.stringify(info.integrity), newJson = JSON.stringify(integrity);
  assert.equal(oldJson.length, newJson.length); assert.equal(info.header.split(oldJson).length, 2);
  const output = Buffer.from(bytes);
  Buffer.from(info.header.replace(oldJson, newJson)).copy(output, 16);
  main.copy(output, info.main.start);
  archive(output);
  return { output, version: info.pkg.version, method: 'verified-helper-shape-v1' };
}

function knownManifests(directory) {
  return fs.readdirSync(directory).filter(name => /^orca-.*-wsl-rename\.json$/.test(name)).map(name => JSON.parse(fs.readFileSync(path.join(directory, name))));
}
async function prepare(bytes, manifests) {
  const sha = hash(bytes), current = manifests.find(m => m.patchedSha256 === sha);
  if (current) return { already: true, version: current.version, sha256: sha };
  const known = manifests.find(m => m.originalSha256 === sha);
  if (!known) return structuralPatch(bytes);
  let cursor = 0; const pieces = [];
  for (const edit of known.edits) {
    assert(Number.isSafeInteger(edit.offset) && edit.offset >= cursor && edit.remove >= 0 && edit.offset + edit.remove <= bytes.length);
    pieces.push(bytes.subarray(cursor, edit.offset), Buffer.from(edit.text)); cursor = edit.offset + edit.remove;
  }
  pieces.push(bytes.subarray(cursor)); const output = Buffer.concat(pieces);
  assert.equal(hash(output), known.patchedSha256); archive(output);
  return { output, version: known.version, method: 'verified-archive-hash' };
}
module.exports = { hash, archive, prepare, structuralPatch, marker };
