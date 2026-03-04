# ATK Registry

Curated plugin registry for [ATK](https://github.com/Svtoo/atk) (AI Toolkit).

## Usage

Install plugins by name:

```bash
atk add openmemory
atk add langfuse
```

## Structure

```
atk-registry/
├── plugins/           # Plugin directories
│   ├── openmemory/
│   ├── langfuse/
│   └── ...
└── index.yaml         # Auto-generated plugin index
```

## Contributing

- Use skill `create-atk-plugin` to create a new plugin.
- You have to review and test the plugin manually before create a pull request.
- Create a PR.

### Plugin Requirements

- Valid `plugin.yaml` (see [plugin schema](https://github.com/Svtoo/atk/blob/main/docs/specs/plugin-schema.md))
- If `lifecycle.install` is defined, `lifecycle.uninstall` must also be defined
- Directory name: lowercase, alphanumeric with hyphens (e.g., `my-plugin`)


