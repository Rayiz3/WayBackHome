import Constants, { ExecutionEnvironment } from 'expo-constants';
import * as Device from 'expo-device';
import type { Notification } from 'expo-notifications';
import { Platform } from 'react-native';

const isExpoGo = Constants.executionEnvironment === ExecutionEnvironment.StoreClient;
let notificationModule: typeof import('expo-notifications') | undefined;

function getNotifications() {
  if (isExpoGo) throw new Error('알림 확인은 Expo Go 대신 WayBackHome 개발 APK에서 해 주세요.');
  if (!notificationModule) {
    // Importing this package runs native push registration side effects, even before a button is pressed.
    const loaded: typeof import('expo-notifications') = require('expo-notifications');
    loaded.setNotificationHandler({
      handleNotification: async () => ({
        shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false,
      }),
    });
    notificationModule = loaded;
  }
  return notificationModule;
}

async function ensurePermission() {
  const Notifications = getNotifications();
  if (Platform.OS !== 'android' || !Device.isDevice) throw new Error('실제 Android 폰에 설치한 앱에서 확인해 주세요.');
  await Notifications.setNotificationChannelAsync('seat-alerts', {
    name: '열차 좌석 알림', importance: Notifications.AndroidImportance.HIGH,
    sound: 'default', vibrationPattern: [0, 250, 250, 250],
  });
  let permission = await Notifications.getPermissionsAsync();
  if (!permission.granted) permission = await Notifications.requestPermissionsAsync();
  if (!permission.granted) throw new Error('알림 권한이 꺼져 있습니다. Android 설정에서 WayBackHome 알림을 허용해 주세요.');
}

export async function registerPush(): Promise<string> {
  const Notifications = getNotifications();
  const projectId = Constants.expoConfig?.extra?.eas?.projectId ?? Constants.easConfig?.projectId;
  if (!projectId) throw new Error('Expo 프로젝트 연결이 필요합니다. 설정을 연결한 뒤 APK를 다시 빌드해 주세요.');
  await ensurePermission();
  return (await Notifications.getExpoPushTokenAsync({ projectId })).data;
}

export async function localNotification(): Promise<void> {
  const Notifications = getNotifications();
  await ensurePermission();
  await Notifications.scheduleNotificationAsync({
    content: { title: 'WayBackHome 알림 확인', body: '기기 알림이 표시되었습니다. 원격 푸시 연결은 별도로 확인합니다.', sound: 'default' },
    trigger: { type: Notifications.SchedulableTriggerInputTypes.TIME_INTERVAL, seconds: 3, channelId: 'seat-alerts' },
  });
}

export function listenNotifications(onMessage: (message: string, alertId?: string) => void): () => void {
  if (isExpoGo) return () => {};
  const Notifications = getNotifications();
  function describe(notification: Notification) {
    const content = notification.request.content;
    const alertId = content.data?.kind === 'seat_available' && typeof content.data?.alertId === 'string' ? content.data.alertId : undefined;
    onMessage(`${content.title ?? '알림'}${content.body ? ` · ${content.body}` : ''}`, alertId);
  }
  const received = Notifications.addNotificationReceivedListener(describe);
  const opened = Notifications.addNotificationResponseReceivedListener(response => describe(response.notification));
  const last = Notifications.getLastNotificationResponse();
  if (last) describe(last.notification);
  return () => { received.remove(); opened.remove(); };
}
