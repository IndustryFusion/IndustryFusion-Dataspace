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

import { enterAdminMode, open, register, rowOf, STAND_INS } from './helpers.js';

const OWNER = 'urn:ui-browser:policy-owner';
const BUILDER = 'urn:ui-browser:policy-builder';

test.skip(STAND_INS, 'Only against a deployment, with real adapters');

test('a real pair: approve, deny and reset through the Policies screen', async ({ page }) => {
  await open(page, 'Participants');
  await enterAdminMode(page);
  await register(page, OWNER, 'factory_owner');
  await register(page, BUILDER, 'machine_builder');

  // The tab keeps admin mode, as the secret stays in memory while the page is open.
  await page.getByRole('tab', { name: 'Policies' }).click();
  await page.getByLabel('Factory owner').selectOption(OWNER);
  await page.getByLabel('Machine builder').selectOption(BUILDER);
  await page.getByRole('button', { name: 'Show' }).click();
  const row = rowOf(page, 'Machine history');
  await expect(row).toContainText('on-request');
  await row.getByRole('button', { name: 'Approve' }).click();
  await expect(row.getByRole('cell').nth(4)).toHaveText('approved');
  await row.getByRole('button', { name: 'Deny' }).click();
  await expect(row.getByRole('cell').nth(4)).toHaveText('denied');
  await row.getByRole('button', { name: 'Reset' }).click();
  await expect(row.getByRole('cell').nth(4)).toHaveText('on-request');

  await page.getByRole('tab', { name: 'Participants' }).click();
  page.on('dialog', (dialog) => dialog.accept());
  for (const id of [OWNER, BUILDER]) {
    await rowOf(page, id).getByRole('button', { name: 'Delete' }).click();
    await expect(page.getByRole('cell', { name: id, exact: true })).toHaveCount(0, { timeout: 120000 });
  }
});
