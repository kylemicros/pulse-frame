import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import {
  cspViolations,
  FRONTEND_ROOT,
  recordCspViolations,
  startBuiltPreview,
  type BuiltPreview,
} from './support/built-preview';
import { guidedPage } from './support/guided-page';
import { MockBackend } from './support/mock-backend';
import { collectPageErrors } from './support/page-helpers';
import {
  DARK_MEDIA,
  JUNK_THEME,
  LIGHT_MEDIA,
  openSettings,
  saveTheme,
  settingsPanel,
  THEME_KEY,
  themeMetas,
  type ThemeMetas,
} from './support/settings';

const DEV_APP_MODULE = '**/src/main.tsx';
const BUILT_SCRIPTS = '**/assets/*.js';
const PUBLIC_DIR = join(FRONTEND_ROOT, 'public');

type FirstPaint = { classes: string[]; colorScheme: string; background: string; metas: ThemeMetas };

type HeadOrder = {
  boot: number;
  lastThemeMeta: number;
  firstStylesheet: number;
  firstModule: number;
  bootType: string | null;
  bootAsync: boolean;
  bootDefer: boolean;
  bootPath: string;
  bootOrigin: string;
  pageOrigin: string;
  plainScripts: number;
  inlineScripts: number;
};

function publicScripts(): string[] {
  return readdirSync(PUBLIC_DIR).filter((name) => /\.(m?js|cjs)$/.test(name));
}

async function firstPaint(page: Page): Promise<FirstPaint> {
  const look = await page.evaluate(() => ({
    classes: Array.from(document.documentElement.classList).filter((name) => name === 'light' || name === 'dark'),
    colorScheme: getComputedStyle(document.documentElement).colorScheme,
    background: getComputedStyle(document.body).backgroundColor,
  }));
  return { ...look, metas: await themeMetas(page) };
}

async function openWithoutApp(page: Page, address: string, blocked: string): Promise<void> {
  await page.route(blocked, (route) => route.abort());
  await page.goto(address);
  await expect(page.locator('#root')).toBeAttached();
}

test.describe('the theme boot script file', () => {
  test('is the one script in frontend/public, plain JavaScript, loaded by index.html with a plain script tag', () => {
    const scripts = publicScripts();
    expect(scripts, 'scripts in frontend/public').toHaveLength(1);
    const [boot] = scripts;
    expect(boot).toMatch(/\.js$/);
    const source = readFileSync(join(PUBLIC_DIR, boot), 'utf8');
    expect(source, 'the boot script imports or exports').not.toMatch(/^\s*(import|export)\b/m);
    const html = readFileSync(join(FRONTEND_ROOT, 'index.html'), 'utf8');
    const tags = Array.from(html.matchAll(/<script\b([^>]*)>/gi), (match) => match[1]);
    const bootTags = tags.filter((attributes) => attributes.includes(`src="/${boot}"`));
    expect(bootTags, `script tags for /${boot} in index.html`).toHaveLength(1);
    expect(bootTags[0], 'the boot script tag').not.toMatch(/\b(type|async|defer)\b/);
    const head = html.slice(0, html.indexOf('</head>'));
    expect(head, 'the boot script sits in the head').toContain(`src="/${boot}"`);
    expect(head.indexOf(`src="/${boot}"`), 'the boot script after the theme colour metas').toBeGreaterThan(
      head.lastIndexOf('name="theme-color"'),
    );
  });
});

test.describe('the theme before the app module runs', () => {
  test('applies a saved Dark choice and its browser colour under a light system', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await saveTheme(page, 'dark');

    await openWithoutApp(page, '/', DEV_APP_MODULE);

    const shown = await firstPaint(page);
    expect(shown.classes).toEqual(['dark']);
    expect(shown.metas).toEqual({ light: 'not all', dark: 'all' });
  });

  test('applies a saved Light choice and its browser colour under a dark system', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });
    await saveTheme(page, 'light');

    await openWithoutApp(page, '/', DEV_APP_MODULE);

    const shown = await firstPaint(page);
    expect(shown.classes).toEqual(['light']);
    expect(shown.metas).toEqual({ light: 'all', dark: 'not all' });
  });

  test('leaves the page on the system theme when nothing is saved', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'dark' });

    await openWithoutApp(page, '/', DEV_APP_MODULE);

    const shown = await firstPaint(page);
    expect(shown.classes).toEqual([]);
    expect(shown.metas).toEqual({ light: LIGHT_MEDIA, dark: DARK_MEDIA });
  });

  test('leaves the page on the system theme and the stored value as it is for an unknown saved theme', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await saveTheme(page, JUNK_THEME);

    await openWithoutApp(page, '/', DEV_APP_MODULE);

    const shown = await firstPaint(page);
    expect(shown.classes).toEqual([]);
    expect(shown.metas).toEqual({ light: LIGHT_MEDIA, dark: DARK_MEDIA });
    expect(await page.evaluate((key) => localStorage.getItem(key), THEME_KEY)).toBe(JUNK_THEME);
  });

  test('opens the page with no script error when the browser refuses storage', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.addInitScript(() => {
      Object.defineProperty(globalThis, 'localStorage', {
        configurable: true,
        get: () => {
          throw new DOMException('Storage refused by the test', 'SecurityError');
        },
      });
    });
    await MockBackend.attach(page);

    await page.goto('/');

    await expect(guidedPage(page).stepList).toBeVisible();
    expect((await firstPaint(page)).classes).toEqual([]);
    expect(errors, 'script errors on the page').toEqual([]);
  });
});

test.describe('the theme boot script in the built page', () => {
  test.describe.configure({ mode: 'default' });

  let site: BuiltPreview | null = null;

  test.beforeAll(async () => {
    site = await startBuiltPreview();
  });

  test.afterAll(async () => {
    await site?.close();
  });

  function builtUrl(): string {
    const url = site?.url ?? '';
    expect(url).not.toBe('');
    return url;
  }

  test('loads the boot script as a plain blocking script in the head, after the theme colour metas and before the stylesheet and the app module', async ({
    page,
  }) => {
    await MockBackend.attach(page);
    const [boot] = publicScripts();
    expect(boot, 'a boot script in frontend/public').toBeDefined();

    await page.goto(builtUrl());

    const order = await page.evaluate((path): HeadOrder => {
      const children = Array.from(document.head.children);
      const indexOf = (match: (element: Element) => boolean): number => children.findIndex(match);
      const lastIndexOf = (match: (element: Element) => boolean): number => children.findLastIndex(match);
      const isBoot = (element: Element): boolean =>
        element instanceof HTMLScriptElement && element.src !== '' && new URL(element.src).pathname === path;
      const bootElement = children.find(isBoot) as HTMLScriptElement | undefined;
      const scripts = Array.from(document.querySelectorAll('script'));
      return {
        boot: indexOf(isBoot),
        lastThemeMeta: lastIndexOf((element) => element.matches('meta[name="theme-color"]')),
        firstStylesheet: indexOf((element) => element.matches('link[rel="stylesheet"]')),
        firstModule: indexOf((element) => element.matches('script[type="module"]')),
        bootType: bootElement?.getAttribute('type') ?? null,
        bootAsync: bootElement?.async ?? true,
        bootDefer: bootElement?.defer ?? true,
        bootPath: bootElement === undefined ? '' : new URL(bootElement.src).pathname,
        bootOrigin: bootElement === undefined ? '' : new URL(bootElement.src).origin,
        pageOrigin: location.origin,
        plainScripts: scripts.filter((script) => script.type === '' || script.type === 'text/javascript').length,
        inlineScripts: scripts.filter((script) => script.src === '').length,
      };
    }, `/${boot}`);

    expect(order.boot, 'the boot script in the head').toBeGreaterThanOrEqual(0);
    expect(order.bootPath).toBe(`/${boot}`);
    expect(order.bootOrigin, 'the boot script origin').toBe(order.pageOrigin);
    expect(order.bootType, 'the boot script type').toBeNull();
    expect(order.bootAsync, 'the boot script is async').toBe(false);
    expect(order.bootDefer, 'the boot script is deferred').toBe(false);
    expect(order.boot, 'the boot script after the theme colour metas').toBeGreaterThan(order.lastThemeMeta);
    expect(order.firstStylesheet, 'a stylesheet in the head').toBeGreaterThanOrEqual(0);
    expect(order.boot, 'the boot script before the stylesheet').toBeLessThan(order.firstStylesheet);
    expect(order.boot, 'the boot script before the app module').toBeLessThan(order.firstModule);
    expect(order.plainScripts, 'plain scripts on the page').toBe(1);
    expect(order.inlineScripts, 'inline scripts on the page').toBe(0);
  });

  test('paints the first frame dark for a saved Dark choice under a light system, before the app module runs', async ({
    page,
  }) => {
    await page.route(BUILT_SCRIPTS, (route) => route.abort());
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.goto(builtUrl());
    const darkSystem = await firstPaint(page);
    await page.emulateMedia({ colorScheme: 'light' });
    await page.reload();
    const lightSystem = await firstPaint(page);
    expect(lightSystem.background, 'the light and dark first frames differ').not.toBe(darkSystem.background);

    await page.evaluate((key) => localStorage.setItem(key, 'dark'), THEME_KEY);
    await page.reload();

    const shown = await firstPaint(page);
    expect(shown.classes).toEqual(['dark']);
    expect(shown.colorScheme).toBe('dark');
    expect(shown.background, 'the first frame background').toBe(darkSystem.background);
    expect(shown.metas).toEqual({ light: 'not all', dark: 'all' });
  });

  test('runs the boot script under the content security policy with no violation, and the app keeps the saved Dark', async ({
    page,
  }) => {
    const errors = collectPageErrors(page);
    await recordCspViolations(page);
    await page.emulateMedia({ colorScheme: 'light' });
    await saveTheme(page, 'dark');
    await MockBackend.attach(page);
    const [boot] = publicScripts();
    expect(boot, 'a boot script in frontend/public').toBeDefined();
    const served: number[] = [];
    page.on('response', (response) => {
      if (new URL(response.url()).pathname === `/${boot}`) {
        served.push(response.status());
      }
    });

    await page.goto(builtUrl());

    await expect(guidedPage(page).stepList).toBeVisible();
    expect(served, 'the boot script responses').toEqual([200]);
    expect((await firstPaint(page)).classes).toEqual(['dark']);
    await openSettings(page);
    await expect(settingsPanel(page).themeChoice('Dark')).toBeChecked();
    expect(await cspViolations(page)).toEqual([]);
    expect(errors).toEqual([]);
  });
});
