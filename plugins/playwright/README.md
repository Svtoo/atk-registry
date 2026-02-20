# Playwright MCP Plugin for ATK

Browser automation using Microsoft's official Playwright MCP server. Enables AI agents to interact with web pages, take
screenshots, fill forms, and execute JavaScript through structured accessibility snapshots.

## Overview

This plugin provides browser automation capabilities via the Model Context Protocol (MCP). Unlike screenshot-based
approaches, Playwright MCP uses structured accessibility snapshots that are more deterministic and token-efficient for
LLMs.

## Features

- **Web Navigation**: Navigate to URLs, go back/forward, manage tabs
- **Element Interaction**: Click, type, fill forms, select dropdowns, hover
- **Page Inspection**: Take accessibility snapshots, screenshots, view console messages
- **JavaScript Execution**: Evaluate JavaScript in page context
- **File Uploads**: Upload files to web forms
- **Browser Control**: Resize viewport, install browsers, manage dialogs

## Environment Variables

| Variable                         | Default                  | Description                                      |
|----------------------------------|--------------------------|--------------------------------------------------|
| `PLAYWRIGHT_BROWSER`             | `chromium`               | Browser type: `chromium`, `firefox`, or `webkit` |
| `PLAYWRIGHT_HEADLESS`            | `false`                  | Run in headless mode (`true` or `false`)         |
| `PLAYWRIGHT_VIEWPORT`            | `1280x720`               | Browser viewport size (`WIDTHxHEIGHT`)           |
| `PLAYWRIGHT_TIMEOUT_ACTION`      | `5000`                   | Action timeout in milliseconds                   |
| `PLAYWRIGHT_TIMEOUT_NAVIGATION`  | `60000`                  | Navigation timeout in milliseconds               |
| `PLAYWRIGHT_OUTPUT_DIR`          | `$ATK_PLUGIN_DIR/output` | Directory for screenshots and traces             |
| `PLAYWRIGHT_IGNORE_HTTPS_ERRORS` | `false`                  | Ignore HTTPS certificate errors                  |

## Installation

```bash
# Add the plugin
atk add playwright

# Configure environment variables
atk setup playwright

# No install/start needed for MCP-only plugins
```

## Usage

After setup, get the MCP configuration:

```bash
atk mcp playwright
```

This outputs the MCP server configuration for your client.

### Available Tools

**Navigation & Interaction:**

- `browser_navigate` - Navigate to a URL
- `browser_click` - Click an element
- `browser_type` - Type text into an element
- `browser_fill_form` - Fill multiple form fields
- `browser_select_option` - Select dropdown option
- `browser_hover` - Hover over element
- `browser_press_key` - Press keyboard keys

**Page Inspection:**

- `browser_snapshot` - Get accessibility snapshot (recommended over screenshots)
- `browser_take_screenshot` - Take a screenshot
- `browser_console_messages` - Get console messages
- `browser_network_requests` - Get network requests

**JavaScript & Evaluation:**

- `browser_evaluate` - Evaluate JavaScript expression
- `browser_run_code` - Run Playwright code snippet

**Tab & Browser Management:**

- `browser_tabs` - List, create, close, or select tabs
- `browser_close` - Close the browser
- `browser_resize` - Resize browser window
- `browser_install` - Install/update browser

### Example Workflow

1. Navigate to a page
2. Take a snapshot to see the page structure
3. Click or interact with elements using their refs
4. Fill forms and submit
5. Take screenshots as needed

```
# Example MCP tool calls:
browser_navigate(url: "https://example.com")
browser_snapshot()  # Returns accessibility tree
browser_click(ref: "element-ref-from-snapshot")
browser_type(ref: "input-ref", text: "Hello World", submit: true)
browser_take_screenshot(filename: "result.png")
```

## Output Files

Screenshots, traces, and session files are saved to `PLAYWRIGHT_OUTPUT_DIR` (default: plugin's output directory).

## Documentation

- [Playwright MCP Repository](https://github.com/microsoft/playwright-mcp)
- [Playwright Documentation](https://playwright.dev)
- [MCP Protocol](https://modelcontextprotocol.io)

## License

Apache-2.0 (same as Playwright)
