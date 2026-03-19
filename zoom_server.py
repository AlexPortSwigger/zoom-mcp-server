#!/usr/bin/env python3
"""
Zoom Team Chat MCP Server - Full API Implementation
Complete coverage of the Zoom Team Chat API (69 endpoints)
Uses a data-driven route table for maintainability.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure local imports work
sys.path.insert(0, str(Path(__file__).parent))

from base_mcp_server import BaseMCPServer
from utils import TokenManager
from mcp.types import Resource, Tool
from zoom_oauth_handler import ZoomOAuthHandler


# ---------------------------------------------------------------------------
# Route table: every Zoom Team Chat API endpoint as a declarative dict.
# Each entry drives tool registration AND request dispatch automatically.
# ---------------------------------------------------------------------------

ENDPOINTS: List[Dict[str, Any]] = [
    # -----------------------------------------------------------------------
    # Authentication (special-cased in call_tool)
    # -----------------------------------------------------------------------
    {
        "name": "zoom_authenticate",
        "summary": "Authenticate with Zoom (opens browser for OAuth)",
        "method": None,
        "path": None,
        "params": {},
        "body": {},
        "required": [],
    },

    # -----------------------------------------------------------------------
    # User Info
    # -----------------------------------------------------------------------
    {
        "name": "zoom_get_my_info",
        "summary": "Get information about the authenticated Zoom user",
        "method": "GET",
        "path": "/users/me",
        "params": {},
        "body": {},
        "required": [],
    },
    {
        "name": "zoom_get_user_id",
        "summary": "Look up a Zoom user by email address",
        "method": "GET",
        "path": "/users/{email}",
        "params": {
            "email": {"type": "string", "description": "Email address to look up"},
        },
        "body": {},
        "required": ["email"],
        "path_params": ["email"],
    },

    # -----------------------------------------------------------------------
    # Messages
    # -----------------------------------------------------------------------
    {
        "name": "zoom_list_messages",
        "summary": "List user's chat messages (to a contact or channel)",
        "method": "GET",
        "path": "/chat/users/me/messages",
        "params": {
            "to_contact": {"type": "string", "description": "Email, user ID, or member ID of chat contact"},
            "to_channel": {"type": "string", "description": "Channel ID to get messages from"},
            "date": {"type": "string", "description": "Query date for messages (yyyy-MM-dd)"},
            "from": {"type": "string", "description": "Start date-time (yyyy-MM-dd'T'HH:mm:ss'Z')"},
            "to": {"type": "string", "description": "End date-time (yyyy-MM-dd'T'HH:mm:ss'Z')"},
            "page_size": {"type": "integer", "description": "Number of records per page (max 50)"},
            "next_page_token": {"type": "string", "description": "Pagination token"},
            "include_deleted_and_edited_message": {"type": "boolean", "description": "Include edited/deleted messages"},
            "search_type": {"type": "string", "description": "Search type: 'message' or 'file'"},
            "search_key": {"type": "string", "description": "Search query string (up to 256 chars)"},
            "exclude_child_message": {"type": "boolean", "description": "Exclude child/thread messages"},
            "download_file_formats": {"type": "string", "description": "File format for download URLs"},
        },
        "body": {},
        "required": [],
    },
    {
        "name": "zoom_send_message",
        "summary": "Send a chat message to a contact or channel",
        "method": "POST",
        "path": "/chat/users/me/messages",
        "params": {},
        "body": {
            "message": {"type": "string", "description": "The message to send"},
            "to_contact": {"type": "string", "description": "Email, user ID, or member ID of recipient"},
            "to_channel": {"type": "string", "description": "Channel ID to send message to"},
            "reply_main_message_id": {"type": "string", "description": "Message ID to reply to (thread)"},
            "file_ids": {"type": "array", "items": {"type": "string"}, "description": "File IDs to attach (max 6)"},
            "at_items": {"type": "array", "items": {"type": "object"}, "description": "Mention items (@mentions)"},
            "rich_text": {"type": "array", "items": {"type": "object"}, "description": "Rich text formatting"},
            "interactive_cards": {"type": "array", "items": {"type": "object"}, "description": "Interactive cards"},
            "scheduled_time": {"type": "string", "description": "Scheduled send time (yyyy-MM-dd'T'HH:mm:ss'Z')"},
        },
        "required": ["message"],
    },
    {
        "name": "zoom_get_message",
        "summary": "Get a specific chat message",
        "method": "GET",
        "path": "/chat/users/me/messages/{messageId}",
        "params": {
            "messageId": {"type": "string", "description": "The message ID"},
            "to_contact": {"type": "string", "description": "Email/user ID/member ID of the contact"},
            "to_channel": {"type": "string", "description": "Channel ID where message was sent"},
            "download_file_formats": {"type": "string", "description": "File format for download URLs"},
        },
        "body": {},
        "required": ["messageId"],
        "path_params": ["messageId"],
    },
    {
        "name": "zoom_update_message",
        "summary": "Update/edit a chat message",
        "method": "PUT",
        "path": "/chat/users/me/messages/{messageId}",
        "params": {
            "messageId": {"type": "string", "description": "The message ID to update"},
        },
        "body": {
            "message": {"type": "string", "description": "Updated message content"},
            "to_contact": {"type": "string", "description": "Email/user ID/member ID of the contact"},
            "to_channel": {"type": "string", "description": "Channel ID where message was sent"},
            "file_ids": {"type": "array", "items": {"type": "string"}, "description": "Updated file IDs"},
            "at_items": {"type": "array", "items": {"type": "object"}, "description": "Updated mention items"},
            "rich_text": {"type": "array", "items": {"type": "object"}, "description": "Updated rich text"},
            "interactive_cards": {"type": "array", "items": {"type": "object"}, "description": "Updated interactive cards"},
        },
        "required": ["messageId", "message"],
        "path_params": ["messageId"],
    },
    {
        "name": "zoom_delete_message",
        "summary": "Delete a chat message",
        "method": "DELETE",
        "path": "/chat/users/me/messages/{messageId}",
        "params": {
            "messageId": {"type": "string", "description": "The message ID to delete"},
            "to_contact": {"type": "string", "description": "Email/user ID/member ID of the contact"},
            "to_channel": {"type": "string", "description": "Channel ID where message was sent"},
        },
        "body": {},
        "required": ["messageId"],
        "path_params": ["messageId"],
    },
    {
        "name": "zoom_react_to_message",
        "summary": "Add or remove an emoji reaction on a message",
        "method": "PATCH",
        "path": "/chat/users/me/messages/{messageId}/emoji_reactions",
        "params": {
            "messageId": {"type": "string", "description": "The message ID"},
        },
        "body": {
            "action": {"type": "string", "description": "'add' or 'remove'"},
            "emoji": {"type": "string", "description": "The emoji character or name"},
            "to_contact": {"type": "string", "description": "Contact who received the message"},
            "to_channel": {"type": "string", "description": "Channel where message was sent"},
        },
        "required": ["messageId", "action", "emoji"],
        "path_params": ["messageId"],
    },

    # -----------------------------------------------------------------------
    # Channels (user-level)
    # -----------------------------------------------------------------------
    {
        "name": "zoom_list_channels",
        "summary": "List channels the authenticated user belongs to",
        "method": "GET",
        "path": "/chat/users/me/channels",
        "params": {
            "page_size": {"type": "integer", "description": "Number of records per page (max 100)"},
            "next_page_token": {"type": "string", "description": "Pagination token"},
        },
        "body": {},
        "required": [],
    },
    {
        "name": "zoom_create_channel",
        "summary": "Create a new chat channel",
        "method": "POST",
        "path": "/chat/users/me/channels",
        "params": {},
        "body": {
            "name": {"type": "string", "description": "Channel name"},
            "type": {"type": "integer", "description": "Channel type: 1=private, 2=private with ext users, 3=public, 4=instant, 5=public with ext users"},
            "members": {"type": "array", "items": {"type": "object"}, "description": "Members to add (max 20). Each: {email: str} or {user_id: str}"},
            "channel_settings": {"type": "object", "description": "Channel settings object"},
        },
        "required": ["name"],
    },
    {
        "name": "zoom_get_channel",
        "summary": "Get a channel's details",
        "method": "GET",
        "path": "/chat/channels/{channelId}",
        "params": {
            "channelId": {"type": "string", "description": "The channel ID"},
        },
        "body": {},
        "required": ["channelId"],
        "path_params": ["channelId"],
    },
    {
        "name": "zoom_update_channel",
        "summary": "Update a channel's name, settings, or type",
        "method": "PATCH",
        "path": "/chat/channels/{channelId}",
        "params": {
            "channelId": {"type": "string", "description": "The channel ID"},
        },
        "body": {
            "name": {"type": "string", "description": "New channel name"},
            "type": {"type": "integer", "description": "New channel type"},
            "channel_settings": {"type": "object", "description": "Updated channel settings"},
        },
        "required": ["channelId"],
        "path_params": ["channelId"],
    },
    {
        "name": "zoom_delete_channel",
        "summary": "Delete a channel",
        "method": "DELETE",
        "path": "/chat/channels/{channelId}",
        "params": {
            "channelId": {"type": "string", "description": "The channel ID to delete"},
        },
        "body": {},
        "required": ["channelId"],
        "path_params": ["channelId"],
    },
    {
        "name": "zoom_search_channels",
        "summary": "Search user's or account's channels",
        "method": "POST",
        "path": "/chat/channels/search",
        "params": {},
        "body": {
            "needle": {"type": "string", "description": "Search query string"},
            "haystack": {"type": "string", "description": "Where to search: 'user_joined', 'account_public', 'all'"},
            "page_size": {"type": "integer", "description": "Records per page"},
            "next_page_token": {"type": "string", "description": "Pagination token"},
        },
        "required": ["needle", "haystack"],
    },

    # -----------------------------------------------------------------------
    # Channel Members
    # -----------------------------------------------------------------------
    {
        "name": "zoom_list_channel_members",
        "summary": "List members of a channel",
        "method": "GET",
        "path": "/chat/channels/{channelId}/members",
        "params": {
            "channelId": {"type": "string", "description": "The channel ID"},
            "page_size": {"type": "integer", "description": "Records per page"},
            "next_page_token": {"type": "string", "description": "Pagination token"},
        },
        "body": {},
        "required": ["channelId"],
        "path_params": ["channelId"],
    },
    {
        "name": "zoom_invite_channel_members",
        "summary": "Invite members to a channel (max 5 per call)",
        "method": "POST",
        "path": "/chat/channels/{channelId}/members",
        "params": {
            "channelId": {"type": "string", "description": "The channel ID"},
        },
        "body": {
            "members": {"type": "array", "items": {"type": "object"}, "description": "Members to invite. Each: {email: str} or {user_id: str}"},
        },
        "required": ["channelId", "members"],
        "path_params": ["channelId"],
    },
    {
        "name": "zoom_join_channel",
        "summary": "Join a public channel",
        "method": "POST",
        "path": "/chat/channels/{channelId}/members/me",
        "params": {
            "channelId": {"type": "string", "description": "The channel ID to join"},
        },
        "body": {},
        "required": ["channelId"],
        "path_params": ["channelId"],
    },
    {
        "name": "zoom_leave_channel",
        "summary": "Leave a channel",
        "method": "DELETE",
        "path": "/chat/channels/{channelId}/members/me",
        "params": {
            "channelId": {"type": "string", "description": "The channel ID to leave"},
        },
        "body": {},
        "required": ["channelId"],
        "path_params": ["channelId"],
    },

    # -----------------------------------------------------------------------
    # Contacts
    # -----------------------------------------------------------------------
    {
        "name": "zoom_list_contacts",
        "summary": "List user's contacts",
        "method": "GET",
        "path": "/chat/users/me/contacts",
        "params": {
            "type": {"type": "string", "description": "Contact type: 'company', 'external'"},
            "page_size": {"type": "integer", "description": "Records per page"},
            "next_page_token": {"type": "string", "description": "Pagination token"},
        },
        "body": {},
        "required": [],
    },
    {
        "name": "zoom_get_contact",
        "summary": "Get detailed info about a contact",
        "method": "GET",
        "path": "/chat/users/me/contacts/{identifier}",
        "params": {
            "identifier": {"type": "string", "description": "Contact's user ID, email, or member ID"},
            "query_presence_status": {"type": "boolean", "description": "Include presence status"},
        },
        "body": {},
        "required": ["identifier"],
        "path_params": ["identifier"],
    },
    {
        "name": "zoom_search_company_contacts",
        "summary": "Search company contacts",
        "method": "GET",
        "path": "/contacts",
        "params": {
            "search_key": {"type": "string", "description": "Search query (name or email)"},
            "query_presence_status": {"type": "boolean", "description": "Include presence status"},
            "page_size": {"type": "integer", "description": "Records per page"},
            "next_page_token": {"type": "string", "description": "Pagination token"},
        },
        "body": {},
        "required": ["search_key"],
    },

    # -----------------------------------------------------------------------
    # Chat Sessions
    # -----------------------------------------------------------------------
    {
        "name": "zoom_list_chat_sessions",
        "summary": "List a user's chat sessions",
        "method": "GET",
        "path": "/chat/users/me/sessions",
        "params": {
            "from": {"type": "string", "description": "Start date (yyyy-MM-dd)"},
            "to": {"type": "string", "description": "End date (yyyy-MM-dd)"},
            "page_size": {"type": "integer", "description": "Records per page"},
            "next_page_token": {"type": "string", "description": "Pagination token"},
        },
        "body": {},
        "required": [],
    },

    # -----------------------------------------------------------------------
    # Bookmarks
    # -----------------------------------------------------------------------
    {
        "name": "zoom_list_bookmarks",
        "summary": "List bookmarked messages",
        "method": "GET",
        "path": "/chat/messages/bookmarks",
        "params": {
            "to_contact": {"type": "string", "description": "Filter by contact"},
            "to_channel": {"type": "string", "description": "Filter by channel ID"},
            "page_size": {"type": "integer", "description": "Records per page"},
            "next_page_token": {"type": "string", "description": "Pagination token"},
        },
        "body": {},
        "required": [],
    },

    # -----------------------------------------------------------------------
    # Pinned Messages
    # -----------------------------------------------------------------------
    {
        "name": "zoom_list_pinned_messages",
        "summary": "List pinned messages in a channel",
        "method": "GET",
        "path": "/chat/channels/{channelId}/pinned",
        "params": {
            "channelId": {"type": "string", "description": "The channel ID"},
            "page_size": {"type": "integer", "description": "Records per page"},
            "next_page_token": {"type": "string", "description": "Pagination token"},
        },
        "body": {},
        "required": ["channelId"],
        "path_params": ["channelId"],
    },

    # -----------------------------------------------------------------------
    # Shared Spaces
    # -----------------------------------------------------------------------
    {
        "name": "zoom_list_shared_spaces",
        "summary": "List shared spaces",
        "method": "GET",
        "path": "/chat/spaces",
        "params": {
            "page_size": {"type": "string", "description": "Records per page"},
            "next_page_token": {"type": "string", "description": "Pagination token"},
        },
        "body": {},
        "required": [],
    },

    # -----------------------------------------------------------------------
    # Custom Emojis
    # -----------------------------------------------------------------------
    {
        "name": "zoom_list_custom_emojis",
        "summary": "List custom emojis",
        "method": "GET",
        "path": "/chat/emoji",
        "params": {
            "search_key": {"type": "string", "description": "Search query for emoji name (min 3 chars)"},
            "page_size": {"type": "integer", "description": "Records per page"},
            "next_page_token": {"type": "string", "description": "Pagination token"},
        },
        "body": {},
        "required": [],
    },
]

# Build a name -> endpoint lookup for fast dispatch
_ENDPOINT_MAP: Dict[str, Dict[str, Any]] = {ep["name"]: ep for ep in ENDPOINTS}


class ZoomMCPServer(BaseMCPServer):
    """Full Zoom Team Chat MCP Server."""

    API_BASE = "https://api.zoom.us/v2"

    def __init__(self):
        super().__init__(
            server_name="zoom-integration",
            description="Zoom Team Chat - full API integration for Claude"
        )

        self.zoom_oauth = ZoomOAuthHandler(
            client_id=self.get_required_env_var("ZOOM_CLIENT_ID"),
            client_secret=self.get_required_env_var("ZOOM_CLIENT_SECRET"),
            redirect_uri=os.getenv("ZOOM_REDIRECT_URI"),
            logger=self.logger,
        )
        self.setup_oauth(self.zoom_oauth)

    # ------------------------------------------------------------------
    # MCP interface
    # ------------------------------------------------------------------

    async def list_resources(self) -> List[Resource]:
        return []

    async def list_tools(self) -> List[Tool]:
        """Generate Tool objects from the ENDPOINTS route table."""
        tools: List[Tool] = []
        for ep in ENDPOINTS:
            properties: Dict[str, Any] = {}
            for pname, pschema in ep.get("params", {}).items():
                properties[pname] = {k: v for k, v in pschema.items()}
            for bname, bschema in ep.get("body", {}).items():
                properties[bname] = {k: v for k, v in bschema.items()}

            schema: Dict[str, Any] = {
                "type": "object",
                "properties": properties,
            }
            if ep.get("required"):
                schema["required"] = ep["required"]

            tools.append(Tool(
                name=ep["name"],
                description=ep["summary"],
                inputSchema=schema,
            ))
        return tools

    async def call_tool(self, name: str, arguments: dict) -> List[Dict[str, Any]]:
        try:
            if name == "zoom_authenticate":
                return await self._handle_authenticate()

            if not await self.ensure_oauth_authenticated():
                return self.create_error_result(
                    "Authentication required. Use 'zoom_authenticate' first."
                )

            ep = _ENDPOINT_MAP.get(name)
            if not ep:
                return self.create_error_result(f"Unknown tool: {name}")

            missing = [r for r in ep.get("required", []) if r not in arguments]
            if missing:
                return self.create_error_result(
                    f"Missing required arguments: {', '.join(missing)}"
                )

            return await self._dispatch(ep, arguments)

        except Exception as e:
            self.logger.error(f"Error in {name}: {e}")
            return self.create_error_result(str(e))

    # ------------------------------------------------------------------
    # Generic dispatcher
    # ------------------------------------------------------------------

    async def _dispatch(self, ep: dict, arguments: dict) -> List[Dict[str, Any]]:
        method = ep["method"]
        path_template = ep["path"]
        path_params = set(ep.get("path_params", []))

        path = path_template
        for pp in path_params:
            value = arguments.get(pp, "")
            path = path.replace(f"{{{pp}}}", str(value))

        url = f"{self.API_BASE}{path}"

        if ep.get("multipart"):
            return await self._dispatch_multipart(ep, url, arguments)

        query_params: Dict[str, Any] = {}
        body_params: Dict[str, Any] = {}

        for pname in ep.get("params", {}):
            if pname in path_params:
                continue
            if pname in arguments:
                query_params[pname] = arguments[pname]

        query_in_body = set(ep.get("query_in_body", []))

        for bname in ep.get("body", {}):
            if bname in arguments:
                if bname in query_in_body:
                    query_params[bname] = arguments[bname]
                else:
                    body_params[bname] = arguments[bname]

        if "message_id" in ep.get("params", {}) and "message_id" in arguments:
            query_params["message_id"] = arguments["message_id"]

        kwargs: Dict[str, Any] = {}
        if query_params:
            kwargs["params"] = query_params
        if body_params and method in ("POST", "PUT", "PATCH"):
            kwargs["json"] = body_params

        response = await self.make_oauth_request(method, url, **kwargs)
        return self._format_response(response)

    async def _dispatch_multipart(
        self, ep: dict, url: str, arguments: dict
    ) -> List[Dict[str, Any]]:
        import mimetypes

        file_path = arguments.get("file_path", "")
        if not file_path or not os.path.isfile(file_path):
            return self.create_error_result(f"File not found: {file_path}")

        mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        filename = os.path.basename(file_path)

        query_params: Dict[str, Any] = {}
        for pname in ep.get("params", {}):
            if pname in arguments:
                query_params[pname] = arguments[pname]

        with open(file_path, "rb") as f:
            files = {"file": (filename, f, mime_type)}
            data: Dict[str, str] = {}
            if "name" in arguments and "name" in ep.get("body", {}):
                data["name"] = arguments["name"]

            kwargs: Dict[str, Any] = {"files": files}
            if data:
                kwargs["data"] = data
            if query_params:
                kwargs["params"] = query_params

            response = await self.make_oauth_request("POST", url, **kwargs)

        return self._format_response(response)

    def _format_response(self, response) -> List[Dict[str, Any]]:
        if response.status_code in (200, 201, 204):
            if response.status_code == 204 or not response.content:
                return self.create_text_result(f"Success ({response.status_code})")
            try:
                return self.create_json_result(response.json())
            except Exception:
                return self.create_text_result(response.text)
        else:
            return self.create_error_result(
                f"HTTP {response.status_code}: {response.text}"
            )

    # ------------------------------------------------------------------
    # Authentication handler
    # ------------------------------------------------------------------

    async def _handle_authenticate(self) -> List[Dict[str, Any]]:
        try:
            self.logger.info("Starting Zoom OAuth authentication...")
            success = await self.ensure_oauth_authenticated()

            if success:
                response = await self.make_oauth_request(
                    "GET", f"{self.API_BASE}/users/me"
                )
                if response.status_code == 200:
                    user = response.json()
                    return self.create_text_result(
                        f"Authenticated with Zoom!\n"
                        f"User: {user.get('display_name', 'Unknown')}\n"
                        f"Email: {user.get('email', 'Unknown')}"
                    )
                return self.create_error_result(
                    f"Auth OK but user info failed: {response.text}"
                )
            return self.create_error_result(
                "Authentication failed. Check your Zoom app configuration."
            )
        except Exception as e:
            self.logger.error(f"Auth error: {e}")
            return self.create_error_result(f"Authentication error: {e}")


if __name__ == "__main__":
    server = ZoomMCPServer()
    server.run_server()
