"""Route table for Zoom MCP tools.

Tools are named with group prefixes so they alphabetise into 5 logical
groups in any client that sorts by name (e.g. Claude Desktop):

  zoom_auth_*    — authentication & profile (login, logout, whoami, resolve)
  zoom_chat_*    — channels, contacts, shared spaces
  zoom_meeting_* — meetings, recordings, transcripts, AI summaries
  zoom_message_* — individual messages, threads, files, pinned, bookmarks
  zoom_search_*  — cross-chat keyword search

Tool descriptions (`summary` field) are written so Claude can route
naturally for these use cases:

  "what's new in #channel today?"        → zoom_message_history
  "summarise #channel this week"         → zoom_message_history + Claude
  "find anything about <topic>"          → zoom_search_messages
  "what did I write recently"            → zoom_search_messages (own scope)
  "who's in #channel?"                   → zoom_chat_channel_members
  "list my channels"                     → zoom_chat_channels
  "list my recent meetings"              → zoom_meeting_list
  "summary of meeting X"                 → zoom_meeting_summary_get
"""
from typing import Any, Dict, List

API_BASE = "https://api.zoom.us/v2"


ENDPOINTS: List[Dict[str, Any]] = [
    # =====================================================================
    # zoom_auth_* — authentication & profile
    # =====================================================================
    {
        "name": "zoom_auth_login",
        "summary": (
            "Authenticate with Zoom. Opens a browser window so the user can "
            "approve the connection, then captures the OAuth callback "
            "locally. Run this first if any Zoom tool reports 'Not "
            "authenticated'."
        ),
        "handler": "authenticate",
    },
    {
        "name": "zoom_auth_logout",
        "summary": (
            "Wipe the local Zoom session: tokens, metadata cache, and "
            "in-memory state. Use to log out or to start fresh."
        ),
        "handler": "revoke_authentication",
    },
    {
        "name": "zoom_auth_whoami",
        "summary": "Get the authenticated user's Zoom profile (cached in memory).",
        "handler": "get_my_info",
    },
    {
        "name": "zoom_auth_resolve",
        "summary": (
            "Resolve a name or email to a channel/contact/user ID using the "
            "local cache. Use this to translate human-friendly names into "
            "the IDs other tools want.\n\n"
            "**Personalisation tip:** when the user repeatedly references "
            "the same people or channels by short or ambiguous names "
            "(e.g. 'Matt', 'the strategy chat', 'our team channel'), record "
            "which specific contact/channel they meant in your memory or "
            "project CLAUDE.md after confirming. Future references can then "
            "resolve directly — no re-scan, no clarifying question."
        ),
        "handler": "resolve",
        "body": {
            "query": {"type": "string", "description": "Name, email, or fragment"},
            "kind": {
                "type": "string",
                "description": "channel | contact | auto (default auto)",
            },
        },
        "required": ["query"],
    },

    # =====================================================================
    # zoom_chat_* — channels, contacts, shared spaces
    # =====================================================================
    {
        "name": "zoom_chat_channels",
        "summary": (
            "List the Zoom Team Chat channels the user is a member of. "
            "Returns id, name, type for each. Use this to (a) get a "
            "channel ID before calling zoom_message_history or "
            "zoom_message_pinned for a specific channel by name, or (b) "
            "discover what channels exist when the user asks 'what "
            "channels am I in?'. Cache-first; data is fresh on first "
            "launch and refreshes lazily.\n\n"
            "Note: Zoom's `/chat/users/me/channels` REST endpoint does "
            "not expose 'starred' status, so we can't filter to "
            "starred-only here. For narrowing, use `name_filter` or "
            "scan results client-side.\n\n"
            "**Personalisation tip:** Zoom workspaces often have hundreds "
            "or thousands of channels but each user actively cares about "
            "a handful. When the same channels recur across a user's "
            "queries, record the shortlist in your memory or project "
            "CLAUDE.md so future lookups can target them by ID directly "
            "instead of paging the full list."
        ),
        "handler": "list_channels",
        "body": {
            "force_refresh": {
                "type": "boolean",
                "description": "Force a fresh fetch from Zoom, bypassing cache.",
            },
            "name_filter": {
                "type": "string",
                "description": (
                    "Optional case-insensitive substring of channel name "
                    "to narrow results (e.g. 'eng', 'product', 'devs')."
                ),
            },
        },
    },
    {
        "name": "zoom_chat_channel_members",
        "summary": (
            "List the members of a channel by name or ID. Use to answer "
            "'who's in #channel?' or to map a sender's email to their "
            "display name in chat history. Cache-first."
        ),
        "handler": "list_channel_members",
        "body": {
            "channel": {
                "type": "string",
                "description": (
                    "Channel name (e.g. 'Devs') or channel ID. Names are "
                    "resolved via the local cache."
                ),
            },
            "force_refresh": {
                "type": "boolean",
                "description": "Force a fresh fetch, bypassing cache.",
            },
        },
        "required": ["channel"],
    },
    {
        "name": "zoom_chat_contacts",
        "summary": (
            "List the user's Zoom contacts (people they can DM). Returns "
            "id, email, display_name. Use this to find the right contact "
            "ID before passing `contact=` to zoom_message_history for a "
            "DM, or to answer 'who can I message on Zoom?'. Cache-first."
        ),
        "handler": "list_contacts",
        "body": {
            "force_refresh": {
                "type": "boolean",
                "description": "Force a fresh fetch from Zoom, bypassing cache.",
            },
        },
    },
    {
        "name": "zoom_chat_shared_spaces",
        "summary": "List shared spaces the user belongs to.",
        "handler": "list_shared_spaces",
        "body": {
            "force_refresh": {
                "type": "boolean",
                "description": "Bypass the metadata cache",
            },
        },
    },
    {
        "name": "zoom_chat_shared_space_get",
        "summary": (
            "Get details for one shared space, optionally including its "
            "channel list and member list via the include arg."
        ),
        "handler": "get_shared_space",
        "body": {
            "space_id": {"type": "string", "description": "Shared space ID"},
            "include": {
                "type": "string",
                "description": "all | detail | channels | members (default detail)",
            },
        },
        "required": ["space_id"],
    },

    # =====================================================================
    # zoom_meeting_* — meetings, recordings, transcripts, AI summaries
    # =====================================================================
    {
        "name": "zoom_meeting_list",
        "summary": (
            "List the authenticated user's Zoom meetings. Use for 'what "
            "meetings do I have today?', 'what's on my Zoom calendar this "
            "week?', or to find a meeting ID before fetching its summary "
            "or transcript.\n\n"
            "`type` semantics:\n"
            "- `upcoming` (default) — meetings starting in the next ~30 days\n"
            "- `live` — meetings currently in progress\n"
            "- `scheduled` — all scheduled meetings (no date filter needed)\n"
            "- `previous_meetings` — past meetings (REQUIRES from_date "
            "  and to_date, max ~1 month range)"
        ),
        "handler": "list_meetings",
        "body": {
            "type": {
                "type": "string",
                "description": (
                    "Filter type: scheduled | live | upcoming | "
                    "previous_meetings (default upcoming)."
                ),
            },
            "from_date": {
                "type": "string",
                "description": "yyyy-MM-dd. Required when type=previous_meetings.",
            },
            "to_date": {
                "type": "string",
                "description": "yyyy-MM-dd. Required when type=previous_meetings.",
            },
        },
    },
    {
        "name": "zoom_meeting_get",
        "summary": (
            "Get a meeting's details plus its recording manifest if a "
            "recording exists."
        ),
        "handler": "get_meeting",
        "body": {
            "meeting_id": {
                "type": "string",
                "description": "Meeting ID or UUID",
            },
        },
        "required": ["meeting_id"],
    },
    {
        "name": "zoom_meeting_recordings",
        "summary": "List the user's cloud recordings within a date range.",
        "handler": "list_recordings",
        "body": {
            "from_date": {"type": "string", "description": "yyyy-MM-dd"},
            "to_date": {"type": "string", "description": "yyyy-MM-dd"},
        },
    },
    {
        "name": "zoom_meeting_transcript",
        "summary": (
            "Download and parse a meeting transcript. Returns plain text "
            "with [HH:MM] speaker tags. Transcript content is never "
            "persisted on disk."
        ),
        "handler": "get_meeting_transcript",
        "body": {
            "meeting_id": {
                "type": "string",
                "description": "Meeting ID or UUID",
            },
        },
        "required": ["meeting_id"],
    },
    {
        "name": "zoom_meeting_summary_get",
        "summary": (
            "Fetch the full AI Companion summary body for one meeting — "
            "overview, action items, next steps. Use after the user picks "
            "a meeting from zoom_meeting_summary_list, or when they say "
            "'summarise meeting X' and you already have the meeting ID."
        ),
        "handler": "get_meeting_summary",
        "body": {
            "meeting_id": {
                "type": "string",
                "description": "Meeting ID or UUID. UUIDs from previous meetings.",
            },
        },
        "required": ["meeting_id"],
    },

    # =====================================================================
    # zoom_message_* — messages, threads, files, pinned, bookmarks, mentions
    # =====================================================================
    {
        "name": "zoom_message_history",
        "summary": (
            "Read messages from a Zoom Team Chat channel or DM, with "
            "auto-pagination, inline emoji reactions, and attachment "
            "metadata. **This is the primary tool for ingesting Zoom chat "
            "content** — use it for:\n\n"
            "- 'What's been said in #channel today?' (channel + today's date)\n"
            "- 'Summarise #channel this week' (channel + 7-day range)\n"
            "- 'Catch me up on my DMs with <person>' (contact = email)\n"
            "- 'What did <person> say in #channel recently?' "
            "  (channel, then filter results by sender)\n\n"
            "Provide either `channel` OR `contact` (not both). Returns "
            "messages oldest-first within the window, each with id, "
            "sender, sender_display_name, date_time, message body, "
            "reactions, files, and (when present) reply_main_message_id "
            "for thread replies."
        ),
        "handler": "get_channel_history",
        "body": {
            "channel": {
                "type": "string",
                "description": (
                    "Channel name (e.g. 'Devs') or ID. Provide this OR "
                    "`contact`. Names resolve via the local channel cache."
                ),
            },
            "contact": {
                "type": "string",
                "description": (
                    "Contact email (e.g. 'jane@…') or contact ID, for DM "
                    "history. Provide this OR `channel`."
                ),
            },
            "from_date": {
                "type": "string",
                "description": (
                    "Start of window. ISO-8601 datetime "
                    "(e.g. '2026-05-09T00:00:00Z') or yyyy-MM-dd. "
                    "Default: 7 days before to_date (or 7 days ago when "
                    "neither is given). Pass an explicit value for any "
                    "other range."
                ),
            },
            "to_date": {
                "type": "string",
                "description": "End of window. Same formats as from_date. Default: now.",
            },
            "max_messages": {
                "type": "integer",
                "description": (
                    "Cap on total messages returned (default 500). Raise "
                    "for full-channel summaries; lower for quick peeks."
                ),
            },
        },
    },
    {
        "name": "zoom_message_thread",
        "summary": (
            "Fetch every reply in a thread, given the parent message ID. "
            "Use when zoom_message_history surfaces a message with a "
            "thread (look for `reply_main_message_id` on the parent or "
            "non-zero `reply_count`) and the user wants the discussion."
        ),
        "handler": "get_thread",
        "body": {
            "message_id": {
                "type": "string",
                "description": "Parent (root) message ID of the thread.",
            },
            "channel": {
                "type": "string",
                "description": (
                    "Channel name or ID where the thread lives. Required if "
                    "`contact` is not given."
                ),
            },
            "contact": {
                "type": "string",
                "description": "Contact email/ID, for threads inside a DM.",
            },
        },
        "required": ["message_id"],
    },
    {
        "name": "zoom_message_get",
        "summary": (
            "Fetch one specific chat message by ID. Use when "
            "zoom_search_messages returns a hit and the user wants the "
            "full message (search results include only a snippet)."
        ),
        "handler": "get_message",
        "body": {
            "message_id": {"type": "string", "description": "Message ID."},
            "channel": {
                "type": "string",
                "description": "Channel name or ID where the message lives.",
            },
            "contact": {"type": "string", "description": "Contact (for DMs)."},
        },
        "required": ["message_id"],
    },
    {
        "name": "zoom_message_file",
        "summary": (
            "Get metadata for a chat file. For text/code MIME types "
            "(text/*, JSON, YAML, TOML, etc.) the file content is also "
            "returned inline (max 1MB). Binary files return metadata + a "
            "one-shot download URL."
        ),
        "handler": "get_file",
        "body": {"file_id": {"type": "string", "description": "Chat file ID"}},
        "required": ["file_id"],
    },
    {
        "name": "zoom_message_pinned",
        "summary": "List the messages pinned in a channel.",
        "handler": "list_pinned_messages",
        "body": {
            "channel": {"type": "string", "description": "Channel name or ID"},
        },
        "required": ["channel"],
    },
    {
        "name": "zoom_message_bookmarks",
        "summary": (
            "List the user's bookmarked chat messages. Useful when the user "
            "asks about messages they saved for later, e.g. 'what did I "
            "bookmark recently?'."
        ),
        "handler": "list_bookmarks",
    },

    # =====================================================================
    # zoom_search_* — cross-chat keyword search
    # =====================================================================
    {
        "name": "zoom_search_messages",
        "summary": (
            "Fast keyword search across Zoom Team Chat using Zoom's native "
            "search API. Use this as the FIRST attempt for 'find anything "
            "about <topic>' or 'has anyone mentioned <X>'.\n\n"
            "**Critical limitation: Zoom caps each call to ~24 hours of "
            "history server-side, regardless of from_date/to_date.** If a "
            "query that should match returns 0 hits, the message is "
            "almost certainly older than yesterday — fall back to "
            "`zoom_search_history` for the same query with a wider date "
            "range. (`zoom_search_messages` is fast; `zoom_search_history` "
            "is slower but unlimited in time range.)\n\n"
            "Returns: results[] (most-recent first, each tagged with its "
            "channel/contact), total_found, scopes_searched, "
            "scopes_errored, sample_errors[] (deduped error fingerprints), "
            "mode='fast'."
        ),
        "handler": "search_messages",
        "body": {
            "query": {
                "type": "string",
                "description": (
                    "Keyword(s) to search for. Zoom does prefix/word matching, "
                    "not substring — search for 'meeting' not 'eet'."
                ),
            },
            "from_date": {
                "type": "string",
                "description": (
                    "yyyy-MM-dd start. Default: 7 days ago. Note: Zoom "
                    "may cap the effective window to ~24h server-side "
                    "regardless of what's passed — if you get 0 hits "
                    "and expect older matches, fall back to "
                    "`zoom_search_history`."
                ),
            },
            "to_date": {
                "type": "string",
                "description": (
                    "yyyy-MM-dd end. Default: now. Also subject to "
                    "Zoom's ~24h server-side cap."
                ),
            },
            "channel_filter": {
                "type": "string",
                "description": (
                    "Optional case-insensitive substring of channel name to "
                    "narrow the fan-out (e.g. 'devs', 'eng'). Strongly "
                    "recommended in workspaces with many channels."
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "Max results returned (default 100).",
            },
        },
        "required": ["query"],
    },
    {
        "name": "zoom_search_history",
        "summary": (
            "Deep keyword search across Zoom Team Chat history — bypasses "
            "Zoom's 24h native-search cap by reading the full message "
            "history of each scope and filtering client-side.\n\n"
            "**WHEN TO USE THIS TOOL:**\n"
            "- Whenever `zoom_search_messages` returns 0 hits and you "
            "  suspect the message exists (especially when its `hint` "
            "  field tells you so). The `zoom_search_messages` 24h cap "
            "  is invisible to the caller; assume any 0-hit result for "
            "  a real-sounding query is hiding older content.\n"
            "- For 'find messages from <person> about <topic>' — pass "
            "  `query=<topic>` and `sender_filter=<their email or "
            "  display name>`.\n"
            "- For 'what did <person> say in our DMs?' — also pass "
            "  `contacts=[<their email>]` to include the DM thread.\n"
            "- When the user gives a rough date range ('last week', "
            "  'this month', 'in March'), use a generous `from_date`/"
            "  `to_date`; deep search honours them fully.\n\n"
            "**RECOMMENDED CALL PATTERN:**\n"
            "```\n"
            "zoom_search_history(\n"
            "  query=\"SVPG\",                       # the keyword\n"
            "  from_date=\"2026-02-10\",             # 90d back\n"
            "  to_date=\"2026-05-10\",               # today\n"
            "  sender_filter=\"alex.craig\",         # if 'from <person>'\n"
            "  channel_filter=\"product\",           # narrow to relevant\n"
            "  contacts=[\"alex.craig@portswigger.net\"],  # DM with them\n"
            ")\n"
            "```\n\n"
            "**PERFORMANCE & SCOPE:**\n"
            "- Default scans ALL channels the user is in (typically "
            "  ~30s for 1500 channels × 30 days). Use `channel_filter` "
            "  to narrow to a name substring whenever you can — drops "
            "  scan time proportionally.\n"
            "- DMs are NOT scanned by default — pass `contacts=[...]` "
            "  to include specific DM threads.\n"
            "- Each scope is paged up to 2000 messages; very high-"
            "  volume channels may be partially scanned.\n\n"
            "**WHAT IT DOESN'T COVER:** This tool only searches Zoom "
            "**Team Chat** messages. It does NOT search meeting "
            "transcripts, meeting summaries, or Zoom Docs. If a user "
            "remembers something said 'in a meeting', try "
            "`zoom_meeting_summary_get` or `zoom_meeting_transcript` "
            "for the relevant meeting instead."
        ),
        "handler": "search_history",
        "body": {
            "query": {
                "type": "string",
                "description": (
                    "Substring to match (case-insensitive) against the "
                    "message body. Plain substring; 'SVPG' matches "
                    "'SVPG / Cagan'. No wildcards/regex."
                ),
            },
            "from_date": {
                "type": "string",
                "description": (
                    "yyyy-MM-dd or ISO-8601 start. **Required** — "
                    "scope-bounded: scan time scales with date range. "
                    "Use 30d for 'last month' queries, 90d for "
                    "'recently', 180d for 'in the last few months'."
                ),
            },
            "to_date": {
                "type": "string",
                "description": "yyyy-MM-dd or ISO-8601 end. Default: now.",
            },
            "channel_filter": {
                "type": "string",
                "description": (
                    "**Strongly recommended for speed.** Case-insensitive "
                    "substring of channel name to narrow scope (e.g. "
                    "'eng', 'product', 'devs'). Without this, all "
                    "channels are scanned (slow in large workspaces)."
                ),
            },
            "contacts": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of contact emails (or contact IDs) for DM "
                    "threads to scan in addition to channels. Use this "
                    "for 'messages with <person>' queries. Empty "
                    "default — DMs are not scanned unless asked for."
                ),
            },
            "sender_filter": {
                "type": "string",
                "description": (
                    "Only return messages whose sender (email) or "
                    "sender_display_name contains this string "
                    "(case-insensitive). Use for 'messages from "
                    "<person>'."
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "Max results returned (default 100).",
            },
        },
        "required": ["query", "from_date"],
    },
]


def endpoint_by_name(name: str) -> Dict[str, Any]:
    for ep in ENDPOINTS:
        if ep["name"] == name:
            return ep
    raise KeyError(name)
