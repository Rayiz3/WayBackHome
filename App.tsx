import { useEffect, useRef, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { StatusBar } from 'expo-status-bar';
import { AppState, FlatList, Linking, Modal, Platform, Pressable, ScrollView, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { defaultSettings, formatDate, formatTime, timeWindow, upsertWatch, validateSettings } from './src/watch';
import type { SavedWatch, WatchSettings } from './src/watch';
import { loadWatches, saveWatches } from './src/watchStore';
import TemporalField from './src/TemporalField';
import { stations, stationSource, stationUpdated } from './src/stations';
import { listenNotifications, localNotification, registerPush } from './src/notifications';
import { flushReceived, loadConnection, recordReceived, registeredIds, rememberRemote, saveConnection, stopRegistered } from './src/monitorConnection';
import { getRemoteWatch, putRemoteWatch, remoteLabels, ServerError } from './src/serverClient';
import type { Connection, RemoteWatch } from './src/serverClient';

function Action({ title, onPress, secondary = false, disabled = false }: {
  title: string; onPress: () => void; secondary?: boolean; disabled?: boolean;
}) {
  return <Pressable accessibilityRole="button" disabled={disabled} onPress={onPress}
    style={({ pressed }) => [styles.button, secondary && styles.secondary, (disabled || pressed) && { opacity: 0.5 }]}>
    <Text style={[styles.buttonText, secondary && { color: '#325139' }]}>{title}</Text>
  </Pressable>;
}
export default function App() {
  const [items, setItems] = useState<SavedWatch[]>([]);
  const [settings, setSettings] = useState<WatchSettings>(defaultSettings);
  const [editor, setEditor] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [message, setMessage] = useState('');
  const [failure, setFailure] = useState('');
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const scroll = useRef<ScrollView>(null);
  const [token, setToken] = useState('');
  const [connection, setConnection] = useState<Connection | null>(null);
  const [serverUrl, setServerUrl] = useState('http://127.0.0.1:8787');
  const [serverKey, setServerKey] = useState('');
  const [remote, setRemote] = useState<Record<string, RemoteWatch | undefined>>({});
  const [remoteErrors, setRemoteErrors] = useState<Record<string, string>>({});
  const [remoteIds, setRemoteIds] = useState<string[]>([]);
  const [notification, setNotification] = useState('아직 수신한 알림이 없습니다.');
  const [tab, setTab] = useState<'watch' | 'notifications'>('watch');
  const [stationField, setStationField] = useState<'departure' | 'arrival' | null>(null);
  const [query, setQuery] = useState('');
  const [removed, setRemoved] = useState<{ item: SavedWatch; index: number } | null>(null);
  const error = validateSettings(settings);
  const disabled = !ready || busy || loadError;
  const goTop = () => scroll.current?.scrollTo({ y: 0, animated: true });
  async function load() {
    setReady(false);
    try { setItems(await loadWatches(AsyncStorage)); setLoadError(false); setFailure(''); }
    catch { setLoadError(true); setFailure('저장된 목록을 불러오지 못했습니다. 기존 데이터를 보호하기 위해 저장을 멈췄습니다. 다시 불러와 주세요.'); }
    finally { setReady(true); }
  }
  useEffect(() => { void load(); }, []);
  useEffect(() => {
    loadConnection().then(value => {
      setConnection(value);
      if (value) { setServerUrl(value.url); setServerKey(value.key); }
    }).catch(() => setFailure('서버 연결 정보를 읽지 못했습니다. 알림 연결에서 다시 확인해 주세요.'));
  }, []);
  useEffect(() => listenNotifications((text, alertId) => {
    setNotification(text); setTab('notifications'); goTop();
    if (alertId) void recordReceived(alertId).catch(() =>
      setMessage('휴대폰에서 알림을 확인했습니다. 서버 수신 확인은 연결이 복구되면 다시 전송합니다.'));
  }), []);
  useEffect(() => {
    if (!ready || busy) return;
    let cancelled = false, refreshing = false;
    async function refresh() {
      if (refreshing || AppState.currentState === 'background') return;
      refreshing = true;
      try {
        const ids = await registeredIds();
        if (!cancelled) setRemoteIds(ids);
        if (connection) {
          for (const id of ids) {
            try {
              const status = await getRemoteWatch(connection, id);
              if (!cancelled) {
                setRemote(previous => ({ ...previous, [id]: status }));
                setRemoteErrors(previous => ({ ...previous, [id]: '' }));
              }
            } catch (cause) {
              if (!cancelled) setRemoteErrors(previous => ({ ...previous, [id]:
                cause instanceof ServerError && cause.status === 404 ? '서버에 감시가 없습니다. 다시 시작해 주세요.' : '서버 상태 확인 실패 · 마지막 상태가 최신이 아닐 수 있습니다.' }));
            }
          }
          await flushReceived();
        }
      } catch {
        if (!cancelled) setMessage('서버 등록 또는 수신 확인 기록을 확인하지 못했습니다. 연결을 확인해 주세요.');
      } finally { refreshing = false; }
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 30000);
    const subscription = AppState.addEventListener('change', state => { if (state === 'active') void refresh(); });
    return () => { cancelled = true; clearInterval(timer); subscription.remove(); };
  }, [connection, ready, busy]);
  function update<K extends keyof WatchSettings>(key: K, value: WatchSettings[K]) {
    setSettings(previous => ({ ...previous, [key]: value })); setFailure('');
  }
  async function run(action: () => Promise<void>) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setFailure('');
    try { await action(); }
    catch (cause) { setFailure(cause instanceof Error ? cause.message : '작업을 마치지 못했습니다. 다시 시도해 주세요.'); }
    finally { lock.current = false; setBusy(false); }
  }
  function edit(item?: SavedWatch) {
    setEditor(item?.id ?? 'new'); setSettings(item?.settings ?? structuredCloneSettings());
    setMessage(''); setFailure(''); goTop();
  }
  async function persist(next: SavedWatch[]) {
    await saveWatches(AsyncStorage, next); setItems(next);
  }
  async function save() {
    if (error) throw new Error(error);
    if (!stations.includes(settings.departure) || !stations.includes(settings.arrival))
      throw new Error('공식 목록에서 출발역과 도착역을 다시 선택해 주세요.');
    const id = editor === 'new' ? Date.now().toString(36) + '-' + Math.random().toString(36).slice(2) : editor!;
    await stopRegistered(id);
    setRemoteIds(await registeredIds());
    setRemote(previous => ({ ...previous, [id]: undefined }));
    await persist(upsertWatch(items, { id, settings }));
    setEditor(null); setMessage('조건을 저장했습니다. 목록에서 감시 시작을 누르면 서버에 등록됩니다.'); goTop();
  }
  async function startWatch(item: SavedWatch) {
    if (!connection) { setTab('notifications'); goTop(); throw new Error('먼저 PC 서버 연결을 저장해 주세요.'); }
    const pushToken = await registerPush();
    setToken(pushToken);
    // Persist intent before the request so an uncertain timeout can still be stopped.
    await rememberRemote(item.id); setRemoteIds(await registeredIds());
    const status = await putRemoteWatch(connection, item.id, item.settings, pushToken);
    setRemote(previous => ({ ...previous, [item.id]: status }));
    setRemoteErrors(previous => ({ ...previous, [item.id]: '' }));
    setMessage(status.worker_live ? '서버에 등록했습니다. 실제 조회 결과를 기다리고 있습니다.' : '서버에 등록했습니다. PC의 조회 실행기를 켜 주세요.');
    goTop();
  }
  async function stopWatch(id: string) {
    await stopRegistered(id); setRemoteIds(await registeredIds());
    setRemote(previous => ({ ...previous, [id]: undefined }));
    setRemoteErrors(previous => ({ ...previous, [id]: '' }));
    setMessage('서버 감시를 중지했습니다. 이미 전송된 알림은 도착할 수 있습니다.');
  }
  function textField(key: 'adults' | 'trainNumbers', label: string, placeholder: string) {
    return <View style={styles.field}><Text style={styles.label}>{label}</Text>
      <TextInput accessibilityLabel={label} value={settings[key]} placeholder={placeholder} editable={!disabled}
        onChangeText={text => update(key, text)} style={styles.input} keyboardType={key === 'adults' ? 'number-pad' : 'default'} />
    </View>;
  }
  function stationButton(key: 'departure' | 'arrival', label: string) {
    return <View style={styles.field}><Text style={styles.label}>{label}</Text>
      <Pressable accessibilityRole="button" accessibilityLabel={label + ' ' + settings[key]} disabled={disabled}
        style={styles.inputButton} onPress={() => { setQuery(''); setStationField(key); }}>
        <Text style={styles.body}>{settings[key]} ▾</Text>
      </Pressable>
    </View>;
  }
  return <SafeAreaProvider><SafeAreaView style={styles.safe}>
    <StatusBar style="dark" />
    <ScrollView ref={scroll} contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
      <View><Text style={styles.wordmark}>WAY BACK HOME</Text><Text style={styles.title}>집으로 가는 기차</Text></View>
      <View style={styles.hero}>
        <Text style={styles.heroLabel}>나의 여정 · 편도 / 직통</Text>
        <Text style={styles.heroTitle}>저장한 감시 조건 {items.length}개</Text>
        <Text style={styles.heroLabel}>KTX 전체 · 청룡·산천 포함</Text>
        <Text style={styles.heroLabel}>조건 저장 후 감시 시작을 눌러 주세요. PC 서버와 조회 실행기가 켜져 있어야 감시가 계속됩니다.</Text>
      </View>
      <View style={styles.row}>
        {(['watch', 'notifications'] as const).map(value => <Pressable key={value} accessibilityRole="tab"
          accessibilityState={{ selected: tab === value }} disabled={busy} onPress={() => { setTab(value); setFailure(''); }}
          style={[styles.tab, tab === value && styles.selectedTab]}>
          <Text style={styles.body}>{value === 'watch' ? '감시 목록' : '알림 연결'}</Text>
        </Pressable>)}
      </View>
      {!!message && <View style={styles.notice}><Text accessibilityLiveRegion="polite" style={styles.body}>{message}</Text></View>}
      {!!failure && <Text accessibilityRole="alert" style={styles.error}>{failure}</Text>}
      {loadError && <Action title="목록 다시 불러오기" onPress={() => void load()} />}
      {tab === 'watch' ? editor !== null ? <View style={styles.card}>
        <Text style={styles.sectionTitle}>{editor === 'new' ? '새 감시 조건' : '감시 조건 수정'}</Text>
        <TemporalField mode="date" label="탑승일" disabled={disabled} display={formatDate(settings.date)}
          value={new Date(settings.date.year, settings.date.month - 1, settings.date.day, 12)}
          onChange={d => update('date', { year: d.getFullYear(), month: d.getMonth() + 1, day: d.getDate() })} />
        <View style={styles.row}>{stationButton('departure', '출발역')}{stationButton('arrival', '도착역')}</View>
        <Action title="출발역 ⇄ 도착역 교체" secondary disabled={disabled}
          onPress={() => setSettings(v => ({ ...v, departure: v.arrival, arrival: v.departure }))} />
        <Text style={styles.label}>출발 시각 · 한국 시간</Text>
        <View style={styles.row}>
          {(['from', 'to'] as const).map(key => <TemporalField key={key} mode="time" label={key === 'from' ? '시작 시각' : '끝 시각'}
            disabled={disabled} display={formatTime(settings[key])} value={new Date(2000, 0, 1, settings[key].hour, settings[key].minute)}
            onChange={d => update(key, { hour: d.getHours(), minute: d.getMinutes() })} />)}
        </View>
        <Text style={styles.body}>{timeWindow(settings)}</Text>
        {textField('adults', '성인 인원', '1')}
        {textField('trainNumbers', '열차번호 (선택)', '비워 두면 모든 KTX · 예: 18, 32')}
        {(['standard', 'first'] as const).map(key => <View key={key} style={styles.switchRow}>
          <Text style={styles.body}>{key === 'standard' ? '일반실' : '특실'}</Text>
          <Switch accessibilityLabel={key === 'standard' ? '일반실' : '특실'} disabled={disabled} value={settings[key]}
            onValueChange={value => update(key, value)} trackColor={{ true: '#23674e' }} />
        </View>)}
        {error && <Text accessibilityRole="alert" style={styles.error}>{error}</Text>}
        {!!failure && <Text accessibilityRole="alert" style={styles.error}>{failure}</Text>}
        <Action title={busy ? '저장 중…' : '조건 저장'} disabled={disabled || !!error} onPress={() => void run(save)} />
        <Action title="취소하고 목록으로" secondary disabled={busy} onPress={() => { setEditor(null); setFailure(''); goTop(); }} />
      </View> : <>
        <Action title={ready ? '+ 감시 조건 추가' : '목록 불러오는 중…'} disabled={disabled} onPress={() => edit()} />
        {ready && !loadError && items.length === 0 && <View style={styles.card}>
          <Text style={styles.sectionTitle}>아직 저장한 조건이 없습니다</Text>
          <Text style={styles.description}>탑승일과 구간을 정해 첫 조건을 추가해 주세요. 여러 날짜와 구간을 따로 저장할 수 있습니다.</Text>
        </View>}
        {items.map((item, index) => <View key={item.id} style={styles.card}>
          <Text style={styles.label}>조건 {index + 1} · {remoteIds.includes(item.id) ? '서버 등록 기록 있음' : '기기에 저장됨 · 감시 미시작'}</Text>
          <Text style={styles.sectionTitle}>{item.settings.departure} → {item.settings.arrival}</Text>
          <Text style={styles.body}>{formatDate(item.settings.date)}</Text>
          <Text style={styles.body}>{timeWindow(item.settings)}</Text>
          <Text style={styles.description}>직통 · {item.settings.trainNumbers ? 'KTX ' + item.settings.trainNumbers : 'KTX 전체'} · 성인 {item.settings.adults}명 · {[item.settings.standard && '일반실', item.settings.first && '특실'].filter(Boolean).join(' / ')}</Text>
          {remote[item.id] && <View style={styles.field}>
            <Text style={styles.body}>{remoteLabels[remote[item.id]!.status] ?? '상태 확인 필요'}</Text>
            {!remote[item.id]!.worker_live && !!remote[item.id]!.enabled && <Text style={styles.error}>조회 실행기 응답 없음 · PC 실행 상태를 확인해 주세요.</Text>}
            <Text style={styles.description}>마지막 조회: {remote[item.id]!.checked_at ? new Date(remote[item.id]!.checked_at! * 1000).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }) : '아직 없음'}</Text>
            {remote[item.id]!.alerts.slice(0, 3).map(alert => <Text key={alert.id} style={styles.description}>
              {remoteLabels[alert.state] ?? alert.state}{alert.error ? ' · ' + alert.error : ''}
            </Text>)}
          </View>}
          {!!remoteErrors[item.id] && <Text style={styles.error}>{remoteErrors[item.id]}</Text>}
          <Action title={'조건 ' + (index + 1) + ' 감시 시작·갱신'} disabled={disabled} onPress={() => void run(() => startWatch(item))} />
          {remoteIds.includes(item.id) && <Action title={'조건 ' + (index + 1) + ' 감시 중지'} secondary disabled={disabled} onPress={() => void run(() => stopWatch(item.id))} />}
          <Action title={'조건 ' + (index + 1) + ' 수정'} secondary disabled={disabled} onPress={() => edit(item)} />
          <Action title={'조건 ' + (index + 1) + ' 삭제'} secondary disabled={disabled} onPress={() => void run(async () => {
            await stopWatch(item.id);
            await persist(items.filter(v => v.id !== item.id)); setRemoved({ item, index }); setMessage('조건을 삭제했습니다. 되돌리기로 복원할 수 있습니다.'); goTop();
          })} />
        </View>)}
        {removed && <Action title="마지막 삭제 되돌리기" secondary disabled={disabled} onPress={() => void run(async () => {
          const next = [...items]; next.splice(removed.index, 0, removed.item); await persist(next); setRemoved(null); setMessage('삭제한 조건을 복원했습니다.'); goTop();
        })} />}
      </> : <View style={styles.card}>
        <Text style={styles.sectionTitle}>휴대폰으로 소식 받기</Text>
        <Text style={styles.description}>설치한 APK에서 PC 서버를 연결한 다음, 감시 목록의 감시 시작을 눌러 주세요.</Text>
        <Text style={styles.label}>PC 서버 주소</Text>
        <TextInput accessibilityLabel="PC 서버 주소" value={serverUrl} onChangeText={setServerUrl} style={styles.input} autoCapitalize="none" autoCorrect={false} editable={!busy} />
        <Text style={styles.label}>서버 연결 키</Text>
        <TextInput accessibilityLabel="서버 연결 키" value={serverKey} onChangeText={setServerKey} secureTextEntry style={styles.input} autoCapitalize="none" autoCorrect={false} editable={!busy} />
        <Text style={styles.description}>USB 연결 시 PC의 연결 안내에 따라 127.0.0.1 주소를 사용합니다. 연결 키는 휴대폰의 보안 저장소에 보관합니다.</Text>
        <Action title="서버 연결 확인·저장" disabled={busy || Platform.OS === 'web'} onPress={() => void run(async () => {
          const saved = await saveConnection({ url: serverUrl, key: serverKey });
          setConnection(saved); setMessage('서버 연결을 저장했습니다. 감시 목록에서 시작할 조건을 선택해 주세요.'); goTop();
        })} />
        {Platform.OS === 'web' && <Text style={styles.description}>서버 연결과 푸시 검증은 설치한 Android 앱에서 진행합니다.</Text>}
        <Text style={styles.description}>{connection ? '저장된 서버: ' + connection.url : '아직 연결된 서버가 없습니다.'}</Text>
        {remoteIds.length > 0 && <Action title="이 기기에 등록된 감시 모두 중지" secondary disabled={busy} onPress={() => void run(async () => {
          for (const id of await registeredIds()) await stopWatch(id);
        })} />}
        <Action title="알림 연결" disabled={busy} onPress={() => void run(async () => {
          setToken(''); setToken(await registerPush()); setMessage('푸시 토큰을 발급했습니다. 원격 테스트 알림 수신을 확인해 주세요.'); goTop();
        })} />
        <Action title="기기 알림 테스트" secondary disabled={busy} onPress={() => void run(async () => {
          await localNotification(); setMessage('3초 뒤 기기 알림이 표시됩니다.'); goTop();
        })} />
        {!!token && <Text selectable style={styles.body}>{token}</Text>}
        <Text style={styles.label}>최근 확인한 알림</Text><Text style={styles.body}>{notification}</Text>
      </View>}
      <Action title="코레일에서 직접 조회하기 ↗" secondary disabled={busy} onPress={() => void run(async () => { await Linking.openURL(stationSource); })} />
      <Text style={styles.footer}>WayBackHome · 모든 시간은 한국 시간입니다.</Text>
    </ScrollView>
    <Modal visible={stationField !== null} animationType="slide" onRequestClose={() => setStationField(null)}>
      <SafeAreaView style={styles.safe}><View style={styles.modal}>
        <Text style={styles.sectionTitle}>{stationField === 'departure' ? '출발역' : '도착역'} 선택</Text>
        <Text style={styles.description}>코레일 공식 예매 역 목록 · {stationUpdated} 기준. KTX 운행 여부는 구간·날짜에 따라 다릅니다.</Text>
        <TextInput accessibilityLabel="역 이름 검색" placeholder="역 이름 검색" value={query} onChangeText={setQuery} style={styles.input} autoCorrect={false} />
        <FlatList data={stations.filter(name => name.toLowerCase().includes(query.trim().toLowerCase()))} keyExtractor={name => name} keyboardShouldPersistTaps="handled"
          ListEmptyComponent={<Text style={styles.description}>일치하는 역이 없습니다. 역 이름을 다시 확인해 주세요.</Text>}
          renderItem={({ item }) => <Pressable accessibilityRole="button" accessibilityLabel={item} style={styles.station}
            onPress={() => { if (stationField) update(stationField, item); setStationField(null); }}>
            <Text style={styles.body}>{item}</Text>
          </Pressable>} />
        <Action title="닫기" secondary onPress={() => setStationField(null)} />
      </View></SafeAreaView>
    </Modal>
  </SafeAreaView></SafeAreaProvider>;
}
function structuredCloneSettings(): WatchSettings {
  return { ...defaultSettings, date: { ...defaultSettings.date }, from: { ...defaultSettings.from }, to: { ...defaultSettings.to } };
}
const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#f3f5f0' },
  content: { width: '100%', maxWidth: 580, alignSelf: 'center', padding: 22, paddingBottom: 36, gap: 18 },
  wordmark: { color: '#4d6658', fontSize: 10, letterSpacing: 2, fontWeight: '800', marginBottom: 7 },
  title: { fontSize: 25, color: '#173b2c', fontWeight: '800' },
  hero: { backgroundColor: '#173f31', borderRadius: 22, padding: 24, gap: 12 },
  heroLabel: { color: '#d2e3d8', fontSize: 13, lineHeight: 21 },
  heroTitle: { color: '#fff', fontSize: 25, fontWeight: '800' },
  row: { flexDirection: 'row', gap: 12 },
  tab: { flex: 1, padding: 14, alignItems: 'center', borderRadius: 10, backgroundColor: '#e7ece3' },
  selectedTab: { backgroundColor: '#fff', borderBottomWidth: 2, borderColor: '#235e44' },
  card: { backgroundColor: '#fff', borderRadius: 19, padding: 21, gap: 15, borderWidth: 1, borderColor: '#e5e9df' },
  sectionTitle: { color: '#203c2b', fontWeight: '700', fontSize: 18 },
  description: { color: '#637264', fontSize: 13, lineHeight: 21 },
  field: { flex: 1, gap: 8, minWidth: 0 }, label: { color: '#4a5d4e', fontSize: 12, fontWeight: '600' },
  input: { minHeight: 48, borderRadius: 10, borderWidth: 1, borderColor: '#dce3d7', backgroundColor: '#fafbf8', paddingHorizontal: 13, color: '#263e2d', fontSize: 15 },
  inputButton: { minHeight: 48, borderRadius: 10, borderWidth: 1, borderColor: '#dce3d7', backgroundColor: '#fafbf8', padding: 12, justifyContent: 'center' },
  switchRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 44 },
  body: { color: '#334c3e', fontSize: 14, lineHeight: 22 },
  button: { backgroundColor: '#235e44', borderRadius: 12, minHeight: 48, padding: 14, alignItems: 'center', justifyContent: 'center' },
  secondary: { backgroundColor: '#e7ede1' }, buttonText: { color: '#fff', fontSize: 14, fontWeight: '700' },
  notice: { backgroundColor: '#e1eddd', borderRadius: 12, padding: 16 },
  error: { color: '#ad342e', fontSize: 13, lineHeight: 21 },
  footer: { textAlign: 'center', color: '#647460', fontSize: 11 },
  modal: { flex: 1, width: '100%', maxWidth: 580, alignSelf: 'center', padding: 22, gap: 15 },
  station: { padding: 15, minHeight: 50, borderBottomWidth: 1, borderColor: '#dce3d7' },
});
