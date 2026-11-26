import { expect, test, type Locator, type Page } from '@playwright/test';
import {
  BOTTOM_FADE_PX,
  contentOrder,
  fadeState,
  gradientShape,
  innerScrollers,
  maxScrollOf,
  pageExtent,
  reachState,
  rectOf,
  scrollportOf,
  scrollRegionTo,
  scrollTopOf,
  shell,
  TOP_FADE_PX,
  type Rect,
} from '../../support/app-shell';
import { calibrationBox, guidedPage } from '../../support/guided-page';

async function expectPinnedAbove(item: Locator, region: Locator, panel: Locator, name: string): Promise<void> {
  await expect(item, `${name} is shown`).toBeVisible();
  await expect(region.locator('*').and(item), `${name} sits outside the scroll area`).toHaveCount(0);
  await expect(panel.locator('*').and(item), `${name} sits in the side panel`).toHaveCount(1);
  const box = await rectOf(item);
  const view = await scrollportOf(region);
  expect(box.bottom, `${name} sits above the scroll area`).toBeLessThanOrEqual(view.top + 1);
}

async function rectsOf(items: Locator[]): Promise<Rect[]> {
  return Promise.all(items.map((item) => rectOf(item)));
}

async function expectStillAfterScroll(page: Page, region: Locator, items: Locator[]): Promise<void> {
  const before = await rectsOf(items);
  await scrollRegionTo(region, 'end');
  await expect.poll(() => scrollTopOf(region)).toBeGreaterThan(0);
  const after = await rectsOf(items);
  expect(after, 'pinned items keep their place while the area scrolls').toEqual(before);
  expect((await pageExtent(page)).scrollY).toBe(0);
}

test.describe('the side panel scroll area at desktop size', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('keeps the title and the prompt pinned above a labelled scroll area during the check', async ({ page }) => {
    await reachState(page, 'check');
    const guided = guidedPage(page);
    const parts = shell(page);
    const region = parts.details('Setup check details');
    const title = guided.headline('Quick setup check');

    await expect(region).toBeVisible();
    await expectPinnedAbove(title, region, parts.panel, 'the title');
    await expectPinnedAbove(guided.setupPrompt, region, parts.panel, 'the prompt');
    await expectStillAfterScroll(page, region, [title, guided.setupPrompt]);
  });

  test('keeps the title, the timer and both bars pinned above the scroll area while counting', async ({ page }) => {
    await reachState(page, 'counting');
    const guided = guidedPage(page);
    const parts = shell(page);
    const region = parts.details('Counting details');
    const title = guided.headline('Counting. Hold still.');
    const pinned = [title, guided.countedTimer, guided.warmUpBar, guided.countedBar];

    await expect(region).toBeVisible();
    await expectPinnedAbove(title, region, parts.panel, 'the title');
    await expectPinnedAbove(guided.countedTimer, region, parts.panel, 'the timer');
    await expectPinnedAbove(guided.warmUpBar, region, parts.panel, 'the warm-up bar');
    await expectPinnedAbove(guided.countedBar, region, parts.panel, 'the counted bar');
    await expectStillAfterScroll(page, region, pinned);
  });

  test('puts the heart rate first, in view without scrolling, and Calibration last while counting', async ({ page }) => {
    await reachState(page, 'counting');
    const guided = guidedPage(page);
    const region = shell(page).details('Counting details');
    const heartRate = guided.liveReadings.getByText('Heart rate', { exact: true });

    await expect(region.getByRole('region', { name: 'Live readings' })).toBeVisible();
    await expect(region.getByRole('region', { name: 'Calibration', exact: true })).toBeVisible();
    const order = await contentOrder(region);
    expect(order.first, 'the first block in the scroll area').toMatch(/^Live readings/);
    expect(order.last, 'the last block in the scroll area').toMatch(/Calibration$/);
    expect(await scrollTopOf(region)).toBe(0);
    const view = await scrollportOf(region);
    const label = await rectOf(heartRate);
    const value = await rectOf(guided.liveReadings.getByText(/^67(\.2)?$/));
    expect(label.top, 'the heart rate label is in view').toBeGreaterThanOrEqual(view.top);
    expect(value.bottom, 'the heart rate number is in view').toBeLessThanOrEqual(view.bottom - BOTTOM_FADE_PX);
  });

  test('puts Calibration last in the scroll area during the check', async ({ page }) => {
    await reachState(page, 'check');
    const region = shell(page).details('Setup check details');

    await expect(region.getByRole('region', { name: 'Calibration', exact: true })).toBeVisible();
    expect((await contentOrder(region)).last).toMatch(/Calibration$/);
  });

  test('puts Calibration last in the run details under a pinned title on the result', async ({ page }) => {
    await reachState(page, 'result');
    const guided = guidedPage(page);
    const parts = shell(page);
    const region = parts.details('Run details');

    await expect(region.getByRole('region', { name: 'Calibration', exact: true })).toBeVisible();
    expect((await contentOrder(region)).last).toMatch(/Calibration$/);
    await expectPinnedAbove(guided.headline('Done. Nice sitting.'), region, parts.panel, 'the title');
  });

  test('makes the scroll area a tab stop that End, Home and Page Down scroll', async ({ page }) => {
    await reachState(page, 'check');
    const region = shell(page).details('Setup check details');
    await expect(region).toBeVisible();
    const max = await maxScrollOf(region);
    expect(max, 'the check content overflows the panel at 1280x800').toBeGreaterThan(0);

    await expect(region).toHaveAttribute('tabindex', '0');
    await region.focus();
    await expect(region).toBeFocused();

    await page.keyboard.press('End');
    await expect.poll(() => scrollTopOf(region)).toBeGreaterThanOrEqual(max - 1);
    await page.keyboard.press('Home');
    await expect.poll(() => scrollTopOf(region)).toBe(0);
    await page.keyboard.press('PageDown');
    await expect.poll(() => scrollTopOf(region)).toBeGreaterThan(0);
    expect((await pageExtent(page)).scrollY).toBe(0);
  });

  test('scrolls the panel under the wheel without moving the page or the camera', async ({ page }) => {
    await reachState(page, 'check');
    const parts = shell(page);
    const region = parts.details('Setup check details');
    await expect(region).toBeVisible();
    const max = await maxScrollOf(region);
    const camera = await rectOf(parts.camera);
    const view = await scrollportOf(region);

    expect(await region.evaluate((element) => getComputedStyle(element).overscrollBehaviorY)).toBe('contain');
    await page.mouse.move((view.left + view.right) / 2, (view.top + view.bottom) / 2);
    await page.mouse.wheel(0, 4000);
    await expect.poll(() => scrollTopOf(region)).toBeGreaterThanOrEqual(max - 1);
    await page.mouse.wheel(0, 4000);

    await expect.poll(async () => (await pageExtent(page)).scrollY).toBe(0);
    expect(await rectOf(parts.camera)).toEqual(camera);
  });

  test('lays the foot fade over content only while more is below and the top fade only once scrolled', async ({
    page,
  }) => {
    await reachState(page, 'check');
    const region = shell(page).details('Setup check details');
    await expect(region).toBeVisible();

    const atStart = await fadeState(region);
    expect(atStart.maxScroll, 'the check content overflows the panel at 1280x800').toBeGreaterThan(0);
    expect(atStart.top).toEqual({
      position: 'sticky',
      edge: '0px',
      height: TOP_FADE_PX,
      image: expect.stringMatching(/gradient/),
      pointerEvents: 'none',
    });
    expect(atStart.bottom).toEqual({
      position: 'sticky',
      edge: '0px',
      height: BOTTOM_FADE_PX,
      image: expect.stringMatching(/gradient/),
      pointerEvents: 'none',
    });
    expect(gradientShape(atStart.top.image), 'top fade runs down from the surface to clear').toEqual({
      downward: true,
      startsClear: false,
      endsClear: true,
    });
    expect(gradientShape(atStart.bottom.image), 'foot fade runs down from clear to the surface').toEqual({
      downward: true,
      startsClear: true,
      endsClear: false,
    });
    expect(atStart.topCovers, 'top fade over content at the start').toBe(false);
    expect(atStart.bottomCovers, 'foot fade over content at the start').toBe(true);

    await scrollRegionTo(region, 'middle');
    const midway = await fadeState(region);
    expect(midway.topCovers, 'top fade over content midway').toBe(true);
    expect(midway.bottomCovers, 'foot fade over content midway').toBe(true);

    await scrollRegionTo(region, 'end');
    const atEnd = await fadeState(region);
    expect(atEnd.scrollTop).toBeGreaterThanOrEqual(atEnd.maxScroll - 1);
    expect(atEnd.topCovers, 'top fade over content at the end').toBe(true);
    expect(atEnd.bottomCovers, 'foot fade over the last line at the end').toBe(false);
    await expect(calibrationBox(page).region).toBeInViewport();
  });
});

test.describe('the side panel scroll area on a tall desktop', () => {
  test.use({ viewport: { width: 1280, height: 2000 } });

  test('shows no fade over content and no tab stop when the content fits', async ({ page }) => {
    await reachState(page, 'check');
    const region = shell(page).details('Setup check details');
    await expect(region).toBeVisible();

    const fits = await fadeState(region);

    expect(fits.maxScroll, 'the check content fits a 2000 px tall window').toBeLessThanOrEqual(0);
    expect(fits.topCovers).toBe(false);
    expect(fits.bottomCovers).toBe(false);
    await expect(region).not.toHaveAttribute('tabindex', '0');
  });
});

test.describe('the side panel when the window crosses the desktop breakpoint', () => {
  test.use({ viewport: { width: 820, height: 1180 } });

  test('turns the details into the inner scroll area under a pinned head and back again', async ({ page }) => {
    await reachState(page, 'check');
    const guided = guidedPage(page);
    const parts = shell(page);
    const region = parts.details('Setup check details');
    const notTabStop = region.and(page.locator('[tabindex="0"]'));

    expect(await innerScrollers(page), 'inner scroll areas while stacked').toEqual([]);
    await expect(notTabStop).toHaveCount(0);

    await page.setViewportSize({ width: 1180, height: 820 });

    await expect(region).toBeVisible();
    await expect(region).toHaveAttribute('tabindex', '0');
    await expect.poll(() => maxScrollOf(region)).toBeGreaterThan(0);
    expect(await region.evaluate((element) => getComputedStyle(element).overflowY)).toBe('auto');
    await expectPinnedAbove(guided.headline('Quick setup check'), region, parts.panel, 'the title');
    await expectPinnedAbove(guided.setupPrompt, region, parts.panel, 'the prompt');
    await expect.poll(async () => (await pageExtent(page)).scrollHeight).toBeLessThanOrEqual(820);

    await page.setViewportSize({ width: 820, height: 1180 });

    await expect.poll(() => innerScrollers(page), { message: 'inner scroll areas once stacked again' }).toEqual([]);
    await expect(notTabStop).toHaveCount(0);
  });
});
