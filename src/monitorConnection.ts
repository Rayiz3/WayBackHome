import AsyncStorage from '@react-native-async-storage/async-storage';
import { readConnection, writeConnection } from './connectionStorage';
import { normalizeConnection, serverRequest, stopRemoteWatch } from './serverClient';
import type { Connection } from './serverClient';
const IDS = 'waybackhome.remoteIds';
const ACKS = 'waybackhome.receivedAlerts';
let serial: Promise<unknown> = Promise.resolve();
function exclusive<T>(action: () => Promise<T>): Promise<T> {
  const next = serial.then(action, action); serial = next.catch(() => {}); return next;
}
export async function loadConnection(): Promise<Connection | null> {
  const raw = await readConnection();
  return raw ? normalizeConnection(JSON.parse(raw)) : null;
}
export async function registeredIds(): Promise<string[]> {
  const raw = await AsyncStorage.getItem(IDS);
  const ids: unknown = raw ? JSON.parse(raw) : [];
  if (!Array.isArray(ids) || !ids.every(v => typeof v === 'string')) throw new Error('서버 등록 기록을 읽지 못했습니다.');
  return ids;
}
export async function rememberRemote(id: string) {
  await exclusive(async () => {
    await AsyncStorage.setItem(IDS, JSON.stringify([...new Set([...await registeredIds(), id])]));
  });
}
export async function forgetRemote(id: string) {
  await exclusive(async () => {
    await AsyncStorage.setItem(IDS, JSON.stringify((await registeredIds()).filter(v => v !== id)));
  });
}
export async function saveConnection(value: Connection) {
  const next = normalizeConnection(value), previous = await loadConnection();
  if ((!previous || previous.url !== next.url || previous.key !== next.key) && (await registeredIds()).length)
    throw new Error('기존 서버의 감시를 모두 중지한 뒤 연결을 변경해 주세요.');
  await serverRequest(next, '/connection');
  await writeConnection(JSON.stringify(next));
  return next;
}
export async function stopRegistered(id: string) {
  if (!(await registeredIds()).includes(id)) return;
  const connection = await loadConnection();
  if (!connection) throw new Error('기존 감시를 중지하려면 서버 연결을 복원해 주세요.');
  await stopRemoteWatch(connection, id);
  await forgetRemote(id);
}
export async function recordReceived(id: string) {
  if (!/^[A-Za-z0-9-]{1,128}$/.test(id)) return;
  await exclusive(async () => {
    const ids: string[] = JSON.parse(await AsyncStorage.getItem(ACKS) ?? '[]');
    await AsyncStorage.setItem(ACKS, JSON.stringify([...new Set([...ids, id])]));
  });
  await flushReceived();
}
export async function flushReceived() {
  const connection = await loadConnection();
  if (!connection) return;
  const ids: string[] = JSON.parse(await AsyncStorage.getItem(ACKS) ?? '[]');
  for (const id of ids) {
    await serverRequest(connection, '/alerts/' + encodeURIComponent(id) + '/received', 'POST');
    await exclusive(async () => {
      const current: string[] = JSON.parse(await AsyncStorage.getItem(ACKS) ?? '[]');
      await AsyncStorage.setItem(ACKS, JSON.stringify(current.filter(v => v !== id)));
    });
  }
}
