# recompose

[English](README.md) | **한국어**

**컨테이너 구성을 VM의 네이티브 Java 서비스로.**

Docker Compose와 Dockerfile을 분석하고, 이전 계획을 검토한 뒤, 실행형 Java JAR을 **systemd + Ansible**로 운영할 배포 패키지를 생성합니다. 대상 VM은 컨테이너 런타임 없이 Java를 직접 실행합니다.

[빠른 시작](#quick-start) · [명령어](#commands) · [배포 패키지](#deployment-bundle) · [지원 범위](#scope) · [로드맵](#roadmap)

> 초기 개발 단계 · 패키지 버전 0.3.2. Compose 분석은 로컬에서 수행하며, 명시적인 `--image` 명령은 선택한 공개 레지스트리에 접속합니다. 실행형 JAR 추출 기능을 내장했습니다. 배포 전 계획 검토가 필요하며 실제 VM 이전의 전체 과정 검증은 아직 완료되지 않았습니다.

## 주요 기능

| 기능 | 현재 제공 범위 |
| --- | --- |
| 내장 이미지 처리 | Docker·Skopeo·umoci 없이 공개 이미지나 로컬 OCI 레이아웃을 조회하고 실행형 JAR을 추출합니다. |
| Compose 분석 | 서비스, 환경변수 이름, 검토 대상 필드를 수집합니다. 환경변수 값은 보고서에서 제외합니다. |
| OS 의존성 검토 | 단순한 `apt`, `apt-get`, `apk`, `dnf`, `yum` 설치 구문에서 패키지 후보와 Dockerfile 단계·논리적 줄 번호를 수집합니다. |
| 명시적 이전 계획 | 아티팩트, Java 버전, 실행 인자, Ubuntu 패키지와 필수 환경변수를 YAML로 검토합니다. |
| 네이티브 서비스 생성 | 단일 실행형 JAR용 systemd 서비스와 Ansible 설치 구성을 생성합니다. |
| 아티팩트 추적 | 제공한 JAR을 복사하고 manifest에 SHA-256 체크섬을 기록합니다. |
| 로컬 생성 | 클러스터에 접속하거나 대상 VM을 변경하지 않고 배포 파일을 생성합니다. |

## 이전 흐름

```text
Compose + 선택적 Dockerfile
            |
         inspect     -> 서비스 목록과 패키지 후보
            |
           plan      -> migration-plan.yaml
            |
     운영자 검토 + 실행형 JAR 제공
            |
         generate    -> systemd + Ansible + 아티팩트
            |
     운영자가 배포 실행 및 애플리케이션 검증
```

분석 성공은 현황 수집의 완료를 의미합니다. 대상 런타임과 배포 설정을 결정하기 전에 검토 항목을 확인해야 합니다.

<a id="quick-start"></a>

## 빠른 시작

### 1. Windows·Linux 바이너리 실행 — Python 설치 불필요

[Releases](https://github.com/uknowpro/recompose/releases)에서 운영체제에 맞는 압축 파일을 다운로드하고 체크섬을 확인한 뒤 실행합니다.

```sh
tar -xzf recompose-linux-amd64.tar.gz
./recompose --version
./recompose inspect --image eclipse-temurin:21-jre --format json
```

Windows x64에서는 PowerShell로 실행합니다.

```powershell
Expand-Archive .\recompose-windows-amd64.zip -DestinationPath .\recompose
.\recompose\recompose.exe --version
.\recompose\recompose.exe inspect --image eclipse-temurin:21-jre --format json
```

| 환경 | 다운로드 |
| --- | --- |
| Windows x64 | `recompose-windows-amd64.zip` 또는 `recompose.exe` |
| Linux x86_64 | `recompose-linux-amd64.tar.gz` 또는 `recompose` |

Python 런타임과 의존성이 실행 파일 안에 포함되어 있습니다. Docker·Skopeo·umoci도 설치할 필요가 없습니다. Windows 바이너리는 Windows Server 2022 러너에서 빌드·실행 검증합니다. Linux는 Debian 12와 Ubuntu 24.04에서 확인했으며 glibc 2.36 이상을 빌드 기준으로 합니다. Windows 바이너리는 코드 서명되지 않았습니다. 두 환경 모두 Linux VM용 배포 구성을 생성합니다. [바이너리 사용·빌드 안내](docs/native-binary.md)를 참고하세요. 실행 파일을 PATH에 추가하면 아래 명령을 `./` 없이 사용할 수 있습니다.

### 대안: 소스에서 설치

Python 3.10 이상이 필요합니다. 아래 명령은 POSIX 셸 기준입니다.

```sh
git clone https://github.com/uknowpro/recompose.git
cd recompose
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

이미지 조회·추출에도 Docker·Skopeo·umoci·Syft 설치가 필요하지 않습니다. 생성된 패키지를 배포할 때는 제어 머신에 Ansible을 별도로 설치해야 합니다.

### 대안 Python 아카이브와 이미지 입력

대안 배포물인 `recompose.pyz`는 Python 3.10 이상이 필요합니다. Python 설치 없이 사용하려면 위의 네이티브 바이너리를 사용하세요. 빌드 방법, 지원 레지스트리와 한계는 [이미지 추출 가이드](docs/image-extraction.md)에 정리했습니다.

```sh
python3 recompose.pyz inspect --image eclipse-temurin:21-jre --format json
# 소스 설치 방식에서는 다음과 같이 실행합니다.
recompose inspect --image eclipse-temurin:21-jre --format json
```

애플리케이션 이미지에 `recompose extract --image IMAGE --output extracted/app`을 실행하면 JAR, 출처 보고서와 미검토 이전 계획을 생성합니다. 공개 이미지의 익명 조회와 로컬 OCI 레이아웃을 지원하며, 사설 레지스트리 로그인은 아직 지원하지 않습니다.

### 2. 예제 구성 분석

```sh
recompose inspect \
  --compose examples/compose.yaml \
  --dockerfile examples/Dockerfile
```

저장소의 예제는 설명용 입력입니다. 실행 가능한 애플리케이션이나 공개된 데모 이미지를 포함하지 않습니다.

### 3. 계획 생성 및 검토

```sh
recompose plan \
  --compose examples/compose.yaml \
  --dockerfile examples/Dockerfile \
  --service demo \
  --output migration-plan.yaml
```

생성된 파일을 수정합니다. 아래는 편집할 필드의 예시이며, 생성된 `analysis` 항목은 참고용으로 유지합니다.

```yaml
schema_version: 1
service: demo
target: ubuntu-24.04
reviewed: true
artifact: /absolute/path/to/your-app.jar
java_version: 21
jvm_options:
  - -Xms256m
  - -Xmx512m
app_args: []
os_packages: []
required_environment:
  - SPRING_PROFILES_ACTIVE
```

`artifact`를 실제 실행형 JAR 경로로 바꾸세요. 상대 경로는 계획 파일의 디렉터리를 기준으로 해석합니다. JAR manifest에는 `Main-Class` 항목이 필요하며, 이 검사가 실행 호환성을 검증하지는 않습니다. 메모리 옵션은 예시이며 용량 산정 권고가 아닙니다.

선택한 Dockerfile 단계의 태그에서 Java 메이저 버전 단서를 찾습니다. 알 수 없으면 `java_version`은 `null`이며 직접 지정해야 합니다. 태그 단서는 실제 런타임 검증 결과가 아닙니다. Java 요구 버전, 외부 파일, 네이티브 라이브러리, 포트, 서비스 연결을 확인한 뒤 `reviewed: true`로 설정하세요. `os_packages`에는 검토한 Ubuntu 패키지 이름만 지정합니다.

### 4. 배포 패키지 생성

```sh
recompose generate --plan migration-plan.yaml --output dist/demo
```

기존 출력 디렉터리와 분석·계획의 `--output` 파일은 덮어쓰지 않습니다. 다시 실행할 때는 새로운 출력 경로를 지정하세요.

### 5. 테스트 VM에 배포

생성된 파일을 검토하고 배포 환경변수를 준비합니다.

```sh
cd dist/demo
cp environment.example.yml environment.yml
# environment.yml에 애플리케이션의 실제 값을 입력합니다.
ansible-playbook -i YOUR_VM, install.yml -e @environment.yml
```

`YOUR_VM`을 접속 가능한 Ubuntu 24.04 호스트로 바꾸고 Ansible의 SSH 접속과 권한 상승을 설정하세요. 환경변수가 없어도 `recompose_environment: {}`를 제공합니다. 실제 환경변수 값은 버전 관리에 포함하지 마세요.

playbook은 패키지 설치, 서비스 계정·디렉터리 생성, 파일 복사와 서비스 활성화를 수행합니다. 배포 후 서비스 상태, 로그, 애플리케이션 엔드포인트와 외부 연동을 확인하세요. 프로세스 시작만으로 애플리케이션 정상 동작을 판단할 수는 없습니다.

<a id="commands"></a>

## 명령어

`inspect`와 `plan`은 `--format yaml|json`, `--build-target NAME`을 지원합니다. `plan`은 선택한 서비스의 `build.target`도 반영합니다. CLI 버전은 `recompose --version`으로 확인합니다.

| 명령 | 필수 인자 | 결과 |
| --- | --- | --- |
| `inspect` | `--compose PATH`, `--image REF`, `--oci-layout DIR` 중 하나 | YAML 분석 결과. 선택적으로 `--dockerfile PATH`, `--output PATH` 지정 |
| `plan` | `--compose PATH --service NAME` | YAML 이전 계획. 선택적으로 `--dockerfile PATH`, `--output PATH` 지정 |
| `extract` | `--image REF` 또는 `--oci-layout DIR`, `--output DIR` | JAR·이미지 보고서·이전 계획. `--jar PATH`, `--platform`, `--service` 선택 가능 |
| `generate` | `--plan PATH --output DIRECTORY` | 배포 패키지와 YAML 요약 |
| `--help` | — | 사용법. 하위 명령에서도 제공 |

검토 필요 항목이 있는 분석을 포함해 정상 실행은 `0`을 반환합니다. 처리된 검증·인자·파일 오류는 `2`를 반환합니다. 종료 코드 `0`은 이전 준비 완료를 보장하지 않습니다. `validate`와 원격 배포 명령은 아직 없습니다.

<a id="deployment-bundle"></a>

## 배포 패키지

```text
dist/demo/
├── artifacts/
│   └── app.jar
├── service.service
├── install.yml
├── app.env.j2
├── environment.example.yml
├── manifest.json
└── RUNBOOK.md
```

| VM 경로 | 용도 |
| --- | --- |
| `/opt/<service>/app.jar` | 애플리케이션 아티팩트 |
| `/etc/<service>/app.env` | root 소유 환경변수 파일, 권한 `0600` |
| `/var/lib/<service>` | 서비스 계정 소유 작업 디렉터리 |
| `/etc/systemd/system/<service>.service` | 네이티브 서비스 정의 |

서비스는 전용 계정으로 `/usr/bin/java`를 실행하고 실패 시 재시작합니다. playbook은 `openjdk-17-jre-headless` 또는 `openjdk-21-jre-headless`를 설치합니다. playbook은 `/usr/bin/java -version`의 메이저 버전이 계획과 다르면 배포를 중단합니다. alternatives 설정은 자동 변경하지 않습니다.

<a id="scope"></a>

## 지원 범위와 근거

| 영역 | 현재 범위 |
| --- | --- |
| 대상 환경 | Ubuntu 24.04, 운영자가 선택하는 Java 17 또는 21 |
| 애플리케이션 | 패키지당 실행형 JAR 하나. 외부 파일은 복사하지 않음 |
| Compose | 정적 YAML 분석. 변수 치환, include, 다중 파일 병합, 이미지 기본 설정 해석 미지원 |
| Dockerfile | 단순 패키지 설치 구문. 후보는 `review-required` 상태 유지 |
| 패키지 요구 사항 | 빌드·실행 단계 정보를 보존. 실제 필요 여부와 대상 패키지 매핑은 검토 필요 |
| 이미지 처리 | 공개 레지스트리·OCI 레이아웃 조회와 제한된 JAR 추출 내장. 상속된 패키지 목록 수집은 미지원 |
| 네트워크·스토리지 | 포트 매핑, 서비스 DNS, 볼륨 데이터, 외부 연결의 별도 이전 필요 |
| 검증 | CLI 동작과 생성 구조의 단위 테스트. 실제 VM 배포 검증 미완료 |

Dockerfile 근거는 줄 이어쓰기를 합친 논리적 줄 번호입니다. 실제 파일의 물리적 줄 번호와 다를 수 있습니다. 복잡한 셸, heredoc, 다운로드 설치, 베이스 이미지에 포함된 패키지는 현재 파서가 완전히 분석하지 않습니다.

분석 결과에서 환경변수 값은 제외하지만 경로, 서비스 이름과 패키지 정보는 표시합니다. 공유 전에 보고서를 확인하세요. 생성된 Ansible은 운영자가 실행할 때 대상 시스템을 변경합니다.

## OpenJDK와 베이스 이미지 검토

**0.2.0 제공 기능:** 단계별 근거와 함께 Java 베이스 이미지를 정적으로 검토합니다. 공식 `openjdk` 이미지 폐기 안내, EA·Alpine 검토 항목, 미확인 상태를 표시합니다. 자세한 내용은 [Java 이미지 진단 가이드](docs/java-image-review.md)를 참고하세요.

Docker Official Image 중 `openjdk`라는 이름의 이미지는 deprecated 상태이며, [공식 안내](https://hub.docker.com/_/openjdk)는 대체 이미지 사용을 권고합니다. 이는 OpenJDK 프로젝트나 모든 OpenJDK 배포판의 지원 종료를 의미하지 않습니다. 배포판과 Java 버전별 지원 정책을 확인해야 합니다. 예를 들어 [Temurin 지원 정책](https://adoptium.net/support/)을 참고할 수 있습니다.

진단은 다음 질문을 구분합니다. 실시간 지원 정책 조회와 실행 검증은 향후 범위입니다.

| 질문 | 판단에 사용할 근거 |
| --- | --- |
| 원본 컨테이너 이미지를 교체해야 하는가? | 이미지 제공자, 태그·digest, 유지보수 정책, 기반 OS 수명주기 |
| VM에는 어떤 Java 런타임을 설치할 것인가? | 애플리케이션 요구 버전, 배포판 지원 정책, 대상 OS에서의 설치 가능성 |
| 호환성 보완이 필요한가? | JVM 옵션, 네이티브 라이브러리, CPU 아키텍처, libc, 인증서, 폰트 |
| 업그레이드가 검증되었는가? | 애플리케이션 테스트와 선택한 런타임에서의 실제 실행 |

VM 이전을 위해 반드시 원본 이미지를 먼저 재빌드해야 하는 것은 아닙니다. 이미지 배포판 교체와 Java 메이저 버전 업그레이드는 별도로 판단합니다. 현재 명령은 정적 진단과 태그 단서를 제공합니다. 실시간 지원 정책 조회나 대체 이미지 자동 선정은 수행하지 않습니다.

## 개발

```sh
python3 -m unittest discover -s tests -v
python3 -m recompose.cli --help
```

현재 구현은 `recompose/cli.py`, `recompose/java_images.py`, `recompose/images.py`에 있으며 분석·계획·생성 함수로 나뉩니다. 테스트는 환경변수 값 제외, 계획 검토 조건, 아티팩트 검증, 인자 이스케이프, 패키지 단계 근거와 배포 패키지 생성을 다룹니다.

<a id="roadmap"></a>

## 로드맵

- [x] Compose 정적 분석과 Dockerfile 패키지 후보 수집
- [x] 검토 가능한 Java 이전 계획
- [x] 실행형 JAR·systemd·Ansible 패키지 생성
- [x] 이미지 digest·설정 분석과 제한된 실행형 JAR 추출 내장
- [x] Python 런타임을 포함한 Windows x64·Linux x86_64 네이티브 바이너리
- [x] 대안 배포물인 단일 파일 Python 아카이브
- [ ] 사설 레지스트리 인증과 추가 이미지 형식
- [ ] Java 런타임·JVM 옵션·외부 의존성 탐지
- [x] Java 이미지 정적 진단과 공식 OpenJDK 이미지 폐기 안내
- [ ] 배포판 실시간 지원 정책 및 대체 이미지 호환성 진단
- [ ] OS 의존성 분류와 대상 패키지 매핑
- [ ] 테스트 VM 배포·상태 검증·롤백 절차
- [ ] WAR/Tomcat과 추가 Linux 배포판
- [ ] AKS/EKS 의존성 검토를 포함한 Kubernetes 입력
- [ ] 다른 애플리케이션 런타임

## 관련 오픈소스

[오픈소스 조사 문서](docs/related-projects.md)에 Syft, Skopeo, umoci, Trivy, Kantra, Docker Compose, Podlet의 역할·선언된 라이선스·연동 우선순위·한계를 정리했습니다. 조사 후보이며 사용자 설치 요건은 아닙니다. 0.3.0은 지원 범위의 이미지 처리를 내부에 직접 구현했습니다.

## 피드백과 기여

버그와 기능 제안은 [GitHub Issues](https://github.com/uknowpro/recompose/issues)에 등록하세요. 실행 명령, Python 버전, 대상 환경과 민감 정보를 제거한 최소 입력을 함께 제공하면 도움이 됩니다. 코드 변경에는 관련 테스트와 지원하지 않는 경우에 대한 설명을 포함하세요.

## 라이선스

[MIT](LICENSE)
