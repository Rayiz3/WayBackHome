# WayBackHome 감시 서버

현재 PC에서 먼저 실수신을 검증한 뒤 상시 서버로 이전한다.

## 구현 상태

- `seat_alerts.py`: 실제 관찰한 코레일 카드 판독 및 조건 필터, Expo 발송·receipt 조회.
- `monitor.py`: SQLite 영속 감시 목록·알림 이력, 조건 revision, 중복 억제, 재시도, 오래된 좌석 폐기.
- `api.py`: 개인용 Bearer 인증 API. 키는 환경변수로 주입하며 앱에 하드코딩하지 않는다.
- `worker.py`: 조회 공급자를 받아 5분 간격으로 조건 확인, 발송 및 receipt 확인.
- `korail_mobile.py`: pykorail 기반 비로그인 모바일 API 조회 공급자. 브라우저 없이 감시 날짜·역·시간 조건을 사용하며 페이지를 겹쳐 읽고 중복 제거한다. HTTP/내부 오류·페이지 정체·스키마 변경은 조회 실패로 처리한다.
- `korail.py`와 `probe.py`: 과거 웹 진단 도구로만 보관. 운영 서버에서는 import하거나 실행하지 않는다.
- 앱: 서버 연결 키를 SecureStore에 보관하고 감시 등록·중지·상태 조회·수신 확인을 지원한다. 테스트 푸시 실수신은 확인했으며 공급자 교체에는 APK 재설치가 필요 없다.

## 테스트

프로젝트 루트에서:

```powershell
python -m unittest discover -s server/tests -v
```

테스트는 관찰 카드와 모의 전송기를 사용한다. 테스트 성공은 실제 푸시 수신 증거가 아니다.

## USB로 PC 서버 연결

Python 의존성을 설치하고 프로젝트 루트에서 실행한다. Chromium 설치는 필요 없다:

```powershell
.\.venv\Scripts\python.exe -m pip install -r server/requirements.txt
.\scripts\start-monitor.ps1
.\.tools\platform-tools\adb.exe devices -l
.\.tools\platform-tools\adb.exe reverse tcp:8787 tcp:8787
```

첫 명령은 API와 조회 작업을 함께 실행하므로 별도 터미널에서 유지한다. 휴대폰은 USB 디버깅 및 PC 연결을 허용해야 한다. USB를 다시 연결하면 reverse 명령을 다시 실행한다.

새 preview APK를 설치한 뒤 알림 탭에서 서버 주소 `http://127.0.0.1:8787`과 `server/.local/server-key.txt`의 연결 키를 입력하고 저장한다. 키를 저장소나 채팅에 공유하지 않는다. 감시 목록에서 목표 조건을 저장한 뒤 **감시 시작**을 눌러야 서버에 등록된다. PC와 서버를 계속 켜 두어야 한다.

preview APK는 localhost에 한해 HTTP를 허용하며, 그 외 서버 주소는 HTTPS를 사용한다. Expo Go로는 Android 원격 푸시를 검증할 수 없다.

## API만 별도로 실행

32자 이상의 임의 연결 키를 `WAYBACKHOME_API_KEY` 환경변수에 설정한 뒤:

```powershell
python -m server.api --host 127.0.0.1 --port 8787
```

이 명령은 로컬 PC의 API만 실행하며 좌석 조회 작업은 실행하지 않는다.
기본 HTTP 서버는 로컬 검증용이며 클라우드에서는 TLS reverse proxy와 운영용 서버 구성을 적용해야 한다.

| 메서드 | 경로 | 기능 |
| --- | --- | --- |
| GET | /health | 서버 응답 확인 |
| GET | /connection | 인증 및 조회 작업의 최근 heartbeat 확인 |
| PUT | /watches/{id} | settings(모바일 date/time 객체), token으로 등록·갱신 |
| GET | /watches/{id} | 감시·최근 발송 상태, 토큰은 응답하지 않음 |
| DELETE | /watches/{id} | 감시 중지, 이력 유지 |
| POST | /alerts/{id}/received | 기기의 실제 수신/열기 확인 |

health 외에는 Authorization: Bearer 연결키가 필요하다. 개인 단일 사용자 서비스이며 다중 사용자 서비스로 공개하지 않는다.

## 상태의 의미

- pending: 등록만 됨, 아직 실제 조회 안 됨.
- available/no_matching_seats: 검증된 조회 결과가 조건에 맞는지에 따른 상태.
- error/waiting/unknown/no_trains: 서로 구분하며 매진으로 치환하지 않음.
- ticket_accepted: Expo 접수. 휴대폰 수신 아님.
- provider_accepted: FCM/APNs 전달 접수. 휴대폰 수신 아님.
- device_received: 앱 수신/알림 열기 callback에서 확인 API 호출.
- uncertain/sending 상태로 남은 발송은 자동 재전송하지 않음. 프로세스가 전송 도중 종료된 경우 중복 여부를 확정할 수 없어 수동 확인 필요.

조회 결과는 2분 이내만 발송하고, Expo 메시지는 5분 TTL을 사용한다. 같은 조건 revision에서 새로운 열차·좌석 등급 조합을 발견하면 현재 예매 가능한 전체 열차를 감시당 푸시 1건으로 묶어 총 편수를 알린다. 같은 열차의 일반실·특실은 1편으로 계산한다. 이미 알린 조합만 남아 있으면 다시 보내지 않으며, 과거 개별 알림 이력도 중복 방지에 사용한다. 여러 감시는 각각 별도 알림을 받는다. 조회 완료 후 5분 뒤 다시 조회한다. 네트워크 재시도는 전달 결과가 불명확한 경우 중복 가능성이 있으므로 exactly-once 수신은 보장하지 않는다.

모바일 API 조회는 요청 간 최소 5초, 감시당 최대 8페이지, HTTP timeout 25초로 제한한다.
페이지가 남은 채 제한에 도달하면 부분 결과로 알리지 않는다. 비공식 API이므로 코레일 앱/API 변경에 따라 재검증이 필요하다.
