# Visual Studio C1083 로그인 소스 파일 복구

`MobleKurly_MFc/MobleKurlyDashboard/` 폴더에 다음 네 파일이 반드시 함께 있어야 합니다.

- UiFont.h
- UiFont.cpp
- ThemedMessageBox.h
- ThemedMessageBox.cpp

`LoginDialog.cpp`, `LoginDialog.h`, `MobleKurlyApp.cpp`, `MobleKurlyDashboard.vcxproj`와 **같은 디렉터리**입니다.

## 권장 설치
1. Visual Studio를 종료합니다.
2. 전체 ZIP을 **새 폴더에 통째로 압축 해제**합니다. 이전 프로젝트의 파일만 부분 덮어쓰지 마세요.
3. `MobleKurly_MFc/MobleKurlyDashboard.sln`을 엽니다.
4. 구성 `Debug | x64`를 선택하고 `빌드 > 솔루션 정리` 후 `솔루션 다시 빌드`합니다.
5. 기존 config.ini를 쓰던 경우, 정상 확인 후 별도 백업본에서 새 실행파일 폴더로 복사합니다.

## 기존 프로젝트를 유지해야 한다면
`MobleKurly_Login_MissingFiles_Patch.zip` 안의 파일을 같은 경로에 복사하세요. `UiFont.cpp/.h`, `ThemedMessageBox.cpp/.h` 네 파일입니다.

## 주의
이 ZIP의 포함 파일과 프로젝트 참조 경로는 검사했으나, Windows/Visual Studio에서 실제 컴파일까지 검증하지는 않았습니다.
