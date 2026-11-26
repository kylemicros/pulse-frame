import { expect, type Locator, type Page } from '@playwright/test';
import { SETUP_MIN_FACE_SPAN_PX } from '../../src/features/guided-capture/lib/setup-check';
import {
  advanceRun,
  advanceRunUntil,
  calibrationBox,
  FRAME_SPACING_MS,
  guidedPage,
  openGuidedRun,
  paceReplies,
  paceUntil,
  passSetupCheck,
  pauseClock,
  pushAndConfirm,
  setHrvAndConfirm,
  SETUP_PROMPTS,
} from './guided-page';
import { installLitCamera } from './lit-camera';
import {
  faceScene,
  faceWithSpan,
  FRAME_HEIGHT_PX,
  FRAME_WIDTH_PX,
  hrv,
  MockBackend,
  usable,
  type Hrv,
  type PatchName,
  type Scene,
} from './mock-backend';
import { refuseCamera } from './page-helpers';

export const CALIBRATE_ADDRESS = '/?calibrate';
export const MIT_LINE = '© 2026 kylemicros. MIT licence.';
export const BAR_CLEARANCE_PX = 16;
export const TOP_FADE_PX = 24;
export const BOTTOM_FADE_PX = 48;
export const PANEL_MIN_PX = 360;
export const PANEL_MAX_PX = 440;

export type DetailsName = 'Setup check details' | 'Counting details' | 'Run details';

export type GuidedState = 'idle' | 'check' | 'warm-up' | 'counting' | 'result' | 'no-reading' | 'camera-denied';

export const GUIDED_STATES: GuidedState[] = [
  'idle',
  'check',
  'warm-up',
  'counting',
  'result',
  'no-reading',
  'camera-denied',
];

export const CAMERA_STATES: GuidedState[] = ['idle', 'check', 'warm-up', 'counting', 'camera-denied'];

export const FAR_SPAN_PX = SETUP_MIN_FACE_SPAN_PX / 2;
export const FAR_FACE = faceWithSpan(FAR_SPAN_PX);
export const CHECK_SETTLE_MS = 5000;
export const CHECK_SETTLED_MS = 1000;
const RUN_SLICE_MS = 5000;
export const EARLIER = hrv({ rmssd_ms: 39.4, sdnn_ms: 45.2, minute_bpm: 68.4, minute_count: 66 });
const WITH_READING = hrv({ rmssd_ms: 41.2, sdnn_ms: 46.7, minute_bpm: 67.8, minute_count: 72 });
const FAINT = hrv({ minute_count: 9, no_reading: 'READING_FLOOR_NOT_CLEARED', why: 'faint_pulse', clear_percent: 18.4 });

export type Extent = { scrollWidth: number; scrollHeight: number; innerWidth: number; innerHeight: number; scrollY: number };

type Fade = { position: string; edge: string; height: number; image: string; pointerEvents: string };

export type FadeState = {
  top: Fade;
  bottom: Fade;
  scrollTop: number;
  maxScroll: number;
  topCovers: boolean;
  bottomCovers: boolean;
};

export type Rect = { top: number; bottom: number; left: number; right: number };

export function shell(page: Page) {
  const main = page.getByRole('main');
  const panel = main.getByTestId('run-panel');
  return {
    main,
    panel,
    camera: guidedPage(page).video,
    footer: page.getByRole('contentinfo'),
    mitLine: page.getByRole('contentinfo').getByText(MIT_LINE, { exact: true }),
    mainButton: main.getByRole('button', { name: /^(Start|Stop|Start again)$/ }),
    details: (name: DetailsName): Locator => panel.getByRole('region', { name, exact: true }),
  };
}

async function openAt(page: Page, address: string): Promise<MockBackend> {
  const backend = await MockBackend.attach(page);
  await page.clock.install();
  await openGuidedRun(page, address);
  return backend;
}

async function startRunAt(page: Page, address: string): Promise<MockBackend> {
  const backend = await openAt(page, address);
  await guidedPage(page).start.click();
  await expect.poll(() => backend.frames.length).toBeGreaterThan(1);
  await passSetupCheck(page, backend);
  return backend;
}

async function finishRun(page: Page, backend: MockBackend, last: Hrv): Promise<void> {
  const guided = guidedPage(page);
  await pushAndConfirm(page, backend, { bpm: 68.2, quality_db: 9.4, state: 'ok' });
  await advanceRunUntil(page, backend, guided.countedTimer, RUN_SLICE_MS);
  await setHrvAndConfirm(page, backend, last);
  await advanceRunUntil(page, backend, guided.startAgain, RUN_SLICE_MS);
}

export async function reachFarCheck(page: Page, stepMs = FRAME_SPACING_MS): Promise<MockBackend> {
  await installLitCamera(page, 'even');
  const backend = await MockBackend.attach(page);
  backend.setScene(FAR_FACE);
  await page.clock.install();
  await openGuidedRun(page, CALIBRATE_ADDRESS);
  await guidedPage(page).start.click();
  await expect.poll(() => backend.frames.length).toBeGreaterThan(1);
  await pauseClock(page);
  const prompt = guidedPage(page).setupPrompt.getByText(SETUP_PROMPTS.far.prompt, { exact: true });
  await paceUntil(page, backend, prompt, CHECK_SETTLE_MS, stepMs);
  await paceReplies(page, backend, CHECK_SETTLED_MS, stepMs);
  await expect(guidedPage(page).headline('Quick setup check')).toBeVisible();
  return backend;
}

export async function reachState(page: Page, state: GuidedState): Promise<void> {
  const guided = guidedPage(page);
  const calibration = calibrationBox(page).region;
  if (state === 'idle') {
    await openAt(page, CALIBRATE_ADDRESS);
    await expect(guided.start).toBeVisible();
    return;
  }
  if (state === 'check') {
    await reachFarCheck(page);
    await expect(calibration).toHaveCount(1);
    return;
  }
  if (state === 'camera-denied') {
    await refuseCamera(page, 'NotAllowedError');
    await openAt(page, CALIBRATE_ADDRESS);
    await guided.start.click();
    await expect(guided.alert).toContainText('Ref: CAMERA_DENIED');
    return;
  }
  const backend = await startRunAt(page, CALIBRATE_ADDRESS);
  if (state === 'warm-up') {
    await advanceRun(page, backend, 12000, 2500);
    await expect(guided.warmUpTimer).toBeVisible();
    await expect(calibration).toHaveCount(1);
    return;
  }
  if (state === 'counting') {
    await pushAndConfirm(page, backend, { bpm: 67.2, quality_db: 9.1, state: 'ok' });
    await advanceRunUntil(page, backend, guided.countedTimer);
    await setHrvAndConfirm(page, backend, EARLIER);
    await advanceRun(page, backend, 3000, 1000);
    await expect(guided.countedTimer).toBeVisible();
    await expect(calibration).toHaveCount(1);
    return;
  }
  await finishRun(page, backend, state === 'result' ? WITH_READING : FAINT);
  await expect(
    guided.headline(state === 'result' ? 'Done. Nice sitting.' : 'Done, but no reading this time.'),
  ).toBeVisible();
  await expect(calibration).toHaveCount(1);
}

export function pageExtent(page: Page): Promise<Extent> {
  return page.evaluate(() => {
    const root = document.scrollingElement ?? document.documentElement;
    return {
      scrollWidth: root.scrollWidth,
      scrollHeight: root.scrollHeight,
      innerWidth: window.innerWidth,
      innerHeight: window.innerHeight,
      scrollY: window.scrollY,
    };
  });
}

export function innerScrollers(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    Array.from(document.body.querySelectorAll('*'))
      .filter((element) => {
        const style = getComputedStyle(element);
        return (
          (/^(auto|scroll)$/.test(style.overflowY) && element.scrollHeight > element.clientHeight + 1) ||
          (/^(auto|scroll)$/.test(style.overflowX) && element.scrollWidth > element.clientWidth + 1)
        );
      })
      .map(
        (element) =>
          `${element.tagName.toLowerCase()} ${element.getAttribute('aria-label') ?? element.getAttribute('data-testid') ?? ''}`.trim(),
      ),
  );
}

export async function rectOf(locator: Locator): Promise<Rect> {
  await expect(locator).toBeAttached();
  return locator.evaluate((element) => {
    const box = element.getBoundingClientRect();
    return { top: box.top, bottom: box.bottom, left: box.left, right: box.right };
  });
}

export function scrollportOf(region: Locator): Promise<Rect> {
  return region.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const top = box.top + element.clientTop;
    const left = box.left + element.clientLeft;
    return { top, bottom: top + element.clientHeight, left, right: left + element.clientWidth };
  });
}

export function fadeState(region: Locator): Promise<FadeState> {
  return region.evaluate((element) => {
    const fade = (pseudo: '::before' | '::after', edge: 'top' | 'bottom') => {
      const style = getComputedStyle(element, pseudo);
      return {
        position: style.position,
        edge: style.getPropertyValue(edge),
        height: Number.parseFloat(style.height),
        image: style.backgroundImage,
        pointerEvents: style.pointerEvents,
      };
    };
    const top = fade('::before', 'top');
    const bottom = fade('::after', 'bottom');
    const box = element.getBoundingClientRect();
    const viewTop = box.top + element.clientTop;
    const viewBottom = viewTop + element.clientHeight;
    const children = Array.from(element.children)
      .map((child) => child.getBoundingClientRect())
      .filter((rect) => rect.height > 2);
    const covers = (from: number, to: number) => children.some((rect) => rect.bottom > from + 1 && rect.top < to - 1);
    return {
      top,
      bottom,
      scrollTop: element.scrollTop,
      maxScroll: element.scrollHeight - element.clientHeight,
      topCovers: covers(viewTop, viewTop + top.height),
      bottomCovers: covers(viewBottom - bottom.height, viewBottom),
    };
  });
}

export function scrollTopOf(region: Locator): Promise<number> {
  return region.evaluate((element) => element.scrollTop);
}

export function maxScrollOf(region: Locator): Promise<number> {
  return region.evaluate((element) => element.scrollHeight - element.clientHeight);
}

export function scrollRegionTo(region: Locator, where: 'start' | 'middle' | 'end'): Promise<void> {
  return region.evaluate((element, place) => {
    const max = element.scrollHeight - element.clientHeight;
    element.scrollTop = place === 'start' ? 0 : place === 'end' ? max : Math.round(max / 2);
  }, where);
}

export type ChildOrder = { first: string | null; last: string | null };

export function contentOrder(region: Locator): Promise<ChildOrder> {
  return region.evaluate((element) => {
    const shown = Array.from(element.children)
      .filter((child) => child.getBoundingClientRect().height > 2)
      .toSorted((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top)
      .map((child) =>
        [...(/^H[2-4]$/.test(child.tagName) ? [child] : []), ...Array.from(child.querySelectorAll('h2, h3, h4'))]
          .map((heading) => (heading.textContent ?? '').trim())
          .join(' | '),
      );
    return { first: shown.at(0) ?? null, last: shown.at(-1) ?? null };
  });
}

export function barRect(page: Page): Promise<Rect | null> {
  return shell(page).mainButton.evaluate((button) => {
    for (let node: Element | null = button; node !== null; node = node.parentElement) {
      if (getComputedStyle(node).position === 'fixed') {
        const box = node.getBoundingClientRect();
        return { top: box.top, bottom: box.bottom, left: box.left, right: box.right };
      }
    }
    return null;
  });
}

export type GradientShape = { downward: boolean; startsClear: boolean; endsClear: boolean };

function topLevelParts(text: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let current = '';
  for (const character of text) {
    depth += character === '(' ? 1 : character === ')' ? -1 : 0;
    if (character === ',' && depth === 0) {
      parts.push(current.trim());
      current = '';
    } else {
      current += character;
    }
  }
  return [...parts, current.trim()];
}

function isClear(stop: string): boolean {
  return /^transparent\b|^rgba\([^)]*,\s*0\)|\/\s*0\)/.test(stop);
}

export function gradientShape(image: string): GradientShape {
  const match = /^linear-gradient\((.*)\)$/.exec(image.trim());
  if (match === null) {
    return { downward: false, startsClear: false, endsClear: false };
  }
  const parts = topLevelParts(match[1]);
  const setup = /^(to |in |-?\d+(\.\d+)?(deg|turn|rad|grad))/.test(parts[0]) ? parts[0] : '';
  const stops = setup === '' ? parts : parts.slice(1);
  const direction = setup.replace(/in \S+( \S+ hue)?/, '').trim();
  return {
    downward: direction === '' || direction === 'to bottom' || direction === '180deg',
    startsClear: isClear(stops[0] ?? ''),
    endsClear: isClear(stops.at(-1) ?? ''),
  };
}

export type OverlayTarget = { name: PatchName; x: number; y: number };

export function overlayScene(targets: readonly OverlayTarget[], half = 0.02): Scene {
  const square = ({ x, y }: OverlayTarget): [number, number][] => [
    [x - half, y - half],
    [x + half, y - half],
    [x + half, y + half],
    [x - half, y + half],
  ];
  const patches = Object.fromEntries(targets.map((target) => [target.name, usable(square(target))])) as Scene['patches'];
  return faceScene({ patches });
}

export type OverlayMiss = { name: PatchName; dx: number; dy: number };

export function overlayMisses(video: Locator, targets: readonly OverlayTarget[]): Promise<OverlayMiss[]> {
  return video.evaluate(
    (element, { points, frameAspect }) => {
      const media = element as HTMLVideoElement;
      const sourceWidth = media.videoWidth;
      const sourceHeight = media.videoHeight;
      const cropWidth = sourceWidth / sourceHeight > frameAspect ? sourceHeight * frameAspect : sourceWidth;
      const cropHeight = sourceWidth / sourceHeight > frameAspect ? sourceHeight : sourceWidth / frameAspect;
      const cropX = (sourceWidth - cropWidth) / 2;
      const cropY = (sourceHeight - cropHeight) / 2;
      const box = media.getBoundingClientRect();
      const scale = Math.max(box.width / sourceWidth, box.height / sourceHeight);
      const offsetX = (box.width - sourceWidth * scale) / 2;
      const offsetY = (box.height - sourceHeight * scale) / 2;
      const host = media.parentElement ?? document.body;
      return points.map(({ name, x, y }) => {
        const shown = host.querySelector(`[data-testid="patch-outline-${name}"]`)?.getBoundingClientRect();
        const unmirroredX = offsetX + (cropX + x * cropWidth) * scale;
        const expectedX = box.left + box.width - unmirroredX;
        const expectedY = box.top + offsetY + (cropY + y * cropHeight) * scale;
        if (shown === undefined) {
          return { name, dx: Number.POSITIVE_INFINITY, dy: Number.POSITIVE_INFINITY };
        }
        return {
          name,
          dx: Math.round(Math.abs(shown.left + shown.width / 2 - expectedX) * 10) / 10,
          dy: Math.round(Math.abs(shown.top + shown.height / 2 - expectedY) * 10) / 10,
        };
      });
    },
    { points: targets, frameAspect: FRAME_WIDTH_PX / FRAME_HEIGHT_PX },
  );
}

export function aspectOf(locator: Locator): Promise<number> {
  return locator.evaluate((element) => {
    const box = element.getBoundingClientRect();
    return box.width / box.height;
  });
}

export function lineCount(locator: Locator): Promise<number> {
  return locator.evaluate((element) => {
    const range = document.createRange();
    range.selectNodeContents(element);
    return new Set(Array.from(range.getClientRects(), (rect) => Math.round(rect.top))).size;
  });
}

export async function setSafeAreaBottom(page: Page, bottom: number): Promise<void> {
  const session = await page.context().newCDPSession(page);
  await session.send('Emulation.setSafeAreaInsetsOverride', { insets: { bottom } });
}
