import { expect, test, type Locator, type Page } from '@playwright/test';
import {
  advanceRunUntil,
  guidedPage,
  openGuidedRun,
  outlineCountChanges,
  passSetupCheck,
  startRun,
  watchOutlineCount,
} from '../../support/guided-page';
import { faceScene, MockBackend, NO_FACE_SCENE, PATCH_NAMES, UNUSABLE, usable } from '../../support/mock-backend';
import {
  boxOf,
  collectPageErrors,
  endVideoTracks,
  spyOnCamera,
  useWideCamera,
  waitForMoreFrames,
} from '../../support/page-helpers';
import { aspectOf, overlayMisses, overlayScene, type OverlayTarget } from '../../support/app-shell';

const OUTLINE_GREEN = 'rgb(0, 158, 115)';
const OUTLINE_EDGE = 'rgb(20, 20, 20)';
const HOLD_MS = 400;
const HOLD_SLACK_MS = 20;

type Paint = { stroke: string; strokeWidth: string; fill: string; linejoin: string; vectorEffect: string };

type EdgeUnder = Paint & { before: boolean };

function paintOf(outline: Locator): Promise<Paint> {
  return outline.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      stroke: style.stroke,
      strokeWidth: style.strokeWidth,
      fill: style.fill,
      linejoin: style.strokeLinejoin,
      vectorEffect: style.vectorEffect,
    };
  });
}

function edgesUnder(outline: Locator, edgeColour: string): Promise<EdgeUnder[]> {
  return outline.evaluate((line, colour) => {
    const surface = line instanceof SVGElement ? line.ownerSVGElement : null;
    if (surface === null) {
      return [];
    }
    const lineBox = line.getBoundingClientRect();
    return Array.from(surface.querySelectorAll('*'))
      .filter((element) => element !== line && getComputedStyle(element).stroke === colour)
      .filter((element) => {
        const box = element.getBoundingClientRect();
        return (
          Math.abs(box.x - lineBox.x) <= 1 &&
          Math.abs(box.y - lineBox.y) <= 1 &&
          Math.abs(box.width - lineBox.width) <= 1 &&
          Math.abs(box.height - lineBox.height) <= 1
        );
      })
      .map((element) => {
        const style = getComputedStyle(element);
        return {
          stroke: style.stroke,
          strokeWidth: style.strokeWidth,
          fill: style.fill,
          linejoin: style.strokeLinejoin,
          vectorEffect: style.vectorEffect,
          before: (element.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0,
        };
      });
  }, edgeColour);
}

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

type GuideCheck = { guides: number; dashed: boolean };

function faceGuide(video: Locator): Promise<GuideCheck> {
  return video.evaluate((element) => {
    const guides = Array.from(element.parentElement?.querySelectorAll('svg') ?? []).filter(
      (surface) => surface.querySelector('ellipse') !== null,
    );
    const [guide] = guides;
    const dashed =
      guide !== undefined &&
      Array.from(guide.querySelectorAll('ellipse, path')).every(
        (shape) => getComputedStyle(shape).strokeDasharray !== 'none',
      );
    return { guides: guides.length, dashed };
  });
}

function drawnAfterFaceGuide(outline: Locator): Promise<boolean> {
  return outline.evaluate((line) => {
    const box = line instanceof SVGElement ? line.ownerSVGElement?.parentElement : null;
    const guide = box?.querySelector('svg ellipse')?.closest('svg');
    if (guide === null || guide === undefined || guide.contains(line)) {
      return false;
    }
    return (guide.compareDocumentPosition(line) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
  });
}

function hiddenFromScreenReaders(outline: Locator): Promise<boolean> {
  return outline.evaluate((element) => element.closest('[aria-hidden="true"]') !== null);
}

async function expectHeldAtLeast400ms(page: Page): Promise<void> {
  const changes = await outlineCountChanges(page);
  const gaps = changes.slice(2).map((change, index) => change.at - changes[index + 1].at);
  expect(gaps.filter((gap) => gap < HOLD_MS - HOLD_SLACK_MS), 'outline changes held under 400 ms').toEqual([]);
}

async function placeUnderCamera(page: Page): Promise<{ left: number; gap: number; width: number; height: number }> {
  const guided = guidedPage(page);
  const camera = await boxOf(guided.video);
  const button = await boxOf(guided.skinOutline);
  return {
    left: Math.round(button.x - camera.x),
    gap: Math.round(button.y - (camera.y + camera.height)),
    width: Math.round(button.width),
    height: Math.round(button.height),
  };
}

async function expectStoresNothing(page: Page): Promise<void> {
  const stored = await page.evaluate(async () => ({
    local: localStorage.length,
    session: sessionStorage.length,
    databases: (await indexedDB.databases()).length,
    cookies: document.cookie,
  }));
  expect(stored).toEqual({ local: 0, session: 0, databases: 0, cookies: '' });
}

test.describe('skin outline on the guided camera', () => {
  for (const colorScheme of ['light', 'dark'] as const) {
    test.describe(`in the ${colorScheme} theme`, () => {
      test.use({ colorScheme });

      test('draws one green 2 px line over a 5 px dark edge for each usable patch, inside the camera', async ({
        page,
      }) => {
        const backend = await MockBackend.attach(page);
        const guided = guidedPage(page);

        await startRun(page, backend);

        await expect(guided.outlines).toHaveCount(3);
        const video = await boxOf(guided.video);
        for (const name of PATCH_NAMES) {
          const line = guided.outline(name);
          const box = await boxOf(line);
          expect(box.x).toBeGreaterThanOrEqual(video.x);
          expect(box.y).toBeGreaterThanOrEqual(video.y);
          expect(box.x + box.width).toBeLessThanOrEqual(video.x + video.width);
          expect(box.y + box.height).toBeLessThanOrEqual(video.y + video.height);
          expect(await paintOf(line)).toEqual({
            stroke: OUTLINE_GREEN,
            strokeWidth: '2px',
            fill: 'none',
            linejoin: 'round',
            vectorEffect: 'non-scaling-stroke',
          });
          expect(await edgesUnder(line, OUTLINE_EDGE)).toEqual([
            {
              stroke: OUTLINE_EDGE,
              strokeWidth: '5px',
              fill: 'none',
              linejoin: 'round',
              vectorEffect: 'non-scaling-stroke',
              before: true,
            },
          ]);
        }
      });
    });
  }

  test('draws through the warm-up and the counted part, and is gone when the run is done', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);

    await startRun(page, backend);
    await expect(guided.warmUpTimer).toBeVisible();
    await expect(guided.outlines).toHaveCount(3);

    await advanceRunUntil(page, backend, guided.countedTimer);
    await expect(guided.outlines).toHaveCount(3);

    await advanceRunUntil(page, backend, guided.startAgain);
    await page.clock.runFor(1000);
    await expect(guided.outlines).toHaveCount(0);
  });

  test('draws nothing while idle, before Start is pressed', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);

    await openGuidedRun(page);

    await expect(guided.start).toBeVisible();
    await expect(guided.skinOutline).toHaveAttribute('aria-pressed', 'true');
    await expect(guided.outlines).toHaveCount(0);
    expect(backend.connections).toEqual([]);
  });

  test('takes the outline away when Stop is pressed', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await expect(guided.outlines).toHaveCount(3);

    await guided.stop.click();

    await expect(guided.startAgain).toBeVisible();
    await expect(guided.outlines).toHaveCount(0);
  });

  test('takes the outline away when the camera drops out mid-run', async ({ page }) => {
    await spyOnCamera(page);
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await expect(guided.outlines).toHaveCount(3);

    await endVideoTracks(page);

    await expect(guided.main.getByText('Ref: CAMERA_LOST', { exact: true })).toBeVisible();
    await expect(guided.outlines).toHaveCount(0);
  });

  test('leaves out a patch that is not usable', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await expect(guided.outlines).toHaveCount(3);

    const scene = faceScene();
    backend.setScene({ ...scene, patches: { ...scene.patches, right_cheek: UNUSABLE } });

    await expect(guided.outlines).toHaveCount(2);
    await expect(guided.outline('right_cheek')).toHaveCount(0);
    await expect(guided.outline('forehead')).toBeVisible();
    await expect(guided.outline('left_cheek')).toBeVisible();
  });

  test('keeps the dashed face guide with the outline on and off, the outline drawn over it', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await expect(guided.outlines).toHaveCount(3);

    expect(await faceGuide(guided.video)).toEqual({ guides: 1, dashed: true });
    for (const name of PATCH_NAMES) {
      expect(await drawnAfterFaceGuide(guided.outline(name))).toBe(true);
    }

    await guided.skinOutline.click();
    await expect(guided.outlines).toHaveCount(0);

    expect(await faceGuide(guided.video)).toEqual({ guides: 1, dashed: true });
  });

  test('sends nothing and stores nothing when the outline is switched during a live run', async ({ page }) => {
    const requests: string[] = [];
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await expect(guided.outlines).toHaveCount(3);
    page.on('request', (request) => requests.push(`${request.method()} ${request.url()}`));
    const connections = backend.connections.length;

    await guided.skinOutline.click();
    await expect(guided.outlines).toHaveCount(0);
    await guided.skinOutline.click();
    await expect(guided.outlines).toHaveCount(3);
    await waitForMoreFrames(backend, 5);

    expect(backend.textMessages).toEqual([]);
    expect(requests).toEqual([]);
    expect(backend.connections).toHaveLength(connections);
    await expectStoresNothing(page);
  });

  test('draws nothing while no face is found', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await expect(guided.outlines).toHaveCount(3);

    backend.setScene(NO_FACE_SCENE);

    await expect(guided.outlines).toHaveCount(0);
    await expect(guided.skinOutline).toHaveAttribute('aria-pressed', 'true');
  });

  test('mirrors the outline like the camera preview', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

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
    await expect(guided.outlines).toHaveCount(1);

    expect(await isMirrored(guided.video)).toBe(true);
    const video = await boxOf(guided.video);
    await expect
      .poll(async () => {
        const outline = await boxOf(guided.outline('forehead'));
        return {
          x: (outline.x + outline.width / 2 - video.x) / video.width,
          y: (outline.y + outline.height / 2 - video.y) / video.height,
        };
      })
      .toEqual({ x: expect.closeTo(0.8, 1), y: expect.closeTo(0.5, 1) });
  });

  test('clips outline points just outside the frame to the camera box', async ({ page }) => {
    const errors = collectPageErrors(page);
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);

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
    await expect(guided.outlines).toHaveCount(1);
    await waitForMoreFrames(backend, 3);

    const video = await boxOf(guided.video);
    const outline = await boxOf(guided.outline('forehead'));
    expect(outline.x).toBeGreaterThanOrEqual(video.x - 1);
    expect(outline.x + outline.width).toBeLessThanOrEqual(video.x + video.width + 1);
    expect(outline.width).toBeGreaterThanOrEqual(video.width * 0.95);
    expect(errors).toEqual([]);
  });

  test('keeps the outline hidden from screen readers', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await expect(guided.outlines).toHaveCount(3);

    for (const name of PATCH_NAMES) {
      expect(await hiddenFromScreenReaders(guided.outline(name))).toBe(true);
    }
    await expect(page.getByRole('img', { name: /skin|patch|outline|overlay/i })).toHaveCount(0);
  });

  test('holds a face that shows for one reply at least 400 ms, so the outline cannot flash on', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    backend.setScene(NO_FACE_SCENE);
    await expect(guided.outlines).toHaveCount(0);
    await waitForMoreFrames(backend, 20);
    await watchOutlineCount(page);

    backend.flashScene(faceScene());

    await expect.poll(() => backend.flashedAtFrames.length).toBe(1);
    await waitForMoreFrames(backend, 30);
    await expect(guided.outlines).toHaveCount(0);
    await expectHeldAtLeast400ms(page);
  });

  test('holds a face lost for one reply at least 400 ms, so the outline cannot flash off', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await expect(guided.outlines).toHaveCount(3);
    await waitForMoreFrames(backend, 20);
    await watchOutlineCount(page);

    backend.flashScene(NO_FACE_SCENE);

    await expect.poll(() => backend.flashedAtFrames.length).toBe(1);
    await waitForMoreFrames(backend, 30);
    await expect(guided.outlines).toHaveCount(3);
    await expectHeldAtLeast400ms(page);
  });
});

test.describe('Skin outline button', () => {
  test('sits under the camera, left aligned and at least 44 px high, on by default', async ({ page }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);

    await openGuidedRun(page);

    await expect(guided.skinOutline).toBeVisible();
    await expect(guided.skinOutline).toHaveAccessibleName('Skin outline: on');
    await expect(guided.skinOutline).toHaveAttribute('aria-pressed', 'true');
    await expect(guided.skinOutline).toBeEnabled();
    expect(await guided.skinOutline.evaluate((element) => element.tagName)).toBe('BUTTON');
    const camera = await boxOf(guided.video);
    const button = await boxOf(guided.skinOutline);
    expect(button.y).toBeGreaterThanOrEqual(camera.y + camera.height - 1);
    expect(Math.abs(button.x - camera.x)).toBeLessThanOrEqual(2);
    expect(button.height).toBeGreaterThanOrEqual(44);
  });

  test('stays in the same place under the camera through the warm-up and after Stop', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);
    await expect(guided.skinOutline).toBeVisible();
    const idle = await placeUnderCamera(page);

    await guided.start.click();
    await expect.poll(() => backend.frames.length).toBeGreaterThan(1);
    await passSetupCheck(page, backend);
    await expect(guided.skinOutline).toBeVisible();
    expect(await placeUnderCamera(page)).toEqual(idle);

    await guided.stop.click();
    await expect(guided.startAgain).toBeVisible();
    await expect(guided.skinOutline).toBeVisible();
    expect(await placeUnderCamera(page)).toEqual(idle);
  });

  test('turns the outline off and on with a click while the run is live', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await expect(guided.outlines).toHaveCount(3);

    await guided.skinOutline.click();

    await expect(guided.skinOutline).toHaveAttribute('aria-pressed', 'false');
    await expect(guided.skinOutline).toHaveAccessibleName('Skin outline: off');
    await expect(guided.outlines).toHaveCount(0);
    await waitForMoreFrames(backend, 10);
    await expect(guided.outlines).toHaveCount(0);

    await guided.skinOutline.click();

    await expect(guided.skinOutline).toHaveAttribute('aria-pressed', 'true');
    await expect(guided.skinOutline).toHaveAccessibleName('Skin outline: on');
    await expect(guided.outlines).toHaveCount(3);
  });

  test('flips with Enter and with Space and keeps focus', async ({ page }) => {
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await expect(guided.outlines).toHaveCount(3);
    await guided.skinOutline.focus();

    await page.keyboard.press('Enter');

    await expect(guided.skinOutline).toHaveAttribute('aria-pressed', 'false');
    await expect(guided.skinOutline).toBeFocused();
    await expect(guided.outlines).toHaveCount(0);

    await page.keyboard.press('Space');

    await expect(guided.skinOutline).toHaveAttribute('aria-pressed', 'true');
    await expect(guided.skinOutline).toBeFocused();
    await expect(guided.outlines).toHaveCount(3);
  });

  test('set off before Start, keeps the outline off for the run and across Start again', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);
    await expect(guided.skinOutline).toHaveAttribute('aria-pressed', 'true');

    await guided.skinOutline.click();
    await expect(guided.skinOutline).toHaveAttribute('aria-pressed', 'false');
    await guided.start.click();

    await expect.poll(() => backend.frames.length).toBeGreaterThan(1);
    await waitForMoreFrames(backend, 10);
    await expect(guided.outlines).toHaveCount(0);
    await passSetupCheck(page, backend);
    await expect(guided.outlines).toHaveCount(0);

    await guided.stop.click();
    await expect(guided.startAgain).toBeVisible();
    await expect(guided.skinOutline).toHaveAttribute('aria-pressed', 'false');
    const framesBefore = backend.frames.length;
    await guided.startAgain.click();

    await expect.poll(() => backend.frames.length).toBeGreaterThan(framesBefore + 1);
    await waitForMoreFrames(backend, 10);
    await expect(guided.skinOutline).toHaveAttribute('aria-pressed', 'false');
    await expect(guided.outlines).toHaveCount(0);

    await guided.skinOutline.click();

    await expect(guided.outlines).toHaveCount(3);
  });

  test('is back on after a reload and stores nothing in the browser', async ({ page }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);
    await expect(guided.skinOutline).toHaveAttribute('aria-pressed', 'true');

    await guided.skinOutline.click();
    await expect(guided.skinOutline).toHaveAttribute('aria-pressed', 'false');
    await expectStoresNothing(page);

    await page.reload();

    await expect(guided.skinOutline).toHaveAttribute('aria-pressed', 'true');
    await expect(guided.skinOutline).toHaveAccessibleName('Skin outline: on');
    await expectStoresNothing(page);
  });
});

const OVERLAY_TARGETS: OverlayTarget[] = [
  { name: 'forehead', x: 0.3, y: 0.15 },
  { name: 'left_cheek', x: 0.72, y: 0.85 },
  { name: 'right_cheek', x: 0.5, y: 0.5 },
];
const ALIGN_SLACK_PX = 3;
const FOUR_BY_THREE = 4 / 3;

for (const viewport of [
  { name: 'desktop', size: { width: 1280, height: 800 } },
  { name: 'short phone', size: { width: 390, height: 300 } },
] as const) {
  test.describe(`skin outline alignment at ${viewport.name} size`, () => {
    test.use({ viewport: viewport.size });

    test('lands each outline on its spot in a 16:9 camera shown in a box that is not 4:3', async ({ page }) => {
      await useWideCamera(page);
      const backend = await MockBackend.attach(page);
      backend.setScene(overlayScene(OVERLAY_TARGETS));
      const guided = guidedPage(page);
      await openGuidedRun(page);
      await guided.start.click();

      await expect(guided.outlines).toHaveCount(3);
      await expect.poll(() => guided.video.evaluate((video) => (video as HTMLVideoElement).videoWidth)).toBe(1280);
      const aspect = await aspectOf(guided.video);
      expect(Math.abs(aspect - FOUR_BY_THREE), `the camera box is ${aspect.toFixed(3)} wide per tall`).toBeGreaterThan(0.05);
      await expect
        .poll(async () =>
          (await overlayMisses(guided.video, OVERLAY_TARGETS)).filter(
            ({ dx, dy }) => dx > ALIGN_SLACK_PX || dy > ALIGN_SLACK_PX,
          ),
        )
        .toEqual([]);
    });
  });
}
