"""Route table for Zoom MCP tools.

Tools are organised into five groups (the order here is how Claude
sees them):

  1. Authentication & profile
  2. AI Companion search & Q&A
  3. Meetings, recordings, transcripts, AI summaries
  4. Chat — channels, contacts, shared spaces
  5. Chat — messages, threads, files, pinned, bookmarks, mention groups
"""
from typing import Any, Dict, List

API_BASE = "https://api.zoom.us/v2"


ENDPOINTS: List[Dict[str, Any]] = [
    # =====================================================================
    # GROUP 1 — Authentication & profile
    # =====================================================================
    {
        "name": "zoom_authenticate",
        "summary": (
            "Authenticate with Zoom. Opens a browser window so the user can "
            "approve the connection, then captures the OAuth callback "
            "locally. Run this first if any Zoom tool reports 'Not "
            "authenticated'."
        ),
        "handler": "authenticate",
    },
    {
        "name": "zoom_revoke_authentication",
        "summary": (
            "Wipe the local Zoom session: tokens, metadata cache, and "
            "in-memory state. Use to log out or to start fresh."
        ),
        "handler": "revoke_authentication",
    },
    {
        "name": "zoom_get_my_info",
        "summary": "Get the authenticated user's Zoom profile (cached in memory).",
        "handler": "get_my_info",
    },
    {
        "name": "zoom_resolve",
        "summary": (
            "Resolve a name or email to a channel/contact/user ID using the "
            "local cache. Use this to translate from human-friendly names "
            "into the IDs other tools want."
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
    # GROUP 2 — AI Companion search & Q&A
    # =====================================================================
    {
        "name": "zoom_search",
        "summary": (
            "AI Companion search across Zoom Meetings, Chat, and Docs. "
            "Returns ranked results spanning all of the user's Zoom content "
            "in a single call. Best first stop for 'find anything about X' "
            "queries."
        ),
        "handler": "ai_companion_search",
        "body": {
            "query": {"type": "string", "description": "Search query"},
            "scope": {
                "type": "string",
                "description": "chat | meetings | docs | all (default all)",
            },
            "from_date": {"type": "string", "description": "ISO-8601 start date"},
            "to_date": {"type": "string", "description": "ISO-8601 end date"},
            "max_results": {
                "type": "integer",
                "description": "Maximum results (default 50)",
            },
        },
        "required": ["query"],
    },
    {
        "name": "zoom_ask",
        "summary": (
            "Ask Zoom AI Companion a grounded question. Returns a generated "
            "answer with citations into the source meetings, chat messages, "
            "or docs. Use when the user wants a synthesised answer rather "
            "than raw search results."
        ),
        "handler": "ai_companion_ask",
        "body": {
            "question": {"type": "string", "description": "Question to ask"},
            "scope": {
                "type": "string",
                "description": "chat | meetings | docs | all (default all)",
            },
            "from_date": {"type": "string", "description": "ISO-8601 start date"},
            "to_date": {"type": "string", "description": "ISO-8601 end date"},
        },
        "required": ["question"],
    },
    {
        "name": "zoom_search_messages",
        "summary": (
            "Manual cross-channel message search via parallel fan-out. "
            "Bypasses AI Companion for cases where exact-substring matching "
            "is wanted, or as a fallback if AI Companion is unavailable."
        ),
        "handler": "search_messages",
        "body": {
            "query": {"type": "string", "description": "Search query string"},
            "from_date": {"type": "string", "description": "ISO-8601 start date"},
            "to_date": {"type": "string", "description": "ISO-8601 end date"},
            "channel_filter": {
                "type": "string",
                "description": "Optional substring to filter channel names",
            },
            "max_results": {
                "type": "integer",
                "description": "Max results to return (default 100)",
            },
        },
        "required": ["query"],
    },

    # =====================================================================
    # GROUP 3 — Meetings, recordings, transcripts, AI summaries
    # =====================================================================
    {
        "name": "zoom_list_meetings",
        "summary": (
            "List the user's meetings. Filter by type (scheduled, live, "
            "upcoming, previous_meetings) and date range."
        ),
        "handler": "list_meetings",
        "body": {
            "type": {
                "type": "string",
                "description": "scheduled | live | upcoming | previous_meetings",
            },
            "from_date": {"type": "string", "description": "yyyy-MM-dd"},
            "to_date": {"type": "string", "description": "yyyy-MM-dd"},
        },
    },
    {
        "name": "zoom_get_meeting",
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
        "name": "zoom_list_recordings",
        "summary": "List the user's cloud recordings within a date range.",
        "handler": "list_recordings",
        "body": {
            "from_date": {"type": "string", "description": "yyyy-MM-dd"},
            "to_date": {"type": "string", "description": "yyyy-MM-dd"},
        },
    },
    {
        "name": "zoom_get_meeting_transcript",
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
        "name": "zoom_list_meeting_summaries",
        "summary": (
            "List Zoom AI Companion-generated summaries for the user's "
            "meetings."
        ),
        "handler": "list_meeting_summaries",
        "body": {
            "from_date": {"type": "string", "description": "yyyy-MM-dd"},
            "to_date": {"type": "string", "description": "yyyy-MM-dd"},
        },
    },
    {
        "name": "zoom_get_meeting_summary",
        "summary": "Get the AI Companion summary for one specific meeting.",
        "handler": "get_meeting_summary",
        "body": {
            "meeting_id": {
                "type": "string",
                "description": "Meeting ID or UUID",
            },
        },
        "required": ["meeting_id"],
    },

    # =====================================================================
    # GROUP 4 — Chat: channels, contacts, shared spaces
    # =====================================================================
    {
        "name": "zoom_list_channels",
        "summary": (
            "List channels the user belongs to. Cache-first; supports a "
            "starred-only filter for the channels the user cares about most."
        ),
        "handler": "list_channels",
        "body": {
            "force_refresh": {
                "type": "boolean",
                "description": "Bypass the metadata cache",
            },
            "starred_only": {
                "type": "boolean",
                "description": "Only return channels the user has starred",
            },
        },
    },
    {
        "name": "zoom_list_channel_members",
        "summary": "List the members of a channel (cache-first).",
        "handler": "list_channel_members",
        "body": {
            "channel": {"type": "string", "description": "Channel name or ID"},
            "force_refresh": {
                "type": "boolean",
                "description": "Bypass the metadata cache",
            },
        },
        "required": ["channel"],
    },
    {
        "name": "zoom_list_contacts",
        "summary": "List the user's Zoom contacts (cache-first).",
        "handler": "list_contacts",
        "body": {
            "force_refresh": {
                "type": "boolean",
                "description": "Bypass the metadata cache",
            },
        },
    },
    {
        "name": "zoom_list_shared_spaces",
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
        "name": "zoom_get_shared_space",
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
    # GROUP 5 — Chat: messages, threads, files, pinned, bookmarks, mentions
    # =====================================================================
    {
        "name": "zoom_get_channel_history",
        "summary": (
            "Auto-paginated message history for a channel or DM. Each "
            "message includes inline emoji reactions and attachment "
            "metadata. Use this for 'summarise the last week in #channel-x' "
            "tasks."
        ),
        "handler": "get_channel_history",
        "body": {
            "channel": {"type": "string", "description": "Channel name or ID"},
            "contact": {
                "type": "string",
                "description": "Contact email or ID (for DMs)",
            },
            "from_date": {"type": "string", "description": "ISO-8601 start"},
            "to_date": {"type": "string", "description": "ISO-8601 end"},
            "max_messages": {
                "type": "integer",
                "description": "Maximum messages to return (default 500)",
            },
        },
    },
    {
        "name": "zoom_get_thread",
        "summary": "Fetch all messages under a thread (parent message ID).",
        "handler": "get_thread",
        "body": {
            "message_id": {
                "type": "string",
                "description": "Parent message ID",
            },
            "channel": {"type": "string", "description": "Channel name or ID"},
            "contact": {
                "type": "string",
                "description": "Contact (for DM threads)",
            },
        },
        "required": ["message_id"],
    },
    {
        "name": "zoom_get_message",
        "summary": (
            "Get a single chat message by ID. Useful for drilling into a "
            "specific citation returned by zoom_search or zoom_ask."
        ),
        "handler": "get_message",
        "body": {
            "message_id": {"type": "string", "description": "Message ID"},
            "channel": {"type": "string", "description": "Channel name or ID"},
            "contact": {"type": "string", "description": "Contact (for DMs)"},
        },
        "required": ["message_id"],
    },
    {
        "name": "zoom_get_file",
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
        "name": "zoom_list_pinned_messages",
        "summary": "List the messages pinned in a channel.",
        "handler": "list_pinned_messages",
        "body": {
            "channel": {"type": "string", "description": "Channel name or ID"},
        },
        "required": ["channel"],
    },
    {
        "name": "zoom_list_bookmarks",
        "summary": "List the user's bookmarked messages.",
        "handler": "list_bookmarks",
    },
    {
        "name": "zoom_list_mention_groups",
        "summary": (
            "List the mention groups (e.g. @engineering) defined for a "
            "channel — useful signal for which teams the channel addresses."
        ),
        "handler": "list_mention_groups",
        "body": {
            "channel": {"type": "string", "description": "Channel name or ID"},
        },
        "required": ["channel"],
    },
]


def endpoint_by_name(name: str) -> Dict[str, Any]:
    for ep in ENDPOINTS:
        if ep["name"] == name:
            return ep
    raise KeyError(name)
