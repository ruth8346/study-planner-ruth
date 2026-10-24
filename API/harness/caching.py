"""Prompt-cache breakpoints (cache_control). Render order is tools -> system -> messages.

Three of the four allowed breakpoints:
  1. last tool definition  -> caches the tool list
  2. system prompt         -> caches tools + system
  3. last block of the last message -> caches the whole conversation so far; the
     next request reads it back and only pays full price for the new turn.
Markers are added to a copy of the request, never to the stored history.
"""
from __future__ import annotations

import copy

from API.harness import logger

log = logger("caching.py")

EPHEMERAL = {"type": "ephemeral"}


def apply(request: dict) -> dict:
    req = copy.deepcopy(request)
    req["tools"][-1]["cache_control"] = EPHEMERAL
    req["system"] = [{"type": "text", "text": req["system"], "cache_control": EPHEMERAL}]
    last = req["messages"][-1]
    if isinstance(last["content"], str):
        last["content"] = [{"type": "text", "text": last["content"]}]
    last["content"][-1]["cache_control"] = EPHEMERAL
    log(f"3 breakpoints: tool '{req['tools'][-1]['name']}', system, messages[{len(req['messages']) - 1}]"
        f".content[{len(last['content']) - 1}] ({last['content'][-1]['type']})")
    return req
