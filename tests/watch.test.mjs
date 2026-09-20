import { test } from 'node:test';
import assert from 'node:assert/strict';
import { defaultSettings as base, readSavedSettings, readWatchList, writeWatchList, upsertWatch, toWatchConfig, validateSettings } from '../src/watch.ts';
import { loadWatches, saveWatches, STORAGE_KEY } from '../src/watchStore.ts';
import { stations } from '../src/stations.ts';
test('날짜와 시간은 숫자 필드로 저장하고 API 경계에서만 문자열로 변환한다', () => {
  const settings = { ...base, date: { year: 2028, month: 2, day: 29 }, from: { hour: 6, minute: 30 }, trainNumbers: '0018,32,18' };
  const saved = readWatchList(writeWatchList([{ id: 'a', settings }]))[0].settings;
  assert.deepEqual(saved, settings);
  const config = toWatchConfig(saved);
  assert.equal(config.departure_date, '2028-02-29');
  assert.equal(config.departure_time_from, '06:30');
  assert.deepEqual(config.train_numbers, ['18', '32']);
  assert.equal(config.enabled, false);
});
test('잘못된 날짜, 시각, 범위 및 조건을 거절한다', () => {
  for (const override of [
    { date: { year: 2026, month: 2, day: 29 } }, { date: { year: 2026, month: 13, day: 1 } },
    { from: { hour: 24, minute: 0 } }, { from: { hour: 20, minute: 1 } }, { to: { hour: 20, minute: 99 } },
    { adults: '0' }, { adults: '1.5' }, { adults: '10' }, { standard: false, first: false },
    { trainNumbers: '18,,32' }, { departure: '수서' },
  ]) assert.ok(validateSettings({ ...base, ...override }));
  assert.equal(validateSettings({ ...base, from: base.to }), null);
});
test('여러 항목 추가 후 한 항목 수정 시 다른 항목을 보존한다', () => {
  let list = upsertWatch([], { id: 'a', settings: base });
  list = upsertWatch(list, { id: 'b', settings: { ...base, arrival: '서울' } });
  list = upsertWatch(list, { id: 'a', settings: { ...base, adults: '2' } });
  assert.equal(list.length, 2);
  assert.equal(list[1].settings.arrival, '서울');
  assert.equal(readWatchList(writeWatchList(list))[0].settings.adults, '2');
});
test('기존 한 조건을 목록으로 이전하고 원본을 보존한다', async () => {
  const legacy = JSON.stringify({ ...base, date: '2026-09-27', from: '12:00', to: '20:00' });
  const data = new Map([['waybackhome.watch.v1', legacy]]);
  const storage = { getItem: async k => data.get(k) ?? null, setItem: async (k,v) => { data.set(k,v); } };
  assert.deepEqual(readSavedSettings(legacy), base);
  assert.deepEqual(await loadWatches(storage), [{ id: 'legacy-watch', settings: base }]);
  assert.equal(data.get('waybackhome.watch.v1'), legacy);
  await saveWatches(storage, []);
  assert.deepEqual(await loadWatches(storage), []); // Empty v2 must not resurrect v1.
});
test('손상되거나 중복된 저장 목록을 덮어쓰지 않는다', async () => {
  let writes = 0;
  await assert.rejects(loadWatches({ getItem: async () => '{', setItem: async () => { writes++; } }));
  assert.equal(writes, 0);
  assert.throws(() => readWatchList('null'));
  assert.throws(() => writeWatchList([{ id: 'a', settings: base }, { id: 'a', settings: base }]));
  assert.throws(() => readSavedSettings(JSON.stringify({ ...base, standard: 'true' })));
});
test('저장 오류를 호출자에 전달하고 이전 실패 시 원본을 남긴다', async () => {
  const storage = { getItem: async k => k === STORAGE_KEY ? null : JSON.stringify(base),
    setItem: async () => { throw new Error('disk full'); } };
  await assert.rejects(saveWatches(storage, [{ id: 'a', settings: base }]), /disk full/);
  await assert.rejects(loadWatches(storage), /disk full/);
});
test('공식 역 목록은 중복이 없고 주요 노선을 포함한다', () => {
  assert.equal(stations.length, new Set(stations).size);
  for (const name of ['부산', '수서', '서울', '서대구', '울산(통도사)', '판교(경기)']) assert.ok(stations.includes(name));
});
