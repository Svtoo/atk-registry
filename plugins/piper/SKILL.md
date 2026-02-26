# Piper TTS — Skill

Local text-to-speech via Piper neural voices. Use this MCP to give yourself a voice and keep
the user informed as you work.

## Tools

- **speak**: Converts text to speech and plays it through the system speakers. Blocks until
  playback is complete — the call returns only after the audio finishes.

## The Narration Requirement

You MUST narrate your workflow using the **Intent-Progress-Result** loop:

1. **Intent (Before):** Before executing a significant command or starting a task, speak your
   intent. *"I'm going to run the tests now."*
2. **Progress (During):** For multi-step tasks, provide short status updates. *"Tests are
   halfway through."*
3. **Result (After):** Once a task completes, summarize the outcome verbally. *"All tests
   passed."*

## When to Call `speak` (Mandatory)

- **Before tool use:** Every time you run a tool that modifies the system, accompany it with a
  `speak` call stating what you are about to do.
- **Decision points:** When choosing between two approaches, briefly explain why verbally.
- **Greetings and farewells:** Greet the user at the start of a session; summarize your work at
  the end.

## Voice Personality

- **Concise and direct:** Keep speech punchy — 1 to 3 sentences per call. Do not read back
  code, file contents, URLs, or long lists. Speak the *meaning*, not the raw data.
- **Natural tone:** Be conversational. Avoid robotic phrasing like "Command executed
  successfully." Say "That worked, the file is updated."
- **Contextual brevity:** If the user is asking many small questions in a row, be briefer. If
  you are doing a big job, be more descriptive.
- **Collaborative:** Use "I" and "we" to emphasize you are working *with* the user, not just
  executing commands.

## Usage Pattern

Call `speak` in parallel with other tools — do not wait for audio to finish before starting
your next action. However, note that `speak` itself blocks on the server side: the MCP call
returns only after playback completes, so do not chain multiple speak calls sequentially unless
you intend the user to hear them in order.

```json
{ "tool": "speak", "arguments": { "text": "Running the test suite now." } }
```

## Volume and Speed

Defaults (`volume=0.15`, `length_scale=1.1`) work well for casual narration. Increase volume
for important alerts. Lower `length_scale` (e.g. `0.9`) for faster delivery during rapid
iteration.

## Rules

1. **Never speak** raw JSON, large data structures, error stack traces, or long URLs.
2. **Never skip narration** because you think it is obvious — the user is watching and relies
   on audio cues.
3. **Respect silence:** If the user asks you to stop narrating, stop calling `speak` until
   explicitly asked to resume.

