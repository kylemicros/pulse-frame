import { expect, test } from '@playwright/test';
import { MockBackend } from '../../support/mock-backend';
import {
  cameraCalls,
  cameraTrackIds,
  cameraTrackStates,
  CODED_ALERT_TEXT,
  endVideoTracks,
  failPreviewAttach,
  monitorPage,
  ownTextLength,
  recordTrackStops,
  recordUnhandledRejections,
  refuseCamera,
  removeCameraApi,
  spyOnCamera,
  startMonitoring,
  stoppedTrackIds,
  unhandledRejections,
  videoIsPlaying,
} from '../../support/monitor-page';

test.describe('camera', () => {
  test('does not ask for the camera until Start is pressed', async ({ page }) => {
    await spyOnCamera(page);
    await MockBackend.attach(page);
    const monitor = monitorPage(page);

    await page.goto('/');
    await expect(monitor.start).toBeVisible();

    expect(await cameraCalls(page)).toBe(0);

    await monitor.start.click();

    await expect.poll(() => cameraCalls(page)).toBe(1);
  });

  test('plays the camera video after Start', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);

    await startMonitoring(page, backend);

    await expect(monitor.video).toBeVisible();
    await expect.poll(() => videoIsPlaying(monitor.video)).toBe(true);
  });

  test('Stop ends every camera track and closes the socket', async ({ page }) => {
    await spyOnCamera(page);
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);
    const [streaming] = backend.openConnections();

    await monitor.stop.click();

    await expect.poll(() => cameraTrackStates(page)).not.toHaveLength(0);
    await expect.poll(async () => (await cameraTrackStates(page)).every((state) => state === 'ended')).toBe(true);
    await expect.poll(() => streaming.closedBy).toBe('page');
    expect(backend.openConnections()).toHaveLength(0);
    await expect(monitor.start).toBeVisible();
  });

  test('shows CAMERA_DENIED guidance when permission is refused', async ({ page }) => {
    await refuseCamera(page, 'NotAllowedError');
    await MockBackend.attach(page);
    const monitor = monitorPage(page);

    await page.goto('/');
    await monitor.start.click();

    const alert = monitor.alertWith('CAMERA_DENIED');
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/camera/i);
    await expect(alert).toContainText(/allow|permission|settings/i);
    await expect(alert).toContainText(/\bStart\b/);
  });

  test('shows CAMERA_NOT_FOUND guidance when no camera is available', async ({ page }) => {
    await refuseCamera(page, 'NotFoundError');
    await MockBackend.attach(page);
    const monitor = monitorPage(page);

    await page.goto('/');
    await monitor.start.click();

    const alert = monitor.alertWith('CAMERA_NOT_FOUND');
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/camera/i);
    await expect(alert).toContainText(/\bStart\b/);
  });

  test('stops every camera track when the page is left mid-session', async ({ page }) => {
    await spyOnCamera(page);
    await recordTrackStops(page);
    const backend = await MockBackend.attach(page);
    await startMonitoring(page, backend);
    const tracks = await cameraTrackIds(page);
    expect(tracks).not.toHaveLength(0);
    expect(await stoppedTrackIds(page)).toEqual([]);

    await page.goto('/?left');

    const stopped = await stoppedTrackIds(page);
    expect(tracks.filter((id) => !stopped.includes(id))).toEqual([]);
  });

  test('shows CAMERA_LOST, offers Start again and closes the socket when the camera goes away', async ({ page }) => {
    await spyOnCamera(page);
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);
    const [streaming] = backend.openConnections();

    await endVideoTracks(page);

    const alert = monitor.alertWith('CAMERA_LOST');
    await expect(alert).toBeVisible();
    await expect(alert).toContainText(/camera/i);
    await expect(alert).toContainText(/\bStart\b/);
    expect((await alert.innerText()).replace('CAMERA_LOST', '').trim().length).toBeGreaterThan(40);
    await expect(monitor.start).toBeVisible();
    await expect.poll(() => streaming.closedBy).toBe('page');
    expect(backend.openConnections()).toHaveLength(0);
    await expect.poll(async () => (await cameraTrackStates(page)).every((state) => state === 'ended')).toBe(true);
  });

  for (const errorName of ['NotReadableError', 'AbortError'] as const) {
    test(`shows CAMERA_IN_USE guidance when the camera fails with ${errorName}`, async ({ page }) => {
      await refuseCamera(page, errorName);
      await MockBackend.attach(page);
      const monitor = monitorPage(page);

      await page.goto('/');
      await monitor.start.click();

      const alert = monitor.alertWith('CAMERA_IN_USE');
      await expect(alert).toBeVisible();
      await expect(alert).toContainText(/camera/i);
      await expect(alert).toContainText(/another app/i);
      await expect(alert).toContainText(/\bquit\b/i);
      await expect(alert).toContainText(/\bStart\b/);
      expect(ownTextLength(await alert.innerText(), 'CAMERA_IN_USE')).toBeGreaterThan(40);
      await expect(monitor.alertWith('CAMERA_NOT_FOUND')).toHaveCount(0);
      await expect(monitor.start).toBeVisible();
    });
  }

  for (const errorName of ['NotFoundError', 'OverconstrainedError'] as const) {
    test(`shows CAMERA_NOT_FOUND guidance to plug one in when the camera fails with ${errorName}`, async ({
      page,
    }) => {
      await refuseCamera(page, errorName);
      await MockBackend.attach(page);
      const monitor = monitorPage(page);

      await page.goto('/');
      await monitor.start.click();

      const alert = monitor.alertWith('CAMERA_NOT_FOUND');
      await expect(alert).toBeVisible();
      await expect(alert).toContainText(/camera/i);
      await expect(alert).toContainText(/\bplug/i);
      await expect(alert).toContainText(/\bStart\b/);
      await expect(alert).not.toContainText(/another app|hogging|in use|busy/i);
      await expect(monitor.alertWith('CAMERA_IN_USE')).toHaveCount(0);
      await expect(monitor.start).toBeVisible();
    });
  }

  for (const errorName of ['TypeError', 'InvalidStateError'] as const) {
    test(`shows START_FAILED, not CAMERA_NOT_FOUND, when the camera fails with an unexpected ${errorName}`, async ({
      page,
    }) => {
      await refuseCamera(page, errorName);
      await MockBackend.attach(page);
      const monitor = monitorPage(page);

      await page.goto('/');
      await monitor.start.click();

      const alert = monitor.alertWith('START_FAILED');
      await expect(alert).toBeVisible();
      await expect(alert).toContainText(/\bStart\b/);
      expect(ownTextLength(await alert.innerText(), 'START_FAILED')).toBeGreaterThan(40);
      await expect(monitor.alertWith('CAMERA_NOT_FOUND')).toHaveCount(0);
      await expect(page.getByRole('alert').filter({ hasText: /\bplug/i })).toHaveCount(0);
      await expect(monitor.start).toBeVisible();
      await expect(monitor.stop).toBeHidden();
    });
  }

  for (const missing of ['mediaDevices', 'getUserMedia'] as const) {
    test(`shows CAMERA_UNSUPPORTED with the page address when navigator ${missing} is missing`, async ({ page }) => {
      await removeCameraApi(page, missing);
      await MockBackend.attach(page);
      const monitor = monitorPage(page);

      await page.goto('/');
      await monitor.start.click();

      const alert = monitor.alertWith('CAMERA_UNSUPPORTED');
      await expect(alert).toBeVisible();
      await expect(alert).toContainText(/camera/i);
      await expect(alert).toContainText('http://127.0.0.1:4173');
      expect(ownTextLength(await alert.innerText(), 'CAMERA_UNSUPPORTED')).toBeGreaterThan(40);
      await expect(monitor.alertWith('CAMERA_NOT_FOUND')).toHaveCount(0);
      await expect(monitor.start).toBeVisible();
    });
  }

  test('ends in a coded alert with Start back, not stuck starting, when the preview refuses the camera stream', async ({
    page,
  }) => {
    await spyOnCamera(page);
    await recordUnhandledRejections(page);
    await failPreviewAttach(page);
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);

    await page.goto('/');
    await monitor.start.click();

    const alert = page.getByRole('alert').filter({ hasText: CODED_ALERT_TEXT });
    await expect(alert).toBeVisible();
    const shown = await alert.innerText();
    const [code] = shown.match(CODED_ALERT_TEXT) ?? [''];
    expect(code).toBe('START_FAILED');
    await expect(monitor.alertWith('START_FAILED')).toBeVisible();
    expect(ownTextLength(shown, code)).toBeGreaterThan(40);
    await expect(monitor.start).toBeVisible();
    await expect(monitor.stop).toBeHidden();
    await expect.poll(() => cameraTrackStates(page)).not.toHaveLength(0);
    await expect.poll(async () => (await cameraTrackStates(page)).every((state) => state === 'ended')).toBe(true);
    expect(backend.openConnections()).toHaveLength(0);
    expect(await unhandledRejections(page)).toEqual([]);
  });
});
