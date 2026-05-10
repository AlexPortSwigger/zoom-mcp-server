"""Route table for Zoom MCP tools.

Drives both tool registration (in tools.py) and dispatch.

Each entry shape:
  name:        tool name (zoom_*)
  summary:     short description for tool list
  handler:     name of method on ZoomTools (e.g. "list_channels" -> _h_list_channels);
               None for tools handled inline by call_tool (zoom_authenticate,
               zoom_revoke_authentication).
  body:        dict[name -> {type, description}] declaring tool input properties
  required:    list of required arg names
"""
from typing import Any, Dict, List

API_BASE = "https://api.zoom.us/v2"

ENDPOINTS: List[Dict[str, Any]] = [
    # ---------- Auth & meta ----------
    {
        "name": "zoom_authenticate",
        "summary": "Authenticate with Zoom (opens browser, captures callback locally)",
        "handler": "authenticate",
    },
    {
        "name": "zoom_revoke_authentication",
        "summary": "Wipe local Zoom tokens, cache, and in-memory state",
        "handler": "revoke_authentication",
    },
    {
        "name": "zoom_get_my_info",
        "summary": "Get the authenticated user's profile (cached in memory)",
        "handler": "get_my_info",
    },

    # ---------- Resolve ----------
    {
        "name": "zoom_resolve",
        "summary": "Resolve a name or email to a channel/contact/user ID via cache",
        "handler": "resolve",
        "body": {
            "query": {"type": "string", "description": "Name, email, or fragment"},
            "kind": {
                "type": "string",
                "description": "channel|contact|auto (default auto)",
            },
        },
        "required": ["query"],
    },

    # ---------- Cross-channel search (manual fan-out) ----------
    {
        "name": "zoom_search_messages",
        "summary": (
            "Search messages across all your channels and DMs. Fans out "
            "scoped searches in parallel and merges results, sorted by "
            "recency. Use this when you want to find a topic without "
            "knowing the specific channel."
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

    # ---------- Channels ----------
    {
        "name": "zoom_list_channels",
        "summary": "List channels the user belongs to (cache-first)",
        "handler": "list_channels",
        "body": {
            "force_refresh": {"type": "boolean", "description": "Bypass cache"},
            "starred_only": {
                "type": "boolean",
                "description": "Only return starred channels",
            },
        },
    },
    {
        "name": "zoom_list_channel_members",
        "summary": "List members of a channel (cache-first)",
        "handler": "list_channel_members",
        "body": {
            "channel": {"type": "string", "description": "Channel name or ID"},
            "force_refresh": {"type": "boolean", "description": "Bypass cache"},
        },
        "required": ["channel"],
    },

    # ---------- Contacts ----------
    {
        "name": "zoom_list_contacts",
        "summary": "List the user's contacts (cache-first)",
        "handler": "list_contacts",
        "body": {
            "force_refresh": {"type": "boolean", "description": "Bypass cache"},
        },
    },

    # ---------- Messages (live) ----------
    {
        "name": "zoom_get_channel_history",
        "summary": (
            "Auto-paginated message history with reactions and attachment "
            "metadata inline"
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
        "summary": "Messages under a thread (parent message ID)",
        "handler": "get_thread",
        "body": {
            "message_id": {"type": "string", "description": "Parent message ID"},
            "channel": {"type": "string", "description": "Channel name or ID"},
            "contact": {"type": "string", "description": "Contact (for DM threads)"},
        },
        "required": ["message_id"],
    },
    {
        "name": "zoom_get_message",
        "summary": "Get a single chat message by ID",
        "handler": "get_message",
        "body": {
            "message_id": {"type": "string", "description": "Message ID"},
            "channel": {"type": "string", "description": "Channel name or ID"},
            "contact": {"type": "string", "description": "Contact (for DMs)"},
        },
        "required": ["message_id"],
    },

    # ---------- Pinned messages (unverified — may 404) ----------
    {
        "name": "zoom_list_pinned_messages",
        "summary": (
            "Pinned messages in a channel. Endpoint is unverified against "
            "Zoom docs; may return 404."
        ),
        "handler": "list_pinned_messages",
        "body": {"channel": {"type": "string", "description": "Channel name or ID"}},
        "required": ["channel"],
    },

    # ---------- Shared spaces (unverified paths — may 404) ----------
    {
        "name": "zoom_list_shared_spaces",
        "summary": (
            "Shared spaces the user belongs to. Endpoint paths added to "
            "Zoom in May 2024 but exact list path is unverified; may 404."
        ),
        "handler": "list_shared_spaces",
        "body": {"force_refresh": {"type": "boolean", "description": "Bypass cache"}},
    },
    {
        "name": "zoom_get_shared_space",
        "summary": (
            "Shared-space detail; include channels/members via include arg. "
            "Sub-paths unverified."
        ),
        "handler": "get_shared_space",
        "body": {
            "space_id": {"type": "string", "description": "Shared space ID"},
            "include": {
                "type": "string",
                "description": "all|detail|channels|members (default detail)",
            },
        },
        "required": ["space_id"],
    },

    # ---------- Meetings + Recordings ----------
    {
        "name": "zoom_list_meetings",
        "summary": "List user's meetings (filter by type and date range)",
        "handler": "list_meetings",
        "body": {
            "type": {
                "type": "string",
                "description": "scheduled|live|upcoming|previous_meetings",
            },
            "from_date": {
                "type": "string",
                "description": "ISO-8601 start (yyyy-MM-dd)",
            },
            "to_date": {"type": "string", "description": "ISO-8601 end (yyyy-MM-dd)"},
        },
    },
    {
        "name": "zoom_get_meeting",
        "summary": "Meeting details + recording manifest if available",
        "handler": "get_meeting",
        "body": {
            "meeting_id": {"type": "string", "description": "Meeting ID or UUID"},
        },
        "required": ["meeting_id"],
    },
    {
        "name": "zoom_list_recordings",
        "summary": "List the user's cloud recordings",
        "handler": "list_recordings",
        "body": {
            "from_date": {"type": "string", "description": "yyyy-MM-dd"},
            "to_date": {"type": "string", "description": "yyyy-MM-dd"},
        },
    },
    {
        "name": "zoom_get_meeting_transcript",
        "summary": "Download and parse a meeting transcript (VTT → text)",
        "handler": "get_meeting_transcript",
        "body": {
            "meeting_id": {"type": "string", "description": "Meeting ID or UUID"},
        },
        "required": ["meeting_id"],
    },

    # ---------- Meeting summaries (real Zoom AI Companion API) ----------
    {
        "name": "zoom_list_meeting_summaries",
        "summary": (
            "List AI-generated meeting summaries for the user. Requires "
            "Zoom AI Companion enabled on the account."
        ),
        "handler": "list_meeting_summaries",
        "body": {
            "from_date": {"type": "string", "description": "yyyy-MM-dd"},
            "to_date": {"type": "string", "description": "yyyy-MM-dd"},
        },
    },
    {
        "name": "zoom_get_meeting_summary",
        "summary": "Get the AI-generated summary for a specific meeting",
        "handler": "get_meeting_summary",
        "body": {
            "meeting_id": {"type": "string", "description": "Meeting ID or UUID"},
        },
        "required": ["meeting_id"],
    },
]


def endpoint_by_name(name: str) -> Dict[str, Any]:
    for ep in ENDPOINTS:
        if ep["name"] == name:
            return ep
    raise KeyError(name)
