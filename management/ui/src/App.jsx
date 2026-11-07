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

import React, { useState } from 'react';

import { AdminBar, AdminProvider } from './admin.jsx';
import Health from './screens/Health.jsx';
import Participants from './screens/Participants.jsx';
import Policies from './screens/Policies.jsx';

const SCREENS = { Health, Participants, Policies };

export default function App() {
  const [screen, setScreen] = useState('Health');
  const Screen = SCREENS[screen];
  return (
    <AdminProvider>
      <header>
        <h1>Dataspace Management</h1>
        <AdminBar />
      </header>
      <nav role="tablist">
        {Object.keys(SCREENS).map((name) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={name === screen}
            onClick={() => setScreen(name)}
          >
            {name}
          </button>
        ))}
      </nav>
      <main>
        <Screen />
      </main>
    </AdminProvider>
  );
}
