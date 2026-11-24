import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page, type TestInfo } from '@playwright/test';
import { build, preview, type PreviewServer } from 'vite';
import { advanceRun, advanceRunUntil, guidedPage, pushAndConfirm, RUN_STOPPED_TEXT } from './support/guided-page';
import { faceScene, MockBackend, STREAM_URL } from './support/mock-backend';
import { longestPathCommands, monitorPage, refuseCamera, setTabHidden, videoIsPlaying } from './support/monitor-page';

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

async function startGuidedRun(page: Page, session: Session): Promise<void> {
  await guidedPage(page).start.click();
  await expect.poll(() => session.backend.frames.length).toBeGreaterThan(1);
}

async function guidedLinkLost(page: Page, session: Session, close: { code: number; reason?: string }): Promise<void> {
  await startGuidedRun(page, session);
  await advanceRun(page, session.backend, 10000, 2500);
  await pushAndConfirm(page, session.backend, OK_READING);
  await expectOnlyMockedSockets(session);
  session.backend.refuseEveryConnection(close);
  session.backend.dropOpenConnections(close);
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

  async function openBuiltGuidedRun(page: Page): Promise<Session> {
    const session = await attachMockOnly(page);
    await page.clock.install();
    await openBuiltPage(page);
    const guided = guidedPage(page);
    await guided.guidedTab.click();
    await expect(guided.panel).toBeVisible();
    return session;
  }

  async function guidedIdle(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);

    await expect(guided.start).toBeVisible();
    await expect(guided.chime).toHaveAttribute('aria-pressed', 'true');
    expect(session.backend.connections).toEqual([]);
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function guidedWarmUp(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);
    await startGuidedRun(page, session);

    await advanceRun(page, session.backend, 12000, 2500);

    await expect(guided.warmUpTimer).toBeVisible();
    await expect(guided.settleBar).toBeVisible();
    await expect.poll(() => videoIsPlaying(guided.panel.getByLabel('Camera preview'))).toBe(true);
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function guidedCounting(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);
    await startGuidedRun(page, session);
    await advanceRunUntil(page, session.backend, guided.countedTimer);
    await pushAndConfirm(page, session.backend, { bpm: 67.2, quality_db: 9.1, state: 'ok' });

    session.backend.setScene(faceScene({ moving: true }));
    await advanceRun(page, session.backend, 3000, 1000);

    await expect(guided.panel.getByText("You're moving. Hold still.", { exact: true })).toBeVisible();
    await expect(guided.liveReadings.getByText(/^67(\.2)?$/)).toBeVisible();
    await expect.poll(() => longestPathCommands(guided.pulseTrace)).toBeGreaterThan(10);
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function guidedDone(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);
    await startGuidedRun(page, session);
    await pushAndConfirm(page, session.backend, { bpm: 68.2, quality_db: 9.4, state: 'ok' });
    await advanceRun(page, session.backend, 100000);
    await pushAndConfirm(page, session.backend, { bpm: 67.8, quality_db: 9.4, state: 'ok' });

    await advanceRunUntil(page, session.backend, guided.startAgain);

    await expect(guided.headline('Done. Nice sitting.')).toBeVisible();
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function guidedNoReading(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);
    await startGuidedRun(page, session);

    await advanceRunUntil(page, session.backend, guided.startAgain);

    await expect(guided.headline('Done, but no reading this time.')).toBeVisible();
    await expect(guided.panel.getByText('Ref: NO_READING', { exact: true })).toBeVisible();
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function guidedCameraDenied(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    await refuseCamera(page, 'NotAllowedError');
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);

    await guided.start.click();

    await expect(guided.alert).toContainText('Ref: CAMERA_DENIED');
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function guidedLastGood(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);
    await startGuidedRun(page, session);
    await pushAndConfirm(page, session.backend, OK_READING);
    await expect(guided.liveReadings.getByText(SHOWN_BPM)).toBeVisible();

    await pushAndConfirm(page, session.backend, { bpm: null, quality_db: 1.2, state: 'low_quality' });
    await advanceRun(page, session.backend, 2000, 500);

    await expect(guided.liveReadings.getByText(SHOWN_BPM)).toBeVisible();
    await expect(guided.liveReadings.getByText('Last good', { exact: true })).toBeVisible();
    await expectOnlyMockedSockets(session);
    await capture(page, testInfo, name);
  }

  async function guidedBusy(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);

    await guidedLinkLost(page, session, { code: 1013, reason: 'ANOTHER_CONNECTION_OPEN' });

    await expect(guided.panel.getByText('Ref: SOCKET_BUSY', { exact: true })).toBeVisible();
    await expect(guided.startAgain).toBeVisible();
    await expect.poll(() => session.backend.openConnections().length).toBe(0);
    await capture(page, testInfo, name);
  }

  async function guidedUnreachable(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);

    await guidedLinkLost(page, session, { code: 1006 });

    await expect(guided.panel.getByText('Ref: SOCKET_UNAVAILABLE', { exact: true })).toBeVisible();
    await expect(guided.startAgain).toBeVisible();
    await expect.poll(() => session.backend.openConnections().length).toBe(0);
    await capture(page, testInfo, name);
  }

  async function guidedHiddenTab(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);
    await startGuidedRun(page, session);
    await advanceRun(page, session.backend, 10000, 2500);
    await expectOnlyMockedSockets(session);

    await setTabHidden(page, true);
    await expect.poll(() => session.backend.openConnections().length).toBe(0);
    await setTabHidden(page, false);

    await expect(guided.panel.getByText('Ref: PAGE_HIDDEN', { exact: true })).toBeVisible();
    await expect(guided.startAgain).toBeVisible();
    await capture(page, testInfo, name);
  }

  async function guidedStopped(page: Page, testInfo: TestInfo, name: string): Promise<void> {
    const session = await openBuiltGuidedRun(page);
    const guided = guidedPage(page);
    await startGuidedRun(page, session);
    await advanceRun(page, session.backend, 10000, 2500);
    await expectOnlyMockedSockets(session);

    await guided.stop.click();

    await expect(guided.panel.getByText(RUN_STOPPED_TEXT, { exact: true })).toBeVisible();
    await expect(guided.startAgain).toBeVisible();
    await expect.poll(() => session.backend.openConnections().length).toBe(0);
    await capture(page, testInfo, name);
  }

  const GUIDED_STATES = [
    { state: 'idle', title: 'the guided run idle page', shoot: guidedIdle },
    { state: 'warm-up', title: 'the guided run warm-up', shoot: guidedWarmUp },
    { state: 'counting', title: 'the guided run counting with the hold still hint', shoot: guidedCounting },
    { state: 'done', title: 'the guided run result', shoot: guidedDone },
    { state: 'no-reading', title: 'the guided run with no reading', shoot: guidedNoReading },
    { state: 'camera-denied', title: 'the guided run camera denied guidance', shoot: guidedCameraDenied },
    { state: 'last-good', title: 'the guided run holding the last good heart rate', shoot: guidedLastGood },
    { state: 'busy', title: 'the guided run stopped because the app is busy elsewhere', shoot: guidedBusy },
    { state: 'unreachable', title: 'the guided run stopped because the pulse reader is unreachable', shoot: guidedUnreachable },
    { state: 'hidden-tab', title: 'the guided run stopped because the tab was hidden', shoot: guidedHiddenTab },
    { state: 'run-stopped', title: 'the guided run stopped with Stop', shoot: guidedStopped },
  ] as const;

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

    test.describe(`${viewport.name} guided run screenshots`, () => {
      test.use({ viewport: viewport.size });

      for (const { state, title, shoot } of GUIDED_STATES) {
        test(`screenshots ${title} at ${viewport.name} width`, async ({ page }, testInfo) => {
          await shoot(page, testInfo, `${viewport.name}-guided-${state}`);
        });
      }
    });

    test.describe(`${viewport.name} guided run dark theme screenshots`, () => {
      test.use({ viewport: viewport.size, colorScheme: 'dark' });

      for (const { state, title, shoot } of GUIDED_STATES) {
        test(`screenshots ${title} in the dark theme at ${viewport.name} width`, async ({ page }, testInfo) => {
          await shoot(page, testInfo, `${viewport.name}-dark-guided-${state}`);
        });
      }
    });
  }
});
