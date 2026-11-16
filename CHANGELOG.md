# Changelog

## 0.3.2 — 2026-11-16

- Add Windows x86/x64/ARM64 executables and ZIP distributions with embedded Python and license texts.
- Add Linux ARM64 and five-platform native-build automation with frozen-executable smoke checks and explicit architecture filenames.
- Keep container paths POSIX on Windows, read input text as UTF-8, and use Windows system trust for HTTPS.
- Windows execution remains a CLI host capability; generated deployment files still target Linux VMs.

## 0.3.1 — 2026-11-16

- Add a native Linux x86_64 executable with embedded Python, dependencies, license texts and fallback CA certificates.
- Add a containerized maintainer build and checksummed distribution archive.
- Verify non-root extraction and live HTTPS image inspection on Ubuntu 24.04 without Python or external image tools.

## 0.3.0 — 2026-11-16

- Add built-in public OCI/Docker schema-2 registry inspection and local OCI-layout input.
- Add executable-JAR extraction, digest/size verification, platform selection, layer whiteouts and bounded processing.
- Generate an unreviewed migration plan and provenance report alongside the extracted JAR.
- Add a single-file Python zipapp builder bundling pure-Python PyYAML and license texts; no external image tools are required.
- Preserve existing Compose/Dockerfile inspection and native VM deployment generation.

Supported registry mode is anonymous HTTPS. Private authentication, zstd, Docker-save archives, Compose/image merge, OS package inventory and actual VM deployment validation remain outside this release's verified scope. The single-file CLI requires Python 3.10+; Ansible remains a deployment-side prerequisite.

Validation: 48 tests, standalone OCI extraction with empty PATH and Python site packages disabled, and live public Java-image metadata inspection. Generated artifacts were tested structurally; no production application or target VM was deployed.

## 0.2.0 — 2026-11-16

- Java Dockerfile image review, stage/target selection, explicit unknown runtime versions, JSON output and deployment Java-major checks.

## 0.1.0 — 2026-11-16

- Initial Compose/Dockerfile inventory, reviewable plans and executable-JAR Ansible/systemd generation.
