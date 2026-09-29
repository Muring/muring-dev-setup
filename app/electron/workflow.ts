import { Config, Snapshot } from './model';

export function configurationKey(config: Config) {
  const { contentCommit, ...rest } = config;
  return JSON.stringify(rest);
}
export function workflowAccess(
  config: Config,
  snapshot: Snapshot,
  reviewed: string,
  connectionVisited: boolean,
) {
  const inspection = snapshot.inspection;
  const sameTarget = config.distro === snapshot.config.distro && config.user === snapshot.config.user;
  const environment = !!(
    sameTarget &&
    inspection?.supported &&
    inspection.wslReady &&
    inspection.linux?.osId === 'ubuntu' &&
    inspection.linux.user === config.user &&
    inspection.distros.some(d => d.name === config.distro && d.version === 2) &&
    !['reboot', 'wsl-restart'].includes(snapshot.phase)
  );
  const unchanged = configurationKey(config) === configurationKey(snapshot.config);
  const events = unchanged ? snapshot.events : [];
  const latest = Object.fromEntries(events.filter(e => e.step !== '_run').map(e => [e.step, e.status]));
  const run = events.filter(e => e.step === '_run').at(-1);
  const started = environment && !!run;
  const ended = !!run && ['completed', 'incomplete'].includes(run.status) && !snapshot.busy;
  // These tasks require the account/app connection screen to finish.
  const connectionTasks = ['kb', 'orca', 'orca-codex', 'orca-patch'];
  const readyForConnections =
    started &&
    ended &&
    config.selected.every(
      id =>
        latest[id] === 'completed' ||
        (connectionTasks.includes(id) && ['action-required', 'pending'].includes(latest[id])),
    );
  const complete =
    readyForConnections &&
    config.selected.every(id => latest[id] === 'completed') &&
    ['gh', 'claude', 'codex']
      .filter(id => config.selected.includes(id))
      .every(id => inspection?.linux?.auth[id]);
  return [
    true,
    environment,
    environment && reviewed === configurationKey(config),
    started,
    readyForConnections,
    complete && connectionVisited,
    environment,
  ];
}
