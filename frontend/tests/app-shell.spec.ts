import { expect, test } from '@playwright/test';

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
