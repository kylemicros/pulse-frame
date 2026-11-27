import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test } from '@playwright/test';
import { inspectSvg } from '../support/brand';
import { buildSite, type BuiltSite } from '../support/built-preview';
import { SHOWCASE_ROOT } from '../support/showcase-server';

test.describe('shipped SVG files', () => {
  let site: BuiltSite | null = null;

  test.beforeAll(async () => {
    site = await buildSite();
  });

  test.afterAll(() => {
    site?.remove();
  });

  function shippedSvgs(): string[] {
    const outDir = site?.outDir ?? '';
    expect(outDir).not.toBe('');
    return readdirSync(outDir, { recursive: true, encoding: 'utf8' })
      .filter((path) => path.toLowerCase().endsWith('.svg'))
      .toSorted();
  }

  test('the SVG check flags each unsafe construct in a planted file', async ({ page }) => {
    const planted = [
      '<svg onload="x()">',
      '<script>x()</script>',
      '<foreignObject width="1" height="1"></foreignObject>',
      '<use href="other.svg#a"/>',
      '<style>@import "a.css"; rect { fill: url(other.svg#b) }</style>',
      '</svg>',
    ].join('');

    const report = await inspectSvg(page, planted);

    expect(report.findings).toEqual([
      'an onload attribute on svg',
      'a script element',
      'a foreignObject element',
      'an external href on use: other.svg#a',
      'an @import in a style',
      'an external url() in a style: other.svg#b',
    ]);
    expect(report.viewBox).toBeNull();
  });

  test('the SVG check flags a planted doctype', async ({ page }) => {
    const report = await inspectSvg(page, '<!DOCTYPE svg [<!ENTITY tile "blue">]><svg viewBox="0 0 32 32"></svg>');

    expect(report.findings).toEqual(['a doctype svg']);
  });

  test('the SVG check flags a planted malformed file', async ({ page }) => {
    const report = await inspectSvg(page, '<svg viewBox="0 0 32 32"><g></svg>');

    expect(report.findings).toEqual(['the file does not parse as SVG']);
  });

  test('the SVG check flags every planted animation element, whatever it animates', async ({ page }) => {
    const planted = [
      '<svg viewBox="0 0 32 32"><a href="#t">',
      '<set attributeName="href" to="other.svg"/>',
      '<animate attributeName="xlink:href" values="other.svg"/>',
      '<animateMotion dur="1s" path="M0 0 L1 1"/>',
      '<animateTransform attributeName="transform" type="scale" to="2"/>',
      '</a></svg>',
    ].join('');

    const report = await inspectSvg(page, planted);

    expect(report.findings).toEqual([
      'an animation element: set',
      'an animation element: animate',
      'an animation element: animateMotion',
      'an animation element: animateTransform',
    ]);
  });

  test('ships icon.svg at the root of the built site', () => {
    expect(shippedSvgs()).toContain('icon.svg');
  });

  test('ships every SVG with no script, event attribute, foreignObject or external link', async ({ page }) => {
    const paths = shippedSvgs();
    expect(paths.length).toBeGreaterThan(0);

    for (const path of paths) {
      const report = await inspectSvg(page, readFileSync(join(site?.outDir ?? '', path), 'utf8'));

      expect(report.root, `${path} is not an SVG document`).toBe('svg');
      expect(report.findings, `unsafe content in ${path}`).toEqual([]);
      expect(report.viewBox, `${path} lost its viewBox`).not.toBeNull();
    }
  });

  test('ships every showcase SVG with no script, event attribute, foreignObject or external link', async ({ page }) => {
    const paths = readdirSync(SHOWCASE_ROOT, { recursive: true, encoding: 'utf8' })
      .filter((path) => path.toLowerCase().endsWith('.svg'))
      .toSorted();
    expect(paths.length).toBeGreaterThan(0);

    for (const path of paths) {
      const report = await inspectSvg(page, readFileSync(join(SHOWCASE_ROOT, path), 'utf8'));

      expect(report.root, `showcase/${path} is not an SVG document`).toBe('svg');
      expect(report.findings, `unsafe content in showcase/${path}`).toEqual([]);
      expect(report.viewBox, `showcase/${path} has no viewBox`).not.toBeNull();
    }
  });
});
