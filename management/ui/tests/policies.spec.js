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

import { enterAdminMode, open, reset, rowOf, STAND_INS } from './helpers.js';

test.skip(!STAND_INS, 'deployment.spec.js covers this against a deployment');
test.beforeEach(async ({ request }) => {
  await reset(request);
  await request.post('/test/pair');
});

async function showPair(page) {
  await page.getByLabel('Factory owner').selectOption('urn:ui:fo');
  await page.getByLabel('Machine builder').selectOption('urn:ui:mb');
  await page.getByRole('button', { name: 'Show' }).click();
}

test('a pair is shown in both directions without signing in', async ({ page }) => {
  await open(page, 'Policies');
  await showPair(page);
  await expect(rowOf(page, 'Machine history')).toContainText('on-request');
  await expect(rowOf(page, 'Vendor confidential')).toContainText('on-request');
  const history = rowOf(page, 'Machine history');
  await expect(history.getByRole('cell').first()).toHaveText('urn:ui:fo');
  await expect(rowOf(page, 'Vendor confidential').getByRole('cell').first()).toHaveText('urn:ui:mb');
});

test('only each side of its type is offered', async ({ page }) => {
  await open(page, 'Policies');
  await expect(page.getByLabel('Factory owner').getByRole('option')).toHaveText(['Choose', 'urn:ui:fo']);
  await expect(page.getByLabel('Machine builder').getByRole('option')).toHaveText(['Choose', 'urn:ui:mb']);
});

test('approve, deny and reset', async ({ page }) => {
  await open(page, 'Policies');
  await enterAdminMode(page);
  await showPair(page);
  const row = rowOf(page, 'Machine history');
  await expect(row.getByRole('button', { name: 'Reset' })).toBeDisabled();

  await row.getByRole('button', { name: 'Approve' }).click();
  await expect(row.getByRole('cell').nth(4)).toHaveText('approved');
  await expect(row.getByRole('cell').nth(5)).toHaveText('explicit');

  await row.getByRole('button', { name: 'Deny' }).click();
  await expect(row.getByRole('cell').nth(4)).toHaveText('denied');

  await row.getByRole('button', { name: 'Reset' }).click();
  await expect(row.getByRole('cell').nth(4)).toHaveText('on-request');
  await expect(row.getByRole('cell').nth(5)).toHaveText('default');
  await expect(row.getByRole('button', { name: 'Reset' })).toBeDisabled();
});

test('an external side needs admin mode, and is noted as held elsewhere', async ({ page, request }) => {
  await request.post('/test/external-builder');
  await open(page, 'Policies');
  await page.getByLabel('Factory owner').selectOption('urn:ui:fo');
  await page.getByLabel('Machine builder').selectOption('urn:ui:ext');
  await page.getByRole('button', { name: 'Show' }).click();
  await expect(page.getByRole('alert')).toHaveText('Missing token');

  await enterAdminMode(page);
  await page.getByRole('button', { name: 'Show' }).click();
  await expect(page.getByRole('note')).toContainText('urn:ui:ext');
  await expect(rowOf(page, 'Machine history')).toBeVisible();
});

test('an error from an action is shown', async ({ page, request }) => {
  await open(page, 'Policies');
  await enterAdminMode(page);
  await showPair(page);
  await rowOf(page, 'Machine history').getByRole('button', { name: 'Approve' }).click();
  await expect(rowOf(page, 'Machine history').getByRole('cell').nth(4)).toHaveText('approved');
  await request.post('/test/adapter-refuses');
  await rowOf(page, 'Machine history').getByRole('button', { name: 'Reset' }).click();
  await expect(page.getByRole('alert')).toHaveText('Request not found');
});

test('an error reading a pair is shown', async ({ page, request }) => {
  await request.post('/test/adapter-down');
  await open(page, 'Policies');
  await showPair(page);
  await expect(page.getByRole('alert')).toHaveText("The participant's adapter is unavailable");
});
