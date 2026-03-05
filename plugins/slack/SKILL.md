# Slack — Agent Skill

Provides access to a Slack workspace: read channel history, list channels and users, post messages, and manage threads.

## Tools

- **`slack_list_channels`** — List channels the bot can access. Use this first to discover `channel_id` values.
- **`slack_get_channel_history`** — Fetch recent messages from a channel. Returns message text, timestamps, and user IDs.
- **`slack_post_message`** — Post a new message to a channel or user. Use a `channel_id` from `slack_list_channels`.
- **`slack_reply_to_thread`** — Reply to an existing message thread using its `thread_ts` timestamp.
- **`slack_get_thread_replies`** — Retrieve all replies within a thread.
- **`slack_add_reaction`** — Add an emoji reaction to a message by `channel_id` + `timestamp`.
- **`slack_get_users`** — List all workspace users. Returns `user_id` values needed for `slack_get_user_profile`.
- **`slack_get_user_profile`** — Get full profile details (name, title, email) for a user by `user_id`.

## Usage Patterns

- **Find a channel then read it**: call `slack_list_channels` → pick `channel_id` → call `slack_get_channel_history`.
- **Reply to a message**: get history to find `thread_ts` → call `slack_reply_to_thread`.
- **Mention someone by name**: call `slack_get_users` to resolve name → `user_id`, then include in your message.
- **No search tool**: the server does not expose a search_messages capability. To find a message, paginate `slack_get_channel_history` or use `slack_get_thread_replies` on a known thread.

## Notes

- The bot must be **invited to a channel** (`/invite @bot`) before it can read or post there.
- `channel_id` is a Slack-internal ID (e.g. `C01ABC123`), not the human-readable name.
- Timestamps (`thread_ts`) use Slack's epoch-with-microseconds format: `"1234567890.123456"`.
- Scopes required: `channels:read`, `channels:history`, `chat:write`, `users:read`, `users.profile:read`, `reactions:write`.
- Private channels require the `groups:read` and `groups:history` scopes and the bot must be a member.

