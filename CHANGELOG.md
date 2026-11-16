# Changelog

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
