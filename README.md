# WayBackHome

KTX 좌석 감시와 Expo 푸시 알림을 위한 개인용 서버입니다.

- [서버 실행 및 API](server/README.md)
- [Render 배포 안내](docs/render-deployment.md)

`render.yaml`은 상시 실행 서버와 영속 디스크를 정의합니다. 서비스 생성 시 Render 요금을 확인하세요.

모바일 앱은 별도 Expo 프로젝트에서 빌드하며, 앱의 서버 연결 설정에 배포 URL과 연결 키를 입력합니다. 비밀 키, Firebase 서비스 계정, 사용자 데이터베이스는 저장소에 포함하지 않습니다.
