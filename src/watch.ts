export type CalendarDate = { year: number; month: number; day: number };
export type ClockTime = { hour: number; minute: number };
export type WatchSettings = {
  date: CalendarDate; departure: string; arrival: string; from: ClockTime; to: ClockTime;
  adults: string; trainNumbers: string; standard: boolean; first: boolean;
};
export type SavedWatch = { id: string; settings: WatchSettings };
export const defaultSettings: WatchSettings = {
  date: { year: 2026, month: 9, day: 27 }, departure: '부산', arrival: '수서',
  from: { hour: 12, minute: 0 }, to: { hour: 20, minute: 0 },
  adults: '1', trainNumbers: '', standard: true, first: true,
};
const pad = (v: number) => String(v).padStart(2, '0');
export const formatDate = (v: CalendarDate) => `${v.year}-${pad(v.month)}-${pad(v.day)}`;
export const formatTime = (v: ClockTime) => `${pad(v.hour)}:${pad(v.minute)}`;
export const timeWindow = (v: WatchSettings) => `${formatTime(v.from)} 에서 ${formatTime(v.to)} 사이`;
export function parseDate(v: string): CalendarDate {
  const [year, month, day] = v.split('-').map(Number); return { year, month, day };
}
export function parseTime(v: string): ClockTime {
  const [hour, minute] = v.split(':').map(Number); return { hour, minute };
}
export function validateSettings(v: WatchSettings): string | null {
  const d = v.date;
  if (!d || ![d.year, d.month, d.day].every(Number.isInteger) || d.year < 1900 || d.year > 9999 ||
      d.month < 1 || d.month > 12 || d.day < 1 || d.day > 31 ||
      new Date(Date.UTC(d.year, d.month - 1, d.day)).toISOString().slice(0, 10) !== formatDate(d))
    return '실제 달력에 있는 날짜를 선택해 주세요.';
  if (!v.departure.trim() || !v.arrival.trim()) return '출발역과 도착역을 선택해 주세요.';
  if (v.departure === v.arrival) return '출발역과 도착역은 달라야 합니다.';
  if (![v.from, v.to].every(t => t && Number.isInteger(t.hour) && Number.isInteger(t.minute) &&
      t.hour >= 0 && t.hour <= 23 && t.minute >= 0 && t.minute <= 59)) return '올바른 시각을 선택해 주세요.';
  if (v.from.hour * 60 + v.from.minute > v.to.hour * 60 + v.to.minute) return '끝 시각은 시작 시각보다 빠를 수 없습니다.';
  if (!/^[1-9]$/.test(v.adults)) return '성인 인원은 1~9명으로 입력해 주세요.';
  if (!v.standard && !v.first) return '일반실 또는 특실을 선택해 주세요.';
  if (v.trainNumbers.trim() && !/^\d{1,5}(\s*,\s*\d{1,5})*$/.test(v.trainNumbers.trim()))
    return '열차번호는 쉼표로 구분한 숫자로 입력해 주세요.';
  return null;
}
export function toWatchConfig(v: WatchSettings) {
  const error = validateSettings(v); if (error) throw new Error(error);
  return {
    departure_date: formatDate(v.date), departure_station: v.departure, arrival_station: v.arrival,
    departure_time_from: formatTime(v.from), departure_time_to: formatTime(v.to), timezone: 'Asia/Seoul',
    direct_only: true, adults: Number(v.adults), train_family: 'KTX',
    train_numbers: v.trainNumbers.trim() ? [...new Set(v.trainNumbers.split(',').map(n => String(Number(n.trim()))))] : [],
    seat_classes: [...(v.standard ? ['standard'] : []), ...(v.first ? ['first'] : [])], enabled: false,
  };
}
function checkedSettings(value: unknown): WatchSettings {
  if (!value || typeof value !== 'object') throw new Error('저장된 조건 형식이 맞지 않습니다.');
  const v = value as WatchSettings;
  for (const key of ['departure', 'arrival', 'adults', 'trainNumbers'] as const)
    if (typeof v[key] !== 'string') throw new Error('저장된 조건 형식이 맞지 않습니다.');
  if (typeof v.standard !== 'boolean' || typeof v.first !== 'boolean') throw new Error('저장된 좌석 형식이 맞지 않습니다.');
  const error = validateSettings(v); if (error) throw new Error(error);
  return v;
}
export function readSavedSettings(raw: string): WatchSettings {
  const v = JSON.parse(raw);
  if (!v || typeof v !== 'object') throw new Error('저장된 조건을 읽을 수 없습니다.');
  return checkedSettings({ ...v, date: typeof v.date === 'string' ? parseDate(v.date) : v.date,
    from: typeof v.from === 'string' ? parseTime(v.from) : v.from, to: typeof v.to === 'string' ? parseTime(v.to) : v.to });
}
export function readWatchList(raw: string): SavedWatch[] {
  const v = JSON.parse(raw);
  if (v?.version !== 2 || !Array.isArray(v.items)) throw new Error('저장된 목록 형식이 맞지 않습니다.');
  const ids = new Set<string>();
  return v.items.map((item: SavedWatch) => {
    if (!item || typeof item.id !== 'string' || !item.id || ids.has(item.id)) throw new Error('저장된 항목 ID가 올바르지 않습니다.');
    ids.add(item.id); return { id: item.id, settings: checkedSettings(item.settings) };
  });
}
export function writeWatchList(items: SavedWatch[]) {
  const raw = JSON.stringify({ version: 2, items }); readWatchList(raw); return raw;
}
export function upsertWatch(items: SavedWatch[], item: SavedWatch) {
  checkedSettings(item.settings);
  return items.some(v => v.id === item.id) ? items.map(v => v.id === item.id ? item : v) : [...items, item];
}
