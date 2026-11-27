import { readdirSync, readFileSync } from 'node:fs';
import { extname, join } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { cspViolations, recordCspViolations } from './support/built-preview';
import { parsePolicy, sortedPolicy } from './support/csp-policy';
import { boxOf, collectPageErrors } from './support/page-helpers';
import {
  headersForAllPaths,
  REPO_URL,
  SHOWCASE_HEADERS,
  SHOWCASE_POLICY,
  SHOWCASE_ROOT,
  startShowcaseServer,
  type ShowcaseServer,
} from './support/showcase-server';

const TITLE = 'pulse frame: a webcam heart rate monitor';
const HEADLINE = 'Sit still. Your face does the rest.';
const COMING_SOON_LINE = 'Coming soon Live readings right in your browser.';
const PRIVACY_FINE_LINE =
  'This page has no sign-up and no analytics, and sets no cookies of its own. Like any website, its host, Cloudflare, sees basic visit details such as your internet address.';
const LEAD =
  'pulse frame is a heart rate monitor that runs on your webcam. No watch, no strap, no finger clip. Just you, a camera and about three minutes.';
const PICTURE_ALT = 'Picture of the pulse frame app after a run, showing a heart rate and two variation numbers.';
const CAPTION = 'pulse frame after a finished run. The numbers in the picture are a sample.';
const DISCLAIMER = 'For wellness and curiosity only. pulse frame is not a medical device, and its numbers are estimates.';
const COPYRIGHT = '© 2026 kylemicros. MIT licence.';
const COMING_SOON_HEADING = 'Live in your browser: coming soon';

const STEPS = [
  ['Sit in front of the camera.', 'Face a window or a lamp so the light on your face is even.'],
  [
    'It watches your skin.',
    "Each heartbeat sends a little more blood to your face, and your skin's colour shifts ever so slightly. Too small for you to see, not too small for a camera.",
  ],
  [
    'It counts the beats.',
    'Those tiny shifts become a pulse wave, and pulse frame counts the beats over a minute and a half of sitting still.',
  ],
  ['You get your numbers.', 'Heart rate and two variation numbers, no wearable needed.'],
];

const NUMBERS = [
  ['BPM', 'Heart rate', 'Beats per minute over the last counted minute, with a likely range around it.'],
  ['ms', 'Beat to beat variation', 'How much the gap between your beats shifts from one beat to the next.'],
  ['ms', 'Overall rhythm variation', 'How much the gaps between your beats spread out over a minute.'],
];

const PRIVACY = [
  ['On the laptop', 'The video stays on that computer. No video is saved, and none is sent anywhere.'],
  ['In your browser, soon', 'Your face never leaves your device. Your phone or laptop does all the work, right there.'],
];

const SECTION_HEADINGS = ['How it works', 'What you get', 'Your face stays yours', COMING_SOON_HEADING];

const THEMES = {
  light: { background: 'rgb(247, 247, 245)', text: 'rgb(26, 26, 26)' },
  dark: { background: 'rgb(20, 20, 20)', text: 'rgb(245, 245, 245)' },
} as const;

let site: ShowcaseServer | null = null;

test.beforeAll(async () => {
  site = await startShowcaseServer();
});

test.afterAll(async () => {
  await site?.close();
});

function siteUrl(): string {
  const url = site?.url ?? '';
  expect(url, 'the showcase test server did not start').not.toBe('');
  return url;
}

async function openShowcase(page: Page) {
  const response = await page.goto(siteUrl());
  expect(response?.status(), 'the showcase page did not load from showcase/index.html').toBe(200);
  return response;
}

function exactText(page: Page, text: string) {
  return page.getByText(text, { exact: true });
}

function sortedPermissions(policy: string): string[] {
  return policy
    .split(',')
    .map((feature) => feature.replaceAll(/\s+/g, ''))
    .filter((feature) => feature !== '')
    .toSorted();
}

function extraHeaders(headers: Record<string, string>) {
  return {
    'x-content-type-options': headers['x-content-type-options'],
    'referrer-policy': headers['referrer-policy'],
    'permissions-policy': sortedPermissions(headers['permissions-policy'] ?? ''),
  };
}

const EXPECTED_EXTRA_HEADERS = {
  ...SHOWCASE_HEADERS,
  'permissions-policy': sortedPermissions(SHOWCASE_HEADERS['permissions-policy']),
};

async function scrollToFooterWithImagesLoaded(page: Page) {
  const footer = page.getByRole('contentinfo');
  await footer.scrollIntoViewIfNeeded();
  await expect(footer.getByText(COPYRIGHT, { exact: true })).toBeInViewport();
  await expect
    .poll(() => page.evaluate(() => [...document.images].every((image) => image.complete && image.naturalWidth > 0)))
    .toBe(true);
}

async function effectiveColours(page: Page) {
  return page.evaluate(() => {
    const bodyBackground = getComputedStyle(document.body).backgroundColor;
    const background = ['transparent', 'rgba(0, 0, 0, 0)'].includes(bodyBackground)
      ? getComputedStyle(document.documentElement).backgroundColor
      : bodyBackground;
    const heading = document.querySelector('h1');
    return { background, text: heading ? getComputedStyle(heading).color : '' };
  });
}

test.describe('showcase folder', () => {
  test('ships only the page, its stylesheet, its pictures and the headers file, with no script', () => {
    const files = readdirSync(SHOWCASE_ROOT, { recursive: true, withFileTypes: true })
      .filter((entry) => entry.isFile())
      .map((entry) => join(entry.parentPath, entry.name).slice(SHOWCASE_ROOT.length + 1));

    expect(files).toContain('index.html');
    expect(files).toContain('_headers');
    expect(files.filter((file) => extname(file) === '.css').length).toBeGreaterThan(0);
    expect(files.filter((file) => extname(file) === '.svg').length).toBeGreaterThan(0);
    expect(files.filter((file) => extname(file) === '.png').length).toBeGreaterThan(0);
    expect(files.filter((file) => file !== '_headers' && !['.html', '.css', '.svg', '.png'].includes(extname(file)))).toEqual([]);
  });

  test('declares the approved content security policy and the safety headers for every path in _headers', () => {
    const headers = headersForAllPaths();
    const policy = headers['content-security-policy'] ?? '';

    expect(policy).not.toBe('');
    expect(parsePolicy(policy)).toEqual(sortedPolicy(SHOWCASE_POLICY));
    expect(extraHeaders(headers)).toEqual(EXPECTED_EXTRA_HEADERS);
  });

  test('references nothing outside the showcase folder', () => {
    const sources = readdirSync(SHOWCASE_ROOT)
      .filter((file) => ['.html', '.css'].includes(extname(file)))
      .map((file) => readFileSync(join(SHOWCASE_ROOT, file), 'utf8'));

    expect(sources.length).toBeGreaterThan(1);
    for (const source of sources) {
      expect(source).not.toContain('../');
      expect(source).not.toMatch(/frontend\//);
    }
  });
});

test.describe('showcase wording', () => {
  test('shows the approved tab title, header button and hero lines', async ({ page }) => {
    await openShowcase(page);
    const banner = page.getByRole('banner');
    const main = page.getByRole('main');

    await expect(page).toHaveTitle(TITLE);
    await expect(banner.getByRole('link', { name: 'pulse frame', exact: true })).toBeVisible();
    await expect(banner.getByRole('link', { name: 'Star on GitHub', exact: true })).toBeVisible();
    await expect(main.getByText(COMING_SOON_LINE, { exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { level: 1, name: HEADLINE, exact: true })).toBeVisible();
    await expect(exactText(page, LEAD)).toBeVisible();
    await expect(main.getByRole('link', { name: 'Star it on GitHub', exact: true })).toHaveCount(2);
    await expect(main.getByRole('link', { name: 'What can I do now?', exact: true })).toBeVisible();
    await expect(page.getByText('Screenshot slot')).toHaveCount(0);
  });

  test('shows the sample picture with the approved text alternative and caption', async ({ page }) => {
    await openShowcase(page);
    const figure = page.getByRole('figure', { name: CAPTION, exact: true });
    const picture = figure.getByRole('img', { name: PICTURE_ALT, exact: true });

    await expect(figure).toBeVisible();
    await expect(picture).toBeVisible();
    await expect(exactText(page, CAPTION)).toBeVisible();
    await expect
      .poll(() => picture.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0))
      .toBe(true);
    expect(await picture.evaluate((image: HTMLImageElement) => new URL(image.currentSrc).pathname)).toMatch(/\.png$/);
  });

  test('shows the section headings in the approved order', async ({ page }) => {
    await openShowcase(page);

    await expect(page.getByRole('heading', { level: 2 })).toHaveText(SECTION_HEADINGS);
  });

  test('shows the four how it works steps in order, word for word', async ({ page }) => {
    await openShowcase(page);
    const steps = page.getByRole('list').filter({ hasText: STEPS[0][0] }).getByRole('listitem');

    await expect(steps).toHaveCount(4);
    for (const [index, [title, body]] of STEPS.entries()) {
      await expect(steps.nth(index).getByText(title, { exact: true })).toBeVisible();
      await expect(steps.nth(index).getByText(body, { exact: true })).toBeVisible();
    }
  });

  test('shows the three numbers you get, their units, the note under them and the disclaimer', async ({ page }) => {
    await openShowcase(page);
    const main = page.getByRole('main');

    for (const [unit, title, body] of NUMBERS) {
      await expect(exactText(page, title)).toBeVisible();
      await expect(exactText(page, body)).toBeVisible();
      await expect(main.getByText(unit, { exact: true }).first()).toBeVisible();
    }
    await expect(main.getByText('ms', { exact: true })).toHaveCount(2);
    await expect(
      exactText(page, 'Both variation numbers are in ms (thousandths of a second). Compare them only with your own runs.'),
    ).toBeVisible();
    await expect(main.getByText(DISCLAIMER, { exact: true })).toHaveCount(1);
  });

  test('states the privacy promise in plain words', async ({ page }) => {
    await openShowcase(page);

    await expect(page.getByRole('heading', { level: 2, name: 'Your face stays yours', exact: true })).toBeVisible();
    for (const [title, body] of PRIVACY) {
      await expect(exactText(page, title)).toBeVisible();
      await expect(exactText(page, body)).toBeVisible();
    }
    await expect(exactText(page, PRIVACY_FINE_LINE)).toBeVisible();
  });

  test('shows the coming soon card with what you can do now and its GitHub button', async ({ page }) => {
    await openShowcase(page);
    const card = page.getByRole('region', { name: COMING_SOON_HEADING, exact: true });

    await expect(card).toBeVisible();
    await expect(card.getByRole('heading', { level: 2, name: COMING_SOON_HEADING, exact: true })).toBeVisible();
    await expect(
      card.getByText(
        'Right now pulse frame runs live on one laptop. Next up, it runs right here in your browser, camera and all, with nothing sent anywhere.',
        { exact: true },
      ),
    ).toBeVisible();
    await expect(card.getByText('What you can do now', { exact: true })).toBeVisible();
    await expect(card.getByRole('listitem')).toHaveText([
      'Catch the live demo.',
      'Star the repo on GitHub to keep tabs on it.',
    ]);
    await expect(card.getByRole('link', { name: 'Star it on GitHub', exact: true })).toBeVisible();
  });

  test('shows the disclaimer and the licence line in the footer', async ({ page }) => {
    await openShowcase(page);
    const footer = page.getByRole('contentinfo');

    await expect(footer.getByText(DISCLAIMER, { exact: true })).toBeVisible();
    await expect(footer.getByText(COPYRIGHT, { exact: true })).toBeVisible();
    await expect(page.getByText(DISCLAIMER, { exact: true })).toHaveCount(2);
  });
});

test.describe('showcase links', () => {
  test('points every GitHub button at the pulse frame repo on github.com', async ({ page }) => {
    await openShowcase(page);
    const githubLinks = page.getByRole('link', { name: /GitHub/ });

    await expect(githubLinks).toHaveCount(3);
    for (const link of await githubLinks.all()) {
      await expect(link).toHaveAttribute('href', REPO_URL);
    }
    expect(new URL(REPO_URL).host).toBe('github.com');
  });

  test('links only to this page or the repo', async ({ page }) => {
    await openShowcase(page);
    const origin = site?.origin ?? '';
    const hrefs = await page.getByRole('link').evaluateAll((links) =>
      links.map((link) => ({ raw: link.getAttribute('href') ?? '', resolved: (link as HTMLAnchorElement).href })),
    );

    expect(hrefs.length).toBeGreaterThan(0);
    expect(
      hrefs.filter(({ raw, resolved }) => raw !== REPO_URL && !raw.startsWith('#') && new URL(resolved).origin !== origin),
    ).toEqual([]);
  });

  test('jumps to the coming soon card from the What can I do now? button', async ({ page }) => {
    await openShowcase(page);
    const jump = page.getByRole('main').getByRole('link', { name: 'What can I do now?', exact: true });
    const heading = page.getByRole('heading', { level: 2, name: COMING_SOON_HEADING, exact: true });

    await expect(heading).not.toBeInViewport();
    await jump.click();

    await expect(page).toHaveURL(/#[^#]+$/);
    await expect(page.locator(':target').getByRole('heading', { name: COMING_SOON_HEADING, exact: true })).toHaveCount(1);
    await expect(heading).toBeInViewport();
  });
});

test.describe('showcase safety', () => {
  test('has no script, no inline style and no inline event handler', async ({ page }) => {
    await openShowcase(page);

    const found = await page.evaluate(() => {
      const elements = [...document.querySelectorAll('*')];
      return {
        scripts: document.querySelectorAll('script, noscript').length,
        httpEquivMeta: document.querySelectorAll('meta[http-equiv]').length,
        styleElements: document.querySelectorAll('style').length,
        styleAttributes: document.querySelectorAll('[style]').length,
        handlers: elements.flatMap((element) =>
          element.getAttributeNames().filter((name) => name.toLowerCase().startsWith('on')).map((name) => `${element.tagName} ${name}`),
        ),
        scriptUrls: elements.flatMap((element) =>
          element
            .getAttributeNames()
            .filter((name) => /^\s*javascript:/i.test(element.getAttribute(name) ?? ''))
            .map((name) => `${element.tagName} ${name}`),
        ),
      };
    });

    expect(found).toEqual({
      scripts: 0,
      httpEquivMeta: 0,
      styleElements: 0,
      styleAttributes: 0,
      handlers: [],
      scriptUrls: [],
    });
  });

  for (const scheme of ['light', 'dark'] as const) {
    test(`loads in ${scheme} with the approved headers, no policy violation and no console error`, async ({ page }) => {
      const errors = collectPageErrors(page);
      await recordCspViolations(page);
      await page.emulateMedia({ colorScheme: scheme });

      const response = await openShowcase(page);
      await scrollToFooterWithImagesLoaded(page);

      const served = response?.headers() ?? {};
      expect(parsePolicy(served['content-security-policy'] ?? '')).toEqual(sortedPolicy(SHOWCASE_POLICY));
      expect(extraHeaders(served)).toEqual(EXPECTED_EXTRA_HEADERS);
      expect(await cspViolations(page)).toEqual([]);
      expect(errors).toEqual([]);
    });

    test(`requests nothing beyond its own files on 127.0.0.1 in ${scheme}`, async ({ page }) => {
      const requests: string[] = [];
      const blocked: string[] = [];
      page.on('request', (request) => requests.push(request.url()));
      await page.route(
        (url) => url.origin !== (site?.origin ?? ''),
        (route) => {
          blocked.push(route.request().url());
          return route.abort('blockedbyclient');
        },
      );
      await page.emulateMedia({ colorScheme: scheme });

      await openShowcase(page);
      await scrollToFooterWithImagesLoaded(page);

      expect(requests.length).toBeGreaterThan(2);
      expect(blocked).toEqual([]);
      expect(requests.filter((url) => new URL(url).hostname !== '127.0.0.1')).toEqual([]);
    });
  }
});

test.describe('showcase theme', () => {
  for (const scheme of ['light', 'dark'] as const) {
    test(`follows the system ${scheme} setting with the approved colours`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await openShowcase(page);

      await expect.poll(() => effectiveColours(page)).toEqual(THEMES[scheme]);
    });
  }

  test('switches theme when the system setting changes, with no theme control on the page', async ({ page }) => {
    await page.emulateMedia({ colorScheme: 'light' });
    await openShowcase(page);
    await expect.poll(() => effectiveColours(page)).toEqual(THEMES.light);

    await page.emulateMedia({ colorScheme: 'dark' });

    await expect.poll(() => effectiveColours(page)).toEqual(THEMES.dark);
    await expect(page.getByRole('button')).toHaveCount(0);
  });
});

test.describe('showcase on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('fits the coming soon line, headline, lead and both hero buttons in the first screen', async ({ page }) => {
    await openShowcase(page);
    const main = page.getByRole('main');

    await expect(main.getByText(COMING_SOON_LINE, { exact: true })).toBeInViewport({ ratio: 1 });
    await expect(page.getByRole('heading', { level: 1, name: HEADLINE, exact: true })).toBeInViewport({ ratio: 1 });
    await expect(exactText(page, LEAD)).toBeInViewport({ ratio: 1 });
    await expect(main.getByRole('link', { name: 'Star it on GitHub', exact: true }).first()).toBeInViewport({ ratio: 1 });
    await expect(main.getByRole('link', { name: 'What can I do now?', exact: true })).toBeInViewport({ ratio: 1 });
  });

  test('puts the picture after the hero buttons', async ({ page }) => {
    await openShowcase(page);
    const buttons = await boxOf(page.getByRole('main').getByRole('link', { name: 'What can I do now?', exact: true }));
    const figure = await boxOf(page.getByRole('figure', { name: CAPTION, exact: true }));

    expect(figure.y).toBeGreaterThanOrEqual(buttons.y + buttons.height);
  });
});

test.describe('showcase on a desktop', () => {
  test.use({ viewport: { width: 1280, height: 800 } });

  test('puts the words on the left and the picture on the right', async ({ page }) => {
    await openShowcase(page);
    const headline = page.getByRole('heading', { level: 1, name: HEADLINE, exact: true });
    const figure = page.getByRole('figure', { name: CAPTION, exact: true });

    await expect(headline).toBeInViewport();
    await expect(figure).toBeInViewport();
    const left = await boxOf(headline);
    const right = await boxOf(figure);
    expect(left.x + left.width).toBeLessThanOrEqual(right.x);
    expect(right.y).toBeLessThan(left.y + left.height);
    expect(right.y + right.height).toBeGreaterThan(left.y);
  });
});

test.describe('showcase at 320 pixels wide', () => {
  test.use({ viewport: { width: 320, height: 640 } });

  test('has no horizontal scroll', async ({ page }) => {
    await openShowcase(page);
    await expect(page.getByRole('heading', { level: 1, name: HEADLINE, exact: true })).toBeVisible();

    const widths = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    expect(widths.scroll).toBeLessThanOrEqual(widths.client);
  });
});

test.describe('showcase accessibility basics', () => {
  test('has one h1, one banner, main and footer landmark, and headings in order', async ({ page }) => {
    await openShowcase(page);

    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1);
    await expect(page.getByRole('heading', { level: 1 })).toHaveAccessibleName(HEADLINE);
    await expect(page.getByRole('banner')).toHaveCount(1);
    await expect(page.getByRole('main')).toHaveCount(1);
    await expect(page.getByRole('contentinfo')).toHaveCount(1);
    const levels = await page.evaluate(() =>
      [...document.querySelectorAll('h1, h2, h3, h4, h5, h6')].map((heading) => Number(heading.tagName.slice(1))),
    );
    expect(levels[0]).toBe(1);
    expect(levels.filter((level, index) => index > 0 && level > levels[index - 1] + 1)).toEqual([]);
  });

  test('gives every link and every picture a name or marks it decorative', async ({ page }) => {
    await openShowcase(page);
    const links = page.getByRole('link');

    expect(await links.count()).toBeGreaterThan(0);
    for (const link of await links.all()) {
      await expect(link).toHaveAccessibleName(/\S/);
    }
    const unnamed = await page.evaluate(() => [
      ...[...document.querySelectorAll('img:not([alt])')].map((image) => `img ${image.getAttribute('src')}`),
      ...[...document.querySelectorAll('svg')]
        .filter((svg) => svg.closest('[aria-hidden="true"]') === null && !svg.getAttribute('aria-label') && !svg.querySelector('title'))
        .map(() => 'svg without a name or aria-hidden'),
    ]);
    expect(unnamed).toEqual([]);
  });
});
