import { expect, test, type Locator } from '@playwright/test';
import { SETUP_START_ANYWAY_MS } from '../src/features/guided-capture/lib/setup-check';
import { reachFarCheck, reachState, shell, startRunAt } from './support/app-shell';
import { contrastRatio, HOP_VERMILION } from './support/brand';
import { advanceRun, guidedPage, LONG_STEP_MS, openGuidedRun, paceUntil } from './support/guided-page';
import { MockBackend } from './support/mock-backend';
import { openSettings, settingsPanel } from './support/settings';

type Theme = 'light' | 'dark';

type Palette = {
  surface: string;
  surface2: string;
  muted: string;
  alertEdge: string;
  primaryBg: string;
  primaryText: string;
  primaryHover: string;
};

const PALETTE: Record<Theme, Palette> = {
  light: {
    surface: 'rgb(255, 255, 255)',
    surface2: 'rgb(240, 240, 238)',
    muted: 'rgb(82, 82, 82)',
    alertEdge: 'rgb(138, 44, 0)',
    primaryBg: 'rgb(26, 26, 26)',
    primaryText: 'rgb(255, 255, 255)',
    primaryHover: 'rgb(58, 58, 58)',
  },
  dark: {
    surface: 'rgb(34, 34, 34)',
    surface2: 'rgb(48, 48, 48)',
    muted: 'rgb(189, 189, 189)',
    alertEdge: 'rgb(255, 176, 138)',
    primaryBg: 'rgb(240, 240, 240)',
    primaryText: 'rgb(20, 20, 20)',
    primaryHover: 'rgb(208, 208, 208)',
  },
};

const DESKTOP = { width: 1280, height: 800 } as const;
const PHONE = { width: 390, height: 844 } as const;
const TEXT_CONTRAST = 4.5;
const EDGE_CONTRAST = 3;
const START_ANYWAY_BUDGET_MS = SETUP_START_ANYWAY_MS + 2000;

function paint(locator: Locator, property: 'backgroundColor' | 'color' | 'borderLeftColor' | 'borderTopColor'): Promise<string> {
  return locator.evaluate((element, name) => getComputedStyle(element)[name], property);
}

function vermilionPaint(scope: Locator, vermilion: string): Promise<string[]> {
  return scope.evaluate((root, colour) => {
    const found: string[] = [];
    for (const element of [root, ...Array.from(root.querySelectorAll('*'))]) {
      const style = getComputedStyle(element);
      const sides = ['Top', 'Right', 'Bottom', 'Left'] as const;
      const painted = [
        style.backgroundColor,
        style.color,
        style.fill,
        style.stroke,
        ...sides.map((side) =>
          style.getPropertyValue(`border-${side.toLowerCase()}-style`) === 'none'
            ? ''
            : style.getPropertyValue(`border-${side.toLowerCase()}-color`),
        ),
      ];
      if (painted.includes(colour) || style.backgroundImage.includes(colour)) {
        found.push(`${element.tagName.toLowerCase()} ${(element.textContent ?? '').trim().slice(0, 40)}`);
      }
    }
    return found;
  }, vermilion);
}

async function expectHover(control: Locator, resting: string, hovered: string): Promise<void> {
  await expect(control, 'background at rest').toHaveCSS('background-color', resting);
  await control.hover();
  await expect(control, 'background on hover').toHaveCSS('background-color', hovered);
  await expect(control, 'opacity on hover').toHaveCSS('opacity', '1');
}

for (const theme of ['light', 'dark'] as const) {
  const colours = PALETTE[theme];

  test.describe(`the page palette in the ${theme} theme on a desktop`, () => {
    test.use({ viewport: DESKTOP, colorScheme: theme });

    test('paints the header and panel on the surface, the live readings box one step up, and muted text at 4.5:1 or more', async ({
      page,
    }) => {
      const backend = await startRunAt(page, '/');
      const guided = guidedPage(page);
      await advanceRun(page, backend, 12000, 2500);
      await expect(guided.warmUpTimer).toBeVisible();
      const line = guided.liveReadings.getByText(/^Both show how much the gap/);

      await expect(page.getByRole('banner'), 'the header').toHaveCSS('background-color', colours.surface);
      await expect(shell(page).panel, 'the side panel').toHaveCSS('background-color', colours.surface);
      await expect(guided.liveReadings, 'the live readings box').toHaveCSS('background-color', colours.surface2);
      await expect(line, 'the variation line under the live readings').toHaveCSS('color', colours.muted);
      await expect(shell(page).mitLine, 'the licence line in the footer').toHaveCSS('color', colours.muted);
      expect(contrastRatio(colours.muted, colours.surface2), 'muted text on the inner box').toBeGreaterThanOrEqual(
        TEXT_CONTRAST,
      );
      expect(contrastRatio(colours.muted, colours.surface), 'muted text on the card').toBeGreaterThanOrEqual(TEXT_CONTRAST);
    });

    test('keeps a control edge at 3:1 or more on the card and on the inner box', async ({ page }) => {
      await reachState(page, 'warm-up');
      const calibration = page.getByRole('main').getByRole('region', { name: 'Calibration', exact: true });
      await expect(calibration).toBeVisible();

      await expect(calibration, 'the calibration box').toHaveCSS('background-color', colours.surface2);
      const edge = await paint(calibration, 'borderTopColor');
      expect(contrastRatio(edge, colours.surface2), `the edge ${edge} on the inner box`).toBeGreaterThanOrEqual(EDGE_CONTRAST);
      expect(contrastRatio(edge, colours.surface), `the edge ${edge} on the card`).toBeGreaterThanOrEqual(EDGE_CONTRAST);
    });

    test('draws the error alert edge in its own alert colour, never the warm-up vermilion, at 3:1 or more', async ({
      page,
    }) => {
      await reachState(page, 'camera-denied');
      const alert = guidedPage(page).alert;
      await expect(alert).toBeVisible();

      await expect(alert, 'the alert left edge').toHaveCSS('border-left-color', colours.alertEdge);
      expect(colours.alertEdge, 'the alert left edge').not.toBe(HOP_VERMILION);
      expect(
        contrastRatio(colours.alertEdge, await paint(alert, 'backgroundColor')),
        'the edge on the alert tint',
      ).toBeGreaterThanOrEqual(EDGE_CONTRAST);
      expect(contrastRatio(colours.alertEdge, colours.surface), 'the edge on the card').toBeGreaterThanOrEqual(EDGE_CONTRAST);
    });

    test('paints nothing vermilion on the page while an error shows, so vermilion means only the warm-up', async ({
      page,
    }) => {
      await reachState(page, 'camera-denied');
      await expect(guidedPage(page).alert).toBeVisible();

      expect(await vermilionPaint(page.getByRole('main'), HOP_VERMILION), 'vermilion in the page').toEqual([]);
    });

    test('hovers the main button to the primary hover fill, never by fading it, its label still 4.5:1 or more', async ({
      page,
    }) => {
      await MockBackend.attach(page);
      await openGuidedRun(page);
      const start = guidedPage(page).start;
      await page.mouse.move(0, 0);

      await expectHover(start, colours.primaryBg, colours.primaryHover);
      await expect(start, 'the Start label on hover').toHaveCSS('color', colours.primaryText);
      expect(contrastRatio(colours.primaryText, colours.primaryHover), 'the Start label on its hover fill').toBeGreaterThanOrEqual(
        TEXT_CONTRAST,
      );
    });

    test('hovers an unchosen theme choice to the inner box colour', async ({ page }) => {
      await MockBackend.attach(page);
      await openGuidedRun(page);
      await openSettings(page);
      const light = settingsPanel(page).themeChoice('Light');
      await expect(light).not.toBeChecked();
      await page.mouse.move(0, 0);

      await expectHover(light, colours.surface, colours.surface2);
    });

    test('hovers Start anyway to the inner box colour', async ({ page }) => {
      const backend = await reachFarCheck(page, LONG_STEP_MS);
      const guided = guidedPage(page);
      await paceUntil(page, backend, guided.startAnyway, START_ANYWAY_BUDGET_MS, LONG_STEP_MS);
      await page.mouse.move(0, 0);

      await expectHover(guided.startAnyway, colours.surface, colours.surface2);
    });
  });

  test.describe(`the Settings sheet palette in the ${theme} theme on a phone`, () => {
    test.use({ viewport: PHONE, colorScheme: theme });

    test('hovers the sheet Done button to the primary hover fill', async ({ page }) => {
      await MockBackend.attach(page);
      await openGuidedRun(page);
      await openSettings(page);
      const done = settingsPanel(page).done;
      await expect(done).toBeVisible();
      await page.mouse.move(0, 0);

      await expectHover(done, colours.primaryBg, colours.primaryHover);
    });
  });
}
