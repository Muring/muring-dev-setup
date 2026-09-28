const fs = require('node:fs'), path = require('node:path');
const { fixture, executable } = require('./fixtures.cjs');
const dir = process.argv[2];
fs.writeFileSync(path.join(dir, 'first.asar'), fixture('1.4.999'));
fs.writeFileSync(path.join(dir, 'next.asar'), fixture('1.4.1000'));
fs.writeFileSync(path.join(dir, 'unknown.asar'), fixture('1.4.1001', 'function differentAPI(){}'));
fs.writeFileSync(path.join(dir, 'app space', 'Orca.exe'), executable());
