'use strict';
const fs = require('node:fs'), path = require('node:path');
const { Controller, json, readJson } = require('./controller.cjs');
const args = process.argv.slice(2), options = {};
for (let i = 0; i < args.length; i++) {
  const key = args[i];
  if (['--once', '--quiet', '--restore'].includes(key)) options[key.slice(2)] = true;
  else if (['--app-dir', '--state-dir'].includes(key)) options[key] = args[++i];
  else throw Error('Unknown argument: ' + key);
}
const stateDir = options['--state-dir'] || path.join(__dirname, 'state');
const appDir = options['--app-dir'] || path.join(process.env.LOCALAPPDATA, 'Programs', 'orca');
fs.mkdirSync(stateDir, { recursive: true });
const lock = path.join(stateDir, 'controller.lock');
try {
  const fd = fs.openSync(lock, 'wx'); fs.writeFileSync(fd, String(process.pid)); fs.closeSync(fd);
} catch (error) {
  if (error.code !== 'EEXIST') throw error;
  const pid = Number(fs.readFileSync(lock, 'utf8'));
  let active = Number.isInteger(pid) && pid > 0;
  if (active) { try { process.kill(pid, 0); } catch (error) { if (error.code === 'ESRCH') active = false; } }
  if (active) { console.log('Controller already running'); process.exit(0); }
  fs.unlinkSync(lock);
  const fd = fs.openSync(lock, 'wx'); fs.writeFileSync(fd, String(process.pid)); fs.closeSync(fd);
}
process.on('exit', () => { try { if (fs.readFileSync(lock, 'utf8') === String(process.pid)) fs.unlinkSync(lock); } catch {} });
const patchesDir = fs.existsSync(path.join(__dirname, 'patches')) ? path.join(__dirname, 'patches') : path.join(__dirname, '..', 'patches');
const manifests = fs.readdirSync(patchesDir).filter(f => /^orca-.*-wsl-rename\.json$/.test(f)).map(f => JSON.parse(fs.readFileSync(path.join(patchesDir, f))));
const controller = new Controller({ stateDir, appDir, manifests, quiet: options.quiet });
(async () => {
  if (options.restore) { console.log(JSON.stringify(controller.restore())); return; }
  do {
    try { const result = await controller.tick(); if (options.once) console.log(JSON.stringify(result)); }
    catch (error) { json(path.join(stateDir, 'auto-status.json'), { checkedAt: new Date().toISOString(), status: 'error', detail: error.message }); if (options.once) throw error; }
    if (!options.once) await new Promise(resolve => setTimeout(resolve, 5000));
  } while (!options.once);
})().catch(error => { console.error(error); process.exitCode = 1; });
