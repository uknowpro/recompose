# Native executable distributions

Version 0.3.2 provides five platform builds. No Python, pip, Docker, Skopeo or umoci installation is needed to run recompose. The archives contain a single executable, license notices and build metadata.

| Machine | Archive | Raw executable | Test environment |
| --- | --- | --- | --- |
| Windows 32-bit Intel/AMD | recompose-windows-x86.zip | recompose-windows-x86.exe | Windows Server 2022 via WOW64 |
| Windows 64-bit Intel/AMD | recompose-windows-x64.zip | recompose-windows-x64.exe | Windows Server 2022 x64 |
| Windows ARM64 | recompose-windows-arm64.zip | recompose-windows-arm64.exe | Windows 11 ARM64 |
| Linux Intel/AMD 64-bit | recompose-linux-amd64.tar.gz | recompose-linux-amd64 | Ubuntu 24.04 x64 |
| Linux ARM64 | recompose-linux-arm64.tar.gz | recompose-linux-arm64 | Ubuntu 24.04 ARM64 |

Download from [Releases](https://github.com/uknowpro/recompose/releases). Each platform has a separately named SHA256SUMS file. `amd64` means Intel/AMD x86_64, not ARM64. ARM builds here mean 64-bit ARM; ARMv7/32-bit ARM and macOS are not included.

## Windows

Choose the ZIP matching the processor/OS architecture. In Windows Settings, check System → About → System type. Most Intel/AMD PCs use x64; ARM-based Windows machines use ARM64; a 32-bit Windows installation needs x86.

PowerShell example for x64:

```powershell
Get-FileHash .\recompose-windows-x64.zip -Algorithm SHA256
Expand-Archive .\recompose-windows-x64.zip -DestinationPath .\recompose
.\recompose\recompose.exe --version
.\recompose\recompose.exe inspect --image eclipse-temurin:21-jre --format json
```

The executable inside each ZIP is named `recompose.exe`; standalone download names include architecture to prevent confusion. Windows binaries are unsigned. Checksums verify file integrity, not publisher identity. Windows 10/11 Intel/AMD are intended desktop environments; automated x86 validation runs under WOW64 on a 64-bit server, not on a separate 32-bit OS installation. Windows ARM64 validation runs natively on Windows 11 ARM64.

Windows TLS uses the Windows certificate stores through the embedded runtime. Image paths always use POSIX separators even when host file paths use Windows syntax. Both Windows and Linux builds produce **Linux VM** deployment configurations; no Windows-service migration is implemented. Run Ansible deployment from a Linux control machine or WSL.

## Linux

```sh
tar -xzf recompose-linux-amd64.tar.gz
./recompose --version
```

Use the arm64 archive on 64-bit ARM Linux. Raw binaries require an executable permission (`chmod +x recompose-linux-arm64`, for example). Both builds use Debian 12/glibc 2.36 as their baseline; compatible kernel/loader/libc are required. Older glibc and Alpine/musl are outside the verified scope. The prior x64 build also passed a Debian 12 startup check.

The embedded runtime needs a writable temporary directory that permits executable mappings; set TMPDIR when /tmp is noexec. Normal OS trust and explicit SSL_CERT_FILE/SSL_CERT_DIR settings are respected. The Linux bundle includes build-time public roots as fallback on minimal systems without a CA file.

## Maintainer builds

Windows builds must use a matching Windows Python interpreter. The builder verifies the produced PE machine field, rather than trusting the filename.

```powershell
python -m pip install PyYAML==6.0.3 pyinstaller==6.22.3
python tools/build_windows.py --arch x64
python tools/smoke_native.py --binary dist/windows/recompose-windows-x64.exe
```

Use `--arch x86` with 32-bit Python, or `--arch arm64` with native ARM64 Python. CI uses Python 3.12 for x86/x64 and 3.13 for Windows ARM64.

Linux builds use Docker/Buildx only at build time:

```sh
sh tools/build_native.sh dist/native amd64
# On an ARM64 builder:
sh tools/build_native.sh dist/native-arm64 arm64
```

The Native builds workflow uses five independent jobs with native ARM runners. It runs the unit suite, builds executables, tests the frozen CLI with PATH empty through inspect → extract → generate (including non-ASCII paths), and checks Windows public-registry HTTPS access. It uploads only successful artifacts. Release publication is separate from the build workflow.

Build dependencies and notices are included; exact distribution packages are resolved at build time, so byte-for-byte reproducibility is not claimed. Native outputs stay outside Git.

## Scope

These checks validate CLI portability and artifact handling, not production Java startup or complete VM migration. Public anonymous registry access and local OCI layouts are supported. Private registry authentication remains unsupported. Ansible and target Java requirements apply to later deployment, not to running recompose.

The image platform selected by `--platform` is independent of the CLI host CPU. An ARM64 CLI can inspect an amd64 image without executing it; this does not prove that the application's native libraries are portable across architectures.
