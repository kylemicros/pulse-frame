import { expect, test, type Page } from '@playwright/test';
import {
  barRect,
  CAMERA_STATES,
  GUIDED_STATES,
  innerScrollers,
  MIT_LINE,
  pageExtent,
  PANEL_MAX_PX,
  PANEL_MIN_PX,
  reachState,
  rectOf,
  shell,
  type GuidedState,
} from './support/app-shell';
import { DISCLAIMER, openGuidedRun } from './support/guided-page';
import { MockBackend } from './support/mock-backend';

const DESKTOPS = [
  { name: 'desktop', size: { width: 1280, height: 800 } },
  { name: 'large desktop', size: { width: 1440, height: 900 } },
  { name: 'wide desktop', size: { width: 1920, height: 1080 } },
] as const;

const NARROW = [
  { name: 'just under the desktop breakpoint', size: { width: 1023, height: 768 } },
  { name: 'tablet', size: { width: 820, height: 1180 } },
  { name: 'phone', size: { width: 390, height: 844 } },
] as const;

const NO_SIDEWAYS = [
  { name: 'tablet', size: { width: 820, height: 1180 } },
  { name: 'phone', size: { width: 390, height: 844 } },
  { name: 'smallest phone', size: { width: 320, height: 568 } },
] as const;

const REFLOW_STATES: GuidedState[] = ['idle', 'check', 'counting', 'result'];

async function expectFillsWindowWithoutPageScroll(page: Page, state: GuidedState): Promise<void> {
  const parts = shell(page);
  const extent = await pageExtent(page);
  expect(extent.scrollHeight, `page height in the ${state} state`).toBeLessThanOrEqual(extent.innerHeight);
  expect(extent.scrollWidth, `page width in the ${state} state`).toBeLessThanOrEqual(extent.innerWidth);
  const footer = await rectOf(parts.footer);
  expect(Math.abs(footer.bottom - extent.innerHeight), 'the footer sits on the window bottom').toBeLessThanOrEqual(1);
  const panel = await rectOf(parts.panel);
  expect(panel.top, 'the panel starts inside the window').toBeGreaterThanOrEqual(0);
  expect(panel.bottom, 'the panel ends above the footer').toBeLessThanOrEqual(footer.top + 1);
  if (CAMERA_STATES.includes(state)) {
    const camera = await rectOf(parts.camera);
    expect(camera.top, 'the camera starts inside the window').toBeGreaterThanOrEqual(0);
    expect(camera.bottom, 'the camera ends above the footer').toBeLessThanOrEqual(footer.top + 1);
  }
}

test.describe('app shell', () => {
  test('shows the pulse-frame page title', async ({ page }) => {
    await page.goto('/');

    await expect(page).toHaveTitle('pulse-frame');
  });

  test('attaches the root element the app mounts into', async ({ page }) => {
    await page.goto('/');

    await expect(page.locator('#root')).toBeAttached();
  });

  test('loads without page errors or console errors', async ({ page }) => {
    const pageErrors: string[] = [];
    const consoleErrors: string[] = [];
    page.on('pageerror', (error) => pageErrors.push(error.message));
    page.on('console', (message) => {
      if (message.type() === 'error') {
        consoleErrors.push(message.text());
      }
    });

    await page.goto('/', { waitUntil: 'load' });

    expect(pageErrors).toEqual([]);
    expect(consoleErrors).toEqual([]);
  });
});

test.describe('the footer', () => {
  test('carries the disclaimer and the licence line once, outside the main area', async ({ page }) => {
    await MockBackend.attach(page);
    const parts = shell(page);

    await openGuidedRun(page);

    await expect(parts.footer).toHaveCount(1);
    await expect(parts.footer.getByText(DISCLAIMER, { exact: true })).toBeVisible();
    await expect(parts.mitLine).toBeVisible();
    await expect(page.getByText(DISCLAIMER, { exact: true })).toHaveCount(1);
    await expect(page.getByText(MIT_LINE, { exact: true })).toHaveCount(1);
    await expect(parts.main.getByText(DISCLAIMER, { exact: true })).toHaveCount(0);
  });

  test.describe('on a desktop', () => {
    test.use({ viewport: { width: 1280, height: 800 } });

    test('puts the disclaimer on the left and the licence line on the right of one row', async ({ page }) => {
      await MockBackend.attach(page);
      const parts = shell(page);
      await openGuidedRun(page);

      const footer = await rectOf(parts.footer);
      const disclaimer = await rectOf(parts.footer.getByText(DISCLAIMER, { exact: true }));
      const licence = await rectOf(parts.mitLine);

      expect(Math.abs(licence.top - disclaimer.top), 'both lines on one row').toBeLessThanOrEqual(4);
      expect(licence.left).toBeGreaterThan(disclaimer.right);
      expect(disclaimer.left - footer.left, 'the disclaimer starts at the left edge').toBeLessThanOrEqual(48);
      expect(footer.right - licence.right, 'the licence line ends at the right edge').toBeLessThanOrEqual(48);
    });
  });

  test.describe('on a phone', () => {
    test.use({ viewport: { width: 390, height: 844 } });

    test('stacks the licence line under the disclaimer and keeps both above the bottom bar at the page end', async ({
      page,
    }) => {
      await MockBackend.attach(page);
      const parts = shell(page);
      await openGuidedRun(page);

      await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
      const disclaimer = await rectOf(parts.footer.getByText(DISCLAIMER, { exact: true }));
      const licence = await rectOf(parts.mitLine);
      const bar = await barRect(page);

      expect(bar, 'the main button sits in a fixed bottom bar').not.toBeNull();
      expect(licence.top, 'the licence line sits under the disclaimer').toBeGreaterThanOrEqual(disclaimer.bottom - 1);
      expect(licence.bottom, 'the licence line clears the bottom bar').toBeLessThanOrEqual(bar?.top ?? 0);
    });
  });
});

for (const viewport of DESKTOPS) {
  test.describe(`the app shell at ${viewport.name} size`, () => {
    test.use({ viewport: viewport.size });

    for (const state of GUIDED_STATES) {
      test(`fills the window with no page scroll in the ${state} state`, async ({ page }) => {
        await reachState(page, state);

        await expectFillsWindowWithoutPageScroll(page, state);
      });
    }

    test('puts the camera column beside the side panel', async ({ page }) => {
      await MockBackend.attach(page);
      const parts = shell(page);
      await openGuidedRun(page);

      const camera = await rectOf(parts.camera);
      const panel = await rectOf(parts.panel);

      expect(camera.right, 'the camera sits left of the panel').toBeLessThanOrEqual(panel.left);
      expect(Math.abs(camera.top - panel.top), 'the camera and the panel start on one line').toBeLessThanOrEqual(24);
      expect(panel.right - panel.left).toBeGreaterThanOrEqual(PANEL_MIN_PX);
      expect(panel.right - panel.left).toBeLessThanOrEqual(PANEL_MAX_PX);
    });
  });
}

test.describe('the app shell at the desktop breakpoint', () => {
  test.use({ viewport: { width: 1024, height: 768 } });

  test('already puts the camera column beside a side panel of 360 to 440 px', async ({ page }) => {
    await MockBackend.attach(page);
    const parts = shell(page);
    await openGuidedRun(page);

    const camera = await rectOf(parts.camera);
    const panel = await rectOf(parts.panel);

    expect(camera.right).toBeLessThanOrEqual(panel.left);
    expect(panel.right - panel.left).toBeGreaterThanOrEqual(PANEL_MIN_PX);
    expect(panel.right - panel.left).toBeLessThanOrEqual(PANEL_MAX_PX);
  });
});

test.describe('the app shell on a 1280 wide desktop', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('gives the side panel 384 px', async ({ page }) => {
    await MockBackend.attach(page);
    await openGuidedRun(page);

    const panel = await rectOf(shell(page).panel);

    expect(Math.abs(panel.right - panel.left - 384)).toBeLessThanOrEqual(1);
  });
});

test.describe('the app shell on a 1920 wide desktop', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('uses the full width with a 440 px panel and no centred narrow card', async ({ page }) => {
    await MockBackend.attach(page);
    const parts = shell(page);
    await openGuidedRun(page);

    const camera = await rectOf(parts.camera);
    const panel = await rectOf(parts.panel);
    const main = await rectOf(parts.main);

    expect(Math.abs(panel.right - panel.left - PANEL_MAX_PX)).toBeLessThanOrEqual(1);
    expect(camera.left, 'the camera column starts near the left edge').toBeLessThanOrEqual(48);
    expect(1920 - panel.right, 'the panel ends near the right edge').toBeLessThanOrEqual(48);
    expect(main.right - main.left, 'the work area spans the window').toBeGreaterThanOrEqual(1920 - 96);
    expect(camera.right - camera.left, 'the camera grows with the window').toBeGreaterThan(1000);
  });
});

for (const viewport of NARROW) {
  test.describe(`the stacked page at ${viewport.name} width`, () => {
    test.use({ viewport: viewport.size });

    test('stacks the panel under the camera and scrolls the page, not an inner area, during the check', async ({
      page,
    }) => {
      await reachState(page, 'check');
      const parts = shell(page);

      const camera = await rectOf(parts.camera);
      const panel = await rectOf(parts.panel);
      const extent = await pageExtent(page);

      expect(panel.top, 'the panel follows the camera').toBeGreaterThanOrEqual(camera.bottom);
      expect(extent.scrollHeight, 'the page itself scrolls').toBeGreaterThan(extent.innerHeight);
      expect(await innerScrollers(page), 'scroll areas inside the page').toEqual([]);
      await expect(parts.details('Setup check details').and(page.locator('[tabindex="0"]'))).toHaveCount(0);
    });
  });
}

for (const viewport of NO_SIDEWAYS) {
  test.describe(`no sideways scroll at ${viewport.name} width`, () => {
    test.use({ viewport: viewport.size });

    for (const state of REFLOW_STATES) {
      test(`fits the ${state} state to the width with no horizontal overflow`, async ({ page }) => {
        await reachState(page, state);

        const extent = await pageExtent(page);

        expect(extent.scrollWidth).toBeLessThanOrEqual(extent.innerWidth);
        expect(await innerScrollers(page), 'scroll areas inside the page').toEqual([]);
      });
    }
  });
}
