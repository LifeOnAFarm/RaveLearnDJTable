# Contributing

Use Python 3.11+, NumPy and the unit suite described in README.md. Keep GPIO,
HTTP, file access, synthesis and remix processing outside audio callbacks.
Buffers crossing threads need explicit ownership; NumPy may release the GIL.
The engine is still soft real-time Python, not a hard real-time guarantee.

Include regression coverage and the hardware/OS, block size, sample rate and
before/after deadline statistics for audio changes. Do not claim latency or
dropout improvements from desktop unit tests alone.

Do not commit config.json, credentials, recordings, uploaded songs, generated
archives, virtual environments or SD images. Submit only media you may legally
redistribute and document its source/licence separately. Report security issues
as described in [SECURITY.md](SECURITY.md); do not post personal network details.

Before opening a pull request, run the checks in the README's "Development checks",
plus `sh -n deploy/*.sh` for any changed script. Shell scripts and Python files must use
LF line endings (`.gitattributes` enforces this). Changes to setup steps must update
[docs/INSTALL.md](docs/INSTALL.md) and [CHANGELOG.md](CHANGELOG.md) in the same pull request.
