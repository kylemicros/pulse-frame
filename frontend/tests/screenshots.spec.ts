import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { build, preview, type PreviewServer } from 'vite';
import { MockBackend, STREAM_URL } from './support/mock-backend';
import { longestPathCommands, monitorPage, refuseCamera, videoIsPlaying } from './support/monitor-page';

const FRONTEND_ROOT = fileURLToPath(new URL('..', import.meta.url));

const VIEWPORTS = [
  { name: 'desktop', size: { width: 1280, height: 800 } },
  { name: 'tablet', size: { width: 820, height: 1180 } },
  { name: 'phone', size: { width: 390, height: 844 } },
] as const;

const OK_READING = { bpm: 72.4, quality_db: 6.3, state: 'ok' } as const;
const SHOWN_BPM = /^(72\.4|72)$/;

const FAKE_DEVICE_LABELS: Record<MediaDeviceKind, RegExp> = {
  videoinput: /^fake_device_\d+$/,
  audioinput: /^Fake (Default )?Audio Input( \d+)?$/,
  audiooutput: /^Fake (Default )?Audio Output( \d+)?$/,
};

type ListedDevice = { kind: MediaDeviceKind; label: string };

type Session = { page: Page; backend: MockBackend; networkSocketUrls: string[] };

type PageSocketsWindow = Window & { socketRecords: Array<{ url: string }> };

function listDevices(page: Page): Promise<ListedDevice[]> {
  return page.evaluate(async () =>
    (await navigator.mediaDevices.enumerateDevices()).map((device) => ({ kind: device.kind, label: device.label })),
  );
}

async function expectOnlyFakeDevices(page: Page): Promise<void> {
  const devices = await listDevices(page);
  const cameraCount = devices.filter((device) => device.kind === 'videoinput').length;
  const notFakeKinds = devices
    .filter((device) => !FAKE_DEVICE_LABELS[device.kind].test(device.label))
    .map((device) => device.kind);

  expect(cameraCount, 'Chromium lists no fake camera').toBeGreaterThan(0);
  expect(notFakeKinds, 'kinds of the listed devices that are not Chromium fake devices').toEqual([]);
}

async function attachMockOnly(page: Page): Promise<Session> {
  const networkSocketUrls: string[] = [];
  page.on('websocket', (socket) => networkSocketUrls.push(socket.url()));
  const backend = await MockBackend.attach(page);
  return { page, backend, networkSocketUrls };
}

function pageSocketUrls(page: Page): Promise<string[]> {
  return page.evaluate(() => (globalThis as unknown as PageSocketsWindow).socketRecords.map((record) => record.url));
}

async function expectOnlyMockedSockets({ page, backend, networkSocketUrls }: Session): Promise<void> {
  const opened = await pageSocketUrls(page);

  expect(opened.filter((url) => url !== STREAM_URL), 'sockets opened to a URL the mock does not serve').toEqual([]);
  await expect
    .poll(() => backend.connections.filter((connection) => connection.accepted).length, {
      message: 'sockets the page opened that the mock did not accept',
    })
    .toBe(opened.length);
  expect(networkSocketUrls, 'sockets that reached the network instead of the mock').toEqual([]);
}

async function capture(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  await page.mouse.move(0, 0);
  await page.screenshot({
    path: testInfo.outputPath(`${name}.png`),
    fullPage: true,
    animations: 'disabled',
    caret: 'hide',
  });
}

test.describe('monitor page screenshots', () => {
  test.describe.configure({ mode: 'default' });

  let outDir = '';
  let server: PreviewServer | null = null;

  test.beforeAll(async () => {
    outDir = mkdtempSync(join(tmpdir(), 'pulse-frame-build-'));
    await build({ root: FRONTEND_ROOT, logLevel: 'silent', build: { outDir, emptyOutDir: true } });
    server = await preview({
      root: FRONTEND_ROOT,
      logLevel: 'silent',
      build: { outDir },
      preview: { host: '127.0.0.1', port: 0, strictPort: false },
    });
  });

  test.afterAll(async () => {
    await server?.close();
    rmSync(outDir, { recursive: true, force: true });
  });

  async function openBuiltPage(page: Page): Promise<void> {
    const url = server?.resolvedUrls?.local[0] ?? '';
    expect(url).not.toBe('');
    await page.goto(url);
    await expectOnlyFakeDevices(page);
  }

  async function idle(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await attachMockOnly(page);
    const monitor = monitorPage(page);

    await openBuiltPage(page);

    await expect(monitor.start).toBeVisible();
    await expect(monitor.quality.getByText('No value yet.', { exact: true })).toBeVisible();
    expect(session.backend.connections).toEqual([]);
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function settling(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await attachMockOnly(page);
    const monitor = monitorPage(page);

    await openBuiltPage(page);
    await monitor.start.click();

    await expect.poll(() => session.backend.frames.length).toBeGreaterThan(1);
    await expect.poll(() => videoIsPlaying(monitor.video)).toBe(true);
    await expect(monitor.heartRate).toContainText(/Settling \d+ s/);
    expect(session.backend.openConnections()).toHaveLength(1);
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function reading(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await attachMockOnly(page);
    const monitor = monitorPage(page);

    await openBuiltPage(page);
    await monitor.start.click();
    await expect.poll(() => session.backend.frames.length).toBeGreaterThan(1);
    session.backend.pushReading(OK_READING);

    await expect(monitor.bpmValue).toHaveText(SHOWN_BPM);
    await expect.poll(() => longestPathCommands(monitor.pulse)).toBeGreaterThan(10);
    await expect.poll(() => videoIsPlaying(monitor.video)).toBe(true);
    expect(session.backend.openConnections()).toHaveLength(1);
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function cameraDenied(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    await refuseCamera(page, 'NotAllowedError');
    const session = await attachMockOnly(page);
    const monitor = monitorPage(page);

    await openBuiltPage(page);
    await monitor.start.click();

    await expect(monitor.alertWith('CAMERA_DENIED')).toBeVisible();
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  for (const viewport of VIEWPORTS) {
    test.describe(`${viewport.name} screenshots`, () => {
      test.use({ viewport: viewport.size });

      test(`screenshots the idle page at ${viewport.name} width`, async ({ page }, testInfo) => {
        await idle(page, testInfo, `${viewport.name}-idle`);
      });

      test(`screenshots the settling page at ${viewport.name} width`, async ({ page }, testInfo) => {
        await settling(page, testInfo, `${viewport.name}-settling`);
      });

      test(`screenshots a live reading at ${viewport.name} width`, async ({ page }, testInfo) => {
        await reading(page, testInfo, `${viewport.name}-reading`);
      });

      test(`screenshots the camera denied error at ${viewport.name} width`, async ({ page }, testInfo) => {
        await cameraDenied(page, testInfo, `${viewport.name}-camera-denied`);
      });
    });

    test.describe(`${viewport.name} dark theme screenshots`, () => {
      test.use({ viewport: viewport.size, colorScheme: 'dark' });

      test(`screenshots the idle page in the dark theme at ${viewport.name} width`, async ({ page }, testInfo) => {
        await idle(page, testInfo, `${viewport.name}-dark-idle`);
      });

      test(`screenshots a live reading in the dark theme at ${viewport.name} width`, async ({ page }, testInfo) => {
        await reading(page, testInfo, `${viewport.name}-dark-reading`);
      });

      test(`screenshots the camera denied error in the dark theme at ${viewport.name} width`, async ({ page }, testInfo) => {
        await cameraDenied(page, testInfo, `${viewport.name}-dark-camera-denied`);
      });
    });
  }
});
