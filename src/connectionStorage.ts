import * as SecureStore from 'expo-secure-store';
export const readConnection = () => SecureStore.getItemAsync('waybackhome.connection');
export const writeConnection = (value: string) => SecureStore.setItemAsync('waybackhome.connection', value);

