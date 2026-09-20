import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = fs.readFileSync(new URL('../src/notifications.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } });

function load(environment) {
  const calls = [];
  const exports = {};
  const native = {
    setNotificationHandler: () => calls.push('handler'),
    addNotificationReceivedListener: () => ({ remove: () => calls.push('remove-received') }),
    addNotificationResponseReceivedListener: () => ({ remove: () => calls.push('remove-opened') }),
    getLastNotificationResponse: () => null,
  };
  vm.runInNewContext(outputText, { exports, require(name) {
    if (name === 'expo-constants') return { __esModule: true, default: { executionEnvironment: environment }, ExecutionEnvironment: { StoreClient: 'storeClient' } };
    if (name === 'expo-device') return { isDevice: true };
    if (name === 'react-native') return { Platform: { OS: 'android' } };
    if (name === 'expo-notifications') {
      calls.push('native-import');
      if (environment === 'storeClient') throw new Error('Native module must never load in Expo Go');
      return native;
    }
    throw new Error('Unexpected import: ' + name);
  }});
  return { api: exports, calls };
}

test('Expo Go startup and notification buttons never load native push module', async () => {
  const { api, calls } = load('storeClient');
  api.listenNotifications(() => assert.fail('No notification expected'))();
  await assert.rejects(api.registerPush(), /개발 APK/);
  await assert.rejects(api.localNotification(), /개발 APK/);
  assert.deepEqual(calls, []);
});

test('development build loads native notifications once and cleans up listeners', () => {
  const { api, calls } = load('bare');
  assert.deepEqual(calls, []);
  const dispose = api.listenNotifications(() => {});
  const disposeAgain = api.listenNotifications(() => {});
  assert.deepEqual(calls, ['native-import', 'handler']);
  dispose(); disposeAgain();
  assert.equal(calls.filter(value => value.startsWith('remove-')).length, 4);
});
