# CLI Reference

The `recollectium` command is the main user-facing interface to Recollectium Core. Commands print human-readable output by default when they return command data. Use `--json` or `cli_output: json` when scripts and adapters need machine-readable output. Non-argparse runtime failures follow the same output preference on stderr.

Global form:

```bash
recollectium [GLOBAL OPTIONS] COMMAND [COMMAND OPTIONS]
```

## Global options

Global options normally go before the command. The output-format flags, `--json` and `--human-readable`, may appear before or after the command.

| Option | Values | What it does |
|---|---|---|
| `--config CONFIG_PATH` | path | Uses a specific JSON config file instead of the default XDG config path. Explicit missing paths fail except for config creation commands. |
| `--db DB_PATH` | path | Overrides `database.path` for this invocation. Useful for tests, alternate profiles, or temporary databases. |
| `--log-level LEVEL` | `debug`, `info`, `warning`, `error` | Overrides the configured log level for this run only. It does not write to the config file. |
| `--json` | none | Prints JSON success and failure output for this invocation, overriding `cli_output`. Mutually exclusive with `--human-readable`. |
| `--human-readable` | none | Prints human-readable success and non-argparse failure output for this invocation, overriding `cli_output`. Mutually exclusive with `--json`. |
| `--version` | none | Prints the installed Recollectium version and exits. |

Example:

```bash
recollectium --log-level debug --db /tmp/recollectium.db list
recollectium list --json
recollectium service discover --json
```

## init

```bash
recollectium init [--db DB_PATH]
```

Initializes Recollectium for first use. It creates the config file if needed, creates XDG directories, creates or migrates the SQLite database, prepares the built-in embedding model cache, and writes model readiness metadata.

Options:

| Option | Required | What it does |
|---|---:|---|
| `--db DB_PATH` | No | Initializes the given SQLite database path instead of the configured default. This is also available as global `--db` before the command. |

Notes:

- First run may download the FastEmbed model cache and can take longer than later runs.
- Success prints initialized config, data, cache, logs, runtime, database, and embedding model paths.

## add

```bash
recollectium add --space user --type preference --content "I prefer concise answers."
recollectium add --space workspace --workspace-uid my-project --type decision --content "Use SQLite for local storage."
```

Adds one memory and stores an embedding for semantic search.

Options:

| Option | Required | Values | What it does |
|---|---:|---|---|
| `--space SPACE` | Yes | `user`, `workspace` | Chooses where the memory belongs. User memory follows the person. Workspace memory belongs to one project or context. |
| `--type TYPE` | Yes | user or workspace memory type | Places the memory in a bucket. User types include `fact`, `preference`, `personal_fact`, `social_context`, `goal`, `communication_style`, `note`. Workspace types include `fact`, `decision`, `task_context`, `configuration`, `bug_finding`, `note`. |
| `--content CONTENT` | Yes | text | The memory text to store and embed. |
| `--workspace-uid UID` | Required for workspace, forbidden for user | string | Stable workspace identifier. Use the repo name or project folder name when possible. |
| `--metadata JSON_OR_PATH` | No | JSON object or `@path/to/file.json` | Optional structured metadata. Must be a JSON object. |
| `--source SOURCE` | No | string | Optional label for where the memory came from, such as `chat`, `manual`, `issue`, or `adapter`. |
| `--confidence SCORE` | No | number from `0.0` to `1.0` | Optional confidence score. |
| `--sensitivity LABEL` | No | string | Optional privacy or sensitivity label for future privacy-aware handling. |

## search-user

```bash
recollectium search-user [--type TYPE] [--limit LIMIT] [--include-archived] "query"
```

Searches user-space memories by semantic similarity. This is the right command when the question is about the person using the agent: preferences, communication style, personal facts, durable goals, and cross-project context.

Arguments and options:

| Name | Required | Default | What it does |
|---|---:|---|---|
| `query` | Yes | none | Natural language search text. Exact wording is not required because search is semantic. |
| `--type TYPE` | No | all user types | Narrows results to one user memory bucket. Usually skip this first and add it only if results are too broad. |
| `--limit LIMIT` | No | `10` | Maximum number of ranked results. Must be positive. |
| `--include-archived` | No | `false` | Includes archived memories in the search candidate set. |

## search-workspace

```bash
recollectium search-workspace --workspace-uid UID [--type TYPE] [--limit LIMIT] [--include-archived] "query"
```

Searches memories for one workspace. This is the right command when the question is about a repo, project, implementation detail, task, decision, bug, or configuration.

Arguments and options:

| Name | Required | Default | What it does |
|---|---:|---|---|
| `query` | Yes | none | Natural language search text. |
| `--workspace-uid UID` | Yes | none | Workspace to search. Aliases resolve to the canonical UID. |
| `--type TYPE` | No | all workspace types | Narrows results to one workspace bucket, such as `decision` or `configuration`. |
| `--limit LIMIT` | No | `10` | Maximum number of ranked results. Must be positive. |
| `--include-archived` | No | `false` | Includes archived workspace memories. |

## list

```bash
recollectium list [--space SPACE] [--type TYPE] [--status STATUS] [--workspace-uid UID] [--include-archived] [--limit LIMIT]
```

Lists memories directly rather than semantically searching them. Use it for inspection, audits, debugging, or finding IDs.

Options:

| Option | Required | What it does |
|---|---:|---|
| `--space SPACE` | No | Filters to `user` or `workspace`. |
| `--type TYPE` | No | Filters to one memory type. |
| `--status STATUS` | No | Filters by status, commonly `active` or `archived`. |
| `--workspace-uid UID` | No | Filters workspace memories to one workspace UID. |
| `--include-archived` | No | Includes archived memories. Without it, archived memories are hidden. |
| `--limit LIMIT` | No | Maximum number of memories to return. Must be positive. |

## get

```bash
recollectium get MEMORY_ID
```

Retrieves one memory by ID and prints it as JSON. Use `list` or `search-user` / `search-workspace` first if you do not know the ID.

Arguments:

| Argument | Required | What it does |
|---|---:|---|
| `MEMORY_ID` | Yes | The memory ID to fetch. |

## update

```bash
recollectium update MEMORY_ID [--type TYPE] [--content CONTENT] [--metadata JSON_OR_PATH] [--source SOURCE] [--confidence SCORE] [--sensitivity LABEL]
```

Updates editable fields on one memory. Updating `--content` regenerates that memory's embedding.

Arguments and options:

| Name | Required | What it does |
|---|---:|---|
| `MEMORY_ID` | Yes | Memory to update. |
| `--type TYPE` | No | Replaces the memory type bucket. |
| `--content CONTENT` | No | Replaces the memory text and regenerates the embedding. |
| `--metadata JSON_OR_PATH` | No | Replaces metadata with a JSON object, either inline or from `@path/to/file.json`. |
| `--source SOURCE` | No | Replaces the source label. |
| `--confidence SCORE` | No | Replaces the confidence score. Must be between `0.0` and `1.0`. |
| `--sensitivity LABEL` | No | Replaces the sensitivity label. |

Use `recollectium upgrade` for package upgrades. `recollectium update` is only for memory records.

## archive

```bash
recollectium archive MEMORY_ID
```

Marks a memory as archived. Archived memories are not hard-deleted, but they are hidden from normal list and search results unless you pass `--include-archived` to the relevant command.

Arguments:

| Argument | Required | What it does |
|---|---:|---|
| `MEMORY_ID` | Yes | Memory to archive. |

## db-status

```bash
recollectium db-status
```

Shows database schema migration status as JSON for the selected database. It initializes the database if needed and reports current and pending schema versions.

Use global `--db DB_PATH` before the command to inspect a non-default database.

## workspace

Workspace commands manage workspace UIDs, aliases, and renames.

### workspace list

```bash
recollectium workspace list [--include-archived] [--include-aliases]
```

Lists known workspace UIDs.

| Option | Required | What it does |
|---|---:|---|
| `--include-archived` | No | Includes UIDs that only appear on archived memories. |
| `--include-aliases` | No | Returns workspace objects with nested alias arrays instead of plain UID strings. |

### workspace resolve

```bash
recollectium workspace resolve UID
```

Normalizes a workspace UID candidate and resolves aliases to the canonical workspace UID.

### workspace rename

```bash
recollectium workspace rename OLD_UID NEW_UID
```

Migrates all memories from `OLD_UID` to `NEW_UID`, including archived memories. Both values are normalized according to `workspace.uid_normalization` before the operation.

### workspace alias add

```bash
recollectium workspace alias add CANONICAL_UID ALIAS_UID [--migrate-existing]
```

Creates an alias so an old or alternate workspace name resolves to a canonical workspace UID.

| Option | Required | What it does |
|---|---:|---|
| `--migrate-existing` | No | Moves existing memories under the alias UID to the canonical UID in the same transaction. Use this when the alias name already has memories. |

### workspace alias list

```bash
recollectium workspace alias list [--workspace UID]
```

Lists alias mappings. With `--workspace`, filters to one canonical workspace UID.

### workspace alias remove

```bash
recollectium workspace alias remove ALIAS_UID
```

Removes an alias mapping. It does not delete memories.

## config

```bash
recollectium config
recollectium config --path
recollectium config --defaults
recollectium config --validate
recollectium config get KEY
recollectium config set KEY VALUE
recollectium config unset KEY
recollectium config init [--force]
recollectium config doctor
recollectium config edit
recollectium config reset
```

Configuration commands inspect and modify the JSON config file.

| Command | What it does |
|---|---|
| `config` | Prints the effective config: built-in defaults merged with the config file. |
| `config --path` | Prints the resolved config file path without creating a file. |
| `config --defaults` | Prints built-in default values without creating a file. |
| `config --validate` | Validates the active config. Exits `0` if valid, `1` if missing, `2` if invalid. |
| `config get KEY` | Prints one effective config value by dot-notation key, such as `service.port`. |
| `config set KEY VALUE` | Writes a config value. `VALUE` is parsed as JSON when possible, otherwise stored as a string. |
| `config unset KEY` | Removes an explicit key so the built-in default applies again. |
| `config init --force` | Creates a starter config file. `--force` overwrites an existing file. |
| `config doctor` | Checks config validity and filesystem writability for data, cache, logs, runtime, and database parent directories. |
| `config edit` | Opens the config file in `$EDITOR`, creating it first if needed. |
| `config reset` | Replaces the config file with built-in defaults. |

Supported keys are listed in [Configuration](Configuration.md).

## service

```bash
recollectium service start api
recollectium service start mcp
recollectium service stop
recollectium service status
recollectium service discover
recollectium service restart [--type api|mcp]
```

Managed services run in the background and write PID and discovery files under the runtime directory.

| Command | What it does |
|---|---|
| `service start api` | Starts the local HTTP JSON API service. |
| `service start mcp` | Starts the managed HTTP MCP service. |
| `service stop` | Stops the running managed Recollectium service, if one exists. |
| `service status` | Prints whether a managed service is running, plus type, PID, and endpoint when available. |
| `service discover` | Prints machine-readable discovery metadata for adapters. Exits `1` with `status: "not_running"` when no service is running. |
| `service restart` | Restarts the currently running service or the last known service type. |
| `service restart --type api` | Restarts API service when no running or previous service type can be inferred. |
| `service restart --type mcp` | Same, but for MCP service. |

## serve

```bash
recollectium serve [--host HOST] [--port PORT]
```

Runs the local HTTP API service in the foreground. This is useful for development and debugging. For normal adapter use, prefer `recollectium service start api`.

Options:

| Option | Required | Default | What it does |
|---|---:|---|---|
| `--host HOST` | No | `service.host`, usually `127.0.0.1` | Bind interface. Non-local binds can expose unauthenticated memory operations. |
| `--port PORT` | No | `service.port`, usually `8765` | TCP port for the API service. |

## mcp-stdio

```bash
recollectium mcp-stdio
```

Runs an MCP server over stdin/stdout. This is intended for MCP clients that spawn Recollectium as a child process. The server runs for the lifetime of the client connection and does not create a PID file.

Use global `--db`, `--config`, and `--log-level` before the command if needed.

## embedding commands

```bash
recollectium embedding-status
recollectium embedding-jobs [--job-id JOB_ID] [--state STATE] [--limit LIMIT]
```

### embedding-status

Prints the active local embedding profile, runtime status, startup re-embedding job reference, and recent job metadata.

### embedding-jobs

Lists embedding jobs or fetches one job by ID.

| Option | Required | What it does |
|---|---:|---|
| `--job-id JOB_ID` | No | Fetches exactly one embedding job. Without it, the command lists jobs. |
| `--state STATE` | No | Filters list mode by state, such as `pending`, `in_progress`, `completed`, or `failed`. |
| `--limit LIMIT` | No | Limits list mode to a positive number of jobs. |

Embedding jobs are used for model readiness and re-embedding memories when the active embedding profile changes or stale embeddings are detected.

## lifecycle commands

### completion

```bash
recollectium completion [SHELL]
recollectium completion [SHELL] --source
recollectium completion [SHELL] --install [--yes]
```

Supported shells are `bash`, `zsh`, `fish`, and `powershell`. If `SHELL` is omitted, Recollectium tries to detect it.

| Option | Required | What it does |
|---|---:|---|
| `SHELL` | No | Shell to configure. |
| `--source` | No | Prints only the raw completion script for eval or shell startup files. |
| `--install` | No | Writes a managed completion block into the shell startup file. Prompts before writing. |
| `--yes` | No | Skips the confirmation prompt when used with `--install`. |

### upgrade

```bash
recollectium upgrade [--check] [--dry-run] [--force] [--install-method METHOD] [--repo OWNER/REPO] [--allow-main] [--timeout SECONDS]
```

Checks for a newer release and upgrades using the detected install method.

| Option | Required | Default | What it does |
|---|---:|---|---|
| `--check` | No | `false` | Checks for an available upgrade and prints the plan without applying it. |
| `--dry-run` | No | `false` | Prints the command that would run without applying it. |
| `--force` | No | `false` | Builds and applies an upgrade plan even if versions appear current. |
| `--install-method METHOD` | No | `auto` | Overrides detection. Values: `auto`, `bootstrap`, `pip`, `pipx`, `uv_tool`, `source`. |
| `--repo OWNER/REPO` | No | Recollectium repo | Checks a different GitHub repo. Passing this also permits main fallback when no release exists. |
| `--allow-main` | No | `false` | Permits main-branch fallback for bootstrap or source upgrades if no release exists. |
| `--timeout SECONDS` | No | `600` | Package-manager command timeout. |

### uninstall

```bash
recollectium uninstall [--purge] [--yes-delete-all-recollectium-data] [--dry-run]
```

Prints safe uninstall instructions and stops managed services. By default, it preserves memories and local data.

| Option | Required | What it does |
|---|---:|---|
| `--purge` | No | Permanently deletes Recollectium-owned config, data, cache, logs, runtime paths, and memories after confirmation. |
| `--yes-delete-all-recollectium-data` | Required only for non-interactive purge | Confirms destructive deletion. Requires `--purge`. |
| `--dry-run` | No | Shows planned actions without stopping services or deleting files. With `--purge`, previews deletion paths. |

## Exit behavior and output

- Human-readable output is the default. When the target output stream is a TTY, human-readable output uses Rich-backed ANSI color for headings, field labels, errors, and hints. Set `cli_output` to `json` in config, or pass `--json`, when scripts or adapters need machine-readable output.
- Pass `--json` to force JSON for one invocation, even when config prefers human-readable output. This is the safest mode for scripts and adapters.
- `--json` and `--human-readable` are mutually exclusive and may appear before or after the command. If you need one of those strings as a literal command value, put it after `--`.
- Protocol commands keep their machine contract: `completion --source`, completion candidate generation, `serve`, and `mcp-stdio` do not switch to human text.
- Non-argparse failures follow the selected output format on stderr.
- Validation errors usually exit `2`.
- Runtime, service, database, migration, not-found, and embedding errors usually exit `1`.
- `service discover` intentionally prints `status: "not_running"` to stdout and exits `1` when no managed service is running, so adapters can read the state. Use `--json` for adapter or script discovery calls.
