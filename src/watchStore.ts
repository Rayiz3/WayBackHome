import { readSavedSettings, readWatchList, writeWatchList } from './watch.ts';
import type { SavedWatch } from './watch.ts';
export const STORAGE_KEY = 'waybackhome.watches.v2';
type Storage = { getItem(key: string): Promise<string | null>; setItem(key: string, value: string): Promise<void> };
export async function loadWatches(storage: Storage): Promise<SavedWatch[]> {
  const raw = await storage.getItem(STORAGE_KEY);
  if (raw !== null) return readWatchList(raw);
  const legacy = await storage.getItem('waybackhome.watch.v1');
  if (legacy === null) return [];
  const items = [{ id: 'legacy-watch', settings: readSavedSettings(legacy) }];
  await saveWatches(storage, items); // Keep the old key as a recovery copy.
  return items;
}
export async function saveWatches(storage: Storage, items: SavedWatch[]) {
  await storage.setItem(STORAGE_KEY, writeWatchList(items));
}
