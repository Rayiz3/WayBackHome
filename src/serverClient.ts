import type { WatchSettings } from './watch';
export type Connection = { url: string; key: string };
export type RemoteWatch = {
  id: string; enabled: number; revision: number; status: string; checked_at: number | null;
  error: string | null; worker_live: boolean;
  alerts: { id: string; state: string; error: string | null; created_at: number; received_at: number | null }[];
};
export function normalizeConnection(value: Connection): Connection {
  const url = new URL(value.url.trim());
  if (url.username || url.password || url.search || url.hash || (url.pathname !== '/' && url.pathname !== ''))
    throw new Error('서버 주소는 경로 없이 입력해 주세요.');
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['127.0.0.1', 'localhost'].includes(url.hostname)))
    throw new Error('HTTPS 주소 또는 USB 연결용 http://127.0.0.1 주소를 사용해 주세요.');
  if (value.key.trim().length < 32) throw new Error('서버 연결 키를 확인해 주세요.');
  return { url: url.origin, key: value.key.trim() };
}
export class ServerError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}
export async function serverRequest<T>(connection: Connection, path: string, method = 'GET', body?: unknown, transport = fetch): Promise<T> {
  const config = normalizeConnection(connection);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await transport(config.url + path, { method, signal: controller.signal,
      headers: { Authorization: 'Bearer ' + config.key, 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    const data = await response.json();
    if (!response.ok) throw new ServerError(data.error ?? '서버 요청을 처리하지 못했습니다.', response.status);
    return data as T;
  } catch (error) {
    if (error instanceof ServerError) throw error;
    throw new Error('PC 서버에 연결할 수 없습니다. 서버 실행과 USB 연결을 확인하고 다시 시도해 주세요.');
  } finally { clearTimeout(timer); }
}
export const putRemoteWatch = (connection: Connection, id: string, settings: WatchSettings, token: string) =>
  serverRequest<RemoteWatch>(connection, '/watches/' + encodeURIComponent(id), 'PUT', { settings, token });
export const getRemoteWatch = (connection: Connection, id: string) =>
  serverRequest<RemoteWatch>(connection, '/watches/' + encodeURIComponent(id));
export const stopRemoteWatch = (connection: Connection, id: string) =>
  serverRequest(connection, '/watches/' + encodeURIComponent(id), 'DELETE');
export const remoteLabels: Record<string, string> = {
  pending: '서버 등록 · 첫 조회 대기', available: '예매 가능한 좌석 확인', no_matching_seats: '조건에 맞는 좌석 없음',
  error: '조회 오류 · 재시도 대기', waiting: '코레일 연결 대기', unknown: '좌석 상태 확인 필요',
  no_trains: '조회된 열차 없음', stopped: '감시 중지', expired: '출발 시간 종료',
  device_unregistered: '알림 연결을 다시 해 주세요',
  queued: '푸시 발송 대기', sending: '푸시 발송 중', retry: '푸시 재시도 대기', failed: '푸시 발송 실패',
  ticket_accepted: 'Expo 접수 · 휴대폰 수신 미확인', provider_accepted: 'FCM 전달 · 휴대폰 수신 미확인',
  device_received: '휴대폰 수신 확인', receipt_missing: '전달 결과 확인 필요', uncertain: '발송 결과 확인 필요',
  cancelled: '발송 취소',
};

