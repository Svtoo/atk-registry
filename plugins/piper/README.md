# Piper TTS

Local text-to-speech using Piper neural voices with MCP integration.

## Overview

Piper is a fast, offline neural text-to-speech engine. This plugin runs Piper as a local
Docker service and exposes a `speak` MCP tool so AI agents can narrate their actions, provide
progress updates, and deliver results as audio through your system speakers.

All processing is local — no cloud API, no data leaving your machine. Voice models are
downloaded on first use and cached in a Docker volume.

## Installation

**Prerequisites:** Docker (running)

```bash
atk add piper
```

On first start, the container downloads the configured voice model (~50–200 MB depending on
quality). Subsequent starts use the cached model.

## Environment Variables

| Variable        | Default                 | Description                                                                                    |
|-----------------|-------------------------|------------------------------------------------------------------------------------------------|
| `PIPER_VOICE`   | `en_GB-alba-medium`     | Voice model to use. See [voice samples](https://rhasspy.github.io/piper-samples/) for options. |
| `PIPER_TTS_URL` | `http://localhost:5847` | URL of the Piper HTTP service. Change if you remap the port.                                   |

Configure with:

```bash
atk setup piper
```

### Choosing a Voice

Browse all available voices at https://rhasspy.github.io/piper-samples/. Voice names follow
the pattern `<lang>_<region>-<name>-<quality>`, e.g.:

| Voice                   | Language     | Quality |
|-------------------------|--------------|---------|
| `en_GB-alba-medium`     | English (GB) | medium  |
| `en_US-ryan-high`       | English (US) | high    |
| `en_US-amy-medium`      | English (US) | medium  |
| `de_DE-thorsten-medium` | German       | medium  |

To switch voice, update `PIPER_VOICE` and restart:

```bash
atk setup piper        # update PIPER_VOICE
atk restart piper
```

No rebuild needed — the entrypoint downloads the new model automatically.

## Usage

After install, the HTTP API is available at:

| Endpoint | URL                   |
|----------|-----------------------|
| TTS HTTP | http://localhost:5847 |

Enable the MCP tool in Claude, Cursor, or any MCP-compatible client:

```bash
atk mcp piper
```

## MCP Tools

### `speak`

Convert text to speech and play it through the system speakers.

| Parameter       | Type   | Default | Description                            |
|-----------------|--------|---------|----------------------------------------|
| `text`          | string | —       | Text to speak (required)               |
| `speaker_id`    | int    | `0`     | Speaker ID for multi-speaker models    |
| `length_scale`  | float  | `1.1`   | Speed: lower = faster, higher = slower |
| `noise_scale`   | float  | `0.667` | Voice variation (expressiveness)       |
| `noise_w_scale` | float  | `0.333` | Pronunciation variation                |
| `volume`        | float  | `0.15`  | Volume from `0.01` to `1.00`           |

The tool call **blocks until playback is complete** — it returns only after the audio finishes.

```json
{
  "tool": "speak",
  "arguments": {
    "text": "Tests passed. Ready to commit."
  }
}
```

## Logs

```bash
atk logs piper
```

## Uninstall

```bash
atk uninstall piper
```

Stops and removes the container and locally-built image. The voice model cache volume
(`piper-models`) is **not** removed. To also delete cached models:

```bash
docker volume rm piper-models
```

## Links

- [Piper repository](https://github.com/rhasspy/piper)
- [Voice samples](https://rhasspy.github.io/piper-samples/)

