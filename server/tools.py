"""Tool registration and call_tool dispatch.

Maps endpoints.ENDPOINTS to handler methods on ZoomTools.
"""
import json
import logging
from typing import Any, Dict, List

from mcp.types import Tool

from . import messages, search, shared_spaces, summaries, transcripts
from .cache.store import CacheStore
from .dispatcher import paginate_all
from .endpoints import API_BASE, ENDPOINTS, endpoint_by_name
from .oauth import ZoomOAuthHandler

logger = logging.getLogger("zoom-mcp")


class ZoomTools:
    """Holds OAuth + cache state and dispatches tool calls."""

    def __init__(self, oauth_handler: ZoomOAuthHandler, cache: CacheStore):
        self.oauth = oauth_handler
        self.cache = cache
        self._my_info_cached: Dict[str, Any] = {}

    # ---- MCP interface ----

    def list_tools(self) -> List[Tool]:
        out: List[Tool] = []
        for ep in ENDPOINTS:
            properties: Dict[str, Any] = {}
            for k, v in ep.get("body", {}).items():
                properties[k] = {key: val for key, val in v.items()}
            schema: Dict[str, Any] = {"type": "object", "properties": properties}
            if ep.get("required"):
                schema["required"] = ep["required"]
            out.append(
                Tool(name=ep["name"], description=ep["summary"], inputSchema=schema)
            )
        return out

    async def call_tool(
        self, name: str, args: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        try:
            ep = endpoint_by_name(name)
        except KeyError:
            return _err(f"Unknown tool: {name}")

        if name == "zoom_authenticate":
            return await self._authenticate()
        if name == "zoom_revoke_authentication":
            return await self._revoke()

        if not await self.oauth.ensure_authenticated():
            return _err("Authentication required. Use 'zoom_authenticate' first.")

        for r in ep.get("required", []):
            if r not in args:
                return _err(f"Missing required argument: {r}")

        try:
            handler_name = ep.get("handler")
            method = getattr(self, f"_h_{handler_name}", None)
            if method is None:
                return _err(f"No handler implemented for {name}")
            return await method(args)
        except Exception as e:
            logger.exception("Handler %s failed", name)
            return _err(str(e))

    # ---- auth handlers ----

    async def _authenticate(self) -> List[Dict[str, Any]]:
        if not self.oauth.token_store.is_expired():
            return _text(
                "Already authenticated. Use zoom_revoke_authentication "
                "first to re-auth."
            )
        ok = await self.oauth.run_browser_flow()
        if not ok:
            return _err(
                "Authentication failed. Common causes: port 8000 in use; "
                "OAuth window closed before granting access; auth timed out "
                "(5 min limit)."
            )
        r = await self.oauth.make_authenticated_request(
            "GET", f"{API_BASE}/users/me"
        )
        if r.status_code == 200:
            u = r.json()
            return _text(
                "Authenticated.\n"
                f"User: {u.get('display_name')}\n"
                f"Email: {u.get('email')}"
            )
        return _err(f"Auth OK but user info failed: HTTP {r.status_code}")

    async def _revoke(self) -> List[Dict[str, Any]]:
        try:
            self.oauth.token_store.delete()
        except Exception:
            pass
        try:
            self.cache.clear_all()
        except Exception:
            pass
        self._my_info_cached = {}
        return _text(
            "Authentication revoked. Local tokens, cache, and in-memory state cleared."
        )

    # ---- info / resolve ----

    async def _h_get_my_info(self, args):
        if self._my_info_cached:
            return _json(self._my_info_cached)
        r = await self.oauth.make_authenticated_request(
            "GET", f"{API_BASE}/users/me"
        )
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}: {r.text}")
        self._my_info_cached = r.json()
        return _json(self._my_info_cached)

    async def _h_resolve(self, args):
        query = args["query"]
        kind = args.get("kind", "auto")

        if kind in ("channel", "auto"):
            ch = self.cache.get_channel_by_name(query)
            if ch:
                return _json({"kind": "channel", "match": ch})

        if kind in ("contact", "auto"):
            c = self.cache.get_contact_by_email(query)
            if c:
                return _json({"kind": "contact", "match": c})
            uid = self.cache.get_user_id_by_email(query)
            if uid:
                return _json(
                    {"kind": "contact", "match": {"id": uid, "email": query}}
                )

        # Cache miss: refresh and try again
        await self._refresh_channels()
        await self._refresh_contacts()

        if kind in ("channel", "auto"):
            ch = self.cache.get_channel_by_name(query)
            if ch:
                return _json({"kind": "channel", "match": ch})
        if kind in ("contact", "auto"):
            c = self.cache.get_contact_by_email(query)
            if c:
                return _json({"kind": "contact", "match": c})

        return _json(
            {
                "kind": None,
                "match": None,
                "message": f"No match for {query!r} in cache.",
            }
        )

    # ---- Cross-channel search (manual fan-out) ----

    async def _h_search_messages(self, args):
        # Make sure we have channels and contacts cached for the fan-out
        channels = self.cache.get_channels()
        if not channels:
            await self._refresh_channels()
            channels = self.cache.get_channels()
        contacts = self.cache.get_contacts()
        if not contacts:
            await self._refresh_contacts()
            contacts = self.cache.get_contacts()
        out = await search.search_messages(
            self.oauth,
            channels=channels,
            contacts=contacts,
            query=args["query"],
            from_date=args.get("from_date"),
            to_date=args.get("to_date"),
            channel_filter=args.get("channel_filter"),
            max_results=int(args.get("max_results", 100)),
        )
        return _json(out)

    # ---- Meeting summaries (real AI Companion APIs) ----

    async def _h_list_meeting_summaries(self, args):
        items = await summaries.list_meeting_summaries(
            self.oauth,
            from_date=args.get("from_date"),
            to_date=args.get("to_date"),
        )
        return _json({"summaries": items, "count": len(items)})

    async def _h_get_meeting_summary(self, args):
        out = await summaries.get_meeting_summary(self.oauth, args["meeting_id"])
        return _json(out)

    # ---- channels & contacts ----

    async def _refresh_channels(self):
        headers = self.oauth.get_auth_headers()
        items = await paginate_all(
            "GET",
            f"{API_BASE}/chat/users/me/channels",
            items_key="channels",
            headers=headers,
        )
        self.cache.put_channels(items)
        return items

    async def _h_list_channels(self, args):
        if args.get("force_refresh"):
            await self._refresh_channels()
        rows = self.cache.get_channels(starred_only=bool(args.get("starred_only")))
        if not rows:
            await self._refresh_channels()
            rows = self.cache.get_channels(
                starred_only=bool(args.get("starred_only"))
            )
        return _json({"channels": rows, "count": len(rows)})

    async def _refresh_contacts(self):
        headers = self.oauth.get_auth_headers()
        items = await paginate_all(
            "GET",
            f"{API_BASE}/chat/users/me/contacts",
            items_key="contacts",
            headers=headers,
        )
        self.cache.put_contacts(items)
        return items

    async def _h_list_contacts(self, args):
        if args.get("force_refresh"):
            await self._refresh_contacts()
        rows = self.cache.get_contacts()
        if not rows:
            await self._refresh_contacts()
            rows = self.cache.get_contacts()
        return _json({"contacts": rows, "count": len(rows)})

    async def _h_list_channel_members(self, args):
        channel_id = await self._resolve_channel_id(args["channel"])
        if not channel_id:
            return _err(f"Unknown channel: {args['channel']!r}")
        if not args.get("force_refresh"):
            cached = self.cache.get_channel_members(channel_id)
            if cached:
                return _json(
                    {
                        "channel_id": channel_id,
                        "members": cached,
                        "count": len(cached),
                    }
                )
        headers = self.oauth.get_auth_headers()
        items = await paginate_all(
            "GET",
            f"{API_BASE}/chat/channels/{channel_id}/members",
            items_key="members",
            headers=headers,
        )
        self.cache.put_channel_members(channel_id, items)
        return _json(
            {"channel_id": channel_id, "members": items, "count": len(items)}
        )

    # ---- ID resolution helpers ----

    async def _resolve_channel_id(self, channel: str):
        # Heuristic: long string with no '@' is likely already an ID
        if len(channel) > 20 and "@" not in channel:
            return channel
        ch = self.cache.get_channel_by_name(channel) or self.cache.get_channel_by_id(
            channel
        )
        if ch:
            return ch["id"]
        await self._refresh_channels()
        ch = self.cache.get_channel_by_name(channel) or self.cache.get_channel_by_id(
            channel
        )
        return ch["id"] if ch else None

    async def _resolve_contact_id(self, contact: str):
        if "@" not in contact:
            return contact
        c = self.cache.get_contact_by_email(contact)
        if c:
            return c["id"]
        # One-shot user lookup by email
        r = await self.oauth.make_authenticated_request(
            "GET", f"{API_BASE}/users/{contact}"
        )
        if r.status_code == 200:
            uid = r.json().get("id")
            if uid:
                self.cache.put_email_to_id(contact, uid)
                return uid
        return contact

    # ---- messages ----

    async def _h_get_channel_history(self, args):
        channel_id = None
        contact_id = None
        if args.get("channel"):
            channel_id = await self._resolve_channel_id(args["channel"])
        elif args.get("contact"):
            contact_id = await self._resolve_contact_id(args["contact"])
        if not channel_id and not contact_id:
            return _err("Either 'channel' or 'contact' is required.")
        items = await messages.get_channel_history(
            self.oauth,
            channel_id=channel_id,
            contact_id=contact_id,
            from_date=args.get("from_date"),
            to_date=args.get("to_date"),
            max_messages=int(args.get("max_messages", 500)),
        )
        return _json({"messages": items, "count": len(items)})

    async def _h_get_thread(self, args):
        channel_id = None
        contact_id = None
        if args.get("channel"):
            channel_id = await self._resolve_channel_id(args["channel"])
        if args.get("contact"):
            contact_id = await self._resolve_contact_id(args["contact"])
        items = await messages.get_thread(
            self.oauth,
            message_id=args["message_id"],
            channel_id=channel_id,
            contact_id=contact_id,
        )
        return _json({"messages": items, "count": len(items)})

    async def _h_get_message(self, args):
        channel_id = None
        contact_id = None
        if args.get("channel"):
            channel_id = await self._resolve_channel_id(args["channel"])
        if args.get("contact"):
            contact_id = await self._resolve_contact_id(args["contact"])
        out = await messages.get_message(
            self.oauth,
            message_id=args["message_id"],
            channel_id=channel_id,
            contact_id=contact_id,
        )
        return _json(out)

    # ---- pinned messages (unverified — may 404) ----

    async def _h_list_pinned_messages(self, args):
        channel_id = await self._resolve_channel_id(args["channel"])
        if not channel_id:
            return _err(f"Unknown channel: {args['channel']!r}")
        items = await messages.list_pinned_messages(self.oauth, channel_id)
        return _json({"messages": items, "count": len(items)})

    # ---- shared spaces ----

    async def _h_list_shared_spaces(self, args):
        if not args.get("force_refresh"):
            cached = self.cache.get_shared_spaces()
            if cached:
                return _json(
                    {"shared_spaces": cached, "count": len(cached)}
                )
        items = await shared_spaces.list_shared_spaces(self.oauth)
        self.cache.put_shared_spaces(items)
        return _json({"shared_spaces": items, "count": len(items)})

    async def _h_get_shared_space(self, args):
        out = await shared_spaces.get_shared_space(
            self.oauth,
            args["space_id"],
            include=args.get("include", "detail"),
        )
        return _json(out)

    # ---- meetings + recordings ----

    async def _h_list_meetings(self, args):
        headers = self.oauth.get_auth_headers()
        params = {}
        if args.get("type"):
            params["type"] = args["type"]
        if args.get("from_date"):
            params["from"] = args["from_date"]
        if args.get("to_date"):
            params["to"] = args["to_date"]
        items = await paginate_all(
            "GET",
            f"{API_BASE}/users/me/meetings",
            items_key="meetings",
            headers=headers,
            params=params,
        )
        return _json({"meetings": items, "count": len(items)})

    async def _h_get_meeting(self, args):
        meeting_id = args["meeting_id"]
        r = await self.oauth.make_authenticated_request(
            "GET", f"{API_BASE}/meetings/{meeting_id}"
        )
        if r.status_code != 200:
            return _err(f"HTTP {r.status_code}: {r.text}")
        detail = r.json()
        rec = await self.oauth.make_authenticated_request(
            "GET", f"{API_BASE}/meetings/{meeting_id}/recordings"
        )
        recordings = rec.json() if rec.status_code == 200 else None
        return _json({"meeting": detail, "recordings": recordings})

    async def _h_list_recordings(self, args):
        headers = self.oauth.get_auth_headers()
        params = {}
        if args.get("from_date"):
            params["from"] = args["from_date"]
        if args.get("to_date"):
            params["to"] = args["to_date"]
        items = await paginate_all(
            "GET",
            f"{API_BASE}/users/me/recordings",
            items_key="meetings",
            headers=headers,
            params=params,
        )
        return _json({"recordings": items, "count": len(items)})

    async def _h_get_meeting_transcript(self, args):
        text = await transcripts.fetch_meeting_transcript(
            self.oauth, args["meeting_id"]
        )
        return _json(
            {
                "meeting_id": args["meeting_id"],
                "transcript": text,
                "length_chars": len(text),
            }
        )


# ---- result helpers ----


def _text(s: str) -> List[Dict[str, Any]]:
    return [{"type": "text", "text": s}]


def _json(obj: Any) -> List[Dict[str, Any]]:
    return [
        {
            "type": "text",
            "text": json.dumps(obj, indent=2, ensure_ascii=False, default=str),
        }
    ]


def _err(msg: str) -> List[Dict[str, Any]]:
    return [{"type": "text", "text": f"Error: {msg}"}]
