import { expect, test, type Locator, type Page } from '@playwright/test';
import { barRect, CALIBRATE_ADDRESS, rectOf, shell, startRunAt } from '../../support/app-shell';
import { advanceRun, expectQuietRef, guidedPage, termLines } from '../../support/guided-page';
import {
  clippedOrScrolling,
  drawnTextSizes,
  FAINT_LEAD,
  FAINT_NO_READING,
  finishResultRun,
  fontPx,
  RANGED_READING,
  reachResult,
  READING_SIZE_PX,
  resultHero,
  RUN_FINISHED_LINE,
  scrollPageToTop,
} from '../../support/result-states';

const RANGE_LINE = 'Average over the last counted minute. Likely 66 to 70.';
const BEAT_TO_BEAT_LINES = [expect.stringMatching(/^41 ?ms$/), 'Over the whole counted part.'];
const OVERALL_LINES = [expect.stringMatching(/^47 ?ms$/), 'Last counted minute.'];
const NOT_THIS_TIME = 'Not enough beats this time';
const TOP_LINE_PX = 48;
const ONE_LINE_SLACK_PX = 24;
const COLUMN_GAP_PX = 32;

async function expectNoCameraBox(page: Page): Promise<void> {
  const guided = guidedPage(page);
  await expect(guided.video).toBeHidden();
  await expect(guided.lock).toBeHidden();
}

async function expectFinishedLineOnTop(page: Page): Promise<void> {
  const parts = resultHero(page);
  await expect(parts.finished).toBeVisible();
  const hero = await rectOf(parts.hero);
  const line = await rectOf(parts.finished);
  const label = await rectOf(parts.heartRateLabel);
  expect(line.top - hero.top, 'the camera line sits in the top line of the card').toBeLessThanOrEqual(TOP_LINE_PX);
  expect(line.bottom, 'the camera line sits above the heart rate').toBeLessThanOrEqual(label.top + 1);
  await expect(guidedPage(page).main.getByText(RUN_FINISHED_LINE, { exact: true })).toHaveCount(1);
}

async function expectHeroWhereTheCameraWas(page: Page): Promise<void> {
  const parts = shell(page);
  const hero = await rectOf(resultHero(page).hero);
  const panel = await rectOf(parts.panel);
  const footer = await rectOf(parts.footer);
  expect(hero.right, 'the card sits left of the side panel').toBeLessThanOrEqual(panel.left + 1);
  expect(panel.left - hero.right, 'the card fills the camera column').toBeLessThanOrEqual(COLUMN_GAP_PX);
  expect(Math.abs(hero.top - panel.top), 'the card and the panel start on one line').toBeLessThanOrEqual(ONE_LINE_SLACK_PX);
  expect(hero.bottom, 'the card ends above the footer').toBeLessThanOrEqual(footer.top + 1);
}

async function expectAboveTheBar(page: Page, text: Locator): Promise<void> {
  await expect(text).toBeInViewport({ ratio: 1 });
  await expect
    .poll(
      async () => {
        const bar = await barRect(page);
        const box = await rectOf(text);
        return bar === null ? 'no bottom bar' : box.bottom <= bar.top;
      },
      { message: 'the text ends above the bottom bar' },
    )
    .toBe(true);
}

test.describe('the result hero on a desktop', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("shows the result as a hero card where the camera was, its top line saying Camera's off. Run finished.", async ({
    page,
  }) => {
    await reachResult(page, RANGED_READING);
    const parts = resultHero(page);

    await expect(parts.hero).toBeVisible();
    await expect(guidedPage(page).headline('Done. Nice sitting.')).toBeVisible();
    await expectNoCameraBox(page);
    await expectHeroWhereTheCameraWas(page);
    await expectFinishedLineOnTop(page);
  });

  test('names the hero card by its one heading, Result', async ({ page }) => {
    await reachResult(page, RANGED_READING);
    const parts = resultHero(page);
    const heading = parts.hero.getByRole('heading', { name: 'Result', exact: true });

    await expect(heading).toHaveCount(1);
    await expect(guidedPage(page).main.getByRole('heading', { name: 'Result', exact: true })).toHaveCount(1);
    const headingId = await heading.getAttribute('id');
    expect(headingId, 'the heading has an id').toBeTruthy();
    await expect(parts.hero).toHaveAttribute('aria-labelledby', headingId ?? '');
    await expect(parts.hero).not.toHaveAttribute('aria-label');
  });

  test('holds the heart rate, its range line, both variation tiles and the ms line in the hero card', async ({
    page,
  }) => {
    await reachResult(page, RANGED_READING);
    const parts = resultHero(page);

    await expect(parts.number(68)).toBeVisible();
    await expect.poll(() => termLines(parts.hero, 'Heart rate')).toEqual([
      expect.stringMatching(/^68 ?BPM$/),
      RANGE_LINE,
    ]);
    await expect.poll(() => termLines(parts.hero, 'Beat to beat variation')).toEqual(BEAT_TO_BEAT_LINES);
    await expect.poll(() => termLines(parts.hero, 'Overall rhythm variation')).toEqual(OVERALL_LINES);
    await expect(parts.variationLine).toBeVisible();
    await expect(shell(page).panel.getByText('Heart rate', { exact: true })).toHaveCount(0);
  });

  test('makes the heart rate the one big number, with its range line at reading size', async ({ page }) => {
    await reachResult(page, RANGED_READING);
    const parts = resultHero(page);
    await expect(parts.number(68)).toBeVisible();

    const sizes = await drawnTextSizes(parts.hero);
    const range = parts.hero.getByText(RANGE_LINE, { exact: true });

    expect(sizes[0]?.text, 'the largest text in the card').toBe('68');
    expect(sizes[1]?.px ?? 0, 'the next largest text against the heart rate').toBeLessThanOrEqual(
      (sizes[0]?.px ?? 0) * 0.6,
    );
    expect(await fontPx(range), 'the range line font size').toBeGreaterThanOrEqual(READING_SIZE_PX);
    const number = await rectOf(parts.number(68));
    const rangeBox = await rectOf(range);
    expect(rangeBox.top, 'the range line sits right under the number').toBeGreaterThanOrEqual(number.bottom - 1);
  });

  test('keeps the watch tip and the title in the side panel beside the card', async ({ page }) => {
    await reachResult(page, RANGED_READING);
    const panel = shell(page).panel;

    await expect(panel.getByRole('heading', { name: 'Done. Nice sitting.', exact: true })).toBeVisible();
    await expect(panel.getByText(/^Checking against a watch\?/)).toBeVisible();
    await expect(resultHero(page).hero.getByText(/^Checking against a watch\?/)).toHaveCount(0);
  });

  test('shows the whole hero card in the window with ?calibrate on, the number in view and nothing scrolling inside it', async ({
    page,
  }) => {
    await reachResult(page, RANGED_READING, CALIBRATE_ADDRESS);
    const parts = resultHero(page);

    await expect(parts.number(68)).toBeInViewport();
    await expect(parts.variationLine).toBeInViewport();
    expect(await clippedOrScrolling(parts.hero), 'parts of the card that scroll or clip').toEqual([]);
    await expectHeroWhereTheCameraWas(page);
  });

  test('moves focus to Start again when the run ends with focus on the privacy lock', async ({ page }) => {
    const backend = await startRunAt(page, '/');
    const guided = guidedPage(page);
    await advanceRun(page, backend, 2000, 1000);
    await guided.lock.focus();
    await expect(guided.lock).toBeFocused();

    await finishResultRun(page, backend, RANGED_READING);

    await expect(resultHero(page).hero).toBeVisible();
    await expect(guided.startAgain).toBeFocused();
  });
});

test.describe('the no reading result on a desktop', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test("shows no reading in the same hero card, Camera's off. Run finished. on top, the reason and the Ref in the side panel", async ({
    page,
  }) => {
    await reachResult(page, FAINT_NO_READING);
    const parts = resultHero(page);
    const guided = guidedPage(page);
    const panel = shell(page).panel;

    await expect(parts.hero).toBeVisible();
    await expect.poll(() => termLines(parts.hero, 'Heart rate')).toEqual(['No reading this time', 'Last counted minute.']);
    await expect.poll(() => termLines(parts.hero, 'Beat to beat variation')).toEqual([NOT_THIS_TIME]);
    await expect.poll(() => termLines(parts.hero, 'Overall rhythm variation')).toEqual([NOT_THIS_TIME]);
    await expect(parts.variationLine).toHaveCount(0);
    await expect(panel.getByRole('heading', { name: 'Done, but no reading this time.', exact: true })).toBeVisible();
    await expectQuietRef(panel, FAINT_LEAD, 'READING_FLOOR_NOT_CLEARED');
    await expect(guided.alert).toHaveCount(0);
    await expectNoCameraBox(page);
    await expectHeroWhereTheCameraWas(page);
    await expectFinishedLineOnTop(page);
  });

  test('sets No reading this time larger than the tile words', async ({ page }) => {
    await reachResult(page, FAINT_NO_READING);
    const parts = resultHero(page);
    await expect(parts.noReading).toBeVisible();

    const lead = await fontPx(parts.noReading);
    const tile = await fontPx(parts.hero.getByText(NOT_THIS_TIME, { exact: true }).first());

    expect(lead, 'No reading this time against the tile words').toBeGreaterThan(tile);
  });
});

test.describe('the result hero on a wide desktop', () => {
  test.use({ viewport: { width: 1920, height: 1080 } });

  test('grows the hero card with the camera column, beside the 440 px panel', async ({ page }) => {
    await reachResult(page, RANGED_READING);
    const hero = await rectOf(resultHero(page).hero);

    await expectNoCameraBox(page);
    await expectHeroWhereTheCameraWas(page);
    expect(hero.left, 'the card starts near the left edge').toBeLessThanOrEqual(48);
    expect(hero.right - hero.left, 'the card grows with the window').toBeGreaterThan(1000);
  });
});

test.describe('the result hero on a tablet', () => {
  test.use({ viewport: { width: 820, height: 1180 } });

  test('puts the hero card full width at the top, above the title, with no camera box', async ({ page }) => {
    await reachResult(page, RANGED_READING);
    const parts = resultHero(page);
    await scrollPageToTop(page);

    const hero = await rectOf(parts.hero);
    const main = await rectOf(shell(page).main);
    const title = await rectOf(guidedPage(page).headline('Done. Nice sitting.'));

    await expectNoCameraBox(page);
    expect(hero.bottom, 'the card comes before the title').toBeLessThanOrEqual(title.top);
    expect(hero.right - hero.left, 'the card spans the page').toBeGreaterThanOrEqual(main.right - main.left - 96);
    await expect(parts.number(68)).toBeInViewport();
  });
});

test.describe('the result hero on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('shows the heart rate on the first screen, clear of the bottom bar', async ({ page }) => {
    await reachResult(page, RANGED_READING);
    const parts = resultHero(page);
    await scrollPageToTop(page);

    await expectNoCameraBox(page);
    await expectAboveTheBar(page, parts.number(68));
    const title = await rectOf(guidedPage(page).headline('Done. Nice sitting.'));
    const hero = await rectOf(parts.hero);
    expect(hero.bottom, 'the card comes before the title').toBeLessThanOrEqual(title.top);
  });

  test('shows No reading this time on the first screen, clear of the bottom bar', async ({ page }) => {
    await reachResult(page, FAINT_NO_READING);
    await scrollPageToTop(page);

    await expectNoCameraBox(page);
    await expectAboveTheBar(page, resultHero(page).noReading);
  });
});
