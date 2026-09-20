# Render 배포

현재 설정은 상시 실행 Web Service 한 개와 SQLite 영구 디스크 1GB를 사용한다.
Render의 HTTPS 주소를 앱 서버 주소로 사용한다. API와 감시 작업은 하나의 프로세스에
있으므로 인스턴스를 늘리거나 별도 worker를 중복 실행하지 않는다.

## 업로드 범위

저장소 루트에 `render.yaml`과 `server/`를 둔다. `server/.local/`, DB, 연결 키,
Firebase 관리자 JSON, `.env`, `.venv`, `.tools`는 커밋하지 않는다.
현재 `mobile/`만 별도 Git 저장소이므로 서버를 포함하는 배포 저장소가 필요하다.

## 배포

1. Render에서 해당 저장소를 선택해 Blueprint를 생성한다.
2. Starter Web Service와 1GB 영구 디스크 비용을 확인한 후 생성한다.
3. 빌드 성공 후 `/health`가 200인지 확인한다.
4. Render 환경 변수의 `WAYBACKHOME_API_KEY`를 앱의 서버 연결 키에 입력한다.
   채팅이나 로그에 이 값을 공개하지 않는다.
5. 앱 서버 주소를 Render HTTPS 주소로 변경하고 감시 시작/갱신을 누른다.
6. `/connection`의 worker_live와 감시의 checked_at/error를 확인한다.
   클라우드 출발 IP에서도 코레일 조회가 되는지는 배포 후 확인해야 한다.

초기 배포는 새 DB로 시작한다. 기존 앱에 저장된 조건으로 감시를 등록할 수 있다.
로컬 알림 이력은 자동 이전하지 않으므로 첫 조회에서는 취합 알림이 한 번 올 수 있다.
로컬 DB와 키 파일은 삭제하지 않는다. Firebase 서비스 계정은 이 서버에서 사용하지
않는다(기존 Expo Push API를 통해 전송).

무료 Web Service는 유휴 시 중지되고 영구 디스크를 붙일 수 없어 현재 상시 감시
구조에 맞지 않는다. 가격은 Render 생성 화면에서 최종 확인한다.

참고: https://render.com/docs/disks · https://render.com/docs/free
