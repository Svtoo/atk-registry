# OpenMemory

Persistent memory layer for AI agents with semantic search and MCP integration.

## Overview

OpenMemory is a self-hosted memory service that lets AI agents store and retrieve memories
across sessions. Memories are persisted in a local SQLite database and indexed with Ollama
embeddings for semantic search. The MCP interface lets AI assistants read and write memories
directly from their context.

All data stays on your machine — no cloud API required.

## Instructions

Develop your own or use the ones from `SKILL.md`. Simply copy the content to the instructions
of your agent.

## Installation

**Prerequisites:** Docker (running), [Ollama](https://ollama.com/download) (running)

```bash
atk add openmemory
```

The install script:

1. Checks Ollama is installed and running
2. Pulls the `mxbai-embed-large` embedding model (~669 MB, one-time download)
3. Clones and builds the OpenMemory backend and dashboard from source
4. Starts both services and waits for them to become healthy

## Environment Variables

| Variable                 | Default                 | Description                                                                                          |
|--------------------------|-------------------------|------------------------------------------------------------------------------------------------------|
| `OPENMEMORY_URL`         | `http://localhost:8787` | Backend API URL used by the MCP stdio proxy. Change if you remap the port.                           |
| `OPENMEMORY_VOLUME_NAME` | `openmemory_data`       | Docker volume that persists memory data. Override to isolate multiple instances on the same machine. |
| `OPENMEMORY_BACKUP_DIR`  | _(empty)_               | Directory for memory backups (e.g. a Google Drive sync folder). If not set, backup is a no-op.       |

Configure with:

```bash
atk setup openmemory
```

## Usage

After install:

| Endpoint  | URL                   |
|-----------|-----------------------|
| API       | http://localhost:8787 |
| Dashboard | http://localhost:3737 |

MCP configuration (for use in Claude, Cursor, etc.):

```bash
atk mcp openmemory
```

## Backup

`backup.sh` copies the persistent memory volume to `OPENMEMORY_BACKUP_DIR`. Set this to a
directory that syncs offsite (e.g. Google Drive, iCloud, Dropbox) and run it regularly.

```bash
# Configure the backup directory first
atk setup openmemory   # set OPENMEMORY_BACKUP_DIR

# Run a backup
atk run openmemory backup
```

What the backup does:

1. Stops OpenMemory services (for a consistent SQLite snapshot)
2. Tarballs the `$OPENMEMORY_VOLUME_NAME` Docker volume into `$OPENMEMORY_BACKUP_DIR/openmemory_backup.tar.gz`
3. Restarts services and waits for the API to become healthy

If the backup file already exists, the script will prompt before overwriting (default: overwrite).
For versioned backups, point `OPENMEMORY_BACKUP_DIR` at a folder managed by backup software
that versions its contents (e.g. Time Machine, Google Drive with version history).

## Restore

`restore.sh` replaces the current memory volume with the contents of the backup file.
**This is destructive — all current memories are wiped before extraction.**

```bash
atk run openmemory restore
```

What the restore does:

1. Prompts for confirmation (default: **no** — safety); non-interactive always declines
2. Stops OpenMemory services
3. Clears the `$OPENMEMORY_VOLUME_NAME` volume, then extracts `$OPENMEMORY_BACKUP_DIR/openmemory_backup.tar.gz`
4. Restarts services and waits for the API to become healthy

## Uninstall

```bash
atk uninstall openmemory
```

The uninstall script **keeps your memory data by default** and will prompt before deleting
the `$OPENMEMORY_VOLUME_NAME` volume. When run non-interactively (e.g. via scripts or CI), it always
preserves the data volume.

To fully wipe including data:

```bash
atk remove openmemory   # stops, uninstalls, removes plugin directory
# then manually: docker volume rm "$OPENMEMORY_VOLUME_NAME"
```

## Links

- [Upstream repository](https://github.com/CaviraOSS/OpenMemory)
- [Ollama](https://ollama.com)

