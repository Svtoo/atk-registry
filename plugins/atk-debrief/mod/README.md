# ATK Debrief mod

The Claude Code mod behind [ATK Debrief](../README.md). Install it with `atk add atk-debrief`; that README says
what it shows, its settings, its cost and the files it keeps.

## In this folder

- `hooks/register.tsx`: the entry point, with every hook, session value and press.
- `hooks/rebuild.ts`: records each turn and rebuilds the dashboard with the model.
- `hooks/turns.ts`, `hooks/prompt.ts`, `hooks/answer.ts`, `hooks/answer-format.ts`, `hooks/board.ts`: the turns,
  the prompt, the model's answer and its schema, and how it folds into the dashboard.
- `hooks/band-model.ts`, `hooks/band.tsx`, `hooks/panes.tsx`, `hooks/kit.tsx`, `hooks/colors.ts`, `hooks/marks.ts`:
  the band, the two panes, and the parts, colours and marks they share.
- `hooks/status.ts`: each problem's wording and the steps that fix it.
- `SYSTEM.md`: the prompt the rebuild model reads.
- `types/index.d.ts`: what the band shows and each session value.
- `tests/`: the test suite.

## Tests

In this folder:

```bash
claude plugin test .
```

```bash
claude plugin validate --strict .claude-plugin/plugin.json
```
