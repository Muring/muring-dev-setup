import { test as base, expect } from '@playwright/test';
import fs from 'node:fs';
import { defaults } from '../electron/model';
const catalog = JSON.parse(fs.readFileSync('../shared/catalog.json', 'utf8'));
const test = base.extend<{ startupFailure: string }>({
  startupFailure: ['', { option: true }],
});
test.beforeEach(async ({ page, startupFailure }) => {
  const config = defaults(catalog);
  await page.addInitScript(
    ({ catalog, config, startupFailure }) => {
      const state: any = {
        config,
        events: [],
        busy: false,
        phase: 'configure',
        logPath: 'test.log',
        inspection: {
          supported: true,
          wslReady: true,
          locationSupported: true,
          distros: [{ name: 'Ubuntu', location: 'D:\\WSL\\Ubuntu', version: 2 }],
          drives: [{ root: 'D:\\', freeGB: 415 }],
          orcaInstalled: false,
          patchSupported: false,
          patchApplied: false,
          linux: {
            osId: 'ubuntu',
            users: ['muring'],
            user: 'muring',
            zshrc: true,
            gitName: '',
            gitEmail: '',
            gitBranch: 'main',
            timezone: 'Asia/Seoul',
            auth: { gh: false, claude: false, codex: false },
            tools: { gh: true, claude: true, codex: true },
          },
        },
      };
      (window as any).testState = state;
      (window as any).bootstrap = {
        snapshot: async () => structuredClone(state),
        catalog: async () => catalog,
        save: async (c: any) => {
          state.config = c;
          return structuredClone(state);
        },
        inspect: async () => structuredClone(state),
        prepare: async () => ({ reboot: false }),
        installOrca: async () => {
          (window as any).orcaInstallerOpened = true;
          return structuredClone(state);
        },
        install: async () => ({ restartWsl: false }),
        previewContent: async () => {
          state.config.contentCommit = 'a'.repeat(40);
          state.contentPreview = {
            commit: state.config.contentCommit,
            message: '공용 명령 업데이트',
            commands: ['commit'],
            skills: ['commit'],
            changes: [{ path: 'skills/commit/SKILL.md', status: 'modified' }],
          };
          return structuredClone(state);
        },
        updateContent: async () => {
          (window as any).contentApplied = true;
          return structuredClone(state);
        },
        run: async (target?: string) => {
          (window as any).installerRan = true;
          state.events = state.config.selected.map((step: string) => ({
            step,
            status: step === 'kb' && !target ? 'action-required' : 'completed',
            message: step === 'kb' && !target ? 'GitHub 로그인 필요' : '실제 상태 확인 완료',
            time: Date.now() / 1000,
            version: 1,
          }));
          state.events.push({
            step: '_run',
            status: 'incomplete',
            message: '연결 대기',
            version: 1,
            time: Date.now() / 1000,
          });
          return structuredClone(state);
        },
        stop: async () => {},
        login: async (t: string) => {
          state.inspection.linux.auth[t] = true;
          return structuredClone(state);
        },
        shutdown: async () => structuredClone(state),
        reboot: async () => {},
        logs: async () => {},
      };
      if (startupFailure) {
        const w = window as any;
        w.startupFail = true;
        w.startupCalls = { catalog: 0, snapshot: 0 };
        for (const method of ['catalog', 'snapshot']) {
          const original = w.bootstrap[method];
          w.bootstrap[method] = async () => {
            w.startupCalls[method]++;
            if (w.startupFail && method === startupFailure) throw Error('초기 조회 실패');
            if (method === 'snapshot' && w.holdStartup)
              await new Promise<void>(resolve => {
                w.releaseStartup = resolve;
              });
            return original();
          };
        }
      }
    },
    { catalog, config, startupFailure },
  );
  await page.goto('/');
});

for (const startupFailure of ['snapshot', 'catalog']) {
  test.describe(`initial ${startupFailure} failure`, () => {
    test.use({ startupFailure, viewport: { width: 900, height: 650 } });
    test('shows repeated errors and reloads both inputs before starting polling', async ({
      page,
    }, testInfo) => {
      await expect(page.getByRole('alert')).toHaveText('초기 조회 실패');
      const retry = page.getByRole('button', { name: '다시 시도', exact: true });
      await expect(retry).toBeEnabled();
      await expect(retry).toBeInViewport();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath('startup-error.png') });
      await page.waitForTimeout(1200);
      expect(await page.evaluate(() => (window as any).startupCalls)).toEqual({ catalog: 1, snapshot: 1 });

      await retry.click();
      await expect
        .poll(() => page.evaluate(() => (window as any).startupCalls))
        .toEqual({ catalog: 2, snapshot: 2 });
      await expect(page.getByRole('alert')).toHaveText('초기 조회 실패');
      await page.evaluate(() => {
        (window as any).startupFail = false;
        (window as any).holdStartup = true;
      });
      await retry.click();
      await expect(page.getByRole('status')).toHaveText('설치 환경을 준비하고 있습니다…');
      await expect(retry).toHaveCount(0);
      await expect(page.getByRole('alert')).toHaveCount(0);
      await page.waitForTimeout(1200);
      expect(await page.evaluate(() => (window as any).startupCalls)).toEqual({ catalog: 3, snapshot: 3 });
      await page.evaluate(() => {
        (window as any).holdStartup = false;
        (window as any).releaseStartup();
      });
      await expect(page.getByRole('heading', { name: '환경 확인', exact: true })).toBeVisible();
      await expect.poll(() => page.evaluate(() => (window as any).startupCalls.snapshot)).toBeGreaterThan(3);
      await page.getByRole('button', { name: '설치 구성 선택 →' }).click();
      await expect(page.getByRole('checkbox')).toHaveCount(23);
      expect(await page.evaluate(() => (window as any).installerRan)).toBeUndefined();
    });
  });
}
test('recommended choices preserve existing config and dependency deselection cascades', async ({ page }) => {
  await page.getByRole('button', { name: '설치 구성 선택 →' }).click();
  await expect(page.getByRole('checkbox')).toHaveCount(23);
  const autoPatch = page.getByRole('checkbox', { name: 'Orca 자동 재패치', exact: false });
  await expect(autoPatch).not.toBeChecked();
  await autoPatch.check();
  await expect(autoPatch).toBeChecked();
  await expect(page.getByRole('checkbox', { name: '.zshrc 전체 교체', exact: false })).not.toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'Claude 권한 경고 생략', exact: false })).not.toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'Orca 1.4.202/1.4.215', exact: false })).toBeDisabled();
  const monitor = page.getByRole('checkbox', { name: 'Orca 패치 누락 감시', exact: false });
  await expect(monitor).not.toBeChecked();
  await expect(monitor).toBeEnabled();
  await monitor.check();
  await expect(monitor).toBeChecked();
  await page.getByRole('checkbox', { name: 'Node · fnm', exact: false }).uncheck();
  await expect(page.getByRole('checkbox', { name: '개인 지식 저장소', exact: false })).not.toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'Codex Recommended', exact: false })).not.toBeChecked();
  await page.getByRole('button', { name: '공통 개발환경', exact: false }).click();
  await expect(page.getByRole('checkbox', { name: 'Node · fnm', exact: false })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'Orca 스킬 연결', exact: false })).not.toBeChecked();
});
test('review, progress, authentication, and incomplete summary are separate', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.getByRole('button', { name: '설치 구성 선택 →' }).click();
  await page.getByRole('checkbox', { name: 'Orca 패치 누락 감시', exact: false }).check();
  await page.getByRole('button', { name: '변경 내용 확인 →' }).click();
  await expect(page.getByText('.zshrc 기존 내용 보존, 관리 블록 연결')).toBeVisible();
  await page.getByRole('button', { name: '선택한 항목 설치 시작' }).click();
  await expect(page.getByText('GitHub 로그인 필요', { exact: true })).toBeVisible();
  await expect(
    page.getByRole('complementary', { name: '진행 상황 패널' }).getByText('설치 진행 기록'),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: '진행 기록 보기' })).toHaveCount(0);
  await page.getByRole('button', { name: '로그인 · 연동 →' }).click();
  await expect(page.getByRole('heading', { name: 'Orca 패치 누락 감시', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '감시 설치·상태 재확인' })).toBeEnabled();
  await page.getByRole('button', { name: '로그인', exact: true }).first().click();
  await expect(page.getByText('연결 확인됨', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '설치 완료 확인' })).toBeDisabled();
  for (const button of await page.getByRole('button', { name: '로그인', exact: true }).all())
    await button.click();
  await page.getByRole('button', { name: 'KB 연결 재시도' }).click();
  await page.getByRole('button', { name: '설치 완료 확인' }).click();
  await expect(page.getByRole('heading', { name: '선택한 도구를 준비했습니다' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('content update requires preview and does not run installer', async ({ page }) => {
  await page.getByRole('button', { name: '커맨드 · 스킬 업데이트', exact: false }).click();
  await expect(page.getByRole('button', { name: '확인한 버전 적용' })).toBeDisabled();
  await page.getByRole('button', { name: '업데이트 확인', exact: true }).click();
  await expect(page.getByText('a'.repeat(40), { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '확인한 버전 적용' }).click();
  expect(await page.evaluate(() => (window as any).contentApplied)).toBe(true);
  expect(await page.evaluate(() => (window as any).installerRan)).toBeUndefined();
});
test('changing content targets requires another preview', async ({ page }) => {
  await page.getByRole('button', { name: '커맨드 · 스킬 업데이트', exact: false }).click();
  await page.getByRole('button', { name: '업데이트 확인', exact: true }).click();
  await expect(page.getByRole('button', { name: '확인한 버전 적용' })).toBeEnabled();
  await page.getByRole('button', { name: '대상 선택 변경' }).click();
  await page.getByRole('checkbox', { name: 'Codex 공용 스킬', exact: false }).uncheck();
  await page.getByRole('button', { name: '커맨드 · 스킬 업데이트', exact: false }).click();
  await expect(page.getByRole('button', { name: '확인한 버전 적용' })).toBeDisabled();
});

test('future stages stay locked and installer is launched only on request', async ({ page }) => {
  for (const name of ['변경 내용 확인', '설치 진행', '로그인 · 연동', '완료'])
    await expect(page.locator('nav').getByRole('button', { name, exact: false })).toBeDisabled();
  const wsl = page.getByRole('button', { name: 'WSL 준비됨' });
  const orca = page.getByRole('button', { name: 'Orca 다운로드 · 설치' });
  await expect(wsl).toBeDisabled();
  const a = await wsl.boundingBox();
  const b = await orca.boundingBox();
  expect(b!.x).toBeGreaterThan(a!.x + a!.width + 15);
  expect(b!.y).toBe(a!.y);
  await page.screenshot({ path: 'test-results/pc-state.png' });
  await orca.click();
  expect(await page.evaluate(() => (window as any).orcaInstallerOpened)).toBe(true);
  await page.evaluate(() => {
    (window as any).testState.inspection.orcaInstalled = true;
  });
  await expect(page.getByRole('button', { name: 'Orca 설치됨' })).toBeDisabled();
  await page.evaluate(() => {
    (window as any).testState.inspection.wslReady = false;
  });
  await expect(page.getByRole('button', { name: 'WSL 준비', exact: true })).toBeEnabled();
  expect(await page.evaluate(() => (window as any).installerRan)).toBeUndefined();
});
test('only body scrolls at the minimum window size', async ({ page }) => {
  await page.setViewportSize({ width: 900, height: 650 });
  await page.getByRole('button', { name: '설치 구성 선택 →' }).click();
  const heading = page.getByRole('heading', { name: '설치 구성', exact: true });
  const next = page.getByRole('button', { name: '변경 내용 확인 →' });
  const before = await heading.boundingBox();
  const buttonBefore = await next.boundingBox();
  await page.locator('.page-content').evaluate(el => (el.scrollTop = el.scrollHeight));
  expect(await heading.boundingBox()).toEqual(before);
  expect(await next.boundingBox()).toEqual(buttonBefore);
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
  expect(await page.locator('.page-content').evaluate(el => el.scrollTop)).toBeGreaterThan(500);
  expect(buttonBefore!.y + buttonBefore!.height).toBeLessThan(650);
  await page.screenshot({ path: 'test-results/fixed-layout.png' });
});
test('editing the inspected account locks configuration and updates', async ({ page }) => {
  await page.getByLabel('Ubuntu 사용자명', { exact: true }).fill('another');
  await expect(page.getByRole('button', { name: '설치 구성 선택 →' })).toBeDisabled();
  await expect(
    page.locator('nav').getByRole('button', { name: '커맨드 · 스킬 업데이트', exact: false }),
  ).toBeDisabled();
});

test('long tasks show live stages, real counts, elapsed time and failure history', async ({ page }) => {
  await page.evaluate(() => {
    const w = window as any;
    w.bootstrap.inspect = () =>
      new Promise((resolve, reject) => {
        const state = w.testState;
        state.busy = true;
        state.operation = {
          title: '환경 확인',
          status: 'running',
          startedAt: Date.now() - 3000,
          current: { label: 'Codex 로그인 상태 확인', completed: 2, total: 13, unit: 'items' },
          steps: [
            { label: 'Windows 검사', time: Date.now(), status: 'completed' },
            { label: 'Codex 로그인 상태 확인', time: Date.now(), status: 'running' },
          ],
        };
        w.failInspection = () => {
          state.busy = false;
          state.operation.status = 'failed';
          state.operation.endedAt = Date.now();
          state.operation.steps[1].status = 'failed';
          reject(Error('검사 연결 실패'));
        };
      });
  });
  await page.getByRole('button', { name: '환경 확인 / 새로고침' }).click();
  const panel = page.getByRole('region', { name: '작업 진행 상황' });
  await expect(panel.getByText('Codex 로그인 상태 확인', { exact: true })).toBeVisible();
  await expect(panel.getByText('2 / 13 항목 처리', { exact: false })).toBeVisible();
  await expect(panel.getByText('진행 과정 2개')).toBeVisible();
  await expect(panel.getByRole('listitem').filter({ hasText: 'Windows 검사' })).toBeVisible();
  await page.screenshot({ path: 'test-results/progress.png' });
  await page.evaluate(() => (window as any).failInspection());
  await expect(page.getByRole('alert')).toContainText('검사 연결 실패');
  await expect(panel).toHaveClass(/failed/);
});
test('dropdown lists are styled, keyboard accessible and close on Escape/outside', async ({ page }) => {
  await page.evaluate(() => {
    (window as any).testState.inspection.distros.push({
      name: 'Ubuntu-Test',
      version: 2,
      location: 'D:\\Test',
    });
  });
  await page.waitForTimeout(1100);
  const distro = page.getByRole('combobox', { name: '배포판' });
  await distro.click();
  await expect(page.getByRole('listbox')).toBeVisible();
  await expect(page.getByRole('option', { name: 'Ubuntu', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await page.screenshot({ path: 'test-results/dropdown.png' });
  await distro.press('ArrowDown');
  await distro.press('Enter');
  await expect(distro).toContainText('Ubuntu-Test');
  await distro.click();
  await distro.press('Escape');
  await expect(page.getByRole('listbox')).toHaveCount(0);
  await distro.click();
  await page.getByRole('heading', { name: '환경 확인', exact: true }).click();
  await expect(page.getByRole('listbox')).toHaveCount(0);
  await expect(page.locator('select')).toHaveCount(0);
  // A scroll event that does not move the trigger (queued by scroll-into-view before opening) must not close the menu; a real scroll must.
  await distro.click();
  await expect(page.getByRole('listbox')).toBeVisible();
  await page.locator('.page-content').dispatchEvent('scroll');
  await expect(page.getByRole('listbox')).toBeVisible();
  await page.locator('.page-content').evaluate(el => {
    el.scrollTop = el.scrollHeight;
  });
  await expect(page.getByRole('listbox')).toHaveCount(0);
  await page.evaluate(() => {
    (window as any).testState.inspection.distros = [];
  });
  const location = page.getByRole('combobox', { name: '저장 위치 선택' });
  await expect(location).toBeVisible();
  await location.click();
  await location.press('End');
  await location.press('Enter');
  await expect(page.getByLabel('Ubuntu 가상 디스크 위치', { exact: true })).toHaveValue('C:\\WSL\\Ubuntu');
});
test('operation state stays with its stage and comes back on return', async ({ page }) => {
  await page.evaluate(() => {
    const w = window as any;
    w.bootstrap.inspect = async () => {
      const state = w.testState;
      state.operation = {
        title: '환경 확인',
        status: 'completed',
        startedAt: Date.now() - 2000,
        endedAt: Date.now(),
        current: { label: 'Ubuntu 검사 완료' },
        steps: [
          { label: 'Windows 검사', time: Date.now(), status: 'completed' },
          { label: 'Ubuntu 검사 완료', time: Date.now(), status: 'completed' },
        ],
      };
      return structuredClone(state);
    };
  });
  const rail = page.getByRole('complementary', { name: '진행 상황 패널' });
  await expect(rail.getByText('이 단계에서 실행한 작업이 없습니다.')).toBeVisible();
  await page.getByRole('button', { name: '환경 확인 / 새로고침' }).click();
  await expect(rail.getByText('Ubuntu 검사 완료', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '설치 구성 선택 →' }).click();
  await page.waitForTimeout(1100);
  await expect(rail.getByText('이 단계에서 실행한 작업이 없습니다.')).toBeVisible();
  await expect(rail.getByText('Ubuntu 검사 완료', { exact: true })).toHaveCount(0);
  await page.locator('nav').getByRole('button', { name: '환경 확인' }).click();
  await expect(rail.getByText('Ubuntu 검사 완료', { exact: true })).toBeVisible();
  await expect(rail.getByText('작업 종료', { exact: false })).toBeVisible();
});
test('rail collapses to a strip and reopens when a new task starts', async ({ page }) => {
  const rail = page.getByRole('complementary', { name: '진행 상황 패널' });
  const body = page.locator('.page-content');
  const openWidth = (await rail.boundingBox())!.width;
  const bodyWidth = (await body.boundingBox())!.width;
  expect(openWidth).toBeGreaterThanOrEqual(280);
  await page.getByRole('button', { name: '진행 상황 패널 접기' }).click();
  await expect(rail).toHaveClass(/closed/);
  await expect.poll(async () => (await rail.boundingBox())!.width).toBeLessThanOrEqual(44);
  await expect.poll(async () => (await body.boundingBox())!.width).toBeGreaterThan(bodyWidth + 200);
  await page.getByRole('button', { name: '진행 상황 패널 펼치기' }).click();
  await expect(rail).toHaveClass(/open/);
  await page.getByRole('button', { name: '진행 상황 패널 접기' }).click();
  await page.getByRole('button', { name: '환경 확인 / 새로고침' }).click();
  await expect(rail).toHaveClass(/open/);
  await page.screenshot({ path: 'test-results/rail.png' });
});
