import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
for (const file of ['.env', '.env.local']) {
  const location = path.join(root, file);
  if (fs.existsSync(location)) process.loadEnvFile(location);
}
const config = JSON.parse(fs.readFileSync(path.join(root, 'app.json'), 'utf8')).expo;
const failures = [];
const projectId = process.env.EXPO_PUBLIC_EAS_PROJECT_ID || config.extra?.eas?.projectId;
if (!projectId || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(projectId)) {
  failures.push('Expo 프로젝트 UUID가 필요합니다: app.json의 expo.extra.eas.projectId 또는 EXPO_PUBLIC_EAS_PROJECT_ID.');
}
const googlePath = path.join(root, 'google-services.json');
if (!fs.existsSync(googlePath)) {
  failures.push('Firebase Android 앱 설정 파일 mobile/google-services.json이 필요합니다.');
} else {
  try {
    const google = JSON.parse(fs.readFileSync(googlePath, 'utf8'));
    if (!google.project_info?.project_id || !google.project_info?.project_number) failures.push('Firebase 프로젝트 정보가 유효하지 않습니다.');
    const client = google.client?.find(c => c.client_info?.android_client_info?.package_name === config.android.package);
    if (!client) failures.push('Firebase Android 패키지명이 앱과 일치하지 않습니다: ' + config.android.package);
    if (!client?.client_info?.mobilesdk_app_id) failures.push('Firebase Android 앱 ID가 없습니다.');
  } catch { failures.push('google-services.json을 읽지 못했습니다. Firebase에서 다운로드한 원본을 사용해 주세요.'); }
}
console.log('Android package: ' + config.android.package);
if (failures.length) {
  console.error('외부 서비스 설정 필요:\n- ' + failures.join('\n- '));
  process.exitCode = 1;
} else {
  console.log('로컬 빌드 설정 확인 완료. EAS의 FCM v1 자격증명 등록과 실제 폰 수신은 별도 검증이 필요합니다.');
}
