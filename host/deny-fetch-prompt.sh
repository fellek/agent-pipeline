#!/usr/bin/env bash
# PermissionRequest hook for WebFetch: nobody answers a prompt in the unattended
# session, so a host without a WebFetch allow rule is refused instead.
cat >/dev/null
printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PermissionRequest","decision":{"behavior":"deny","message":"This host is not in the WebFetch(domain:...) allow rules of .claude/settings.json. Read the local source instead, or report the missing domain as an open point."}}}'
