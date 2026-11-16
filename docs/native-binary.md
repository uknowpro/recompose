# Native Windows and Linux executables

Version 0.3.2 provides self-contained Windows x64 and Linux x86_64 executables. **Users do not install Python, pip, Docker, Skopeo or umoci.** The Python interpreter and application dependencies are embedded in the executable.

## Run

Download `recompose-linux-amd64.tar.gz` and `SHA256SUMS` from the matching [release](https://github.com/uknowpro/recompose/releases). Verify the archive against its checksum, then:

```sh
tar -xzf recompose-linux-amd64.tar.gz
./recompose --version
./recompose inspect --image eclipse-temurin:21-jre --format json
```

The archive contains the executable, license notices and build metadata. If using the raw `recompose` asset instead, preserve its executable bit or run `chmod +x recompose`.

```sh
./recompose extract --image YOUR_PUBLIC_APP_IMAGE --output extracted/app
```

Replace the placeholder with a public application image. Existing image-mode limitations, including private-registry authentication, still apply. See [image extraction](image-extraction.md).

## Windows

Download `recompose-windows-amd64.zip` and `SHA256SUMS-windows.txt` from the matching release. Verify the archive hash with `Get-FileHash`, then:

```powershell
Expand-Archive .\recompose-windows-amd64.zip -DestinationPath .\recompose
.\recompose\recompose.exe --version
.\recompose\recompose.exe inspect --image eclipse-temurin:21-jre --format json
```

The `.exe` runs without Python, pip or Docker. It is unsigned; published checksums provide an integrity check, not publisher authentication. Windows Server 2022 x64 is the automated build/test environment; Windows 10/11 x64 are intended usage environments but are not separately tested here. Windows ARM64 and 32-bit builds are not provided.

Windows native TLS uses the Windows certificate stores through the embedded Python runtime. Windows host paths may contain spaces/non-ASCII text; image paths always use POSIX `/` separators. The executable generates **Linux VM** deployment files, not Windows services. Execute generated Ansible playbooks from a supported Linux control machine or WSL.

## Compatibility

- Linux x86_64, built on Debian 12 with glibc 2.36; tested on Debian 12 and Ubuntu 24.04.
- This is not a fully static executable: a compatible Linux kernel, loader and system C library are required. Older glibc systems and Alpine/musl are not covered.
- No administrator privileges are needed to inspect or extract images. The binary needs a writable temporary directory that permits loading executable code. Set `TMPDIR` if the system's `/tmp` is mounted `noexec`.
- Normal system CA certificates and explicit `SSL_CERT_FILE` / `SSL_CERT_DIR` settings are respected. On a minimal system without a CA file, the embedded Debian build-time public roots are used; update binaries to refresh that fallback trust store.
- macOS and ARM64 native binaries require separate platform builds and are not published by this workflow.
- Ansible is still required on the control machine when an operator runs the generated deployment playbook. Java is installed on the target VM by that playbook. Neither is required to run recompose itself.

## Maintainer build

Docker with Buildx is a build-time requirement only:

```sh
sh tools/build_native.sh
```

Outputs in `dist/native/`: `recompose`, `recompose-linux-amd64.tar.gz`, `SHA256SUMS`, `LICENSES/`, `BUILD-INFO.txt` and `BUILD-DEPENDENCIES.txt`. The builder refuses an existing destination. PyInstaller and PyYAML versions are pinned; the resolved transitive build packages are recorded. Distribution packages are fetched at build time, so this is not a byte-for-byte reproducible build claim.

The build runs the unit suite before packaging. The executable embeds license texts; the archive also includes them as readable files. No native output is committed to Git.

## Windows maintainer build and automation

On Windows x64 with x64 Python 3.12:

```powershell
python -m pip install PyYAML==6.0.3 pyinstaller==6.22.3
python -m unittest discover -s tests -v
python tools/build_windows.py
python tools/smoke_native.py --binary dist/windows/recompose.exe
```

The `Native builds` GitHub Actions workflow is manually dispatched. Windows and Linux jobs run unit tests, build executables and smoke-test the resulting binaries with PATH empty. The smoke test covers local OCI inspection, JAR extraction and deployment generation, including a non-ASCII output directory. The Windows job also checks public registry HTTPS access. Only successful jobs upload distribution artifacts; publication is a separate reviewed step.

## Verification

- 48 tests passed under the embedded runtime's Python 3.12 build environment.
- On a clean Ubuntu 24.04 container without Python or image tools, a non-root user executed the binary and extracted a synthetic OCI JAR with networking disabled.
- The same minimal Ubuntu environment successfully inspected a public Java image over HTTPS without installing extra packages.
- Debian 12 startup was checked separately.

Containers are used only as clean test/build environments here. This validates CLI distribution, not a real VM application migration or production application startup.

Packaging reference: [PyInstaller one-file mode](https://pyinstaller.org/en/stable/usage.html).
