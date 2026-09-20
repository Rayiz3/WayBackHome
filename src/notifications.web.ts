const message = '알림 연결은 실제 Android 폰에 설치한 앱에서 확인해 주세요.';
export async function registerPush(): Promise<string> { throw new Error(message); }
export async function localNotification(): Promise<void> { throw new Error(message); }
export function listenNotifications(_onMessage: (message: string, alertId?: string) => void): () => void { return () => {}; }
