import { expect, type Locator, type Page } from '@playwright/test';

export const PRIVACY_SENTENCE = 'Your video stays on this computer. No frame is ever saved.';
export const LOCK_WORDS = 'Stays on this computer';
export const PAGE_BACKGROUND = { light: 'rgb(247, 247, 245)', dark: 'rgb(20, 20, 20)' } as const;

export const THEME_KEY = 'theme';
export const JUNK_THEME = 'purple<script>';
export const LIGHT_MEDIA = '(prefers-color-scheme: light)';
export const DARK_MEDIA = '(prefers-color-scheme: dark)';

export type ThemeMetas = { light: string | null; dark: string | null };

export function themeMetas(page: Page): Promise<ThemeMetas> {
  return page.locator('head meta[name="theme-color"]').evaluateAll((metas) => {
    const media = (content: string): string | null =>
      metas.find((meta) => meta.getAttribute('content')?.toLowerCase() === content)?.getAttribute('media') ?? null;
    return { light: media('#f7f7f5'), dark: media('#141414') };
  });
}

export function saveTheme(page: Page, value: string): Promise<void> {
  return page.addInitScript(([key, saved]) => localStorage.setItem(key, saved), [THEME_KEY, value]);
}

export type SettingName = 'Skin outline' | 'Chime' | 'Calibration numbers';
export type ThemeChoice = 'Light' | 'Dark' | 'System';

export const THEME_CHOICES: ThemeChoice[] = ['Light', 'Dark', 'System'];

export const SETTING_LINES: Record<SettingName, string> = {
  'Skin outline': 'Shows where we read your skin.',
  Chime: 'A soft ding when counting starts and ends.',
  'Calibration numbers': 'Shows or hides the Calibration box. Here because the address has ?calibrate.',
};

export type ButtonLook = {
  colour: string;
  iconColour: string;
  background: string;
  borderWidths: string[];
  borderStyles: string[];
  shadow: string;
};

export type FocusRing = { outlineStyle: string; outlineWidth: number; shadow: string };

export function settingsPanel(page: Page) {
  const dialog = page.getByRole('dialog', { name: 'Settings', exact: true });
  const theme = dialog.getByRole('radiogroup', { name: 'Theme', exact: true });
  const setting = (name: SettingName): Locator => dialog.getByRole('switch', { name: new RegExp(`^${name}(\\s|$)`) });
  return {
    gear: page.getByRole('banner').getByRole('button', { name: 'Settings', exact: true }),
    dialog,
    close: dialog.getByRole('button', { name: 'Close settings', exact: true }),
    done: dialog.getByRole('button', { name: 'Done', exact: true }),
    setting,
    skinOutline: setting('Skin outline'),
    chime: setting('Chime'),
    calibrationNumbers: setting('Calibration numbers'),
    theme,
    themeChoices: theme.getByRole('radio'),
    themeChoice: (name: ThemeChoice): Locator => theme.getByRole('radio', { name, exact: true }),
    privacy: dialog.getByText(PRIVACY_SENTENCE, { exact: true }),
  };
}

export async function openSettings(page: Page): Promise<void> {
  const settings = settingsPanel(page);
  await expect(settings.gear).toBeVisible();
  await settings.gear.click();
  await expect(settings.dialog).toBeVisible();
  await expect(settings.skinOutline).toBeFocused();
}

export async function closeSettings(page: Page): Promise<void> {
  const settings = settingsPanel(page);
  await page.keyboard.press('Escape');
  await expect(settings.dialog).toBeHidden();
}

export async function expectSetting(page: Page, name: SettingName, on: boolean): Promise<void> {
  await openSettings(page);
  const control = settingsPanel(page).setting(name);
  await (on ? expect(control).toBeChecked() : expect(control).not.toBeChecked());
  await closeSettings(page);
}

export async function setSetting(page: Page, name: SettingName, on: boolean): Promise<void> {
  await openSettings(page);
  const control = settingsPanel(page).setting(name);
  if ((await control.getAttribute('aria-checked')) !== String(on)) {
    await control.click();
  }
  await (on ? expect(control).toBeChecked() : expect(control).not.toBeChecked());
  await closeSettings(page);
}

export async function chooseTheme(page: Page, choice: ThemeChoice): Promise<void> {
  await openSettings(page);
  const radio = settingsPanel(page).themeChoice(choice);
  await radio.click();
  await expect(radio).toBeChecked();
  await closeSettings(page);
}

export function pageBackground(page: Page): Promise<string> {
  return page.evaluate(() => {
    for (let node = document.elementFromPoint(2, Math.round(innerHeight / 2)); node !== null; node = node.parentElement) {
      const colour = getComputedStyle(node).backgroundColor;
      if (colour !== 'rgba(0, 0, 0, 0)' && colour !== 'transparent') {
        return colour;
      }
    }
    return getComputedStyle(document.documentElement).backgroundColor;
  });
}

export function buttonLook(button: Locator): Promise<ButtonLook> {
  return button.evaluate((element) => {
    const style = getComputedStyle(element);
    const icon = element.querySelector('svg');
    const sides = ['Top', 'Right', 'Bottom', 'Left'] as const;
    return {
      colour: style.color,
      iconColour: icon === null ? style.color : getComputedStyle(icon).color,
      background: style.backgroundColor,
      borderWidths: sides.map((side) => style.getPropertyValue(`border-${side.toLowerCase()}-width`)),
      borderStyles: sides.map((side) => style.getPropertyValue(`border-${side.toLowerCase()}-style`)),
      shadow: style.boxShadow,
    };
  });
}

export function focusRing(control: Locator): Promise<FocusRing> {
  return control.evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      outlineStyle: style.outlineStyle,
      outlineWidth: Number.parseFloat(style.outlineWidth) || 0,
      shadow: style.boxShadow,
    };
  });
}

export function hasNoBorder(look: ButtonLook): boolean {
  return look.borderWidths.every((width, index) => width === '0px' || look.borderStyles[index] === 'none');
}

export const CLEAR = 'rgba(0, 0, 0, 0)';

export async function tabTo(page: Page, control: Locator, most = 40): Promise<void> {
  await expect(control).toBeVisible();
  for (let presses = 0; presses < most; presses += 1) {
    if (await control.evaluate((element) => element === document.activeElement)) {
      return;
    }
    await page.keyboard.press('Tab');
  }
  await expect(control, `reached by Tab within ${most} presses`).toBeFocused();
}

export function holdsFocus(scope: Locator): Promise<boolean> {
  return scope.evaluate((element) => element.contains(document.activeElement));
}

export function drawn(locator: Locator): Promise<boolean> {
  return locator.evaluateAll((elements) =>
    elements.some((element) => {
      for (let node: Element | null = element; node !== null && node.tagName !== 'LI'; node = node.parentElement) {
        const box = node.getBoundingClientRect();
        const style = getComputedStyle(node);
        if (box.width <= 2 || box.height <= 2 || style.visibility === 'hidden' || style.opacity === '0') {
          return false;
        }
      }
      return true;
    }),
  );
}

export function underAriaHidden(locator: Locator): Promise<boolean> {
  return locator.evaluate((element) => element.closest('[aria-hidden="true"]') !== null);
}

export function insideInertOrHidden(locator: Locator): Promise<boolean> {
  return locator.evaluate((element) => element.closest('[inert], [aria-hidden="true"]') !== null);
}
