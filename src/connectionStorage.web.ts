// Web preview retains the server key only for the current tab session.
export async function readConnection() { return sessionStorage.getItem('waybackhome.connection'); }
export async function writeConnection(value: string) { sessionStorage.setItem('waybackhome.connection', value); }

