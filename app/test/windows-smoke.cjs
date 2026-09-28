// Optional read-only smoke test for an already launched Windows build.
// Start the app with --remote-debugging-port=9337 and an isolated LOCALAPPDATA.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9337');
  const page = browser
    .contexts()[0]
    .pages()
    .find(p => p.url().startsWith('file:'));
  assert(page, 'App page missing');
  assert.equal(await page.title(), 'MuRing Dev Setup');
  await page.getByText('MuRing · 설치 마법사 0.1.10', { exact: true }).waitFor();
  const errors = [];
  page.on('pageerror', error => errors.push(String(error)));
  await page.getByRole('heading', { name: '환경 확인', exact: true }).waitFor();
  const result = await page.evaluate(async () => {
    const catalog = await window.bootstrap.catalog();
    const samples = [];
    const timer = setInterval(async () => {
      samples.push((await window.bootstrap.snapshot()).operation?.status);
    }, 150);
    const state = await window.bootstrap.inspect();
    clearInterval(timer);
    if (!samples.includes('running')) throw Error('Live operation progress was not visible');
    if (!state.operation.steps.some(step => step.label.includes('Windows 검사 완료')))
      throw Error('Windows progress missing');
    if (!state.operation.steps.some(step => step.label.includes('Codex 로그인')))
      throw Error('Ubuntu progress missing');
    return {
      catalog: catalog.length,
      supported: state.inspection.supported,
      wsl: state.inspection.wslReady,
      linux: !!state.inspection.linux,
      os: state.inspection.linux?.osId,
      error: state.inspection.error,
    };
  });
  assert.equal(result.catalog, 22);
  assert.equal(result.supported, true);
  assert.equal(result.wsl, true);
  assert.equal(result.linux, true, result.error);
  assert.equal(result.os, 'ubuntu');
  const preview = await page.evaluate(async () => {
    const state = await window.bootstrap.previewContent();
    return state.contentPreview;
  });
  assert.match(preview.commit, /^[0-9a-f]{40}$/);
  assert(preview.commands.includes('commit'));
  assert(preview.skills.includes('code-audit'));
  assert.deepEqual(errors, []);
  await page.getByRole('button', { name: '설치 구성 선택 →' }).click();
  await page.getByRole('heading', { name: '설치 구성', exact: true }).waitFor();
  assert.equal(await page.getByRole('checkbox').count(), 22);
  const monitor = page.getByRole('checkbox', { name: 'Orca 패치 누락 감시', exact: false });
  assert.equal(await monitor.isChecked(), false);
  assert.equal(await monitor.isEnabled(), true);
  await monitor.check();
  assert.equal(await monitor.isChecked(), true);
  assert.equal(
    await page.locator('nav').getByRole('button', { name: '설치 진행', exact: false }).isDisabled(),
    true,
  );
  const heading = page.getByRole('heading', { name: '설치 구성', exact: true });
  const before = await heading.boundingBox();
  await page.locator('.page-content').evaluate(el => (el.scrollTop = el.scrollHeight));
  assert.deepEqual(await heading.boundingBox(), before);
  assert.equal(await page.evaluate(() => window.scrollY), 0);
  await page.screenshot({
    path: require('node:path').join(process.env.TEMP, 'dev-bootstrap-smoke.png'),
    fullPage: true,
  });
  console.log(
    'PASS: packaged Windows Electron app, sandbox preload, IPC, actual WSL inspection, live GitHub content preview and configuration screen',
  );
  await page.evaluate(() => window.close());
  await browser.close();
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
