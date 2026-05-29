# Installation

## Recommended bootstrap install

Linux and macOS:

```bash
curl -LsSf https://raw.githubusercontent.com/AlfonsoDehesa/recollectium/main/install.sh | sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/AlfonsoDehesa/recollectium/main/install.ps1 | iex"
```

The bootstrap installer:

- Installs uv if needed.
- Installs Recollectium in an isolated tool environment.
- Runs `recollectium init`.
- Creates config, data, cache, logs, and runtime directories.
- Creates and migrates the SQLite database.
- Downloads the built-in FastEmbed model cache.
- Installs shell completion in a managed block when safe.

## Package manager installs

If you already have Python 3.12 or newer:

```bash
pip install recollectium
```

For isolated CLI installs:

```bash
pipx install recollectium
uv tool install recollectium
```

Try without a permanent install:

```bash
uvx recollectium --version
```

After package-manager installs, initialize once:

```bash
recollectium init
```

## Development install

```bash
git clone https://github.com/AlfonsoDehesa/recollectium.git
cd recollectium
uv sync --group dev
uv run recollectium --help
```

## Shell completion

Bootstrap install sets up completion automatically for supported shells when safe.

Manual install:

```bash
recollectium completion --install
recollectium completion --install bash
recollectium completion --install zsh
recollectium completion --install fish
```

PowerShell:

```powershell
recollectium completion --install powershell
```

Print setup instructions instead of installing:

```bash
recollectium completion bash
recollectium completion zsh
recollectium completion fish
recollectium completion powershell
```

Print the raw completion source:

```bash
recollectium completion bash --source
```

## Upgrade

```bash
recollectium upgrade
```

Non-mutating checks:

```bash
recollectium upgrade --check
recollectium upgrade --dry-run
```

Override install-method detection when needed:

```bash
recollectium upgrade --install-method pip
recollectium upgrade --install-method pipx
recollectium upgrade --install-method uv_tool
recollectium upgrade --install-method source
```

If a managed API or MCP service is running, Recollectium stops it, upgrades the package, then restarts the same service type when the upgrade succeeds.

## Uninstall

Safe uninstall preserves memories and local data:

```bash
recollectium uninstall
```

Preview a destructive purge:

```bash
recollectium uninstall --purge --dry-run
```

Permanently delete Recollectium-owned config, data, cache, logs, runtime files, and memories:

```bash
recollectium uninstall --purge
```

For non-interactive purge automation:

```bash
recollectium uninstall --purge --yes-delete-all-recollectium-data
```

Use purge carefully. It deletes memories and cannot be undone.
