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

import { defineConfig } from '@playwright/test';

// By default the tests run against the real API code, with in-memory stand-ins behind it.
// Set UI_BASE_URL to run against a deployment instead.
const external = process.env.UI_BASE_URL;
const port = process.env.UI_TEST_PORT || '3123';
const python = process.env.UI_TEST_PYTHON || 'python3';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  timeout: Number(process.env.UI_TEST_TIMEOUT || 30000),
  use: { baseURL: external || `http://127.0.0.1:${port}` },
  webServer: external
    ? undefined
    : {
        command: `${python} ../api/tests/ui_test_server.py ${port} dist`,
        url: `http://127.0.0.1:${port}/health`,
        reuseExistingServer: false,
      },
});
