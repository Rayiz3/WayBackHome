import { test } from 'node:test';
import assert from 'node:assert/strict';
import { normalizeConnection, serverRequest, ServerError } from '../src/serverClient.ts';

const connection = { url: 'http://127.0.0.1:8787/', key: 'x'.repeat(32) };
test('USB loopback or HTTPS only; reject credentials and unexpected URL parts', () => {
  assert.equal(normalizeConnection(connection).url, 'http://127.0.0.1:8787');
  for (const url of ['http://example.com', 'http://192.168.0.3:8787', 'https://user:pass@example.com',
    'https://example.com/path', 'https://example.com/?key=secret', 'file:///tmp/server']) {
    assert.throws(() => normalizeConnection({ ...connection, url }));
  }
});
test('authenticated request carries the watch payload and returns server state', async () => {
  const result = await serverRequest(connection, '/watches/a', 'PUT', { token: 'test' }, async (url, init) => {
    assert.equal(url, 'http://127.0.0.1:8787/watches/a');
    assert.equal(init.headers.Authorization, 'Bearer ' + connection.key);
    assert.equal(init.method, 'PUT');
    assert.deepEqual(JSON.parse(init.body), { token: 'test' });
    return { ok: true, json: async () => ({ status: 'pending', worker_live: false }) };
  });
  assert.equal(result.status, 'pending');
  assert.equal(result.worker_live, false);
});
test('server rejection and connection failure never become registration success', async () => {
  await assert.rejects(serverRequest(connection, '/connection', 'GET', undefined, async () =>
    ({ ok: false, status: 401, json: async () => ({ error: 'wrong key' }) })), e => e instanceof ServerError && e.status === 401);
  await assert.rejects(serverRequest(connection, '/connection', 'GET', undefined, async () => {
    throw new Error('network');
  }), /PC 서버에 연결/);
});

