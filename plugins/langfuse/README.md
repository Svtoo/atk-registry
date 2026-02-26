# Langfuse

Open-source LLM observability and tracing platform.

## Overview

Langfuse lets you trace, debug, and evaluate LLM applications. Every prompt, completion,
token count, latency, and cost is recorded and visualised in a local web UI. You instrument
your code with the Langfuse SDK and point it at this self-hosted instance — no data leaves
your machine.

The stack runs as Docker containers: a Next.js web app, a background worker, Postgres
(metadata store), ClickHouse (analytics store), Redis (queue), and MinIO (blob storage).

## Installation

**Prerequisites:** Docker (running)

```bash
atk add langfuse
```

After install, run the one-time ClickHouse setup to configure TTL policies and disable
resource-intensive system logging tables that would otherwise bloat disk:

```bash
atk run langfuse maintenance --setup
```

## Environment Variables

Configure with (only run if you need to change anything, atk add prompts this automatically):

```bash
atk setup langfuse
```

### SDK Integration

Set these in your application to send traces to this instance:

| Variable               | Default                    | Description                       |
|------------------------|----------------------------|-----------------------------------|
| `LANGFUSE_PUBLIC_KEY`  | `pk-lf-local-public`       | Project public key for SDK auth   |
| `LANGFUSE_SECRET_KEY`  | `sk-lf-local-secret`       | Project secret key for SDK auth   |
| `LANGFUSE_HOST`        | `http://localhost:13000`   | URL your SDK sends traces to      |

NOTE: you can add other projects and keys in the web UI.

### Instance Initialisation

These control the admin account and default project created on first start:

| Variable                  | Default                  | Description                          |
|---------------------------|--------------------------|--------------------------------------|
| `LANGFUSE_ORG_NAME`       | `Default Organization`   | Organisation name shown in the UI    |
| `LANGFUSE_PROJECT_NAME`   | `Default Project`        | Project name shown in the UI         |
| `LANGFUSE_USER_EMAIL`     | `admin@localhost.com`    | Admin login email                    |
| `LANGFUSE_USER_PASSWORD`  | `admin123`               | Admin login password                 |

## Usage

After install the web UI is available at:

| Endpoint  | URL                      |
|-----------|--------------------------|
| Web UI    | http://localhost:13000   |

Log in with `LANGFUSE_USER_EMAIL` / `LANGFUSE_USER_PASSWORD` (defaults above).

### SDK Integration

Install the Langfuse SDK in your project and configure it using the variables above.
Example for Python:

```python
import os
os.environ["LANGFUSE_PUBLIC_KEY"] = "pk-lf-local-public"
os.environ["LANGFUSE_SECRET_KEY"] = "sk-lf-local-secret"
os.environ["LANGFUSE_HOST"]       = "http://localhost:13000"
```

See the [SDK documentation](https://langfuse.com/docs/sdk) for all languages and
frameworks (OpenAI, LangChain, LlamaIndex, etc.).

## Maintenance

`maintenance.sh` manages ClickHouse storage and keeps disk usage under control.

```bash
# Show disk usage and table sizes, run routine cleanup (no restart)
atk run langfuse maintenance

# One-time initial setup: configure TTLs, disable bloated system tables, restart ClickHouse
atk run langfuse maintenance --setup

# Reclaim disk space: drop bloated system tables, clean logs, restart ClickHouse
atk run langfuse maintenance --deep-clean

# Pull latest images and recreate containers (data volumes are preserved)
atk run langfuse maintenance --update

# Inspect storage
atk run langfuse maintenance --tables-only   # table sizes
atk run langfuse maintenance --disk-usage    # Docker volume sizes

# Show cost breakdown for a specific trace
atk run langfuse maintenance --trace-cost <trace_id>
```

> **Disk tip:** ClickHouse accumulates system logs aggressively. Run `--setup` once after
> install, and `--deep-clean` whenever disk usage grows unexpectedly.

## Uninstall

```bash
atk uninstall langfuse
```

This stops and removes the containers and locally-built images. Docker volumes (all stored
data) are **not** removed. To also delete the data:

```bash
docker volume rm langfuse_postgres_data langfuse_clickhouse_data \
    langfuse_clickhouse_logs langfuse_clickhouse_config langfuse_minio_data
```

## Links

- [Langfuse documentation](https://langfuse.com/docs)
- [Upstream repository](https://github.com/langfuse/langfuse)

