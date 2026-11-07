# Management UI

Administration screens for the dataspace, with React 18 and Vite. The management API serves the built files, as its image includes them. [management-api.md](../../management-api.md) describes the API it uses.

```bash
npm ci
npm run build                     # to dist/
MANAGEMENT_API_URL=http://localhost:3000 npm run dev   # against a running API
```

## Browser tests

The tests drive the real API code in a browser, with in-memory stand-ins for what is behind it. The server is `management/api/tests/ui_test_server.py`.

```bash
npm ci && npx playwright install chromium
pip install "../api[dev]"
npm run build
npm test
```

Set `UI_TEST_PYTHON` to the Python that has the API's packages installed.

To run them against a deployment, set `UI_BASE_URL` to its address and `UI_ADMIN_SECRET` to the `dataspace-admin-cli` secret, and raise `UI_TEST_TIMEOUT`, as a registration waits for pods. Tests that need the stand-ins are skipped.
