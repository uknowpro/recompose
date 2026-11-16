# recompose

**English** | [한국어](README.ko.md)

**From container configuration to native Java services on VMs.**

Inspect Docker Compose and Dockerfile inputs, review a migration plan, and generate a deployment bundle for running an executable Java JAR with **systemd + Ansible**. The target VM runs Java directly, without a container runtime.

[Quick start](#quick-start) · [Commands](#commands) · [Deployment bundle](#deployment-bundle) · [Scope](#scope-and-evidence) · [Roadmap](#roadmap)

> Early development · package version 0.4.0. Compose analysis is local; image extraction (including images selected through Compose) accesses the selected public registry. Executable JAR extraction is built in. Review the generated plan before deployment; end-to-end VM migration remains unverified.

## Features

| Capability | Available today |
| --- | --- |
| Built-in image access | Inspect public registry images or local OCI layouts and extract executable JARs without Docker, Skopeo or umoci. |
| Compose inspection | Inventory services, environment variable names and fields requiring review. Environment values are omitted from reports. |
| OS dependency review | Collect package candidates from simple `apt`, `apt-get`, `apk`, `dnf` and `yum` installation statements, with Dockerfile stage and logical-line evidence. |
| Explicit migration plans | Review the artifact, Java version, arguments, Ubuntu packages and required environment variables in YAML. |
| Native service generation | Generate a systemd unit and Ansible installation playbook for a single executable JAR. |
| Traceable artifacts | Copy the supplied JAR and record its SHA-256 checksum in a manifest. |
| Local generation | Generate deployment files without connecting to a cluster or modifying the destination VM. |

### Compose execution settings and supplemental files

```sh
./recompose extract --compose compose.yaml --service app --output extracted
# Use a local image instead of a registry pull:
./recompose extract --oci-layout image-layout --compose compose.yaml --service app \
  --include-file /app/config/ --output extracted-local
```

`extract --compose` uses the selected service's `image` unless `--image` or `--oci-layout` is provided. It merges `entrypoint`, `command` and `working_dir` with image metadata. Direct `java -jar` commands retain recognized JVM/application options and map referenced configuration, Java agents, loader JARs and native libraries beneath `/opt/<service>/rootfs`. `--include-file` is repeatable; a trailing `/` selects a directory. Files must be regular files in the final image filesystem; links and files hidden by Compose mounts are excluded.

Review `jvm_options`, `app_args`, `working_directory`, `artifact_destination` and `required_environment`. Each supplemental `files` entry requires `reviewed: true`, and every `review_items` entry requires `resolved: true` **after the issue is addressed**. Then set the plan's top-level `reviewed: true` and run `generate`. Changed supplemental file content invalidates its SHA-256; review it and update the checksum before generating again.

Shell wrappers, interpolation, unsupported arguments, agent option strings, manifest Class-Path dependencies and external Compose resources require manual resolution. Environment values are never copied. Obvious credential files and literal secrets in common configuration formats are omitted with a finding; screening is heuristic, so review every included file before sharing. Native libraries still require ABI, architecture and OS dependency checks. File collection is bounded to 256 retained candidates across layers. Full details: [runtime mapping](docs/runtime-mapping.md).

## Migration workflow

```text
Compose + optional Dockerfile
            |
         inspect     -> service inventory and package candidates
            |
           plan      -> migration-plan.yaml
            |
     operator review + supplied executable JAR
            |
         generate    -> systemd + Ansible + artifact bundle
            |
     operator-run deployment and application verification
```

A successful analysis is an inventory, not a compatibility certification. Review findings before choosing the destination runtime and deployment settings.

## Quick start

### 1. Run the Windows or Linux binary — no Python installation

Download the archive for your platform from [Releases](https://github.com/uknowpro/recompose/releases), verify its checksum and extract it:

```sh
tar -xzf recompose-linux-amd64.tar.gz
./recompose --version
./recompose inspect --image eclipse-temurin:21-jre --format json
```

Windows x64 example (PowerShell; choose x86 or arm64 for those machines):

```powershell
Expand-Archive .\recompose-windows-x64.zip -DestinationPath .\recompose
.\recompose\recompose.exe --version
.\recompose\recompose.exe inspect --image eclipse-temurin:21-jre --format json
```

| Platform | Download |
| --- | --- |
| Windows 32-bit (x86) | `recompose-windows-x86.zip` |
| Windows Intel/AMD 64-bit (x64) | `recompose-windows-x64.zip` |
| Windows ARM64 | `recompose-windows-arm64.zip` |
| Linux Intel/AMD 64-bit | `recompose-linux-amd64.tar.gz` |
| Linux ARM64 | `recompose-linux-arm64.tar.gz` |

Python and dependencies are embedded. No Docker, Skopeo or umoci installation is required. Windows x86/x64 binaries are tested on Windows Server 2022 (x86 through WOW64); Windows ARM64 is tested on Windows 11 ARM64. Linux ARM64 is tested on Ubuntu 24.04 ARM64. Linux was tested on Debian 12 and Ubuntu 24.04; glibc 2.36+ is the build baseline. Windows binaries are unsigned. Both platforms generate deployment files for Linux VMs. See [native binary usage and builds](docs/native-binary.md). Add the executable to PATH to use the `recompose` commands below without `./`.

### Alternative: install from source

Requires Python 3.10 or later. Run the following commands in a POSIX shell:

```sh
git clone https://github.com/uknowpro/recompose.git
cd recompose
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Docker, Skopeo, umoci and Syft are not required for image inspection or extraction either. Ansible is required separately on the control machine when deploying the generated bundle.

### Alternative Python archive and image input

The alternative `recompose.pyz` archive bundles dependencies but requires Python 3.10+. Use the native binary above when Python is unavailable. See [packaging and image extraction](docs/image-extraction.md) for build instructions, supported registries and limits.

```sh
python3 recompose.pyz inspect --image eclipse-temurin:21-jre --format json
# With source installation, use the equivalent command:
recompose inspect --image eclipse-temurin:21-jre --format json
```

For your application image, `recompose extract --image IMAGE --output extracted/app` creates a JAR, provenance report and unreviewed migration plan. Public anonymous pulls and local OCI layouts are supported; private registry login is not yet supported.

### 2. Inspect the example configuration

```sh
recompose inspect \
  --compose examples/compose.yaml \
  --dockerfile examples/Dockerfile
```

The checked-in examples are illustrative inputs. They do not include a runnable application or a published demo image.

### 3. Create and review a plan

```sh
recompose plan \
  --compose examples/compose.yaml \
  --dockerfile examples/Dockerfile \
  --service demo \
  --output migration-plan.yaml
```

Edit the generated file. The following shows the editable fields; retain its generated `analysis` section for reference:

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

Replace the artifact path with your own executable JAR. Relative paths resolve against the plan file's directory. The JAR must contain a `Main-Class` manifest entry; this check does not verify runtime compatibility. The memory settings above are examples, not sizing recommendations.

The selected Dockerfile stage provides a Java-major tag hint. When unavailable, `java_version` is `null` and must be set explicitly; a hint is not runtime verification. Confirm the application's Java requirements, external files, native libraries, ports and service connections before setting `reviewed: true`. Select only reviewed Ubuntu package names for `os_packages`.

### 4. Generate the deployment bundle

```sh
recompose generate --plan migration-plan.yaml --output dist/demo
```

The CLI refuses to overwrite an existing output directory or an existing `--output` analysis/plan file. Choose a new destination for subsequent runs.

### 5. Deploy to a test VM

Review the generated files, then prepare the deployment environment:

```sh
cd dist/demo
cp environment.example.yml environment.yml
# Edit environment.yml with the application's actual values.
ansible-playbook -i YOUR_VM, install.yml -e @environment.yml
```

Replace `YOUR_VM` with a reachable Ubuntu 24.04 host and configure SSH and privilege escalation for Ansible. Supply `recompose_environment: {}` when no variables are required. Keep actual environment values out of version control.

The playbook installs packages, creates a service account and directories, copies files, and enables the service. Verify service status, logs, application endpoints and external dependencies after deployment. A started process alone does not establish application health.

## Commands

`inspect` and `plan` accept `--format yaml|json` and `--build-target NAME`. `plan` also honors the selected service’s `build.target`. Use `recompose --version` to identify the CLI version.

| Command | Required arguments | Output |
| --- | --- | --- |
| `inspect` | One of `--compose PATH`, `--image REF`, `--oci-layout DIR` | YAML inventory; optional `--dockerfile PATH` and `--output PATH` |
| `plan` | `--compose PATH --service NAME` | YAML migration plan; optional `--dockerfile PATH` and `--output PATH` |
| `extract` | `--image REF` or `--oci-layout DIR`, plus `--output DIR` | JAR, image report and migration plan; optional `--jar PATH`, `--platform`, `--service` |
| `generate` | `--plan PATH --output DIRECTORY` | Deployment bundle and a YAML summary |
| `--help` | — | CLI usage; also available on each subcommand |

Successful commands return `0`, including inspection with review-required findings. Handled validation, argument and file errors return `2`. Exit `0` does not prove migration readiness. There is no `validate` or remote deployment command yet.

## Deployment bundle

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

| Destination on the VM | Purpose |
| --- | --- |
| `/opt/<service>/app.jar` | Application artifact |
| `/etc/<service>/app.env` | Root-owned environment file, mode `0600` |
| `/var/lib/<service>` | Service-owned working directory |
| `/etc/systemd/system/<service>.service` | Native service definition |

The generated service uses `/usr/bin/java`, restarts on failure and runs as a dedicated account. The playbook installs `openjdk-17-jre-headless` or `openjdk-21-jre-headless`. The playbook checks the major reported by `/usr/bin/java -version` and stops if it differs from the plan. Alternatives are not managed automatically.

## Scope and evidence

| Area | Current boundary |
| --- | --- |
| Target | Ubuntu 24.04; Java 17 or 21 selected by the operator |
| Application | One executable JAR plus reviewed, explicitly referenced configuration, agents and libraries |
| Compose | Single-service image/Compose execution merge during extraction; no interpolation, include resolution or multi-file merge |
| Dockerfile | Simple package-install statements; candidates remain `review-required` |
| Package requirements | Build-stage and runtime-stage candidates retain their stage; actual necessity and destination package mappings require review |
| Image access | Built-in public registry/OCI-layout inspection and bounded JAR extraction; inherited package inventory is not implemented |
| Networking and storage | Port mappings, service DNS, volume contents and external connections require explicit migration |
| Verification | Unit tests cover CLI behavior and generated structures; no real-VM deployment certification |

Dockerfile evidence uses logical line numbers after continuation joining. It is not always a physical file line number. Complex shell constructs, heredocs, downloaded installers and inherited packages are outside the current parser's coverage.

Environment values are omitted from the inventory, but paths, service names and package metadata remain visible. Inspect reports before sharing them. Generated Ansible playbooks change the target system only when you explicitly execute them.

## OpenJDK and base-image review

**Available in 0.2.0:** static Java base-image review with per-stage evidence, official `openjdk` image deprecation findings, EA/Alpine review flags and explicit unknowns. See the [Java image review guide](docs/java-image-review.md).

The Docker Official Image named `openjdk` is deprecated; its [official notice](https://hub.docker.com/_/openjdk) recommends replacement images. This does not mean that the OpenJDK project or every OpenJDK distribution is deprecated. Support must be checked for the selected vendor and Java release; see, for example, the [Temurin support policy](https://adoptium.net/support/).

The review separates the following questions; live support checks and execution verification remain future work:

| Question | Intended evidence |
| --- | --- |
| Should the source container image be replaced? | Image publisher, tag/digest, maintenance policy and base OS lifecycle |
| Which Java runtime should the VM use? | Application Java requirements, selected vendor support and target OS availability |
| Does the application need compatibility work? | JVM options, native libraries, architecture, libc, certificates and fonts |
| Is an upgrade verified? | Application tests and actual execution on the selected runtime |

Migrating to a VM does not inherently require rebuilding the source image first. Replacing an image distribution and upgrading the Java major version are separate decisions. Current commands report static findings and tag hints. They do not perform live lifecycle checks or automatically select replacement images.

## Development

```sh
python3 -m unittest discover -s tests -v
python3 -m recompose.cli --help
```

The implementation lives in `recompose/cli.py`, `recompose/java_images.py` and `recompose/images.py`, with separate inspection, planning and generation functions. Tests cover secret-value omission, plan review requirements, artifact validation, argument escaping, package-stage evidence and bundle generation.

## Roadmap

- [x] Static Compose inventory and Dockerfile package candidates
- [x] Reviewable Java migration plan
- [x] Executable JAR, systemd and Ansible bundle generation
- [x] Built-in image digest/config inspection and bounded executable-JAR extraction
- [x] Native Windows x86/x64/ARM64 and Linux amd64/ARM64 binaries with embedded Python runtime
- [x] Alternative single-file Python archive with bundled dependencies
- [ ] Private registry authentication and broader image format coverage
- [x] Direct `java -jar` option discovery and referenced file extraction
- [ ] Full Java runtime and transitive dependency verification
- [x] Static Java image review and official OpenJDK image deprecation findings
- [ ] Live distribution lifecycle and replacement-image compatibility assessment
- [ ] OS dependency classification and target-package mapping
- [ ] Test-VM deployment, health verification and rollback workflows
- [ ] WAR/Tomcat and additional Linux distributions
- [ ] Kubernetes inputs, including AKS/EKS dependency review
- [ ] Additional application runtimes

## Related projects

See the [open-source survey](docs/related-projects.md) for Syft, Skopeo, umoci, Trivy, Kantra, Docker Compose and Podlet: capabilities, declared licenses, integration priorities and boundaries. These tools are research candidates, not installation prerequisites. Version 0.3.0 implements the supported image-access subset internally.

## Feedback and contributions

Use [GitHub Issues](https://github.com/uknowpro/recompose/issues) for bugs and feature requests. Include the command, Python version, target environment and a minimal sanitized input. For code changes, include relevant tests and document unsupported cases.

## License

[MIT](LICENSE)
