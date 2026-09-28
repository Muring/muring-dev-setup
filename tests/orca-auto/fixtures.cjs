const { hash } = require('../../windows/orca-auto/patch-engine.cjs');
const helper = 'async function ZZ(a,b,c,d){if(c)return{kind:`remote`,cwd:a,execute:(x,y,z,q)=>c.executeCommitMessagePlan(x,y,z,q),missingBinaryLocation:`remote PATH`};let v=await PP(b,d.getAgentEnvResolvers());return v.ok?{kind:`local`,cwd:a,...v.env?{env:v.env}:{}}:null}';
function fixture(version = '1.4.999', code = helper) {
  const main = Buffer.from('\n;(() => {\n  const guardKey = "__ORCA_BOOTSTRAP_FATAL_EXIT_GUARD__";\n' + '          // padding\n'.repeat(100) + '})();\n;(() => {})();\n' + code);
  const pkg = Buffer.from(JSON.stringify({ name: 'orca', version }));
  const tree = { files: { 'package.json': { offset: '0', size: pkg.length }, out: { files: { main: { files: { 'index.js': { offset: String(pkg.length), size: main.length, integrity: { algorithm: 'SHA256', hash: hash(main), blockSize: 4194304, blocks: [hash(main)] } } } } } } } };
  const text = Buffer.from(JSON.stringify(tree)), padding = (4 - text.length % 4) % 4;
  const header = Buffer.alloc(16 + text.length + padding);
  header.writeUInt32LE(4, 0); header.writeUInt32LE(8 + text.length + padding, 4); header.writeUInt32LE(4 + text.length + padding, 8); header.writeUInt32LE(text.length, 12); text.copy(header, 16);
  return Buffer.concat([header, pkg, main]);
}
module.exports = { fixture, helper };

function executable(enabled = false) { return Buffer.concat([Buffer.from('MZ_fixture_dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX'), Buffer.from([1, 8, 49, 49, 49, 49, enabled ? 49 : 48, 49, 48, 49])]); }
module.exports.executable = executable;
