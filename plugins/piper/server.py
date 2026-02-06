"""Piper TTS MCP server.

Exposes a 'speak' tool that converts text to speech via a local Piper TTS
Docker service and plays the audio through the system speakers.
"""

import io
import os
import time
import warnings
from typing import Optional

import requests

warnings.filterwarnings("ignore")
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "hide"
import pygame  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

PIPER_TTS_URL = os.environ.get("PIPER_TTS_URL", "http://localhost:5847")

mcp = FastMCP("Piper TTS")


@mcp.tool()
def speak(
    text: str,
    speaker_id: Optional[int] = 0,
    length_scale: Optional[float] = 1.1,
    noise_scale: Optional[float] = 0.667,
    noise_w_scale: Optional[float] = 0.333,
    volume: Optional[float] = 0.15,
) -> str:
    """Convert text to speech and play it through the speakers.

    Args:
        text: The text to convert to speech
        speaker_id: Voice speaker ID (default: 0)
        length_scale: Speech speed control (default: 1.1, lower = faster)
        noise_scale: Voice variation control (default: 0.667)
        noise_w_scale: Pronunciation variation control (default: 0.333)
        volume: Volume level from 0.01 to 1.00 (default: 0.15)

    Returns:
        Success or error message
    """
    try:
        volume = max(0.01, min(1.00, volume))

        data = {
            "text": text,
            "speaker_id": speaker_id,
            "length_scale": length_scale,
            "noise_scale": noise_scale,
            "noise_w_scale": noise_w_scale,
        }

        response = requests.post(
            PIPER_TTS_URL,
            headers={"Content-Type": "application/json"},
            json=data,
            timeout=30,
        )

        if response.status_code != 200:
            return f"TTS service error: HTTP {response.status_code}"

        # Play audio — try in-memory first, fall back to temp file
        try:
            pygame.mixer.init()
            pygame.mixer.music.set_volume(volume)
            audio_data = io.BytesIO(response.content)
            pygame.mixer.music.load(audio_data)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.wait(100)
        except Exception:
            filename = f"speak_{int(time.time())}.wav"
            with open(filename, "wb") as f:
                f.write(response.content)
            pygame.mixer.init()
            pygame.mixer.music.set_volume(volume)
            pygame.mixer.music.load(filename)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.wait(100)
            try:
                os.remove(filename)
            except OSError:
                pass

        return f"Successfully spoke: '{text}'"

    except requests.exceptions.ConnectionError:
        return f"Error: TTS service not available at {PIPER_TTS_URL}"
    except requests.exceptions.Timeout:
        return "Error: TTS service request timed out"
    except Exception as e:
        return f"Error: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")

