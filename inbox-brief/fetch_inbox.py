#!/usr/bin/env python3
"""Fetch recent Gmail for the daddyshome inbox briefing.

Reads an app password from the macOS Keychain (never from a file):
    security add-generic-password -a <you@gmail.com> -s daddyshome-gmail -w

Messages are fetched with BODY.PEEK so nothing gets marked as read.

    python3 fetch_inbox.py [--days N] [--all] [--max N]

    --days N   look back N days (default 2)
    --all      include already-read mail (default: unread only)
    --max N    cap at N messages (default 40)
"""

import argparse
import email
import email.policy
import html
import imaplib
import os
import subprocess
import sys
from datetime import datetime, timedelta

# Zero-width and BOM characters used as padding in marketing email.
ZERO_WIDTH = {ord(c): None for c in "​‌‍⁠﻿"}

KEYCHAIN_SERVICE = "daddyshome-gmail"
IMAP_HOST = "imap.gmail.com"
SNIPPET_CHARS = 400


EMAIL_FILE = os.path.expanduser("~/.config/daddyshome/email")


def account():
    """Resolve the mailbox: env var, then ~/.config/daddyshome/email."""
    addr = os.environ.get("DADDYSHOME_EMAIL", "").strip()
    if not addr and os.path.exists(EMAIL_FILE):
        with open(EMAIL_FILE, encoding="utf-8-sig") as fh:
            addr = fh.read().strip()
    if not addr:
        sys.exit(
            "No mailbox configured. Either:\n"
            f"  echo you@gmail.com > {EMAIL_FILE}\n"
            "or set DADDYSHOME_EMAIL in your environment."
        )
    return addr


ACCOUNT = account()


def keychain_password():
    try:
        out = subprocess.run(
            ["security", "find-generic-password",
             "-a", ACCOUNT, "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError:
        sys.exit(
            f"No app password in the Keychain for {ACCOUNT}.\n"
            f"Generate one at https://myaccount.google.com/apppasswords (2FA required), then run:\n"
            f'  security add-generic-password -a {ACCOUNT} -s {KEYCHAIN_SERVICE} -w "your-app-password"'
        )
    return out.stdout.strip()


def snippet(msg):
    """Plain-text body, truncated. Falls back to stripped HTML."""
    try:
        part = msg.get_body(preferencelist=("plain", "html"))
        if part is None:
            return ""
        text = part.get_content()
        if part.get_content_subtype() == "html":
            import re
            text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
            text = re.sub(r"<[^>]+>", " ", text)
        # Marketing mail pads with entities and zero-width chars; strip both.
        text = html.unescape(text)
        text = text.translate(ZERO_WIDTH)
        text = " ".join(text.split())
    except Exception as exc:
        return f"[could not decode body: {exc}]"
    return text[:SNIPPET_CHARS] + ("..." if len(text) > SNIPPET_CHARS else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=2)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--max", type=int, default=40)
    args = ap.parse_args()

    since = (datetime.now() - timedelta(days=args.days)).strftime("%d-%b-%Y")
    criteria = ["SINCE", since] if args.all else ["UNSEEN", "SINCE", since]

    try:
        imap = imaplib.IMAP4_SSL(IMAP_HOST)
        imap.login(ACCOUNT, keychain_password())
    except imaplib.IMAP4.error as exc:
        sys.exit(f"Gmail login failed: {exc}\n"
                 "If this says AUTHENTICATIONFAILED, the app password is wrong or was revoked.")

    try:
        imap.select("INBOX", readonly=True)
        status, data = imap.search(None, *criteria)
        if status != "OK":
            sys.exit(f"IMAP search failed: {status}")

        ids = data[0].split()
        total = len(ids)
        ids = ids[-args.max:]

        scope = "all mail" if args.all else "unread"
        print(f"INBOX BRIEF — {scope}, last {args.days} day(s), {ACCOUNT}")
        print(f"{total} message(s) matched"
              + (f"; showing most recent {len(ids)}" if total > len(ids) else ""))
        print("=" * 72)

        if not ids:
            print("\nNothing new.")
            return

        for n, mid in enumerate(reversed(ids), 1):
            status, raw = imap.fetch(mid, "(BODY.PEEK[])")
            if status != "OK" or not raw or not isinstance(raw[0], tuple):
                print(f"\n[{n}] could not fetch message {mid.decode()}")
                continue
            msg = email.message_from_bytes(raw[0][1], policy=email.policy.default)
            print(f"\n[{n}] {msg.get('Subject', '(no subject)')}")
            print(f"    From: {msg.get('From', '(unknown)')}")
            print(f"    Date: {msg.get('Date', '(unknown)')}")
            body = snippet(msg)
            if body:
                print(f"    {body}")
    finally:
        try:
            imap.close()
        except Exception:
            pass
        imap.logout()


if __name__ == "__main__":
    main()
