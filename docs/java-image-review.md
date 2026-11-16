# Java image review

Available in 0.2.0. Rules last reviewed on 2026-11-16.

```sh
recompose inspect --compose examples/compose.yaml --dockerfile examples/Dockerfile --format json
recompose plan --compose examples/compose.yaml --dockerfile examples/Dockerfile --service demo --output migration-plan.yaml
```

The report adds `java_image_review` with stage evidence, the selected stage, a Java-major hint and rule findings. Dockerfile FROM evidence uses physical start-line numbers. Package-candidate evidence retains the previous logical-line behavior.

The final stage is selected by default. `--build-target NAME` selects a named stage. `plan` also reads the selected service's `build.target` unless a CLI target overrides it. The supplied Dockerfile is operator-selected: recompose does not automatically locate Dockerfiles or associate one file with every Compose service. Use it for the service being planned. Inspect does not infer a target from multiple services.

Previous named-stage inheritance is followed. ARG substitutions, custom escape directives and heredocs are not interpreted; the latter two are rejected for this analysis. Known official Docker Hub Java image names are recognized, including explicit Docker Hub/library prefixes. Private images with the same basename are not assumed to be official images.

| Code | Meaning |
| --- | --- |
| `JAVA_OPENJDK_IMAGE_DEPRECATED` | The official `openjdk` image has a replacement recommendation, based on its upstream deprecation notice |
| `JAVA_VENDOR_SUPPORT_UNVERIFIED` | A known distribution is recognized, but its patch/lifecycle support has not been checked |
| `JAVA_EARLY_ACCESS` | The recognized image tag indicates EA |
| `JAVA_LIBC_REVIEW` | The recognized image tag suggests Alpine; review native dependencies for Ubuntu |
| `IMAGE_DIGEST_UNPINNED` | The image reference does not include a SHA-256 digest |
| `JAVA_VERSION_UNKNOWN` | No reliable major-version hint is available |
| `JAVA_IMAGE_UNKNOWN` | The Java distribution cannot be inferred |
| `JAVA_IMAGE_UNRESOLVED` | The reference includes unresolved variables or unsupported syntax |

Each finding contains a message, action, official source and policy review date. The [OpenJDK Docker image notice](https://hub.docker.com/_/openjdk) is the source for the deprecation rule. [Dockerfile FROM semantics](https://docs.docker.com/reference/dockerfile/#from) inform stage/reference handling; compatibility actions are recompose review guidance, not upstream compatibility guarantees.

## Runtime planning

`java_version` now uses the selected stage's tag hint. If unavailable, it is `null`; generation requires an explicit supported selection. A detected major such as 8 is retained in the plan instead of silently upgraded, but the current generator supports only 17 and 21. `java_version_evidence` records `tag-hint-only` or `unknown`.

Tags are not runtime proof. Later RUN/COPY instructions can replace Java, application bytecode can require another version, and the image may not match the Dockerfile. The plan still requires operator review. Do not interpret this as automatic JAR compatibility detection.

The generated playbook checks `/usr/bin/java -version` after installing packages and stops before copying application files if its major differs from the plan. It does not change alternatives or verify vendor/patch support.

## Boundaries

No registry contact, image extraction, CVE assessment, live lifecycle lookup, automatic FROM rewrite or major-version upgrade occurs. Image replacement for continued container operation is separate from selecting the VM runtime. Unknown/support-unverified is never reported as healthy or supported.

Research and proposed integrations: [related projects](related-projects.md).
