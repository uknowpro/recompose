# Built-in image inspection and extraction

Introduced in 0.3.0 and extended in 0.4.0. **No Docker daemon, Skopeo, umoci or Syft installation is required.** Image access and bounded layer processing are implemented inside recompose with Python's standard library. These external projects remain research references, not runtime prerequisites.

## Native binary (recommended)

Version 0.4.0 provides Windows and Linux binaries, with Python embedded and no separate runtime installation. See [native binary usage](native-binary.md).

## Alternative Python archive

The single-file `recompose.pyz` includes recompose, pure-Python PyYAML, dependency version metadata and license texts. Running it requires Python 3.10+ with TLS support; no pip or separate Python packages are needed on the user's machine.

```sh
python3 recompose.pyz --version
python3 recompose.pyz inspect --image eclipse-temurin:21-jre --format json
```

Maintainers can build this file from an environment with the project's dependencies installed:

```sh
python3 tools/build_zipapp.py --output dist/recompose.pyz
python3 -I -S dist/recompose.pyz --version
```

The builder refuses to overwrite existing files and requires the installed PyYAML license. Source installation with `pip install .` remains supported. No public binary release or native executable is implied by the build command. Generated Ansible deployment still requires Ansible on the deployment control machine.

## Registry images

```sh
# Metadata only: fetch manifest/index and image config, not filesystem layers.
recompose inspect --image eclipse-temurin:21-jre --platform linux/amd64 --format json

# Replace the example reference with a public application image containing a JAR.
recompose extract --image registry.example.com/team/app:1.0 \
  --platform linux/amd64 --service app --output extracted/app

# Explicit selection when the command is a wrapper or candidates are ambiguous.
recompose extract --image registry.example.com/team/app:1.0 \
  --jar /app/application.jar --output extracted/selected
```

The Temurin example is a runtime image and is not expected to contain your application JAR. Extraction examples use a placeholder registry and require a real application image. `extract` downloads layers; it never starts a container or executes application scripts.

Public anonymous pulls over HTTPS are supported, including Bearer challenges used by Docker Hub. Registry credentials, Docker credential helpers, cloud login, private ECR/ACR repositories, HTTP registries, Docker-save archives and zstd layers are not supported in this version. Redirects must remain HTTPS, and bearer authorization is removed on cross-host redirects.

## Local OCI layout

For offline use, provide an already available OCI layout directory containing `oci-layout`, `index.json` and `blobs/sha256/`:

```sh
recompose inspect --oci-layout ./image-layout --format json
recompose extract --oci-layout ./image-layout --jar /app/app.jar --output extracted/local
```

No network requests occur in local-layout mode. The layout is an input format, not a requirement to install an OCI conversion tool. A public registry image can be read directly with `--image`.

## Output and review

```text
extracted/app/
├── app.jar
├── files/                 # reviewed supplemental file candidates
├── image-report.json
└── migration-plan.yaml
```

The report records index/manifest/config digests, platform, registry identity for remote inputs, JAR source path and SHA-256, and executable-JAR candidate paths. It includes environment variable names but excludes their values and unsupported argument values; recognized execution options are included.

Selection order: explicit `--jar`, a direct `java ... -jar PATH` effective image/Compose command, or a single executable-JAR candidate. If the command names a missing/non-executable JAR, extraction fails instead of silently choosing another. Multiple candidates without a direct selection require `--jar`. Symlink/hardlink JARs are not followed.

The generated plan remains `reviewed: false`. `JAVA_VERSION` from image environment provides a hint only; otherwise Java is `null`. Review JVM/application arguments, required environment variables, external files, native libraries and connection settings before approval. `required_environment` lists application environment names (excluding standard image runtime keys unless explicitly overridden by Compose). Values must be supplied separately. Use `extract --compose compose.yaml --service app` to merge execution settings. Review each supplemental file and resolve each finding before generation; see [runtime mapping](runtime-mapping.md).

```sh
# Edit extracted/app/migration-plan.yaml before generation.
recompose generate --plan extracted/app/migration-plan.yaml --output dist/app
```

## Supported processing and limits

- OCI and Docker schema-2 manifests; Linux amd64 or arm64, optional explicit variant.
- Platform selection is exact for OS/architecture; ambiguous indexes fail.
- SHA-256 descriptor size/digest verification for selected manifests, config and compressed blobs.
- Uncompressed tar and gzip layers; OCI whiteouts, opaque directories and upper-layer replacement.
- JAR and requested supplemental files are copied to generated temporary filenames. Archive paths, symlinks, hardlinks and device entries are never materialized on the host.
- Metadata: 8 MiB; each blob: 1 GiB; total fetched config/layers: 2 GiB; expanded layer reads: 4 GiB; entry payload: 512 MiB.
- At most 256 layers, 200,000 archive entries and 256 retained file candidates across layers. Oversized or unsupported inputs fail without publishing an extraction directory.
- Existing output directories are not overwritten. Temporary workspaces are cleaned on success/failure.

This is a bounded artifact reader, not a general-purpose OCI runtime or complete filesystem exporter. It does not inventory OS packages, execute Java to verify its version, rewrite entrypoint scripts, validate application bytecode, move databases or prove VM compatibility.

## Verification evidence

Automated tests cover local OCI extraction through deployment-bundle generation, mocked anonymous registry authentication/extraction, digest corruption, layer replacement, whiteouts, ambiguous candidates, traversal, links, platform selection and resource limits. A live public `eclipse-temurin:21-jre` metadata query was also verified during development. Synthetic JAR fixtures validate structure and byte preservation; they do not establish application startup correctness. Real VM deployment remains unverified.

Protocol references: [OCI layers](https://github.com/opencontainers/image-spec/blob/main/layer.md), [OCI distribution](https://github.com/opencontainers/distribution-spec/blob/main/spec.md), [registry authentication](https://docs.docker.com/reference/api/registry/auth/).
