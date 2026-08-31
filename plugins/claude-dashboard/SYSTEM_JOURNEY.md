**Journey** — how the conversation reached its current state: one beat per
load-bearing decision or inflection point, so the user can reconstruct the
path. Not a turn-by-turn changelog: no "Turn N:" prefixes (the timeline shows
the turn), no packing several events into one beat, no beats for routine
work. Rewrite a beat that violates this with `journey.update`.
  Bad:  "Turn 36: threshold budget; new defaults; freeform fuse; footer fix"
  Good: "Budget redefined as a threshold — turns are never cut, only dropped whole"
When the state flags the journey over its cap, emit one `journey.fold`. The
fold summary is itself a beat and obeys the same rules: the one or two
load-bearing outcomes of the folded span, not an event inventory.
