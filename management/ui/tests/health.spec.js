/*
 * Copyright (c) 2026 IndustryFusion Foundation
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

import { expect, test } from '@playwright/test';

import { open, reset, STAND_INS } from './helpers.js';

test.beforeEach(async ({ request }) => reset(request));

test('shows each component without signing in', async ({ page }) => {
  await open(page, 'Health');
  for (const name of ['registry', 'gateway', 'dsp-gateway', 'keycloak', 'postgresql', 'storage']) {
    await expect(page.getByRole('cell', { name, exact: true })).toBeVisible();
  }
  await expect(page.getByRole('button', { name: 'Admin mode' })).toBeVisible();
});

test('refreshes every 15 seconds and shows a component going down', async ({ page, request }) => {
  test.skip(!STAND_INS, 'Needs a component to go down');
  await page.clock.install();
  let calls = 0;
  page.on('request', (sent) => {
    if (sent.url().endsWith('/api/health')) calls += 1;
  });
  await open(page, 'Health');
  await expect(page.getByText('Overall:').locator('.badge')).toHaveText('ok');
  const before = calls;

  await request.post('/test/registry-down');
  await page.clock.runFor(14000);
  expect(calls).toBe(before);
  await page.clock.runFor(1500);
  await expect(page.getByText('Overall:').locator('.badge')).toHaveText('degraded');
  await expect(page.getByRole('row').filter({ hasText: 'registry' })).toContainText('It could not be reached');
  expect(calls).toBe(before + 1);
});

test('shows an error if the API cannot be read', async ({ page }) => {
  await page.route('**/api/health', (route) =>
    route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Health is out"}' }),
  );
  await open(page, 'Health');
  await expect(page.getByRole('alert')).toHaveText('Health is out');
});

test('stops refreshing on another screen', async ({ page }) => {
  await page.clock.install();
  await open(page, 'Health');
  await page.getByRole('tab', { name: 'Participants' }).click();
  let calls = 0;
  page.on('request', (sent) => {
    if (sent.url().endsWith('/api/health')) calls += 1;
  });
  await page.clock.runFor(31000);
  expect(calls).toBe(0);
});
