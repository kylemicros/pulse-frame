import { expect, test, type Locator } from '@playwright/test';
import {
  faceScene,
  MockBackend,
  NO_FACE_SCENE,
  PATCH_NAMES,
  UNUSABLE,
  usable,
} from '../../support/mock-backend';
import {
  boxOf,
  collectPageErrors,
  hintUnderVideo,
  monitorPage,
  startMonitoring,
  waitForMoreFrames,
} from '../../support/monitor-page';

function isMirrored(video: Locator): Promise<boolean> {
  return video.evaluate((element) => {
    let flips = 0;
    for (let node: Element | null = element; node !== null; node = node.parentElement) {
      const style = getComputedStyle(node);
      const matrix = /^matrix\(([^,]+),/.exec(style.transform);
      if (matrix !== null && Number(matrix[1]) < 0) {
        flips += 1;
      }
      const scaleX = style.scale === 'none' ? 1 : Number.parseFloat(style.scale.split(' ')[0]);
      if (scaleX < 0) {
        flips += 1;
      }
    }
    return flips % 2 === 1;
  });
}

test.describe('skin patch overlay', () => {
  test('draws one outline per usable patch over the video', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);

    await startMonitoring(page, backend);

    await expect(monitor.overlay).toBeVisible();
    await expect(monitor.outlines).toHaveCount(3);
    const video = await boxOf(monitor.video);
    for (const name of PATCH_NAMES) {
      const outline = await boxOf(monitor.outline(name));
      expect(outline.x).toBeGreaterThanOrEqual(video.x);
      expect(outline.y).toBeGreaterThanOrEqual(video.y);
      expect(outline.x + outline.width).toBeLessThanOrEqual(video.x + video.width);
      expect(outline.y + outline.height).toBeLessThanOrEqual(video.y + video.height);
    }
  });

  test('leaves out a patch that is not usable', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);
    await expect(monitor.outlines).toHaveCount(3);

    const scene = faceScene();
    backend.setScene({ ...scene, patches: { ...scene.patches, right_cheek: UNUSABLE } });

    await expect(monitor.outlines).toHaveCount(2);
    await expect(monitor.outline('right_cheek')).toHaveCount(0);
    await expect(monitor.outline('forehead')).toBeVisible();
    await expect(monitor.outline('left_cheek')).toBeVisible();
  });

  test('draws no outline and says no face when no face is found', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);
    await expect(monitor.outlines).toHaveCount(3);
    expect(await hintUnderVideo(page, /no face/i)).toBe(false);

    backend.setScene(NO_FACE_SCENE);

    await expect(monitor.outlines).toHaveCount(0);
    await expect.poll(() => hintUnderVideo(page, /no face/i)).toBe(true);
  });

  test('draws outlines only, each patch in its own colour', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);
    await expect(monitor.outlines).toHaveCount(3);

    const paints = await Promise.all(
      PATCH_NAMES.map((name) =>
        monitor.outline(name).evaluate((element) => {
          const style = getComputedStyle(element);
          return { stroke: style.stroke, fill: style.fill, fillOpacity: Number(style.fillOpacity) };
        }),
      ),
    );
    for (const paint of paints) {
      expect(paint.stroke).not.toBe('none');
      expect(paint.fill === 'none' || paint.fill === 'rgba(0, 0, 0, 0)' || paint.fillOpacity === 0).toBe(true);
    }
    expect(new Set(paints.map((paint) => paint.stroke)).size).toBe(3);
  });

  test('mirrors the video and its outlines selfie style', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);

    backend.setScene({
      face: true,
      moving: false,
      patches: {
        forehead: usable([
          [0.19, 0.49],
          [0.21, 0.49],
          [0.21, 0.51],
          [0.19, 0.51],
        ]),
        left_cheek: UNUSABLE,
        right_cheek: UNUSABLE,
      },
    });
    await expect(monitor.outlines).toHaveCount(1);

    expect(await isMirrored(monitor.video)).toBe(true);
    const video = await boxOf(monitor.video);
    await expect
      .poll(async () => {
        const outline = await boxOf(monitor.outline('forehead'));
        return {
          x: (outline.x + outline.width / 2 - video.x) / video.width,
          y: (outline.y + outline.height / 2 - video.y) / video.height,
        };
      })
      .toEqual({ x: expect.closeTo(0.8, 1), y: expect.closeTo(0.5, 1) });
  });

  test('clips outline points just outside the frame to the video area', async ({ page }) => {
    const errors = collectPageErrors(page);
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);

    backend.setScene({
      face: true,
      moving: false,
      patches: {
        forehead: usable([
          [-0.01, 0.3],
          [1.01, 0.3],
          [1.01, 0.6],
          [-0.01, 0.6],
        ]),
        left_cheek: UNUSABLE,
        right_cheek: UNUSABLE,
      },
    });
    await expect(monitor.outlines).toHaveCount(1);
    await waitForMoreFrames(backend, 3);

    const video = await boxOf(monitor.video);
    const outline = await boxOf(monitor.outline('forehead'));
    expect(outline.x).toBeGreaterThanOrEqual(video.x - 1);
    expect(outline.x + outline.width).toBeLessThanOrEqual(video.x + video.width + 1);
    expect(outline.width).toBeGreaterThanOrEqual(video.width * 0.95);
    expect(errors).toEqual([]);
  });

  test('hides the outlines when the overlay is switched off', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const monitor = monitorPage(page);
    await startMonitoring(page, backend);
    await expect(monitor.outlines).toHaveCount(3);
    await expect(monitor.overlayToggle).toHaveAttribute('aria-pressed', 'true');

    await monitor.overlayToggle.click();

    await expect(monitor.overlayToggle).toHaveAttribute('aria-pressed', 'false');
    await waitForMoreFrames(backend, 5);
    await expect(monitor.outlines).toHaveCount(0);

    await monitor.overlayToggle.click();

    await expect(monitor.overlayToggle).toHaveAttribute('aria-pressed', 'true');
    await expect(monitor.outlines).toHaveCount(3);
  });
});
