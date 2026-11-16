# recompose

[English](README.md) | **한국어**

**컨테이너 구성을 VM의 네이티브 Java 서비스로.**

Docker Compose와 Dockerfile을 분석하고, 이전 계획을 검토한 뒤, 실행형 Java JAR을 **systemd + Ansible**로 운영할 배포 패키지를 생성합니다. 대상 VM은 컨테이너 런타임 없이 Java를 직접 실행합니다.

[빠른 시작](#quick-start) · [명령어](#commands) · [배포 패키지](#deployment-bundle) · [지원 범위](#scope) · [로드맵](#roadmap)

> 초기 개발 단계 · 패키지 버전 0.1.0. 현재 분석은 로컬 파일을 대상으로 수행합니다. 실행형 JAR을 직접 준비하고 계획을 검토해야 파일을 생성할 수 있습니다. 이미지 추출과 실제 VM 이전의 전체 과정 검증은 아직 구현되지 않았습니다.

## 주요 기능

| 기능 | 현재 제공 범위 |
| --- | --- |
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

### 1. 소스에서 설치

Python 3.10 이상이 필요합니다. 아래 명령은 POSIX 셸 기준입니다.

```sh
git clone https://github.com/uknowpro/recompose.git
cd recompose
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

현재 정적 분석 CLI에는 Docker가 필요하지 않습니다. 생성된 패키지를 배포할 때는 제어 머신에 Ansible을 별도로 설치해야 합니다.

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

Java 21은 계획의 기본값이며 자동 판별 결과가 아닙니다. Java 요구 버전, 외부 파일, 네이티브 라이브러리, 포트, 서비스 연결을 확인한 뒤 `reviewed: true`로 설정하세요. `os_packages`에는 검토한 Ubuntu 패키지 이름만 지정합니다.

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

| 명령 | 필수 인자 | 결과 |
| --- | --- | --- |
| `inspect` | `--compose PATH` | YAML 분석 결과. 선택적으로 `--dockerfile PATH`, `--output PATH` 지정 |
| `plan` | `--compose PATH --service NAME` | YAML 이전 계획. 선택적으로 `--dockerfile PATH`, `--output PATH` 지정 |
| `generate` | `--plan PATH --output DIRECTORY` | 배포 패키지와 YAML 요약 |
| `--help` | — | 사용법. 하위 명령에서도 제공 |

검토 필요 항목이 있는 분석을 포함해 정상 실행은 `0`을 반환합니다. 처리된 검증·인자·파일 오류는 `2`를 반환합니다. 종료 코드 `0`은 이전 준비 완료를 보장하지 않습니다. `validate`, 원격 배포, 이미지 추출 명령은 아직 없습니다.

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

서비스는 전용 계정으로 `/usr/bin/java`를 실행하고 실패 시 재시작합니다. playbook은 `openjdk-17-jre-headless` 또는 `openjdk-21-jre-headless`를 설치합니다. Java가 여러 개 설치된 VM에서는 `/usr/bin/java`가 선택하는 런타임을 확인해야 합니다. alternatives 설정은 자동 변경하지 않습니다.

<a id="scope"></a>

## 지원 범위와 근거

| 영역 | 현재 범위 |
| --- | --- |
| 대상 환경 | Ubuntu 24.04, 운영자가 선택하는 Java 17 또는 21 |
| 애플리케이션 | 패키지당 실행형 JAR 하나. 외부 파일은 복사하지 않음 |
| Compose | 정적 YAML 분석. 변수 치환, include, 다중 파일 병합, 이미지 기본 설정 해석 미지원 |
| Dockerfile | 단순 패키지 설치 구문. 후보는 `review-required` 상태 유지 |
| 패키지 요구 사항 | 빌드·실행 단계 정보를 보존. 실제 필요 여부와 대상 패키지 매핑은 검토 필요 |
| 베이스 이미지 | 이미지 조회, 상속된 패키지 목록, Java 배포판·버전 자동 판별 미지원 |
| 네트워크·스토리지 | 포트 매핑, 서비스 DNS, 볼륨 데이터, 외부 연결의 별도 이전 필요 |
| 검증 | CLI 동작과 생성 구조의 단위 테스트. 실제 VM 배포 검증 미완료 |

Dockerfile 근거는 줄 이어쓰기를 합친 논리적 줄 번호입니다. 실제 파일의 물리적 줄 번호와 다를 수 있습니다. 복잡한 셸, heredoc, 다운로드 설치, 베이스 이미지에 포함된 패키지는 현재 파서가 완전히 분석하지 않습니다.

분석 결과에서 환경변수 값은 제외하지만 경로, 서비스 이름과 패키지 정보는 표시합니다. 공유 전에 보고서를 확인하세요. 생성된 Ansible은 운영자가 실행할 때 대상 시스템을 변경합니다.

## OpenJDK와 베이스 이미지 검토

**예정 기능:** 원본 Java 이미지의 교체 필요성과 대상 VM의 런타임 선택을 근거 및 미확인 항목과 함께 제안합니다.

Docker Official Image 중 `openjdk`라는 이름의 이미지는 deprecated 상태이며, [공식 안내](https://hub.docker.com/_/openjdk)는 대체 이미지 사용을 권고합니다. 이는 OpenJDK 프로젝트나 모든 OpenJDK 배포판의 지원 종료를 의미하지 않습니다. 배포판과 Java 버전별 지원 정책을 확인해야 합니다. 예를 들어 [Temurin 지원 정책](https://adoptium.net/support/)을 참고할 수 있습니다.

계획 중인 진단은 다음 질문을 구분합니다.

| 질문 | 판단에 사용할 근거 |
| --- | --- |
| 원본 컨테이너 이미지를 교체해야 하는가? | 이미지 제공자, 태그·digest, 유지보수 정책, 기반 OS 수명주기 |
| VM에는 어떤 Java 런타임을 설치할 것인가? | 애플리케이션 요구 버전, 배포판 지원 정책, 대상 OS에서의 설치 가능성 |
| 호환성 보완이 필요한가? | JVM 옵션, 네이티브 라이브러리, CPU 아키텍처, libc, 인증서, 폰트 |
| 업그레이드가 검증되었는가? | 애플리케이션 테스트와 선택한 런타임에서의 실제 실행 |

VM 이전을 위해 반드시 원본 이미지를 먼저 재빌드해야 하는 것은 아닙니다. 이미지 배포판 교체와 Java 메이저 버전 업그레이드는 별도로 판단합니다. 현재 recompose 명령은 이 진단이나 대체 이미지 자동 선정을 수행하지 않습니다.

## 개발

```sh
python3 -m unittest discover -s tests -v
python3 -m recompose.cli --help
```

현재 구현은 `recompose/cli.py`에 있으며 분석·계획·생성 함수로 나뉩니다. 테스트는 환경변수 값 제외, 계획 검토 조건, 아티팩트 검증, 인자 이스케이프, 패키지 단계 근거와 배포 패키지 생성을 다룹니다.

<a id="roadmap"></a>

## 로드맵

- [x] Compose 정적 분석과 Dockerfile 패키지 후보 수집
- [x] 검토 가능한 Java 이전 계획
- [x] 실행형 JAR·systemd·Ansible 패키지 생성
- [ ] 이미지 digest·설정 분석과 안전한 아티팩트 추출
- [ ] Java 런타임·JVM 옵션·외부 의존성 탐지
- [ ] OpenJDK 배포판 및 베이스 이미지 교체 필요성 진단
- [ ] OS 의존성 분류와 대상 패키지 매핑
- [ ] 테스트 VM 배포·상태 검증·롤백 절차
- [ ] WAR/Tomcat과 추가 Linux 배포판
- [ ] AKS/EKS 의존성 검토를 포함한 Kubernetes 입력
- [ ] 다른 애플리케이션 런타임

## 피드백과 기여

버그와 기능 제안은 [GitHub Issues](https://github.com/uknowpro/recompose/issues)에 등록하세요. 실행 명령, Python 버전, 대상 환경과 민감 정보를 제거한 최소 입력을 함께 제공하면 도움이 됩니다. 코드 변경에는 관련 테스트와 지원하지 않는 경우에 대한 설명을 포함하세요.

## 라이선스

[MIT](LICENSE)
