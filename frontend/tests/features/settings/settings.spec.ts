import { expect, test, type Locator, type Page } from '@playwright/test';
import { CALIBRATE_ADDRESS, reachFarCheck } from '../../support/app-shell';
import { backgroundBehind, contrastRatio } from '../../support/brand';
import {
  advanceRun,
  advanceRunUntil,
  calibrationBox,
  guidedPage,
  openGuidedRun,
  startRun,
  timerSeconds,
} from '../../support/guided-page';
import { MockBackend } from '../../support/mock-backend';
import { boxOf } from '../../support/page-helpers';
import {
  buttonLook,
  chooseTheme,
  CLEAR,
  closeSettings,
  expectSetting,
  focusRing,
  hasNoBorder,
  holdsFocus,
  insideInertOrHidden,
  openSettings,
  PAGE_BACKGROUND,
  pageBackground,
  setSetting,
  SETTING_LINES,
  settingsPanel,
  tabTo,
  THEME_CHOICES,
} from '../../support/settings';

const TARGET_PX = 44;
const MIN_ICON_CONTRAST = 3;
const TAB_PRESSES = 12;
const STILL_PX = 0.5;
const THEME_KEY = 'theme';
const JUNK_THEME = 'purple<script>';
const LIGHT_MEDIA = '(prefers-color-scheme: light)';
const DARK_MEDIA = '(prefers-color-scheme: dark)';

type Rect = { x: number; y: number; width: number; height: number };

type Stored = { localKeys: string[]; session: number; databases: number };

type ThemeMetas = { light: string | null; dark: string | null };

async function rectsOf(page: Page): Promise<Record<string, Rect>> {
  const stop = page.getByRole('button', { name: 'Stop', exact: true, includeHidden: true }).filter({ visible: true });
  return {
    camera: await boxOf(page.getByLabel('Camera preview', { exact: true })),
    mainButton: await boxOf(stop),
  };
}

function expectStill(before: Record<string, Rect>, after: Record<string, Rect>): void {
  for (const [name, rect] of Object.entries(before)) {
    for (const side of ['x', 'y', 'width', 'height'] as const) {
      expect(Math.abs(after[name][side] - rect[side]), `${name} ${side} moved`).toBeLessThanOrEqual(STILL_PX);
    }
  }
}

async function expectRing(control: Locator): Promise<void> {
  const ring = await focusRing(control);
  expect(
    (ring.outlineStyle !== 'none' && ring.outlineWidth >= 2) || ring.shadow !== 'none',
    `focus ring ${JSON.stringify(ring)}`,
  ).toBe(true);
}

async function expectQuietIconButton(page: Page, button: Locator): Promise<void> {
  await page.mouse.move(0, 0);
  const resting = await buttonLook(button);
  await button.hover();
  const hovered = await buttonLook(button);

  expect(hasNoBorder(resting), `border at rest ${JSON.stringify(resting)}`).toBe(true);
  expect(hasNoBorder(hovered), `border on hover ${JSON.stringify(hovered)}`).toBe(true);
  expect(resting.background, 'background at rest').toBe(CLEAR);
  expect(hovered.background, 'background on hover').toBe(CLEAR);
  expect(resting.shadow, 'shadow at rest').toBe('none');
  expect(hovered.shadow, 'shadow on hover').toBe('none');
  expect(hovered.iconColour, 'the icon colour on hover').not.toBe(resting.iconColour);
}

function storedInBrowser(page: Page): Promise<Stored> {
  return page.evaluate(async () => ({
    localKeys: Array.from({ length: localStorage.length }, (_, index) => localStorage.key(index) ?? ''),
    session: sessionStorage.length,
    databases: (await indexedDB.databases()).length,
  }));
}

function themeMetas(page: Page): Promise<ThemeMetas> {
  return page.locator('head meta[name="theme-color"]').evaluateAll((metas) => {
    const media = (content: string): string | null =>
      metas.find((meta) => meta.getAttribute('content')?.toLowerCase() === content)?.getAttribute('media') ?? null;
    return { light: media('#f7f7f5'), dark: media('#141414') };
  });
}

test.describe('the Settings gear on a desktop', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  for (const colorScheme of ['light', 'dark'] as const) {
    test(`shows a borderless 44 px Settings gear with no background whose icon only changes colour on hover in the ${colorScheme} theme`, async ({
      page,
    }) => {
      await page.emulateMedia({ colorScheme });
      await MockBackend.attach(page);
      const settings = settingsPanel(page);
      await openGuidedRun(page);

      await expect(settings.gear).toBeVisible();
      await expect(settings.gear).toHaveAttribute('aria-haspopup', 'dialog');
      await expect(settings.gear).toHaveAttribute('aria-expanded', 'false');
      await expect(settings.gear.locator('svg')).toHaveCount(1);
      const gear = await boxOf(settings.gear);
      expect(gear.width).toBeGreaterThanOrEqual(TARGET_PX);
      expect(gear.height).toBeGreaterThanOrEqual(TARGET_PX);
      await page.mouse.move(0, 0);
      const resting = await buttonLook(settings.gear);
      const behind = await backgroundBehind(settings.gear);
      expect(
        contrastRatio(resting.iconColour, behind),
        `the resting gear ${resting.iconColour} on ${behind}`,
      ).toBeGreaterThanOrEqual(MIN_ICON_CONTRAST);
      await expectQuietIconButton(page, settings.gear);
    });
  }

  test('draws a focus ring around the gear on keyboard focus', async ({ page }) => {
    await MockBackend.attach(page);
    const settings = settingsPanel(page);
    await openGuidedRun(page);

    await tabTo(page, settings.gear);

    await expectRing(settings.gear);
  });

  test('gives the Settings close button the gear look and a focus ring', async ({ page }) => {
    await MockBackend.attach(page);
    const settings = settingsPanel(page);
    await openGuidedRun(page);
    await openSettings(page);

    await expect(settings.close).toBeVisible();
    await expectQuietIconButton(page, settings.close);
    await expect(settings.skinOutline).toBeFocused();
    await page.keyboard.press('Shift+Tab');
    await expect(settings.close).toBeFocused();
    await expectRing(settings.close);
  });

  test('drops the popover under the gear, right aligned with the main button, clear of the camera', async ({ page }) => {
    await MockBackend.attach(page);
    const guided = guidedPage(page);
    const settings = settingsPanel(page);
    await openGuidedRun(page);

    await openSettings(page);

    const dialog = await boxOf(settings.dialog);
    const gear = await boxOf(settings.gear);
    const button = await boxOf(guided.start);
    const camera = await boxOf(guided.video);
    expect(dialog.y, 'the popover drops under the gear').toBeGreaterThanOrEqual(gear.y + gear.height - 1);
    expect(
      Math.abs(dialog.x + dialog.width - (button.x + button.width)),
      'the popover right edge against the main button right edge',
    ).toBeLessThanOrEqual(4);
    expect(dialog.x, 'the popover stays clear of the camera').toBeGreaterThanOrEqual(camera.x + camera.width - 1);
  });
});

for (const viewport of [
  { name: 'desktop', size: { width: 1280, height: 800 } },
  { name: 'tablet', size: { width: 820, height: 1180 } },
] as const) {
  test.describe(`Settings as a popover on a ${viewport.name}`, () => {
    test.use({ viewport: viewport.size });

    test('opens a non-modal Settings popover from the gear with focus on the first switch', async ({ page }) => {
      await MockBackend.attach(page);
      const guided = guidedPage(page);
      const settings = settingsPanel(page);
      await openGuidedRun(page);
      await expect(settings.gear).toBeVisible();

      await settings.gear.click();

      await expect(settings.dialog).toBeVisible();
      await expect(settings.dialog).not.toHaveAttribute('aria-modal', 'true');
      await expect(settings.gear).toHaveAttribute('aria-expanded', 'true');
      await expect(settings.skinOutline).toBeFocused();
      expect(await insideInertOrHidden(guided.main), 'the page under the popover is shut off').toBe(false);
      await expect(guided.start).toBeVisible();
    });

    test('closes the popover with Escape and puts focus back on the gear', async ({ page }) => {
      await MockBackend.attach(page);
      const settings = settingsPanel(page);
      await openGuidedRun(page);
      await openSettings(page);

      await page.keyboard.press('Escape');

      await expect(settings.dialog).toBeHidden();
      await expect(settings.gear).toHaveAttribute('aria-expanded', 'false');
      await expect(settings.gear).toBeFocused();
    });

    test('closes the popover with its close button and puts focus back on the gear', async ({ page }) => {
      await MockBackend.attach(page);
      const settings = settingsPanel(page);
      await openGuidedRun(page);
      await openSettings(page);

      await settings.close.click();

      await expect(settings.dialog).toBeHidden();
      await expect(settings.gear).toBeFocused();
    });

    test('closes the popover on a click outside it and puts focus back on the gear', async ({ page }) => {
      await MockBackend.attach(page);
      const guided = guidedPage(page);
      const settings = settingsPanel(page);
      await openGuidedRun(page);
      await openSettings(page);

      await guided.disclaimer.click();

      await expect(settings.dialog).toBeHidden();
      await expect(settings.gear).toBeFocused();
    });
  });
}

test.describe('Settings as a bottom sheet on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('opens a modal bottom sheet across the foot of the screen with focus on the first switch', async ({ page }) => {
    await MockBackend.attach(page);
    const settings = settingsPanel(page);
    await openGuidedRun(page);
    await expect(settings.gear).toBeVisible();

    await settings.gear.click();

    await expect(settings.dialog).toBeVisible();
    await expect(settings.dialog).toHaveAttribute('aria-modal', 'true');
    await expect(settings.gear).toHaveAttribute('aria-expanded', 'true');
    await expect(settings.skinOutline).toBeFocused();
    const sheet = await boxOf(settings.dialog);
    expect(Math.abs(sheet.y + sheet.height - 844), 'the sheet sits on the screen foot').toBeLessThanOrEqual(1);
    expect(sheet.width, 'the sheet spans the screen').toBeGreaterThanOrEqual(380);
  });

  test('keeps focus inside the sheet while tabbing forwards and backwards', async ({ page }) => {
    await MockBackend.attach(page);
    const settings = settingsPanel(page);
    await openGuidedRun(page);
    await openSettings(page);

    for (let press = 1; press <= TAB_PRESSES; press += 1) {
      await page.keyboard.press('Tab');
      expect(await holdsFocus(settings.dialog), `focus inside the sheet after ${press} Tab presses`).toBe(true);
    }
    for (let press = 1; press <= TAB_PRESSES; press += 1) {
      await page.keyboard.press('Shift+Tab');
      expect(await holdsFocus(settings.dialog), `focus inside the sheet after ${press} Shift+Tab presses`).toBe(true);
    }
  });

  test('closes the sheet when the scrim above it is pressed and puts focus back on the gear', async ({ page }) => {
    await MockBackend.attach(page);
    const settings = settingsPanel(page);
    await openGuidedRun(page);
    await openSettings(page);
    const sheet = await boxOf(settings.dialog);
    expect(sheet.y, 'room above the sheet for the scrim').toBeGreaterThan(40);

    await page.mouse.click(195, sheet.y / 2);

    await expect(settings.dialog).toBeHidden();
    await expect(settings.gear).toBeFocused();
  });

  test('closes the sheet with Escape, with Done and with its close button, focus back on the gear each time', async ({
    page,
  }) => {
    await MockBackend.attach(page);
    const settings = settingsPanel(page);
    await openGuidedRun(page);

    for (const how of ['Escape', 'Done', 'close'] as const) {
      await openSettings(page);
      if (how === 'Escape') {
        await page.keyboard.press('Escape');
      } else {
        await (how === 'Done' ? settings.done : settings.close).click();
      }
      await expect(settings.dialog, `closed with ${how}`).toBeHidden();
      await expect(settings.gear, `focus back after ${how}`).toBeFocused();
    }
  });
});

test.describe('what Settings holds', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('lists Skin outline, Chime and Theme, then the privacy sentence, with no Calibration numbers without ?calibrate', async ({
    page,
  }) => {
    await MockBackend.attach(page);
    const settings = settingsPanel(page);
    await openGuidedRun(page);

    await openSettings(page);

    await expect(settings.dialog.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible();
    await expect(settings.dialog.getByRole('switch')).toHaveCount(2);
    await expect(settings.calibrationNumbers).toHaveCount(0);
    await expect(settings.privacy).toBeVisible();
    const order = [
      await boxOf(settings.skinOutline),
      await boxOf(settings.chime),
      await boxOf(settings.theme),
      await boxOf(settings.privacy),
    ].map((box) => box.y);
    expect(order, 'Skin outline, Chime, Theme, then the privacy sentence, top to bottom').toEqual(
      order.toSorted((a, b) => a - b),
    );
  });

  test('shows each switch on by default with its line and the word On', async ({ page }) => {
    await MockBackend.attach(page);
    const settings = settingsPanel(page);
    await openGuidedRun(page);

    await openSettings(page);

    for (const name of ['Skin outline', 'Chime'] as const) {
      const control = settings.setting(name);
      await expect(control).toBeChecked();
      await expect(settings.dialog.getByText(SETTING_LINES[name], { exact: true })).toBeVisible();
      await expect(control.getByText('On', { exact: true })).toBeVisible();
    }
  });

  test('gives a switch and a theme choice a target of 44 px or more', async ({ page }) => {
    await MockBackend.attach(page);
    const settings = settingsPanel(page);
    await openGuidedRun(page);

    await openSettings(page);

    for (const [name, control] of [
      ['the Skin outline switch', settings.skinOutline],
      ['the Light choice', settings.themeChoice('Light')],
    ] as const) {
      const box = await boxOf(control);
      expect(box.width, `${name} width`).toBeGreaterThanOrEqual(TARGET_PX);
      expect(box.height, `${name} height`).toBeGreaterThanOrEqual(TARGET_PX);
    }
  });

  test('leaves no Skin outline or Chime toggle on the page', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page);

    await expect(page.getByRole('switch')).toHaveCount(0);
    await expect(page.getByRole('button', { name: /Skin outline|Chime/ })).toHaveCount(0);

    await startRun(page, backend);

    await expect(guided.warmUpTimer).toBeVisible();
    await expect(page.getByRole('switch')).toHaveCount(0);
    await expect(page.getByRole('button', { name: /Skin outline|Chime/ })).toHaveCount(0);
  });

  test('turns the Chime switch back on after a reload', async ({ page }) => {
    await MockBackend.attach(page);
    await openGuidedRun(page);
    await setSetting(page, 'Chime', false);

    await page.reload();

    await expectSetting(page, 'Chime', true);
  });
});

test.describe('the theme control', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('offers Light, Dark and System with an icon each as one radio group, System chosen first', async ({ page }) => {
    await MockBackend.attach(page);
    const settings = settingsPanel(page);
    await openGuidedRun(page);

    await openSettings(page);

    await expect(settings.theme).toBeVisible();
    await expect(settings.themeChoices).toHaveCount(3);
    for (const [index, name] of THEME_CHOICES.entries()) {
      const choice = settings.themeChoice(name);
      await expect(settings.themeChoices.nth(index)).toHaveAccessibleName(name);
      await expect(choice.locator('svg'), `${name} carries an icon`).toHaveCount(1);
      await (name === 'System' ? expect(choice).toBeChecked() : expect(choice).not.toBeChecked());
    }
  });

  test('switches the page to dark when Dark is chosen under a light system setting', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await MockBackend.attach(page);
    await openGuidedRun(page);
    expect(await pageBackground(page)).toBe(PAGE_BACKGROUND.light);

    await chooseTheme(page, 'Dark');

    await expect.poll(() => pageBackground(page)).toBe(PAGE_BACKGROUND.dark);
  });

  test('switches the page to light when Light is chosen under a dark system setting', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await MockBackend.attach(page);
    await openGuidedRun(page);
    expect(await pageBackground(page)).toBe(PAGE_BACKGROUND.dark);

    await chooseTheme(page, 'Light');

    await expect.poll(() => pageBackground(page)).toBe(PAGE_BACKGROUND.light);
  });

  test('follows the system setting again, live, once System is chosen', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await MockBackend.attach(page);
    await openGuidedRun(page);
    await chooseTheme(page, 'Dark');
    await expect.poll(() => pageBackground(page)).toBe(PAGE_BACKGROUND.dark);

    await chooseTheme(page, 'System');

    await expect.poll(() => pageBackground(page)).toBe(PAGE_BACKGROUND.light);
    await page.emulateMedia({ colorScheme: 'dark' });
    await expect.poll(() => pageBackground(page)).toBe(PAGE_BACKGROUND.dark);
  });

  test('moves the theme choice with the arrow keys', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await MockBackend.attach(page);
    const settings = settingsPanel(page);
    await openGuidedRun(page);
    await openSettings(page);
    await settings.themeChoice('System').focus();

    await page.keyboard.press('ArrowLeft');

    await expect(settings.themeChoice('Dark')).toBeChecked();
    await expect(settings.themeChoice('Dark')).toBeFocused();
    await expect(settings.themeChoice('System')).not.toBeChecked();
    await expect.poll(() => pageBackground(page)).toBe(PAGE_BACKGROUND.dark);

    await page.keyboard.press('ArrowRight');

    await expect(settings.themeChoice('System')).toBeChecked();
    await expect.poll(() => pageBackground(page)).toBe(PAGE_BACKGROUND.light);
  });

  test('keeps a Dark choice in this browser across a reload, sending nothing and setting no cookie', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    const backend = await MockBackend.attach(page);
    const settings = settingsPanel(page);
    await openGuidedRun(page);
    const requests: string[] = [];
    page.on('request', (request) => requests.push(`${request.method()} ${request.url()}`));

    await chooseTheme(page, 'Dark');

    expect(requests, 'requests made by choosing a theme').toEqual([]);
    expect(backend.connections, 'sockets opened by choosing a theme').toEqual([]);
    expect(await page.context().cookies(), 'cookies set by choosing a theme').toEqual([]);

    await page.reload();
    await expect(guidedPage(page).stepList).toBeVisible();

    expect(await pageBackground(page)).toBe(PAGE_BACKGROUND.dark);
    await openSettings(page);
    await expect(settings.themeChoice('Dark')).toBeChecked();
    expect(await page.context().cookies(), 'cookies after the reload').toEqual([]);
    expect(backend.connections, 'sockets opened after the reload').toEqual([]);
  });

  test('stores only the theme key for a Dark choice and clears it when System is chosen again', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await MockBackend.attach(page);
    const settings = settingsPanel(page);
    await openGuidedRun(page);
    expect(await storedInBrowser(page), 'stored before any choice').toEqual({ localKeys: [], session: 0, databases: 0 });

    await chooseTheme(page, 'Dark');

    expect(await storedInBrowser(page), 'stored after choosing Dark').toEqual({
      localKeys: [THEME_KEY],
      session: 0,
      databases: 0,
    });

    await chooseTheme(page, 'System');

    expect(await storedInBrowser(page), 'stored after choosing System').toEqual({
      localKeys: [],
      session: 0,
      databases: 0,
    });

    await page.reload();
    await expect(guidedPage(page).stepList).toBeVisible();

    expect(await pageBackground(page)).toBe(PAGE_BACKGROUND.light);
    await openSettings(page);
    await expect(settings.themeChoice('System')).toBeChecked();
  });

  test('points the browser theme colour at the chosen theme and back at the system for System', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await MockBackend.attach(page);
    await openGuidedRun(page);
    expect(await themeMetas(page)).toEqual({ light: LIGHT_MEDIA, dark: DARK_MEDIA });

    await chooseTheme(page, 'Dark');

    await expect.poll(() => themeMetas(page)).toEqual({ light: 'not all', dark: 'all' });

    await chooseTheme(page, 'System');

    await expect.poll(() => themeMetas(page)).toEqual({ light: LIGHT_MEDIA, dark: DARK_MEDIA });
  });

  for (const colorScheme of ['light', 'dark'] as const) {
    test(`shows the System look under a ${colorScheme} system setting and leaves an unknown stored theme as it is`, async ({
      page,
    }) => {
      await page.addInitScript(([key, junk]) => localStorage.setItem(key, junk), [THEME_KEY, JUNK_THEME]);
      await page.emulateMedia({ colorScheme });
      await MockBackend.attach(page);
      const settings = settingsPanel(page);

      await openGuidedRun(page);

      expect(await pageBackground(page)).toBe(PAGE_BACKGROUND[colorScheme]);
      expect(await page.evaluate((key) => localStorage.getItem(key), THEME_KEY)).toBe(JUNK_THEME);
      await openSettings(page);
      await expect(settings.themeChoice('System')).toBeChecked();
    });
  }
});

test.describe('the Calibration numbers switch', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('shows the Calibration numbers switch, on, with its line, last of the switches when the address has ?calibrate', async ({
    page,
  }) => {
    await MockBackend.attach(page);
    const settings = settingsPanel(page);
    await openGuidedRun(page, CALIBRATE_ADDRESS);

    await openSettings(page);

    await expect(settings.calibrationNumbers).toBeVisible();
    await expect(settings.calibrationNumbers).toBeChecked();
    await expect(settings.dialog.getByText(SETTING_LINES['Calibration numbers'], { exact: true })).toBeVisible();
    await expect(settings.dialog.getByRole('switch')).toHaveCount(3);
    expect((await boxOf(settings.calibrationNumbers)).y, 'Calibration numbers under the theme').toBeGreaterThan(
      (await boxOf(settings.theme)).y,
    );
    expect((await boxOf(settings.privacy)).y, 'the privacy sentence last').toBeGreaterThan(
      (await boxOf(settings.calibrationNumbers)).y,
    );
  });

  test('removes the Calibration box when turned off during the check and brings it back when turned on', async ({
    page,
  }) => {
    await reachFarCheck(page);
    await page.clock.resume();
    const box = calibrationBox(page);
    const settings = settingsPanel(page);
    await expect(box.region).toBeVisible();
    await openSettings(page);

    await settings.calibrationNumbers.click();

    await expect(settings.calibrationNumbers).not.toBeChecked();
    await expect(box.region).toHaveCount(0);

    await settings.calibrationNumbers.click();

    await expect(settings.calibrationNumbers).toBeChecked();
    await expect(box.region).toBeVisible();
  });

  test('keeps the Calibration box out of the run when turned off before Start', async ({ page }) => {
    await page.clock.install();
    const backend = await MockBackend.attach(page);
    const guided = guidedPage(page);
    await openGuidedRun(page, CALIBRATE_ADDRESS);
    await setSetting(page, 'Calibration numbers', false);

    await guided.start.click();
    await expect.poll(() => backend.frames.length).toBeGreaterThan(1);
    await advanceRun(page, backend, 3000, 500);

    await expect(guided.stop).toBeVisible();
    await expect(calibrationBox(page).region).toHaveCount(0);
  });

  test('is back on after a reload', async ({ page }) => {
    await MockBackend.attach(page);
    await openGuidedRun(page, CALIBRATE_ADDRESS);
    await setSetting(page, 'Calibration numbers', false);

    await page.reload();

    await expectSetting(page, 'Calibration numbers', true);
  });
});

for (const viewport of [
  { name: 'desktop', size: { width: 1280, height: 800 } },
  { name: 'phone', size: { width: 390, height: 844 } },
] as const) {
  test.describe(`Settings mid-run on a ${viewport.name}`, () => {
    test.use({ viewport: viewport.size });

    test('opens Settings while counting without moving the camera or the main button, and the countdown carries on', async ({
      page,
    }) => {
      await page.clock.install();
      const backend = await MockBackend.attach(page);
      const guided = guidedPage(page);
      const settings = settingsPanel(page);
      await startRun(page, backend);
      await advanceRunUntil(page, backend, guided.countedTimer);
      const before = await rectsOf(page);
      const left = await timerSeconds(guided.countedTimer);

      await openSettings(page);

      expectStill(before, await rectsOf(page));
      await settings.chime.click();
      await expect(settings.chime).not.toBeChecked();
      await advanceRun(page, backend, 5000, 1000);
      await expect(settings.dialog).toBeVisible();
      expectStill(before, await rectsOf(page));
      await closeSettings(page);

      expect(await timerSeconds(guided.countedTimer), 'the countdown after 5 s with Settings open').toBeLessThanOrEqual(
        left - 4,
      );
      await expect(guided.stop).toBeVisible();
    });
  });
}
