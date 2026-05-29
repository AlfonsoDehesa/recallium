# Troubleshooting

## `recollectium` command not found

Open a new shell after installation. If `recollectium` is still not found, check the directory where uv installs tool executables:

```bash
uv tool dir --bin
uv tool list
```

Add the reported bin directory to PATH, then restart your shell. Common defaults are:

```bash
# Linux and macOS
export PATH="$HOME/.local/bin:$PATH"

# Windows PowerShell
$env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
```

Then verify the installed command directly:

```bash
recollectium --version
recollectium --help
```

After a bootstrap install, you should run `recollectium` directly. You should not need to prefix normal commands with `uv`.

If `uv` itself is also not found after bootstrap install, the same PATH issue is likely hiding both `uv` and `recollectium`, because bootstrap installs `uv` into the same user bin directory it tries to place on PATH.

If installed from a source checkout rather than through bootstrap, use the development form from the repository root:

```bash
uv run recollectium --help
```

## First init is slow

The first `recollectium init` downloads the local FastEmbed model cache. This can take 30 to 120 seconds.

Retry if the network failed:

```bash
recollectium init
```

## Config validation fails

Run:

```bash
recollectium config doctor
recollectium config --validate
recollectium config --path
```

If needed, reset to defaults:

```bash
recollectium config reset
```

## Service will not start

Check status and logs:

```bash
recollectium service status
recollectium service discover
```

Look in the logs directory. See [Logs](Logs.md).

A stale PID file is usually cleaned automatically by status or discovery commands.

## Port already in use

Change the service port:

```bash
recollectium config set service.port 9090
recollectium service restart --type api
```

## Search returns unexpected results

Try these checks:

- Search the correct scope: user vs workspace.
- Confirm the workspace UID.
- Search without `--type` first.
- Include archived memories if needed.
- Check embedding status.

```bash
recollectium workspace resolve my-project
recollectium embedding-status
recollectium embedding-jobs
```

## MCP client cannot connect

For stdio clients, verify the configured command works in a shell:

```bash
recollectium mcp-stdio
```

For managed MCP service mode:

```bash
recollectium service start mcp
recollectium service status
```

## API client cannot connect

Start the API service and validate health:

```bash
recollectium service start api
curl http://127.0.0.1:8765/v1/health
```

## Unsafe host binding warning

If you changed `service.host` to `0.0.0.0`, a LAN IP, or a VPN IP, remember that v1 services are unauthenticated. Use private networking and external access controls.
