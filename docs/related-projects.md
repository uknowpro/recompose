# Related open-source projects

Reviewed: 2026-11-16. This is a source-based design survey, not an integration benchmark. None of these projects is bundled with or invoked by recompose. Version 0.3.0 implements a bounded OCI/registry reader internally so users do not install image tools. The adapter proposals below remain future alternatives, not installation requirements. Licenses below are those declared by the linked upstream repositories; dependencies and redistribution notices need review at a pinned integration version.

## Recommended integration order

1. **Syft JSON import:** enrich OS/Java package inventory without implementing every package database parser. Preserve source-image digest and cataloger evidence. Presence is not proof of runtime necessity.
2. **Skopeo + umoci adapter:** inspect/copy an explicit image to OCI layout, then unpack its merged filesystem in an isolated workspace. Record platform and digest before selecting JARs. Never execute the image to inspect it.
3. **Kantra report import:** attach Java migration findings when source or suitable application artifacts are available. Keep compatibility findings separate from deployment generation.
4. **Optional Trivy evidence:** attach scan results and database timestamps to image review. A scan cannot establish application compatibility or prove an image safe.

These are proposed engineering choices based on the projects' documented roles, not implemented capabilities.

## Comparison

| Project / upstream source | Declared license | Relevant capability | Proposed use in recompose | Boundary |
| --- | --- | --- | --- | --- |
| [Syft](https://github.com/anchore/syft) | Apache-2.0 | SBOM generation from container images and filesystems | Import discovered OS and Java packages with evidence | Installed packages may be unused; an SBOM does not map all dependencies to Ubuntu packages |
| [Skopeo](https://github.com/podman-container-tools/skopeo) | Apache-2.0 | Inspect and copy images across registries and storage transports | Resolve digest/platform and stage images without running application containers | Does not generate native VM services or determine Java compatibility |
| [umoci](https://github.com/opencontainers/umoci) | Apache-2.0 | Manipulate OCI images and unpack image bundles | Reconstruct a filesystem before artifact selection | Unpacked paths, ownership, links and extraction limits still need an isolation policy |
| [Trivy](https://github.com/aquasecurity/trivy) | Apache-2.0 | Vulnerability, configuration, secret and SBOM scanning | Optional supporting findings for image replacement review | Results depend on scan scope and vulnerability data freshness; not a migration engine |
| [Kantra](https://github.com/konveyor/kantra) | Apache-2.0 | Konveyor analysis and transformation CLI with Java tooling | Explore Java source/application compatibility analysis and report import | Runtime prerequisites and rules must be selected for the intended migration |
| [Docker Compose](https://github.com/docker/compose) | Apache-2.0 | Compose application definition and execution | Reference semantics and consider an explicit normalized-config input path | Configuration resolution may expose environment values; recompose must redact before reporting |
| [Podlet](https://github.com/containers/podlet) | MPL-2.0 | Generate Podman Quadlet files from commands, Compose or existing objects | Reference conversion UX, unsupported-field reporting and systemd integration | Output still uses containers; it does not meet recompose's native-VM target |

## Architectural implications

Use optional external tools behind versioned adapters, with structured output, explicit timeouts and bounded input/output. Keep the core CLI usable for local-file analysis without automatically downloading tools, images or vulnerability databases.

The internal evidence model should associate each fact with its source: Dockerfile location, image digest, tool/version, artifact checksum, rule identifier and collection date. Conflicting evidence must remain visible. An image tag is a version hint; a runtime inspection or JAR requirement is a different evidence level.

For image extraction, test multi-platform selection, layer whiteouts, symbolic links, hard links, oversized files, registry authentication, offline operation and cleanup after failure. Start with non-executing artifact discovery before automatically generating a deployment.

For Java analysis, retain the source Java major until an explicit upgrade is selected and tested. Separate distribution replacement from language/runtime upgrades and from migration to a VM.

## Next proof of concept

Use three fixtures: a simple executable JAR, a multi-stage build, and a Java app with a native/font dependency. Compare the Dockerfile candidates with Syft's inventory, extract the same JAR via an OCI workflow, and compare its checksum with the build artifact. Validate execution on a clean Ubuntu VM separately.

Acceptance criteria: reproducible input digest, no execution of the source application during inspection, traceable package findings, explicit unknowns, bounded extraction, and no credentials in reports.

## Current conclusion

The strongest near-term combination is **Syft for inventory + Skopeo/umoci for image access and extraction**, with recompose owning the native-VM execution model, review decisions and Ansible/systemd output. Kantra and Trivy are complementary evidence providers. Podlet is a useful adjacent project, but its container-based target differs from this project's objective.
