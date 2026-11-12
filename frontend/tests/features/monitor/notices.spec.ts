import { expect, test } from '@playwright/test';
import { faceScene, MockBackend, NO_FACE_SCENE } from '../../support/mock-backend';
import { hintUnderVideo, monitorPage, startMonitoring } from '../../support/monitor-page';

test.describe('monitor notices', () => {
  test('warns that glancing away resets the reading while monitoring', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);

    await startMonitoring(page, backend);

    await expect(monitor.glanceNotice).toBeVisible();
    await expect(monitor.glanceNotice).toContainText(/reset|start(s)? over/i);
  });

  test('shows a hold still hint under the video while the user moves', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    const backend = await MockBackend.attach(page);
    await startMonitoring(page, backend);
    expect(await hintUnderVideo(page, /hold still/i)).toBe(false);

    backend.setScene(faceScene({ moving: true }));

    await expect.poll(() => hintUnderVideo(page, /hold still/i)).toBe(true);

    backend.setScene(faceScene());

    await expect.poll(() => hintUnderVideo(page, /hold still/i)).toBe(false);
  });

  test('shows a no face hint under the video when no face is found', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    const backend = await MockBackend.attach(page);
    await startMonitoring(page, backend);
    expect(await hintUnderVideo(page, /no face/i)).toBe(false);

    backend.setScene(NO_FACE_SCENE);

    await expect.poll(() => hintUnderVideo(page, /no face/i)).toBe(true);
  });
});
