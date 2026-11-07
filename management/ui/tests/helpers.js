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

import { expect } from '@playwright/test';

export const ADMIN_SECRET = process.env.UI_ADMIN_SECRET || 'right';
export const STAND_INS = !process.env.UI_BASE_URL;

export async function open(page, screen) {
  await page.goto('/');
  await page.getByRole('tab', { name: screen }).click();
}

export async function enterAdminMode(page) {
  await page.getByRole('button', { name: 'Admin mode' }).click();
  await page.getByLabel('Client secret').fill(ADMIN_SECRET);
  await page.getByRole('button', { name: 'Enter' }).click();
  await expect(page.getByRole('button', { name: 'Leave admin mode' })).toBeVisible();
}

export async function register(page, id, type = 'factory_owner') {
  const form = page.getByRole('form', { name: 'Register a participant' });
  await form.getByLabel('Participant id').fill(id);
  await form.getByLabel('Type').selectOption(type);
  await form.getByRole('button', { name: 'Register' }).click();
  await expect(page.getByRole('cell', { name: id, exact: true })).toBeVisible({ timeout: 300000 });
}

export async function reset(request) {
  // Only the stand-ins have this. It is not a route of the API.
  if (STAND_INS) await request.post('/test/reset');
}

export const rowOf = (page, text) => page.getByRole('row').filter({ hasText: text });
