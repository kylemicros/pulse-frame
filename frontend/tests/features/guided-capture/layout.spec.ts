import { expect, test, type Page } from '@playwright/test';
import {
  calibrationBox,
  fontFamily,
  guidedPage,
  LONG_STEP_MS,
  openGuidedRun,
  paceUntil,
  pushAndConfirm,
  SETUP_ROWS,
  SLOW_STEP_MS,
  startRun,
} from '../../support/guided-page';
import { MockBackend } from '../../support/mock-backend';
import { boxOf } from '../../support/page-helpers';
import {
  BAR_CLEARANCE_PX,
  barRect,
  lineCount,
  pageExtent,
  reachFarCheck,
  rectOf,
  setSafeAreaBottom,
  type Rect,
} from '../../support/app-shell';
import { PAGE_BACKGROUND } from '../../support/settings';

const SAFE_AREA_PX = 34;
const SHORT_PHONE_HEIGHT = 480;
const START_ANYWAY_BUDGET_MS = 17000;
const STRIP_CLEARANCE_PX = 16;


function backgroundBehind(page: Page, x: number, y: number): Promise<string> {
  return page.evaluate(
    ([left, top]) => {
      for (let node = document.elementFromPoint(left, top); node !== null; node = node.parentElement) {
        const colour = getComputedStyle(node).backgroundColor;
        if (colour !== 'rgba(0, 0, 0, 0)' && colour !== 'transparent') {
          return colour;
        }
      }
      return getComputedStyle(document.documentElement).backgroundColor;
    },
    [x, y],
  );
}

test.describe('the guided run as the only page', () => {
  test('shows one main landmark, the brand as the one level 1 heading, and no tabs', async ({ page }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);

    await openGuidedRun(page);

    await expect(page.getByRole('main')).toHaveCount(1);
    await expect(page.getByRole('main')).toBeVisible();
    await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
    await expect(page.getByRole('heading', { level: 1 })).toHaveAccessibleName('pulse frame');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByRole('tablist')).toHaveCount(0);
    await expect(page.getByRole('tab')).toHaveCount(0);
    await expect(page.getByRole('tabpanel')).toHaveCount(0);
    await expect(page.getByText('Live monitor')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Start', exact: true })).toHaveCount(1);
    await expect(guided.start).toBeVisible();
    await expect(page).toHaveTitle('pulse frame');
  });

  for (const colorScheme of ['light', 'dark'] as const) {
    test(`fills the page with the ${colorScheme} page background from the first load`, async ({ page }) => {
      await page.emulateMedia({ colorScheme });
      await MockBackend.attach(page);
      const viewport = page.viewportSize();
      expect(viewport).not.toBeNull();

      await openGuidedRun(page);

      const header = await boxOf(page.getByRole('banner'));
      const underHeader = Math.ceil(header.y + header.height) + STRIP_CLEARANCE_PX;

      expect(await backgroundBehind(page, 2, (viewport?.height ?? 0) - 2)).toBe(PAGE_BACKGROUND[colorScheme]);
      expect(await backgroundBehind(page, (viewport?.width ?? 0) - 2, underHeader)).toBe(PAGE_BACKGROUND[colorScheme]);
    });

    test(`sets the header on the surface colour in the ${colorScheme} theme`, async ({ page }) => {
      await page.emulateMedia({ colorScheme });
      await MockBackend.attach(page);
      await openGuidedRun(page);
      const banner = page.getByRole('banner');
      const header = await boxOf(banner);

      const surface = await page.evaluate(() => {
        const probe = document.createElement('div');
        probe.style.background = 'var(--ds-surface)';
        document.body.append(probe);
        const colour = getComputedStyle(probe).backgroundColor;
        probe.remove();
        return colour;
      });

      expect(surface).not.toBe(PAGE_BACKGROUND[colorScheme]);
      expect(await backgroundBehind(page, header.x + 2, header.y + 2), 'the header top left').toBe(surface);
      expect(
        await backgroundBehind(page, header.x + header.width - 2, header.y + header.height - 2),
        'the header bottom right',
      ).toBe(surface);
    });
  }
});

test.describe('guided run layout', () => {
  test('sets prose in the system sans and numbers in JetBrains Mono', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await startRun(page, backend);
    await pushAndConfirm(page, backend, { bpm: 66.6, quality_db: 9.0, state: 'ok' });

    const headline = await fontFamily(guided.headline('Stay in frame. No need to watch.'));
    const number = await fontFamily(guided.liveReadings.getByText(/^67$|^66\.6$/));
    const countdown = await fontFamily(guided.warmUpTimer);

    expect(headline).not.toMatch(/JetBrains Mono/);
    expect(headline).toMatch(/system-ui|ui-sans-serif|sans-serif/);
    expect(number).toMatch(/^"?JetBrains Mono/);
    expect(countdown).toMatch(/^"?JetBrains Mono/);
  });

  test.describe('on a phone', () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test('keeps the main button as a full-width bar at the bottom of the screen', async ({ page }) => {
      await MockBackend.attach(page);
      const guided = guidedPage(page);
      await openGuidedRun(page);

      const button = await boxOf(guided.start);

      expect(button.width).toBeGreaterThanOrEqual(390 * 0.85);
      expect(button.y + button.height).toBeGreaterThanOrEqual(844 - 32);
      expect(button.y + button.height).toBeLessThanOrEqual(844);
    });
  });

  test.describe('on a phone with a home indicator', () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test('pads the bottom bar by the safe-area inset under the main button', async ({ page }) => {
      await MockBackend.attach(page);
      const guided = guidedPage(page);
      await openGuidedRun(page);
      const plainBar = await barRect(page);
      const plainButton = await rectOf(guided.start);

      await setSafeAreaBottom(page, SAFE_AREA_PX);
      const insetBar = await barRect(page);
      const insetButton = await rectOf(guided.start);

      expect(plainBar, 'the main button sits in a fixed bottom bar').not.toBeNull();
      expect(insetBar?.bottom).toBe(844);
      expect(
        (insetBar?.bottom ?? 0) - insetButton.bottom - ((plainBar?.bottom ?? 0) - plainButton.bottom),
        'extra space under the button',
      ).toBeCloseTo(SAFE_AREA_PX, 0);
    });

    test('scroll-pads the page bottom by at least the bar height plus 16 px', async ({ page }) => {
      await MockBackend.attach(page);
      await openGuidedRun(page);
      await setSafeAreaBottom(page, SAFE_AREA_PX);
      const bar = await barRect(page);
      expect(bar).not.toBeNull();
      const barHeight = (bar?.bottom ?? 0) - (bar?.top ?? 0);

      const padding = await page.evaluate(
        () => Number.parseFloat(getComputedStyle(document.documentElement).scrollPaddingBottom) || 0,
      );

      expect(padding).toBeGreaterThanOrEqual(barHeight + BAR_CLEARANCE_PX - 1);
    });

    test('scrolls a control that sits under the bottom bar clear of it when it takes focus', async ({ page }) => {
      const backend = await reachFarCheck(page, LONG_STEP_MS);
      const guided = guidedPage(page);
      await paceUntil(page, backend, guided.startAnyway, START_ANYWAY_BUDGET_MS, LONG_STEP_MS);
      await setSafeAreaBottom(page, SAFE_AREA_PX);

      const control = guided.startAnyway;
      for (const height of [844, SHORT_PHONE_HEIGHT]) {
        const name = `the Start anyway button at 390x${height}`;
        await page.setViewportSize({ width: 390, height });
        await page.evaluate(() => {
          (document.activeElement as HTMLElement | null)?.blur();
          window.scrollTo(0, 0);
        });
        const bar = await barRect(page);
        expect(bar, 'the main button sits in a fixed bottom bar').not.toBeNull();
        const barTop = bar?.top ?? 0;
        const before = await rectOf(control);
        await page.evaluate((by) => window.scrollBy(0, by), before.top - (barTop + 4));
        const parked = await rectOf(control);
        expect(parked.top, `${name} starts under the bar at 390x${height}`).toBeGreaterThan(barTop);
        expect(parked.top, `${name} starts inside the window`).toBeLessThan(height);

        await control.focus();

        await expect(control).toBeFocused();
        expect((await rectOf(control)).bottom, `${name} clears the bar once focused`).toBeLessThanOrEqual(barTop);
      }
    });
  });

  test.describe('on a desktop', () => {
    test.use({ viewport: { width: 1280, height: 800 } });

    test('keeps the main button at the right end of the header row, after the steps', async ({ page }) => {
      await MockBackend.attach(page);
      const guided = guidedPage(page);
      await openGuidedRun(page);
      const banner = page.getByRole('banner');

      await expect(banner.getByRole('button', { name: 'Start', exact: true })).toBeVisible();
      const button = await boxOf(guided.start);
      const steps = await boxOf(guided.stepList);
      const header = await boxOf(banner);

      expect(button.x, 'the main button sits after the steps').toBeGreaterThanOrEqual(steps.x + steps.width - 1);
      expect(button.x + button.width, 'the main button reaches the right end of the header').toBeGreaterThanOrEqual(
        header.x + header.width - 48,
      );
      expect(
        Math.abs(button.y + button.height / 2 - (steps.y + steps.height / 2)),
        'the main button sits on the row of the steps',
      ).toBeLessThanOrEqual(8);
    });
  });
});

for (const viewport of [
  { name: 'desktop', size: { width: 1280, height: 800 } },
  { name: 'tablet', size: { width: 820, height: 1180 } },
  { name: 'phone', size: { width: 390, height: 844 } },
  { name: 'smallest phone', size: { width: 320, height: 568 } },
] as const) {
  test.describe(`setup check status rows at ${viewport.name} width`, () => {
    test.use({ viewport: viewport.size });

    test('keeps each row on one line, its word unwrapped and clear of the label, with no row touching another', async ({
      page,
    }) => {
      await reachFarCheck(page, SLOW_STEP_MS);
      const guided = guidedPage(page);
      await expect(guided.setupRow('Distance').getByText('Not yet', { exact: true })).toBeVisible();
      await expect(guided.setupRow('Camera speed').getByText('Not yet', { exact: true })).toBeVisible();

      const rows: Rect[] = [];
      for (const name of SETUP_ROWS) {
        const row = guided.setupRow(name);
        const label = row.getByText(name, { exact: true });
        const word = row.getByText(/^(Good|Not yet)$/);
        const labelBox = await rectOf(label);
        const wordBox = await rectOf(word);

        expect(await lineCount(word), `${name}: the check word stays on one line`).toBe(1);
        expect(await lineCount(label), `${name}: the label stays on one line`).toBe(1);
        expect(wordBox.left - labelBox.right, `${name}: space between the label and the word`).toBeGreaterThanOrEqual(8);
        expect(
          Math.abs((wordBox.top + wordBox.bottom) / 2 - (labelBox.top + labelBox.bottom) / 2),
          `${name}: the word sits on the label's line`,
        ).toBeLessThanOrEqual(4);
        expect(
          await row.evaluate((element) => element.scrollWidth - element.clientWidth),
          `${name}: nothing runs out of the row`,
        ).toBeLessThanOrEqual(0);
        rows.push(await rectOf(row));
      }

      for (const [index, first] of rows.entries()) {
        for (const second of rows.slice(index + 1)) {
          const apart = Math.max(second.left - first.right, first.left - second.right, second.top - first.bottom, first.top - second.bottom);
          expect(apart, 'space between two status rows').toBeGreaterThanOrEqual(4);
        }
      }
      expect((await pageExtent(page)).scrollWidth).toBeLessThanOrEqual(viewport.size.width);
    });
  });
}

async function checkPanelBoxes(page: Page) {
  await reachFarCheck(page);
  const guided = guidedPage(page);
  await expect(guided.liveReadings).toBeVisible();
  await expect(calibrationBox(page).region).toBeVisible();
  return {
    title: await rectOf(guided.headline('Quick setup check')),
    rows: await rectOf(guided.setupCheck),
    readings: await rectOf(guided.liveReadings),
    calibration: await rectOf(calibrationBox(page).region),
  };
}

test.describe('the stacked panel on a tablet', () => {
  test.use({ viewport: { width: 820, height: 1180 } });

  test('sets the live readings beside the setup check and Calibration full width under both', async ({ page }) => {
    const { title, rows, readings, calibration } = await checkPanelBoxes(page);

    expect(readings.left, 'the live readings sit right of the setup check').toBeGreaterThanOrEqual(rows.right - 1);
    expect(readings.top, 'the live readings start beside the setup check, not under it').toBeLessThan(rows.bottom);
    expect(Math.abs(readings.top - title.top), 'both columns start on one line').toBeLessThanOrEqual(40);
    expect(calibration.top, 'Calibration sits under both columns').toBeGreaterThanOrEqual(
      Math.max(rows.bottom, readings.bottom) - 1,
    );
    expect(calibration.left, 'Calibration starts under the left column').toBeLessThanOrEqual(title.left);
    expect(calibration.right, 'Calibration reaches under the right column').toBeGreaterThanOrEqual(readings.right - 1);
  });
});

test.describe('the stacked panel on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('keeps one column: setup check, then live readings, then Calibration', async ({ page }) => {
    const { rows, readings, calibration } = await checkPanelBoxes(page);

    expect(readings.top, 'the live readings follow the setup check').toBeGreaterThanOrEqual(rows.bottom - 1);
    expect(Math.abs(readings.left - rows.left), 'one column').toBeLessThanOrEqual(24);
    expect(calibration.top, 'Calibration follows the live readings').toBeGreaterThanOrEqual(readings.bottom - 1);
  });
});
