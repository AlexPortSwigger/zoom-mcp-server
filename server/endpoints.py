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
            "the IDs other tools want."
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
            "Returns id, name, type, and starred flag for each. Use this "
            "to (a) get the channel ID before calling zoom_message_history "
            "or zoom_message_pinned for a specific channel by name, or "
            "(b) discover what channels exist when the user asks 'what "
            "channels am I in?'. Pass starred_only=true to focus on the "
            "channels the user actively cares about (typically their "
            "team / project channels) — strongly recommended as a default "
            "for 'pulse on Zoom' style queries across hundreds of "
            "channels. Cache-first; data is fresh on first launch and "
            "refreshes lazily."
        ),
        "handler": "list_channels",
        "body": {
            "force_refresh": {
                "type": "boolean",
                "description": "Force a fresh fetch from Zoom, bypassing cache.",
            },
            "starred_only": {
                "type": "boolean",
                "description": (
                    "Return only channels the user has starred in the Zoom "
                    "client. Use this for 'pulse / important channels' queries."
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
        "name": "zoom_meeting_summary_list",
        "summary": (
            "List AI Companion-generated meeting summaries available to the "
            "user. Use this to discover which meetings have a summary "
            "(then call zoom_meeting_summary_get for the body), e.g. "
            "'show me summaries from this week's meetings'. Returns "
            "meeting_uuid, topic, start_time, summary_start_time, "
            "summary_end_time, summary_status."
        ),
        "handler": "list_meeting_summaries",
        "body": {
            "from_date": {
                "type": "string",
                "description": "yyyy-MM-dd lower bound (required for ranges).",
            },
            "to_date": {
                "type": "string",
                "description": "yyyy-MM-dd upper bound. Max ~1 month window.",
            },
        },
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
                    "Default: ~last few days."
                ),
            },
            "to_date": {
                "type": "string",
                "description": "End of window. Same formats as from_date.",
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
            "Search Zoom Team Chat messages by keyword across all the user's "
            "channels and DMs in parallel. Use this for 'find anything about "
            "<topic>', 'has anyone mentioned <X>?', 'what did <person> say "
            "about <Y>?'. Returns each hit tagged with the channel/contact "
            "it came from, with most-recent first.\n\n"
            "Important behaviour to know:\n"
            "- Zoom enforces a server-side cap of ~24 hours on each search "
            "  call regardless of `from_date`/`to_date` — for older content, "
            "  prefer `zoom_message_history` over a date range and let the "
            "  caller scan results.\n"
            "- For wide queries across 1000+ channels, use `channel_filter` "
            "  to narrow to a name substring (e.g. 'eng', 'product') so the "
            "  fan-out stays fast.\n"
            "- The result includes `total_found`, `scopes_searched`, "
            "  `scopes_errored`, and `sample_errors[]` so callers can see "
            "  exactly what worked and what didn't."
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
                    "yyyy-MM-dd start. Note: Zoom caps the effective window "
                    "to ~24h regardless of what's passed."
                ),
            },
            "to_date": {
                "type": "string",
                "description": "yyyy-MM-dd end (also subject to ~24h cap).",
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
]


def endpoint_by_name(name: str) -> Dict[str, Any]:
    for ep in ENDPOINTS:
        if ep["name"] == name:
            return ep
    raise KeyError(name)
