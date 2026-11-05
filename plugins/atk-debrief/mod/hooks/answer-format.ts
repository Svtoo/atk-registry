// How the rebuild model must answer, with the change set's JSON schema; board.ts checks an answer against the same rules,
// and core.test.ts holds the two together.
export const OUTPUT_FORMAT = `<output_format>
Reply with an <update> block holding the op-set as one JSON object, then one <freeform> block per freeform.upsert holding that card's Markdown body:

<update>
{ the op-set JSON }
</update>
<freeform ref="THE_BODYREF">
## The card's title
Markdown; each diagram an <svg> block on lines of its own
</freeform>

The op-set JSON matches this schema:
{
 "$defs": {
  "CtaRemove": {
   "additionalProperties": false,
   "properties": {
    "op": {
     "const": "cta.remove",
     "type": "string"
    },
    "id": {
     "description": "id of the resolved CTA to remove",
     "type": "string"
    },
    "reason": {
     "default": "",
     "description": "one-line motivation",
     "maxLength": 400,
     "type": "string"
    }
   },
   "required": [
    "op",
    "id"
   ],
   "type": "object"
  },
  "CtaUpsert": {
   "additionalProperties": false,
   "properties": {
    "op": {
     "const": "cta.upsert",
     "type": "string"
    },
    "id": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "existing CTA id; omit to create a new one"
    },
    "text": {
     "anyOf": [
      {
       "maxLength": 400,
       "type": "string"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "the blocker/question for the user; required when creating"
    },
    "reason": {
     "default": "",
     "description": "one-line motivation for this change",
     "maxLength": 400,
     "type": "string"
    }
   },
   "required": [
    "op"
   ],
   "type": "object"
  },
  "FreeformUpsert": {
   "additionalProperties": false,
   "properties": {
    "op": {
     "const": "freeform.upsert",
     "type": "string"
    },
    "id": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "existing slot id; omit to create a new visual"
    },
    "bodyRef": {
     "description": "ref of the <freeform ref=\\"\\u2026\\"> block carrying this card's body: Markdown that opens with a \`## \` title line, each diagram an <svg> block on lines of its own, coloured with the theme variables var(--fg), var(--muted), var(--accent), var(--border), var(--ok), var(--warn), var(--bad)",
     "type": "string"
    },
    "reason": {
     "default": "",
     "description": "one-line motivation, e.g. what changed in the visual",
     "maxLength": 400,
     "type": "string"
    }
   },
   "required": [
    "op",
    "bodyRef"
   ],
   "type": "object"
  },
  "HeadsupRemove": {
   "additionalProperties": false,
   "properties": {
    "op": {
     "const": "headsup.remove",
     "type": "string"
    },
    "id": {
     "description": "id of the open row to remove; acknowledged rows are locked",
     "type": "string"
    },
    "reason": {
     "description": "what is clearly wrong or useless about it",
     "maxLength": 400,
     "minLength": 1,
     "type": "string"
    }
   },
   "required": [
    "op",
    "id",
    "reason"
   ],
   "type": "object"
  },
  "HeadsupUpsert": {
   "additionalProperties": false,
   "properties": {
    "op": {
     "const": "headsup.upsert",
     "type": "string"
    },
    "id": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "existing row id; omit to create a new one"
    },
    "sev": {
     "anyOf": [
      {
       "$ref": "#/$defs/OpSev"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "risk | flag; required when creating"
    },
    "what": {
     "anyOf": [
      {
       "maxLength": 400,
       "type": "string"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "the thing the user likely missed; required when creating"
    },
    "why": {
     "anyOf": [
      {
       "maxLength": 400,
       "type": "string"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "why it might bite; required when creating"
    },
    "where": {
     "anyOf": [
      {
       "maxLength": 400,
       "type": "string"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "where to check"
    },
    "reason": {
     "default": "",
     "description": "one-line motivation for this change",
     "maxLength": 400,
     "type": "string"
    }
   },
   "required": [
    "op"
   ],
   "type": "object"
  },
  "LastTurnSet": {
   "additionalProperties": false,
   "properties": {
    "op": {
     "const": "last_turn.set",
     "type": "string"
    },
    "bullets": {
     "description": "1-3 short outcome bullets for the newest turn only; replaces the previous set wholesale",
     "items": {
      "maxLength": 400,
      "type": "string"
     },
     "maxItems": 3,
     "minItems": 1,
     "type": "array"
    }
   },
   "required": [
    "op",
    "bullets"
   ],
   "type": "object"
  },
  "LinkRemove": {
   "additionalProperties": false,
   "properties": {
    "op": {
     "const": "link.remove",
     "type": "string"
    },
    "id": {
     "description": "id of the link that stopped mattering",
     "type": "string"
    },
    "reason": {
     "default": "",
     "description": "one-line motivation",
     "maxLength": 400,
     "type": "string"
    }
   },
   "required": [
    "op",
    "id"
   ],
   "type": "object"
  },
  "LinkUpsert": {
   "additionalProperties": false,
   "properties": {
    "op": {
     "const": "link.upsert",
     "type": "string"
    },
    "id": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "existing link id; omit to create a new one"
    },
    "label": {
     "anyOf": [
      {
       "maxLength": 400,
       "type": "string"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "display text; required when creating"
    },
    "url": {
     "anyOf": [
      {
       "maxLength": 400,
       "minLength": 1,
       "type": "string"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "destination, a real URL; a new link needs one"
    },
    "kind": {
     "anyOf": [
      {
       "maxLength": 40,
       "type": "string"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "short type tag shown on the chip: issue | pr | branch | doc | \\u2026"
    },
    "reason": {
     "default": "",
     "description": "one-line motivation for this change",
     "maxLength": 400,
     "type": "string"
    }
   },
   "required": [
    "op"
   ],
   "type": "object"
  },
  "OpSev": {
   "enum": [
    "risk",
    "flag"
   ],
   "type": "string"
  },
  "Phase": {
   "enum": [
    "planning",
    "building",
    "blocked",
    "review",
    "shipped"
   ],
   "type": "string"
  },
  "TodoRemove": {
   "additionalProperties": false,
   "properties": {
    "op": {
     "const": "todo.remove",
     "type": "string"
    },
    "id": {
     "description": "id of the open step to remove; done steps are locked",
     "type": "string"
    },
    "reason": {
     "description": "what is clearly wrong or useless about it",
     "maxLength": 400,
     "minLength": 1,
     "type": "string"
    }
   },
   "required": [
    "op",
    "id",
    "reason"
   ],
   "type": "object"
  },
  "TodoStatus": {
   "enum": [
    "open",
    "active",
    "done",
    "blocked"
   ],
   "type": "string"
  },
  "TodoUpsert": {
   "additionalProperties": false,
   "properties": {
    "op": {
     "const": "todo.upsert",
     "type": "string"
    },
    "id": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "existing task id from the digest; omit to create a new task"
    },
    "text": {
     "anyOf": [
      {
       "maxLength": 400,
       "type": "string"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "task text; required when creating (no id)"
    },
    "status": {
     "anyOf": [
      {
       "$ref": "#/$defs/TodoStatus"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "open | active | done | blocked"
    },
    "reason": {
     "default": "",
     "description": "one-line motivation for this change (kept for future turns)",
     "maxLength": 400,
     "type": "string"
    }
   },
   "required": [
    "op"
   ],
   "type": "object"
  }
 },
 "additionalProperties": false,
 "description": "One turn's delta. Omitting an item keeps it; the dashboard mints ids.",
 "properties": {
  "phase": {
   "anyOf": [
    {
     "$ref": "#/$defs/Phase"
    },
    {
     "type": "null"
    }
   ],
   "default": null,
   "description": "set only when the phase changes"
  },
  "essence": {
   "anyOf": [
    {
     "maxLength": 400,
     "type": "string"
    },
    {
     "type": "null"
    }
   ],
   "default": null,
   "description": "the 'what' \\u2014 one line on what this chat is really about, the mission in plain words; set it once the mission is clear, change it only when the mission changes"
  },
  "ops": {
   "description": "the changes this turn; emit ONLY what materially changed, omit the rest",
   "items": {
    "discriminator": {
     "mapping": {
      "cta.remove": "#/$defs/CtaRemove",
      "cta.upsert": "#/$defs/CtaUpsert",
      "freeform.upsert": "#/$defs/FreeformUpsert",
      "headsup.remove": "#/$defs/HeadsupRemove",
      "headsup.upsert": "#/$defs/HeadsupUpsert",
      "last_turn.set": "#/$defs/LastTurnSet",
      "link.remove": "#/$defs/LinkRemove",
      "link.upsert": "#/$defs/LinkUpsert",
      "todo.remove": "#/$defs/TodoRemove",
      "todo.upsert": "#/$defs/TodoUpsert"
     },
     "propertyName": "op"
    },
    "oneOf": [
     {
      "$ref": "#/$defs/TodoUpsert"
     },
     {
      "$ref": "#/$defs/TodoRemove"
     },
     {
      "$ref": "#/$defs/CtaUpsert"
     },
     {
      "$ref": "#/$defs/CtaRemove"
     },
     {
      "$ref": "#/$defs/LinkUpsert"
     },
     {
      "$ref": "#/$defs/LinkRemove"
     },
     {
      "$ref": "#/$defs/LastTurnSet"
     },
     {
      "$ref": "#/$defs/HeadsupUpsert"
     },
     {
      "$ref": "#/$defs/HeadsupRemove"
     },
     {
      "$ref": "#/$defs/FreeformUpsert"
     }
    ]
   },
   "maxItems": 40,
   "type": "array"
  }
 },
 "type": "object"
}
Only the content inside the blocks is read — text before, between, or after is ignored, so you may reason first if you need to. Always close the <update> block: if it is missing or unclosed the whole reply is discarded and the dashboard is left unchanged.
</output_format>`
