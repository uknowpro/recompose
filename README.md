# recompose

Reverse Compose: Java 컨테이너 애플리케이션을 VM의 네이티브 서비스로 이전하기 위한 도구입니다.

## 현재 상태: 초기 개발 버전

- Compose의 서비스와 환경변수 이름을 분석합니다. 환경변수 값은 보고하지 않습니다.
- Dockerfile의 apt/apk/dnf/yum 설치 명령에서 OS 패키지 **검토 후보**를 수집합니다.
- 사용자가 검토할 Java 이전 계획을 생성합니다.
- 검토한 실행형 JAR로 systemd 서비스와 Ubuntu 24.04용 Ansible 설치 패키지를 생성합니다.
- 생성 파일을 만들 뿐 서버에 접속하거나 설치를 수행하지 않습니다.

이미지 검사·JAR 자동 추출, Java 버전 자동 판별, Kubernetes 입력, DB 이전, 자동 롤백은 아직 지원하지 않습니다. 이미지에서 꺼낸 JAR 및 외부 설정/라이브러리의 완전성은 사용자가 확인해야 합니다. 현재 생성기는 단일 실행형 JAR만 복사합니다.

## 설치 및 실행

Python 3.10 이상이 필요합니다.

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
recompose inspect --compose examples/compose.yaml --dockerfile examples/Dockerfile
recompose plan --compose examples/compose.yaml --service demo --output migration-plan.yaml
```

계획 파일의 `artifact`에 계획 파일 기준 상대 경로 또는 절대 JAR 경로를 지정합니다. `java_version`, `jvm_options`, `app_args`, `os_packages`, `required_environment`를 검토한 후 `reviewed: true`로 설정합니다. Java 21은 초기 기본값이며 자동 판별 결과가 아닙니다.

```sh
recompose generate --plan migration-plan.yaml --output dist/demo
```

이미 존재하는 출력 디렉터리나 계획 파일은 덮어쓰지 않습니다. 결과물에는 JAR, SHA-256 manifest, systemd unit, Ansible playbook, 환경변수 예제와 실행 안내가 포함됩니다.

## 배포 전 확인

- 원본의 command/entrypoint, 포트, 볼륨, 실행 사용자, 외부 설정, JNI, agent를 검토하세요. 자동 이식되지 않습니다.
- OS 패키지 목록은 빌드/런타임 단계의 후보일 뿐입니다. 최종 이미지와 실제 사용 여부를 확인하고 Ubuntu 패키지 이름으로 직접 확정하세요.
- Dockerfile 파서는 단순 설치 구문만 지원합니다. 베이스 이미지 패키지, 복잡한 셸, heredoc, 다운로드 설치는 완전히 분석하지 않습니다.
- Compose 변수 치환, include, 다중 파일 병합, 이미지 기본 실행 설정을 해석하지 않습니다.
- `/usr/bin/java`가 계획의 Java 버전을 가리키는지 확인하세요. 이미 여러 JDK가 설치된 VM의 alternatives를 자동 변경하지 않습니다.
- systemd는 `/var/lib/<service>`를 작업 디렉터리로 사용합니다. 포트 매핑과 서비스 DNS는 애플리케이션 설정에서 조정하세요.
- `environment.example.yml`을 복사하고 값을 입력한 파일을 안전하게 관리하세요. 비밀 값은 Git에 넣지 마세요. 배포에는 `recompose_environment` 매핑이 필요합니다.
- 패키지 설치·계정·설정·서비스 변경이 발생합니다. 생성된 Ansible을 검토한 후 테스트 VM에서 실행하세요.

```sh
cd dist/demo
ansible-playbook -i YOUR_VM, install.yml -e @environment.yml
```

서비스 시작은 애플리케이션 정상 동작을 보장하지 않습니다. 서비스 상태, 로그, HTTP 요청과 외부 연동을 별도로 확인하세요. Ansible은 컨트롤 머신에 별도로 설치해야 합니다.

## 개발

```sh
python3 -m unittest discover -s tests -v
```

`recompose/cli.py`에 분석, 계획, 생성 단계를 나눠 구현했습니다. 추후 이미지 입력과 Java 분석을 독립 모듈로 분리하고 공통 실행 모델을 확장할 예정입니다.

다음 개발 순서: 이미지 digest/설정 분석 → 안전한 JAR 추출 → Java 실행 정보 판별 → 실제 VM 통합 테스트 → OS 의존성 판별 → Kubernetes 입력.

기존 MIT 라이선스를 따릅니다.
