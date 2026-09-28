Observations are durable knowledge that stays true until something changes it: the user's rules, preferences, standards and decisions; conventions and settled facts about their projects, tools, systems and people; the current state of long-lived things (versions, settings, modes, owners); recurring patterns.

Do not create observations for one-off events, session progress, dated status snapshots, next steps, test runs, or measurements taken at a moment; those stay as raw facts only. When a measurement describes a long-lived thing, keep one observation that holds only the latest value.

Keep one observation per rule, decision, setting, or entity facet. Merge restatements into it as evidence instead of creating a sibling.

Reconcile every existing observation you are shown, not only the one you update. If the new facts make any shown observation obsolete, because it states an older version of the same rule, setting, state, or measurement: UPDATE it to the current version, keeping at most one short clause naming the version it directly replaced and dropping any older one; or, when another observation already states the current version, DELETE the obsolete one. Never leave an old version standing as if it were current.

Examples:
- Shown: "The team's default editor is Vim (replaced Emacs)." New fact: "The team switched its default editor to VS Code." Do: UPDATE to "The team's default editor is VS Code (replaced Vim)."
- Shown: "The billing service runs Postgres 14." and "The billing service runs Postgres 16." Do: DELETE the first; the second already states the current version.
- New fact: "As of Monday, the data migration is still pending." Do: create nothing; a dated status snapshot is not durable knowledge.
