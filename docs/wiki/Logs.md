# Logs

Recollectium writes structured JSON logs for diagnostics while keeping CLI stdout reserved for command output. CLI output is human-readable by default and can be switched to JSON with `cli_output` or `--json`; logs still stay out of stdout.

## Default location

Logs use the XDG state path by default:

```text
~/.local/state/recollectium/logs/
```

You can override the logs directory with `directories.logs` in config.

## Log config

Defaults:

```json
{
  "logging": {
    "level": "info",
    "format": "json",
    "max_bytes": 10485760,
    "backup_count": 5
  }
}
```

Update log level:

```bash
recollectium config set logging.level debug
```

Override for one command:

```bash
recollectium --log-level debug list
```

## Service logs

Managed services redirect stdout and stderr to service log files in the configured logs directory.

Common files include:

- `service-api.log`
- `service-mcp.log`
- Rotated backups based on `logging.max_bytes` and `logging.backup_count`

## What logs are for

Use logs to diagnose:

- Config loading and validation problems.
- Database and migration issues.
- Service startup and shutdown behavior.
- Service discovery cleanup.
- Embedding readiness and re-embedding jobs.
- Runtime failures that are hard to see from CLI output alone.

## What logs should not contain

Logs should not include:

- Memory content.
- Full metadata payloads.
- Credentials, tokens, passwords, API keys, or private keys.
- Sensitive local secrets.

If you share logs in an issue, review them first and replace anything sensitive with `[REDACTED]`.
