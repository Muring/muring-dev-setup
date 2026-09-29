import { test } from 'node:test';
import { strict as assert } from 'node:assert';
import { workflowAccess, configurationKey } from '../electron/workflow';
import { Config, Snapshot } from '../electron/model';
const config = {
  distro: 'Ubuntu',
  user: 'developer',
  selected: ['base', 'gh', 'kb'],
  contentCommit: '',
} as Config;
function state(status = 'completed'): Snapshot {
  return {
    config,
    events: [
      ...config.selected.map(step => ({
        step,
        status: step === 'kb' ? 'action-required' : status,
        version: 1,
        time: 1,
        message: '',
      })),
      { step: '_run', status: 'incomplete', version: 1, time: 1, message: '' },
    ],
    busy: false,
    phase: 'configure',
    logPath: '',
    inspection: {
      supported: true,
      wslReady: true,
      locationSupported: true,
      orcaInstalled: false,
      patchSupported: false,
      patchApplied: false,
      drives: [],
      linux: {
        osId: 'ubuntu',
        user: 'developer',
        users: ['developer'],
        zshrc: false,
        gitName: '',
        gitEmail: '',
        gitBranch: 'main',
        timezone: 'UTC',
        auth: { gh: false },
        tools: {},
      },
      distros: [{ name: 'Ubuntu', location: '', version: 2 }],
    },
  };
}
test('environment and review gates reject unverified targets and stale selections', () => {
  const s = state();
  s.events = [];
  assert.deepEqual(workflowAccess(config, s, '', false), [true, true, false, false, false, false, true]);
  assert(workflowAccess(config, s, configurationKey(config), false)[2]);
  assert(!workflowAccess({ ...config, user: 'other' }, s, '', false)[1]);
  s.phase = 'reboot';
  assert(!workflowAccess(config, s, '', false)[1]);
});
test('failed or paused installation cannot advance but connection tasks can', () => {
  assert(!workflowAccess(config, state('failed'), '', false)[4]);
  const s = state();
  assert(workflowAccess(config, s, '', false)[4]);
  assert(!workflowAccess(config, s, '', true)[5]);
  s.events.at(-1)!.status = 'paused';
  assert(!workflowAccess(config, s, '', true)[4]);
});
test('completion requires installed items, authentication and connection review', () => {
  const s = state();
  s.events.forEach(e => (e.status = 'completed'));
  s.inspection!.linux!.auth.gh = true;
  assert(!workflowAccess(config, s, '', false)[5]);
  assert(workflowAccess(config, s, '', true)[5]);
  assert(!workflowAccess({ ...config, selected: ['base'] }, s, '', true)[3]);
});

test('Orca Codex waiting for shutdown can advance to connections and retry', () => {
  const s = state();
  const c = { ...config, selected: ['base', 'node', 'codex', 'orca-codex'] };
  s.config = c;
  s.events = c.selected.map(step => ({
    step,
    status: step === 'orca-codex' ? 'action-required' : 'completed',
    version: 1,
    time: 1,
    message: '',
  }));
  s.events.push({ step: '_run', status: 'incomplete', version: 1, time: 1, message: '' });
  assert(workflowAccess(c, s, '', false)[4]);
  assert(!workflowAccess(c, s, '', true)[5]);
  s.events.find(e => e.step === 'orca-codex')!.status = 'completed';
  s.inspection!.linux!.auth.codex = true;
  assert(workflowAccess(c, s, '', true)[5]);
});
