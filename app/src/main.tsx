import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Config, Item, Snapshot, CONTENT_GROUPS, defaults, recommended, toggle } from '../electron/model';
import '@fontsource-variable/noto-sans-kr';
import './style.css';
import { Select } from './Select';
import { ProgressRail } from './ProgressRail';
import type { Operation } from '../electron/progress';
import { configurationKey, workflowAccess } from '../electron/workflow';

interface Bridge {
  snapshot(): Promise<Snapshot>;
  catalog(): Promise<Item[]>;
  save(config: Config): Promise<Snapshot>;
  inspect(): Promise<Snapshot>;
  prepare(): Promise<{ reboot: boolean }>;
  install(): Promise<{ restartWsl: boolean }>;
  run(step?: string): Promise<Snapshot>;
  stop(): Promise<void>;
  login(tool: string): Promise<Snapshot>;
  shutdown(): Promise<Snapshot>;
  reboot(): Promise<void>;
  logs(): Promise<void>;
  installOrca(): Promise<Snapshot>;
  previewContent(): Promise<Snapshot>;
  updateContent(): Promise<Snapshot>;
}
declare global {
  interface Window {
    bootstrap: Bridge;
  }
}
const api = window.bootstrap;
const pages = [
  '환경 확인',
  '설치 구성',
  '변경 내용 확인',
  '설치 진행',
  '로그인 · 연동',
  '완료',
  '커맨드 · 스킬 업데이트',
];
const labels: Record<string, string> = {
  pending: '대기',
  running: '진행 중',
  completed: '완료',
  failed: '실패',
  skipped: '선택 안 함',
  'action-required': '사용자 작업 필요',
  'reboot-required': '재시작 필요',
  paused: '중지됨',
  incomplete: '미완료',
};

function App() {
  const [catalog, setCatalog] = useState<Item[]>([]);
  const [snapshot, setSnapshot] = useState<Snapshot>();
  const [config, setConfig] = useState<Config>();
  const [page, setPage] = useState(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [working, setWorking] = useState(false);
  // Each stage keeps the last operation started from it, so moving on hides it and coming back restores it.
  const [operations, setOperations] = useState<Record<number, Operation>>({});
  const ownerRef = useRef(0);
  const staleRef = useRef<number | undefined>(undefined);
  const [railOpen, setRailOpen] = useState(() => window.innerWidth >= 1240);
  const [reviewed, setReviewed] = useState('');
  const [connectionVisited, setConnectionVisited] = useState(false);
  const [startupAttempt, setStartupAttempt] = useState(0);
  const [startupError, setStartupError] = useState('');
  useEffect(() => {
    let active = true;
    Promise.all([api.catalog(), api.snapshot()])
      .then(([items, state]) => {
        if (!active) return;
        setCatalog(items);
        setSnapshot(state);
        setConfig(state.config);
        if (state.events.length)
          setNotice(
            '이전 설치 기록이 있습니다. 환경 확인 후 재실행하면 실제 상태를 검사해 이어서 진행합니다.',
          );
      })
      .catch(e => {
        if (active) setStartupError(String(e).replace(/^Error: /, ''));
      });
    return () => {
      active = false;
    };
  }, [startupAttempt]);
  const initialized = config !== undefined;
  useEffect(() => {
    if (!initialized) return;
    const timer = setInterval(() => {
      api
        .snapshot()
        .then(setSnapshot)
        .catch(() => {});
    }, 1000);
    return () => clearInterval(timer);
  }, [initialized]);
  // Below 1240px the open rail overlays the body, so collapse it when the window gets that narrow.
  useLayoutEffect(() => {
    const onResize = () => {
      if (window.innerWidth < 1240) setRailOpen(false);
    };
    onResize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  const liveOperation = snapshot?.operation;
  // The 1s poll can still deliver the operation that was live before the new action; skip that one by its start time.
  useEffect(() => {
    if (liveOperation && liveOperation.startedAt !== staleRef.current)
      setOperations(previous => ({ ...previous, [ownerRef.current]: liveOperation }));
  }, [liveOperation]);
  if (!config || !snapshot)
    return (
      <main className="loading" aria-busy={!startupError}>
        {startupError ? (
          <>
            <h1>설치 환경을 불러오지 못했습니다.</h1>
            <p role="alert" className="banner error">
              {startupError}
            </p>
            <button
              className="primary"
              onClick={() => {
                setStartupError('');
                setStartupAttempt(attempt => attempt + 1);
              }}>
              다시 시도
            </button>
          </>
        ) : (
          <p role="status">설치 환경을 준비하고 있습니다…</p>
        )}
      </main>
    );
  const busy = working || snapshot.busy;
  const access = workflowAccess(config, snapshot, reviewed, connectionVisited);
  const visiblePage =
    access[page] || busy
      ? page
      : page === 6
        ? 0
        : (Array.from({ length: page + 1 }, (_, i) => i)
            .reverse()
            .find(i => access[i]) ?? 0);
  function navigate(next: number) {
    if (access[next] && !busy) {
      setPage(next);
      if (next === 4) setConnectionVisited(true);
    }
  }
  const inspection = snapshot.inspection;
  const existing = inspection?.distros.find(i => i.name === config.distro);
  const selected = catalog.filter(i => config.selected.includes(i.id));
  const latest = Object.fromEntries(snapshot.events.filter(e => e.step !== '_run').map(e => [e.step, e]));
  const completed = selected.filter(i => latest[i.id]?.status === 'completed').length;
  const runState = snapshot.events.filter(e => e.step === '_run').at(-1);
  const authTools = ['gh', 'claude', 'codex'].filter(t => config.selected.includes(t));
  const authPending = authTools.filter(t => !inspection?.linux?.auth[t]);
  function update<K extends keyof Config>(key: K, value: Config[K]) {
    setConfig({ ...config!, [key]: value });
  }
  async function action(work: () => Promise<unknown>, owner = page) {
    setError('');
    setNotice('');
    setSnapshot(previous => (previous ? { ...previous, operation: undefined } : previous));
    ownerRef.current = owner;
    staleRef.current = snapshot?.operation?.startedAt;
    setRailOpen(true);
    setWorking(true);
    try {
      await work();
      setSnapshot(await api.snapshot());
    } catch (e) {
      setError(String(e).replace(/^Error: /, ''));
    } finally {
      setWorking(false);
    }
  }
  async function save() {
    const state = await api.save(config!);
    setConfig(state.config);
    return state;
  }
  async function preview() {
    await save();
    const state = await api.previewContent();
    setSnapshot(state);
    setConfig(state.config);
    return state;
  }
  const contentSelected = config.selected.some(id => CONTENT_GROUPS.includes(id));
  const contentKey = (value: Config) =>
    JSON.stringify([
      value.distro,
      value.user,
      value.selected.filter(id => CONTENT_GROUPS.includes(id)).sort(),
    ]);
  const previewed =
    !!snapshot.contentPreview &&
    snapshot.contentPreview.commit === config.contentCommit &&
    contentKey(config) === contentKey(snapshot.config);
  const contentCard = (
    <section className="card">
      <div className="section-heading">
        <h2>GitHub 커맨드 · 스킬</h2>
        <button disabled={busy || !contentSelected} onClick={() => action(preview)}>
          업데이트 확인
        </button>
      </div>
      <p>EXE와 별도로 다운로드합니다. 선택한 커밋의 파일만 검증해 적용하며, 기존 버전과 연결을 백업합니다.</p>
      <p className="muted">
        설치된 버전:{' '}
        {inspection?.linux?.contentCommit?.slice(0, 12) ||
          snapshot.contentPreview?.installedCommit?.slice(0, 12) ||
          '아직 확인되지 않음'}
      </p>
      {snapshot.contentPreview && previewed ? (
        <>
          <dl>
            <dt>적용할 커밋</dt>
            <dd>{snapshot.contentPreview.commit}</dd>
            <dt>변경 요약</dt>
            <dd>{snapshot.contentPreview.message}</dd>
            <dt>공용 명령</dt>
            <dd>{snapshot.contentPreview.commands.join(', ')}</dd>
            <dt>스킬</dt>
            <dd>{snapshot.contentPreview.skills.join(', ')}</dd>
          </dl>
          <details>
            <summary>변경 파일 {snapshot.contentPreview.changes.length}개</summary>
            <ul>
              {snapshot.contentPreview.changes.map(change => (
                <li key={change.path}>
                  {change.status} · {change.path}
                </li>
              ))}
            </ul>
          </details>
        </>
      ) : (
        <p>업데이트 확인을 눌러 적용할 버전과 변경 내용을 검토하세요.</p>
      )}
      <p className="muted">
        Claude 커맨드·Claude 스킬·Codex 공용 스킬의 선택은 설치 구성에서 변경합니다. 이미 이 설치기로 연결한
        대상은 같은 원본 버전을 함께 사용합니다.
      </p>
    </section>
  );
  const orcaInstallButton = (
    <button
      disabled={busy || !inspection?.supported || inspection.orcaInstalled}
      onClick={() =>
        action(async () => {
          setNotice('공식 Orca 설치 파일을 다운로드하고 검증하고 있습니다. 완료되면 설치 창이 열립니다.');
          await api.installOrca();
          setNotice(
            '공식 Orca 설치 창에서 설치를 마친 뒤 설치 상태를 다시 확인하세요. Orca 로그인 후 대상 Ubuntu의 WSL 터미널을 한 번 여세요.',
          );
        })
      }>
      {inspection?.orcaInstalled ? 'Orca 설치됨' : 'Orca 다운로드 · 설치'}
    </button>
  );
  async function inspect() {
    await save();
    const state = await api.inspect();
    setSnapshot(state);
    setConfig(state.config);
  }
  function field(key: keyof Config, label: string, placeholder = '', disabled = false) {
    return (
      <label className="field">
        {label}
        <input
          disabled={busy || disabled}
          value={String(config![key])}
          placeholder={placeholder}
          onChange={e => update(key, e.target.value as never)}
        />
      </label>
    );
  }
  function choose(item: Item, on: boolean) {
    const next = toggle(catalog, config!.selected, item.id, on);
    const changed = on
      ? next.filter(id => !config!.selected.includes(id) && id !== item.id)
      : config!.selected.filter(id => !next.includes(id) && id !== item.id);
    if (changed.length)
      setNotice(
        `${changed.map(id => catalog.find(i => i.id === id)!.title).join(', ')} 항목도 ${on ? '함께 선택' : '함께 해제'}했습니다.`,
      );
    update('selected', next);
  }
  return (
    <div className="layout">
      <aside>
        <div className="brand">
          <span className="brand-icon">↗</span> MuRing Dev Setup
        </div>
        <p className="aside-caption">새 PC, 익숙한 개발환경.</p>
        <nav>
          {pages.map((name, index) => (
            <button
              key={name}
              className={visiblePage === index ? 'active' : ''}
              disabled={busy || !access[index]}
              title={!access[index] ? '앞 단계의 필수 작업을 완료하세요.' : undefined}
              onClick={() => navigate(index)}>
              <span>{index === 6 ? '↻' : index + 1}</span>
              {name}
            </button>
          ))}
        </nav>
        <div className="aside-bottom">
          WINDOWS + UBUNTU
          <br />
          <small>MuRing · 설치 마법사 0.1.12</small>
        </div>
      </aside>
      <main>
        <header>
          <div className="eyebrow">{visiblePage === 6 ? '유지 관리' : `STEP ${visiblePage + 1} / 6`}</div>
          <h1>{pages[visiblePage]}</h1>
          <p>
            {
              [
                '현재 PC 상태를 확인하고 사용할 Ubuntu를 정합니다.',
                '필요한 도구만 선택하세요. 권장 항목도 자유롭게 바꿀 수 있습니다.',
                '설치 전에 변경할 내용을 확인하세요.',
                '실행 터미널의 안내에 따라 진행하세요. 완료한 단계는 실제 상태를 다시 확인합니다.',
                '도구 설치와 계정 연결은 별도입니다. 필요한 계정에 로그인하세요.',
                '선택한 항목과 계정 연결 상태를 확인하세요.',
                '개발 도구를 재설치하지 않고 공용 명령과 스킬만 업데이트합니다.',
              ][visiblePage]
            }
          </p>
        </header>
        <div className="page-content" key={visiblePage} tabIndex={0} aria-label="단계 본문">
          {error && (
            <div role="alert" className="banner error">
              {error}
            </div>
          )}
          {notice && (
            <div role="status" className="banner">
              {notice}
            </div>
          )}
          {snapshot.phase === 'reboot' && (
            <div className="banner">
              WSL 준비 후 Windows 재부팅이 필요합니다. 다시 앱을 열면 이어서 진행합니다.{' '}
              <button disabled={busy} onClick={() => action(() => api.reboot())}>
                재부팅
              </button>
            </div>
          )}
          {snapshot.phase === 'wsl-restart' && (
            <div className="banner">
              Ubuntu 사용자 설정 반영을 위해 WSL 재시작이 필요합니다.{' '}
              <button disabled={busy} onClick={() => action(() => api.shutdown())}>
                WSL 재시작
              </button>
            </div>
          )}
          {visiblePage === 0 && (
            <>
              <section className="card">
                <div className="section-heading">
                  <h2>PC 상태</h2>
                  <button disabled={busy} onClick={() => action(inspect)}>
                    환경 확인 / 새로고침
                  </button>
                </div>
                {!inspection ? (
                  <p>환경 확인을 눌러 시작하세요. 설치나 설정 변경 없이 현재 상태를 확인합니다.</p>
                ) : (
                  <>
                    <div className="facts">
                      <div>
                        Windows 11 x64
                        <strong>{inspection.supported ? '지원 환경' : '지원 환경 확인 필요'}</strong>
                      </div>
                      <div>
                        WSL
                        <strong>
                          {inspection.wslReady
                            ? `준비됨${inspection.wslVersion ? ` · ${inspection.wslVersion}` : ''}`
                            : '준비 필요'}
                        </strong>
                        <div className="fact-action">
                          <button
                            disabled={busy || !inspection.supported || inspection.wslReady}
                            onClick={() =>
                              action(async () => {
                                await save();
                                const result = await api.prepare();
                                setNotice(
                                  result.reboot
                                    ? '재부팅 후 앱을 다시 열어 주세요.'
                                    : 'WSL 준비를 확인했습니다. Ubuntu 설치를 진행하세요.',
                                );
                              })
                            }>
                            {inspection.wslReady ? 'WSL 준비됨' : 'WSL 준비'}
                          </button>
                        </div>
                      </div>
                      <div>
                        Orca<strong>{inspection.orcaInstalled ? '설치됨' : '설치 가능'}</strong>
                        <div className="fact-action">{orcaInstallButton}</div>
                      </div>
                    </div>
                    {inspection.error && <p className="warning">{inspection.error}</p>}
                  </>
                )}
              </section>
              <section className="card">
                <h2>Ubuntu와 개발 계정</h2>
                <Select
                  label="배포판"
                  disabled={busy}
                  value={config.distro}
                  options={Array.from(
                    new Set(['Ubuntu', ...(inspection?.distros.map(i => i.name) || [])]),
                  ).map(name => ({ value: name, label: name }))}
                  onChange={value =>
                    setConfig({
                      ...config,
                      distro: value,
                      installLocation: inspection?.distros.find(i => i.name === value)?.location || '',
                    })
                  }
                />
                {field('user', 'Ubuntu 사용자명', 'muring')}
                {inspection?.linux && (
                  <p className="muted">
                    확인된 계정: {inspection.linux.users.join(', ')} · 기존 .zshrc{' '}
                    {inspection.linux.zshrc ? '있음 — 보존 권장' : '없음'}
                  </p>
                )}
                {!existing && (
                  <Select
                    label="저장 위치 선택"
                    disabled={busy}
                    value={
                      inspection?.drives.some(d => config.installLocation === `${d.root}WSL\\Ubuntu`)
                        ? config.installLocation
                        : config.installLocation
                          ? 'custom'
                          : ''
                    }
                    options={[
                      { value: '', label: 'Windows 기본 위치' },
                      ...(inspection?.drives || []).map(d => ({
                        value: `${d.root}WSL\\Ubuntu`,
                        label: `${d.root}WSL\\Ubuntu · 여유 ${d.freeGB} GB`,
                      })),
                      { value: 'custom', label: '직접 입력' },
                    ]}
                    onChange={value =>
                      update('installLocation', value === 'custom' ? 'C:\\WSL\\Ubuntu' : value)
                    }
                  />
                )}
                {field(
                  'installLocation',
                  existing ? '기존 Ubuntu 위치 · 자동 이동하지 않음' : 'Ubuntu 가상 디스크 위치',
                  '비워 두면 Windows 기본 위치',
                  !!existing,
                )}
                {!existing && (
                  <p className="muted">새 계정은 개발용 WSL에 비밀번호 없는 sudo 권한으로 생성합니다.</p>
                )}
                <div className="actions">
                  <button
                    disabled={busy || !inspection?.supported || !inspection.wslReady}
                    onClick={() =>
                      action(async () => {
                        await save();
                        await api.install();
                        const state = await api.snapshot();
                        setConfig(state.config);
                        setNotice('Ubuntu 준비를 확인했습니다. 설치 구성을 선택하세요.');
                      })
                    }>
                    {existing ? '기존 Ubuntu 확인' : 'Ubuntu 설치'}
                  </button>
                </div>
              </section>
            </>
          )}
          {visiblePage === 1 && (
            <>
              <div className="profiles">
                {(['muring', 'common'] as const).map(profile => (
                  <button
                    disabled={busy}
                    className={`profile ${config.profile === profile ? 'selected' : ''}`}
                    key={profile}
                    onClick={() => {
                      const next = defaults(catalog, profile);
                      setConfig({ ...config, profile, selected: next.selected });
                    }}>
                    <strong>{profile === 'muring' ? 'MuRing 구성' : '공통 개발환경'}</strong>
                    {profile === 'muring' && <span className="badge">Recommended</span>}
                    <p>
                      {profile === 'muring'
                        ? 'Claude · Codex · 개인 KB · Orca'
                        : '기본 도구부터 필요한 항목만 추가'}
                    </p>
                  </button>
                ))}
              </div>
              <div className="banner">
                기존 셸 설정 보존 <span className="badge">Recommended</span>
                <br />
                필요한 도구 초기화만 별도 파일로 연결합니다. 전체 교체는 직접 선택할 수 있습니다.
              </div>
              <section className="card selections">
                {catalog.map(item => (
                  <label className={`option ${item.required ? 'required' : ''}`} key={item.id}>
                    <input
                      type="checkbox"
                      checked={config.selected.includes(item.id)}
                      disabled={
                        busy || item.required || (item.id === 'orca-patch' && !inspection?.patchSupported)
                      }
                      onChange={e => choose(item, e.target.checked)}
                    />
                    <div>
                      <strong>{item.title}</strong>{' '}
                      {item.required ? (
                        <span className="badge neutral">Required</span>
                      ) : recommended(item, config) ? (
                        <span className="badge">Recommended</span>
                      ) : null}
                      <p>{item.description}</p>
                      {item.id === 'orca-patch' && !inspection?.patchSupported && (
                        <small>검증된 Orca 1.4.202/1.4.215 파일이 확인되지 않아 선택할 수 없습니다.</small>
                      )}
                      {recommended(item, config) && (
                        <small>
                          {item.recommend === 'all'
                            ? '기본 개발 작업에 자주 사용하는 도구입니다.'
                            : item.recommend === 'zsh'
                              ? '선택한 zsh 환경의 편의 기능입니다.'
                              : 'MuRing 개발환경에서 사용하는 도구입니다.'}
                        </small>
                      )}
                    </div>
                  </label>
                ))}
              </section>
              <section className="card">
                <h2>선택 항목의 설정</h2>
                {config.selected.includes('git-name') && field('gitName', 'Git 작성자 이름')}
                {config.selected.includes('git-email') && field('gitEmail', 'Git 이메일')}
                {config.selected.includes('timezone') && field('timezone', '시간대')}
                {config.selected.includes('kb') && (
                  <>
                    {field('kbRepo', 'KB 저장소 URL')}
                    {field('kbDir', 'Ubuntu 안의 KB 설치 경로')}
                    <p className="muted">이 저장소를 읽을 수 있는 GitHub 계정으로 로그인해야 합니다.</p>
                  </>
                )}
              </section>
            </>
          )}
          {visiblePage === 2 && (
            <>
              {contentSelected && contentCard}
              <section className="card">
                <h2>설치할 항목 {selected.length}개</h2>
                <div className="chips">
                  {selected.map(item => (
                    <span key={item.id}>{item.title}</span>
                  ))}
                </div>
                <dl>
                  <dt>대상</dt>
                  <dd>
                    {config.distro} / {config.user}
                  </dd>
                  <dt>Windows 저장 위치</dt>
                  <dd>{config.installLocation || 'Windows 기본 위치'}</dd>
                  <dt>기존 설정</dt>
                  <dd>
                    {config.selected.includes('shell-replace')
                      ? '.zshrc 백업 후 전체 교체'
                      : '.zshrc 기존 내용 보존, 관리 블록 연결'}
                  </dd>
                  <dt>백업</dt>
                  <dd>변경하는 사용자 설정 파일 옆에 .bak.시간 형식으로 저장</dd>
                  <dt>도구 초기화</dt>
                  <dd>~/.config/dev-bootstrap에 관리 파일을 만들고 .bashrc와 로그인 설정에 연결</dd>
                  <dt>인증</dt>
                  <dd>
                    {authTools.join(' · ') || '선택된 로그인 없음'}
                    {config.selected.includes('orca') ? ' · Orca 앱 로그인' : ''}
                  </dd>
                </dl>
                {config.selected.includes('shell-theme') && (
                  <p>
                    프롬프트·단축키·자동완성 설정이 적용됩니다. 개인 설정은 ~/.zshrc.local에서 추가할 수
                    있습니다.
                  </p>
                )}
                {config.selected.includes('claude-settings') && (
                  <p>
                    Claude 설정이 없으면 fullscreen·dark-ansi·opus 설정을 생성합니다. 기존 파일은 유지합니다.
                  </p>
                )}
                {config.selected.includes('claude-permissions') && (
                  <p className="warning">선택한 Claude 권한 경고 생략 설정을 적용합니다.</p>
                )}
                {config.selected.includes('git-gcm') && (
                  <p>Windows Git Credential Manager가 설치되어 있어야 합니다.</p>
                )}
              </section>
              <section className="card">
                <h2>실행 안내</h2>
                <p>
                  별도 Ubuntu 실행 창이 열립니다. sudo 비밀번호를 요청하면 그 창에 입력하세요. 앱은 비밀번호를
                  받거나 저장하지 않습니다.
                </p>
                <p>KB 인증이나 Orca 준비가 필요하면 해당 항목을 안내하고 다른 독립 작업을 계속합니다.</p>
              </section>
            </>
          )}
          {visiblePage === 3 && (
            <>
              <section className="card">
                <div className="section-heading">
                  <h2>{busy ? '개발환경을 준비하고 있습니다' : labels[runState?.status || 'pending']}</h2>
                  <span>
                    {completed} / {selected.length} 단계
                  </span>
                </div>
                <progress max={selected.length} value={completed} />
                <p className="muted">단계 수 기준입니다. 각 단계의 소요 시간은 다릅니다.</p>
                <div className="steps">
                  {selected.map(item => (
                    <div className="step-row" key={item.id}>
                      <span className={`dot ${latest[item.id]?.status || 'pending'}`} />
                      <div>
                        <strong>{item.title}</strong>
                        <small>{latest[item.id]?.message || '실행 대기'}</small>
                      </div>
                      <span className="status">{labels[latest[item.id]?.status || 'pending']}</span>
                      {['failed', 'action-required', 'pending'].includes(latest[item.id]?.status) && (
                        <button disabled={busy} onClick={() => action(() => api.run(item.id))}>
                          재시도
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              </section>
              <div className="actions">
                <button
                  disabled={!busy}
                  onClick={() => api.stop().then(() => setNotice('현재 단계가 끝나면 중지합니다.'))}>
                  현재 단계 후 중지
                </button>
                <button disabled={busy} onClick={() => action(() => api.run())}>
                  전체 재검사 · 재시도
                </button>
                <button onClick={() => api.logs()}>로그 폴더 열기</button>
              </div>
            </>
          )}
          {visiblePage === 4 && (
            <>
              <section className="card">
                <h2>계정 연결</h2>
                <p>
                  선택한 항목의 설치와 계정 연결을 마치면 완료 화면이 열립니다. 남은 설치{' '}
                  {selected.length - completed}개 · 계정 연결 {authPending.length}개
                </p>
                <p>로그인 창에서 브라우저 안내를 따라 주세요. 창이 종료되면 인증 상태를 다시 확인합니다.</p>
                {authTools.map(tool => (
                  <div className="connection" key={tool}>
                    <div>
                      <strong>{tool}</strong>
                      <small>{inspection?.linux?.auth[tool] ? '연결 확인됨' : '로그인 필요'}</small>
                    </div>
                    <button
                      disabled={busy || !inspection?.linux?.tools[tool]}
                      onClick={() => action(() => api.login(tool))}>
                      로그인
                    </button>
                  </div>
                ))}
                <button disabled={busy} onClick={() => action(inspect)}>
                  인증 상태 다시 확인
                </button>
              </section>
              {config.selected.includes('kb') && (
                <section className="card">
                  <h2>개인 지식 저장소</h2>
                  <p>
                    GitHub 로그인 후 저장소 읽기 권한이 있는지 확인하세요. 연결이 끝나면 새 Codex 세션을
                    시작합니다.
                  </p>
                  <button disabled={busy} onClick={() => action(() => api.run('kb'))}>
                    KB 연결 재시도
                  </button>
                </section>
              )}
              {config.selected.includes('orca-auto') && (
                <section className="card">
                  <h2>Orca 자동 재패치</h2>
                  <p>
                    업데이트 후 이름 생성·터미널 출력 복원 패치를 확인하고 필요한 수정만 적용합니다. 이미
                    수정된 코드는 유지하며, 파일 잠금이 풀릴 때까지 기다리며, Orca를 강제 종료하지 않습니다.
                  </p>
                  <p>
                    처리할 수 없는 버전은 알림으로 안내합니다. 완료 표시는 자동화 설치 완료를 뜻하며, 현재
                    패치 적용 완료와는 다릅니다.
                  </p>
                  <button disabled={busy} onClick={() => action(() => api.run('orca-auto'))}>
                    자동 재패치 설치·상태 재확인
                  </button>
                </section>
              )}
              {config.selected.includes('orca-monitor') && (
                <section className="card">
                  <h2>Orca 패치 누락 감시</h2>
                  <p>
                    로그인 시와 5분마다 패치 상태를 확인합니다. 누락되거나 검증되지 않은 버전이면 알리며, 앱을
                    자동 수정하거나 종료하지 않습니다.
                  </p>
                  <p>이 항목의 완료는 감시 설치 완료를 뜻합니다. Orca 패치 적용 여부는 별도로 확인하세요.</p>
                  <button disabled={busy} onClick={() => action(() => api.run('orca-monitor'))}>
                    감시 설치·상태 재확인
                  </button>
                </section>
              )}
              {config.selected.includes('orca') && (
                <section className="card">
                  <h2>Orca 연결</h2>
                  <ol>
                    <li>아래 설치 버튼으로 공식 Windows 설치 창을 열고 설치를 마칩니다.</li>
                    <li>
                      앱에서 로그인하고 <strong>{config.distro}</strong>의 WSL 터미널을 한 번 엽니다.
                    </li>
                    <li>아래 버튼으로 스킬을 연결합니다.</li>
                  </ol>
                  <p>
                    앱 상태: {inspection?.orcaInstalled ? '설치 확인됨' : '아직 확인되지 않음'} · 브리지:{' '}
                    {inspection?.linux?.tools['orca-ide'] ? '확인됨' : '준비 필요'}
                  </p>
                  {orcaInstallButton}
                  <button disabled={busy} onClick={() => action(inspect)}>
                    Orca 설치 상태 확인
                  </button>
                  <button
                    disabled={busy || !inspection?.orcaInstalled}
                    onClick={() => action(() => api.run('orca'))}>
                    Orca 스킬 연결
                  </button>
                  {config.selected.includes('orca-patch') && (
                    <>
                      <p>
                        스킬 연결 후 Orca를 완전히 종료하고 패치를 실행하세요. 지원 파일을 다시 검증합니다.
                      </p>
                      <button disabled={busy} onClick={() => action(() => api.run('orca-patch'))}>
                        패치 적용
                      </button>
                    </>
                  )}
                </section>
              )}
            </>
          )}
          {visiblePage === 5 && (
            <>
              <section className="card summary">
                <div className="summary-icon">{completed === selected.length ? '✓' : '→'}</div>
                <h2>
                  {completed === selected.length ? '선택한 도구를 준비했습니다' : '마무리할 항목이 있습니다'}
                </h2>
                <p>
                  설치 확인 {completed} / {selected.length} · 계정 연결 대기 {authPending.length}개
                </p>
                {selected
                  .filter(i => latest[i.id]?.status !== 'completed')
                  .map(i => (
                    <p key={i.id}>
                      {i.title} — {labels[latest[i.id]?.status || 'pending']}
                    </p>
                  ))}
                <p>계정 연결은 도구 설치와 별도로 확인합니다. 새 Ubuntu 터미널에서 개발을 시작하세요.</p>
              </section>
              <div className="actions">
                <button disabled={busy} onClick={() => setPage(3)}>
                  설치 단계로 이동
                </button>
                <button disabled={busy} onClick={() => setPage(4)}>
                  계정 연결
                </button>
                <button onClick={() => api.logs()}>로그 폴더 열기</button>
                <button disabled={busy} onClick={() => action(() => api.shutdown())}>
                  WSL 재시작
                </button>
              </div>
            </>
          )}
          {visiblePage === 6 && (
            <>
              {contentCard}
              <section className="card">
                <h2>선택한 대상에 적용</h2>
                <div className="chips">
                  {selected
                    .filter(item => CONTENT_GROUPS.includes(item.id))
                    .map(item => (
                      <span key={item.id}>{item.title}</span>
                    ))}
                </div>
                <p>
                  이 작업은 sudo나 개발 도구 재설치 없이 실행합니다. Claude의 /명령과 Codex의 $스킬이 같은
                  원본을 읽도록 연결하며, 새 세션에서 반영 여부를 확인하세요.
                </p>
                <p>다른 설치 방식으로 만든 경로와 충돌하면 내용을 보존하고 안내합니다.</p>
              </section>
            </>
          )}
        </div>
        <div className="page-actions">
          {visiblePage === 0 && (
            <footer>
              <span>Ubuntu 환경 확인을 완료하면 다음 단계가 열립니다.</span>
              <button className="primary" disabled={busy || !access[1]} onClick={() => navigate(1)}>
                설치 구성 선택 →
              </button>
            </footer>
          )}
          {visiblePage === 1 && (
            <footer>
              <button disabled={busy} onClick={() => setPage(0)}>
                이전
              </button>
              <button
                className="primary"
                disabled={busy}
                onClick={() =>
                  action(async () => {
                    const state = contentSelected ? await preview() : await save();
                    setReviewed(configurationKey(state.config));
                    setPage(2);
                  })
                }>
                변경 내용 확인 →
              </button>
            </footer>
          )}
          {visiblePage === 2 && (
            <footer>
              <button disabled={busy} onClick={() => setPage(1)}>
                선택 변경
              </button>
              <button
                className="primary"
                disabled={busy || !inspection?.linux || (contentSelected && !previewed)}
                onClick={() =>
                  action(async () => {
                    await save();
                    setPage(3);
                    await api.run();
                  }, 3)
                }>
                선택한 항목 설치 시작
              </button>
            </footer>
          )}
          {visiblePage === 3 && (
            <footer>
              <span>{!access[4] && !busy ? '필수 설치를 완료하거나 실패한 항목을 재시도하세요.' : ''}</span>
              <button className="primary" disabled={busy || !access[4]} onClick={() => navigate(4)}>
                로그인 · 연동 →
              </button>
            </footer>
          )}
          {visiblePage === 4 && (
            <footer>
              <button disabled={busy} onClick={() => setPage(3)}>
                설치 상태 보기
              </button>
              <button className="primary" disabled={busy || !access[5]} onClick={() => navigate(5)}>
                설치 완료 확인
              </button>
            </footer>
          )}
          {visiblePage === 6 && (
            <footer>
              <button disabled={busy} onClick={() => setPage(1)}>
                대상 선택 변경
              </button>
              <button
                className="primary"
                disabled={busy || !contentSelected || !previewed || !snapshot.contentPreview}
                onClick={() =>
                  action(async () => {
                    await save();
                    const state = await api.updateContent();
                    setSnapshot(state);
                    setConfig(state.config);
                    setNotice('커맨드·스킬 업데이트를 마쳤습니다. 새 Claude·Codex 세션을 시작하세요.');
                  })
                }>
                확인한 버전 적용
              </button>
            </footer>
          )}
        </div>
        <div className="bottom-note">
          {busy
            ? '작업 중입니다. 실행 터미널에 입력 요청이 있는지 확인하세요.'
            : '진행 기록은 이 PC에 보관됩니다. 다시 실행하면 실제 설치 상태를 확인합니다.'}
        </div>
      </main>
      <ProgressRail
        operation={operations[visiblePage]}
        busy={busy && ownerRef.current === visiblePage}
        open={railOpen}
        onToggle={() => setRailOpen(!railOpen)}
        events={visiblePage === 3 ? snapshot.events : undefined}
        labels={labels}
      />
    </div>
  );
}
createRoot(document.getElementById('root')!).render(<App />);
