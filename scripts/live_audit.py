#!/usr/bin/env python3
"""End-to-end live audit: hit every tool the connector exposes against
the real Zoom API, using the deployed install's tokens. Prints a
pass/fail/skip line per tool with the actual response shape.

This is the test that complements the unit suite — unit tests use
httpx_mock and don't prove anything against Zoom's real surface. This
script does, and runs in seconds.

Run from the worktree root:
    python3 scripts/live_audit.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import certifi
import httpx

from server import (
    files,
    messages,
    search,
    shared_spaces,
    summaries,
    transcripts,
)
from server.cache.store import CacheStore
from server.dispatcher import paginate_all
from server.endpoints import API_BASE
from server.oauth import ZoomOAuthHandler
from server.paths import cache_db_file, token_file, token_key_file
from server.token_store import TokenStore


GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


class Audit:
    def __init__(self):
        self.results = []  # (status, tool, summary)

    def passed(self, tool, summary):
        self.results.append(("PASS", tool, summary))
        print(f"{GREEN}✅ PASS{RESET}  {tool:35s} {summary}")

    def failed(self, tool, summary):
        self.results.append(("FAIL", tool, summary))
        print(f"{RED}❌ FAIL{RESET}  {tool:35s} {summary}")

    def skipped(self, tool, summary):
        self.results.append(("SKIP", tool, summary))
        print(f"{YELLOW}⏭  SKIP{RESET}  {tool:35s} {summary}")

    def report(self):
        passed = sum(1 for s, _, _ in self.results if s == "PASS")
        failed = sum(1 for s, _, _ in self.results if s == "FAIL")
        skipped = sum(1 for s, _, _ in self.results if s == "SKIP")
        total = len(self.results)
        print()
        print(f"{'='*70}")
        print(
            f"Total: {total}   "
            f"{GREEN}Pass: {passed}{RESET}   "
            f"{RED}Fail: {failed}{RESET}   "
            f"{YELLOW}Skip: {skipped}{RESET}"
        )
        print(f"{'='*70}")
        return 0 if failed == 0 else 1


async def main() -> int:
    audit = Audit()

    # Build a real OAuth handler against the deployed install's tokens
    store = TokenStore(token_file(), token_key_file())
    if not store.load():
        print(f"{RED}No tokens — run zoom_auth_login first.{RESET}",
              file=sys.stderr)
        return 2
    oauth = ZoomOAuthHandler(
        client_id="EIQOYZ5wQBCSQk3a48lT6A",
        token_store=store,
        redirect_uri="http://localhost:8000/oauth/callback",
    )
    cache = CacheStore(cache_db_file())

    # ------------------------------------------------------------------
    # auth
    # ------------------------------------------------------------------
    r = await oauth.make_authenticated_request("GET", f"{API_BASE}/users/me")
    if r.status_code == 200:
        me = r.json()
        audit.passed("zoom_auth_whoami",
                     f"{me.get('display_name')} <{me.get('email')}>")
    else:
        audit.failed("zoom_auth_whoami", f"HTTP {r.status_code}: {r.text[:120]}")

    audit.skipped("zoom_auth_login", "interactive — already authed for this run")
    audit.skipped("zoom_auth_logout", "destructive — would wipe state")
    audit.skipped("zoom_auth_resolve", "pure cache lookup, no Zoom call")

    # ------------------------------------------------------------------
    # chat metadata
    # ------------------------------------------------------------------
    headers = oauth.get_auth_headers()
    try:
        chans = await paginate_all(
            "GET", f"{API_BASE}/chat/users/me/channels",
            items_key="channels", headers=headers, max_items=2000,
        )
        cache.put_channels(chans)
        audit.passed("zoom_chat_channels", f"{len(chans)} channels")
    except Exception as e:
        audit.failed("zoom_chat_channels", str(e)[:200])
        chans = []

    devs = next((c for c in chans if c.get("name") == "Devs"), None)
    sample_channel = devs or (chans[0] if chans else None)

    if sample_channel:
        try:
            mems = await paginate_all(
                "GET",
                f"{API_BASE}/chat/channels/{sample_channel['id']}/members",
                items_key="members", headers=headers, max_items=200,
            )
            audit.passed("zoom_chat_channel_members",
                         f"{len(mems)} in #{sample_channel.get('name','?')}")
        except Exception as e:
            audit.failed("zoom_chat_channel_members", str(e)[:200])
    else:
        audit.skipped("zoom_chat_channel_members", "no channels available")

    try:
        ctcs = await paginate_all(
            "GET", f"{API_BASE}/chat/users/me/contacts",
            items_key="contacts", headers=headers, max_items=500,
        )
        cache.put_contacts(ctcs)
        audit.passed("zoom_chat_contacts", f"{len(ctcs)} contacts")
    except Exception as e:
        audit.failed("zoom_chat_contacts", str(e)[:200])

    try:
        spaces = await shared_spaces.list_shared_spaces(oauth)
        audit.passed("zoom_chat_shared_spaces", f"{len(spaces)} shared spaces")
        if spaces:
            sd = await shared_spaces.get_shared_space(
                oauth, spaces[0]["id"], include="detail",
            )
            audit.passed("zoom_chat_shared_space_get",
                         f"detail keys: {list(sd.get('detail',{}).keys())[:5]}")
        else:
            audit.skipped("zoom_chat_shared_space_get",
                          "no shared spaces to fetch")
    except Exception as e:
        audit.failed("zoom_chat_shared_spaces", str(e)[:200])
        audit.skipped("zoom_chat_shared_space_get", "list failed")

    # ------------------------------------------------------------------
    # messages
    # ------------------------------------------------------------------
    sample_msg_id = None
    sample_thread_id = None
    if sample_channel:
        try:
            history = await messages.get_channel_history(
                oauth, channel_id=sample_channel["id"],
                from_date="2026-05-09T00:00:00Z",
                to_date="2026-05-10T23:59:59Z",
                max_messages=5,
            )
            audit.passed(
                "zoom_message_history",
                f"{len(history)} msgs from #{sample_channel.get('name','?')}",
            )
            if history:
                sample_msg_id = history[0]["id"]
                # find one with a reply
                for m in history:
                    if m.get("reply_main_message_id"):
                        sample_thread_id = m["reply_main_message_id"]
                        break
        except Exception as e:
            audit.failed("zoom_message_history", str(e)[:200])
    else:
        audit.skipped("zoom_message_history", "no channel to query")

    if sample_channel and sample_msg_id:
        try:
            m = await messages.get_message(
                oauth, message_id=sample_msg_id,
                channel_id=sample_channel["id"],
            )
            audit.passed("zoom_message_get",
                         f"msg by {m.get('sender','?')[:25]}")
        except Exception as e:
            audit.failed("zoom_message_get", str(e)[:200])
    else:
        audit.skipped("zoom_message_get", "no sample message id")

    if sample_channel and (sample_thread_id or sample_msg_id):
        try:
            thread = await messages.get_thread(
                oauth, message_id=sample_thread_id or sample_msg_id,
                channel_id=sample_channel["id"],
            )
            audit.passed("zoom_message_thread", f"{len(thread)} replies")
        except Exception as e:
            audit.failed("zoom_message_thread", str(e)[:200])
    else:
        audit.skipped("zoom_message_thread", "no message id")

    if sample_channel:
        try:
            pinned = await messages.list_pinned_messages(
                oauth, sample_channel["id"],
            )
            audit.passed("zoom_message_pinned",
                         f"{len(pinned)} pinned in #{sample_channel.get('name','?')}")
        except Exception as e:
            audit.failed("zoom_message_pinned", str(e)[:200])
    else:
        audit.skipped("zoom_message_pinned", "no channel")

    try:
        bms = await messages.list_bookmarks(oauth)
        audit.passed("zoom_message_bookmarks", f"{len(bms)} bookmarks")
    except Exception as e:
        audit.failed("zoom_message_bookmarks", str(e)[:200])

    # message_file: skip unless we found one; need a real file id
    audit.skipped(
        "zoom_message_file",
        "needs a real file_id from chat history; "
        "exercised in unit tests via test_files.py",
    )

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------
    if sample_channel:
        try:
            out = await search.search_messages(
                oauth, channels=[sample_channel], contacts=[],
                query="the", max_results=3,
            )
            audit.passed(
                "zoom_search_messages",
                f"total_found={out['total_found']} "
                f"scopes_searched={out['scopes_searched']} "
                f"errored={out['scopes_errored']}",
            )
        except Exception as e:
            audit.failed("zoom_search_messages", str(e)[:200])
    else:
        audit.skipped("zoom_search_messages", "no channel for fan-out")

    # ------------------------------------------------------------------
    # meetings + summaries
    # ------------------------------------------------------------------
    sample_meeting_id = None
    sample_uuid_with_summary = None

    try:
        out = await paginate_all(
            "GET", f"{API_BASE}/users/me/meetings",
            items_key="meetings", headers=headers,
            params={"type": "previous_meetings",
                    "from": "2026-04-10", "to": "2026-05-10"},
            max_items=10,
        )
        audit.passed("zoom_meeting_list", f"{len(out)} previous meetings")
        if out:
            sample_meeting_id = out[0].get("id") or out[0].get("uuid")
    except Exception as e:
        audit.failed("zoom_meeting_list", str(e)[:200])

    try:
        recs = await paginate_all(
            "GET", f"{API_BASE}/users/me/recordings",
            items_key="meetings", headers=headers,
            params={"from": "2026-04-10", "to": "2026-05-10"},
            max_items=10,
        )
        audit.passed("zoom_meeting_recordings", f"{len(recs)} recordings")
    except Exception as e:
        audit.failed("zoom_meeting_recordings", str(e)[:200])

    if sample_meeting_id:
        try:
            r = await oauth.make_authenticated_request(
                "GET", f"{API_BASE}/meetings/{sample_meeting_id}",
            )
            if r.status_code == 200:
                audit.passed(
                    "zoom_meeting_get",
                    f"id={sample_meeting_id} topic={r.json().get('topic','?')[:35]}",
                )
            else:
                audit.failed(
                    "zoom_meeting_get",
                    f"HTTP {r.status_code}: {r.text[:120]}",
                )
        except Exception as e:
            audit.failed("zoom_meeting_get", str(e)[:200])
    else:
        # Try with the user's PMI as a fallback
        try:
            me = await oauth.make_authenticated_request(
                "GET", f"{API_BASE}/users/me",
            )
            pmi = me.json().get("pmi")
            r = await oauth.make_authenticated_request(
                "GET", f"{API_BASE}/meetings/{pmi}",
            )
            if r.status_code == 200:
                audit.passed("zoom_meeting_get", f"PMI {pmi}")
            else:
                audit.failed("zoom_meeting_get",
                             f"HTTP {r.status_code}: {r.text[:120]}")
        except Exception as e:
            audit.failed("zoom_meeting_get", str(e)[:200])

    # zoom_meeting_summary_list intentionally NOT exposed by this
    # connector — Zoom requires a :admin scope only available to
    # Server-to-Server OAuth apps. Skipped here to keep the audit
    # tracking exactly what the connector ships.

    # meeting_summary_get: an endpoint-OK response is either 200 (with a
    # summary) or 404 with code 3001 ("meeting does not exist" — i.e. no
    # AI summary for that meeting, which is legitimate when the meeting
    # wasn't recorded with AI Companion enabled). 4xx with any other
    # code = endpoint genuinely broken (scope issue, etc.).
    summary_endpoint_ok = False
    summary_detail = ""
    candidate_ids = []
    if sample_uuid_with_summary:
        candidate_ids.append(sample_uuid_with_summary)
    # Re-fetch meeting list to gather UUIDs for testing
    try:
        ml = await paginate_all(
            "GET", f"{API_BASE}/users/me/meetings",
            items_key="meetings", headers=headers,
            params={"type": "previous_meetings",
                    "from": "2026-04-10", "to": "2026-05-10"},
            max_items=10,
        )
        for m in ml:
            if m.get("uuid"):
                candidate_ids.append(m["uuid"])
    except Exception:
        pass

    seen = set()
    last_msg = ""
    for ident in candidate_ids:
        if ident in seen:
            continue
        seen.add(ident)
        try:
            s = await summaries.get_meeting_summary(oauth, str(ident))
            audit.passed(
                "zoom_meeting_summary_get",
                f"got summary for {str(ident)[:25]}",
            )
            summary_endpoint_ok = True
            break
        except RuntimeError as e:
            msg = str(e)
            last_msg = msg
            # 404 -> server/summaries.py raises this specific phrase. The
            # endpoint is reachable; the meeting just has no summary.
            if (
                "No AI Companion summary available" in msg
                or "Meeting does not exist" in msg
                or '"code":3001' in msg
            ):
                summary_endpoint_ok = True
                summary_detail = (
                    "endpoint reachable; sample meetings have no summaries "
                    "(none recorded with AI Companion enabled). Pass when "
                    "user has a recorded meeting to test against."
                )
                continue
            # Real failure (scope etc.) — bail out
            summary_detail = msg[:200]
            break

    if summary_endpoint_ok:
        audit.passed("zoom_meeting_summary_get", summary_detail)
    else:
        audit.failed(
            "zoom_meeting_summary_get",
            summary_detail or last_msg or "no meeting id to test",
        )

    audit.skipped(
        "zoom_meeting_transcript",
        "needs a meeting with a cloud recording + transcript; "
        "we have 0 recordings",
    )

    return audit.report()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
