import { expect, type Locator, type Page } from '@playwright/test';
import { EARLIER, startRunAt } from './app-shell';
import {
  advanceRun,
  advanceRunUntil,
  guidedPage,
  pushAndConfirm,
  setHrvAndConfirm,
  startRun,
  VARIATION_LINE,
} from './guided-page';
import { hrv, MockBackend, type Hrv } from './mock-backend';
import { endVideoTracks, spyOnCamera } from './page-helpers';

export const IDLE_HEADLINE = 'Sit still. Your face does the rest.';
export const IDLE_CAMERA_LABEL = 'Camera preview, off until you press Start.';
export const RUN_FINISHED_LINE = "Camera's off. Run finished.";
export const OLD_IDLE_CAMERA_LINE = "Camera's off. Press Start and your face shows up here.";
export const READING_SIZE_PX = 16;

export const RANGED_READING = hrv({
  rmssd_ms: 41.2,
  sdnn_ms: 46.7,
  minute_bpm: 67.8,
  minute_count: 72,
  bpm_low: 66.4,
  bpm_high: 69.3,
});
export const FAINT_NO_READING = hrv({
  minute_count: 9,
  no_reading: 'READING_FLOOR_NOT_CLEARED',
  why: 'faint_pulse',
  clear_percent: 38.2,
});
export const FAINT_LEAD =
  'Your pulse showed clearly in only 38% of the counted part. Face a window so the light is even, hold still, then press Start again.';

export function resultHero(page: Page) {
  const hero = page.getByRole('main').getByRole('region', { name: 'Result', exact: true });
  return {
    hero,
    finished: hero.getByText(RUN_FINISHED_LINE, { exact: true }),
    heartRateLabel: hero.getByText('Heart rate', { exact: true }),
    number: (bpm: number): Locator => hero.getByText(String(bpm), { exact: true }),
    noReading: hero.getByText('No reading this time', { exact: true }),
    variationLine: hero.getByText(VARIATION_LINE, { exact: true }),
  };
}

export function idleHeadline(page: Page): Locator {
  return page.getByRole('main').getByText(IDLE_HEADLINE, { exact: true });
}

export async function finishResultRun(page: Page, backend: MockBackend, last: Hrv): Promise<void> {
  const guided = guidedPage(page);
  await pushAndConfirm(page, backend, { bpm: 68.2, quality_db: 9.4, state: 'ok' });
  await advanceRunUntil(page, backend, guided.countedTimer);
  await setHrvAndConfirm(page, backend, EARLIER);
  await advanceRun(page, backend, 60000);
  await setHrvAndConfirm(page, backend, last);
  await advanceRunUntil(page, backend, guided.startAgain);
}

export async function reachResult(page: Page, last: Hrv, address = '/'): Promise<MockBackend> {
  const backend = await startRunAt(page, address);
  await finishResultRun(page, backend, last);
  return backend;
}

export function clippedOrScrolling(scope: Locator): Promise<string[]> {
  return scope.evaluate((root) =>
    [root, ...Array.from(root.querySelectorAll('*'))]
      .filter((element) => {
        const style = getComputedStyle(element);
        return (
          /^(auto|scroll|hidden|clip)$/.test(style.overflowY) && element.scrollHeight > element.clientHeight + 1
        );
      })
      .map((element) => `${element.tagName.toLowerCase()} ${(element.textContent ?? '').trim().slice(0, 40)}`),
  );
}

export async function reachCameraLostInWarmUp(page: Page): Promise<MockBackend> {
  await spyOnCamera(page);
  const backend = await MockBackend.attach(page);
  const guided = guidedPage(page);
  await startRun(page, backend);
  await advanceRun(page, backend, 10000, 2500);
  await expect(guided.warmUpTimer).toBeVisible();
  await endVideoTracks(page);
  await page.clock.runFor(1000);
  await expect(guided.alert).toContainText('Ref: CAMERA_LOST');
  return backend;
}

export function drawnTexts(scope: Locator, skipAlerts = false): Promise<string[]> {
  return scope.evaluate((root, skip) => {
    const isDrawn = (element: Element): boolean => {
      for (let node: Element | null = element; node !== null; node = node.parentElement) {
        const box = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        if (box.width <= 2 || box.height <= 2 || style.visibility === 'hidden' || style.opacity === '0') {
          return false;
        }
        if (node === root) {
          return true;
        }
      }
      return true;
    };
    const texts: string[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
      const text = (node.textContent ?? '').replaceAll(/\s+/g, ' ').trim();
      const parent = node.parentElement;
      if (text === '' || parent === null) {
        continue;
      }
      if (skip && parent.closest('[role="alert"]') !== null) {
        continue;
      }
      if (isDrawn(parent)) {
        texts.push(text);
      }
    }
    return texts;
  }, skipAlerts);
}

export function fontPx(locator: Locator): Promise<number> {
  return locator.evaluate((element) => Number.parseFloat(getComputedStyle(element).fontSize));
}

export type SizedText = { text: string; px: number };

export function drawnTextSizes(scope: Locator): Promise<SizedText[]> {
  return scope.evaluate((root) => {
    const sizes: SizedText[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
      const text = (node.textContent ?? '').replaceAll(/\s+/g, ' ').trim();
      const parent = node.parentElement;
      if (text === '' || parent === null) {
        continue;
      }
      const box = parent.getBoundingClientRect();
      if (box.width <= 2 || box.height <= 2 || getComputedStyle(parent).visibility === 'hidden') {
        continue;
      }
      sizes.push({ text, px: Number.parseFloat(getComputedStyle(parent).fontSize) });
    }
    return sizes.toSorted((a, b) => b.px - a.px);
  });
}

export async function expectNoResultTiles(page: Page): Promise<void> {
  const guided = guidedPage(page);
  await expect(guided.main.getByText('Heart rate', { exact: true })).toHaveCount(0);
  await expect(guided.main.getByText('Beat to beat variation', { exact: true })).toHaveCount(0);
  await expect(guided.main.getByText('Overall rhythm variation', { exact: true })).toHaveCount(0);
  await expect(guided.main.getByText('No reading yet', { exact: true })).toHaveCount(0);
  await expect(guided.notEnoughBeats).toHaveCount(0);
  await expect(guided.main.getByText('Not enough beats this time', { exact: true })).toHaveCount(0);
  await expect(guided.variationLine).toHaveCount(0);
}

export async function scrollPageToTop(page: Page): Promise<void> {
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
}
