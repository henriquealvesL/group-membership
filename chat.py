#!/usr/bin/env python3
"""
chat.py — Distributed chat application using the Group Membership building block.

Each chat node is an independent process that communicates via TCP (Berkeley Sockets).
The GroupMembership building block maintains a consistent view of who is online,
detects failures via heartbeats, and coordinates view changes.

Usage (run each in a separate terminal):

    # Terminal 1 — create the chat room
    python chat.py --name Alice --port 5001 --start

    # Terminal 2 — join via any existing member
    python chat.py --name Bob --port 5002 --join localhost:5001

    # Terminal 3
    python chat.py --name Charlie --port 5003 --join localhost:5001

    Ctrl+C = graceful leave.  Kill the terminal = simulated crash (detected by heartbeat).
"""

import argparse
import logging
import sys
import threading

from group_membership import GroupMembership, View

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)

COLORS = {
    "reset":   "\033[0m",
    "bold":    "\033[1m",
    "green":   "\033[32m",
    "yellow":  "\033[33m",
    "cyan":    "\033[36m",
    "red":     "\033[31m",
    "magenta": "\033[35m",
    "gray":    "\033[90m",
}

USER_COLORS = ["\033[36m", "\033[33m", "\033[35m", "\033[32m", "\033[34m", "\033[91m"]


class ChatApp:
    def __init__(self, name: str, host: str, port: int):
        self.name = name
        self.gm = GroupMembership(host, port)
        self.gm.on_view_change = self._on_view_change
        self.gm.on_message = self._on_message

        self._names: dict[tuple, str] = {}
        self._names[(host, port)] = name
        self._color_map: dict[str, str] = {}
        self._color_idx = 0

    def _get_color(self, name: str) -> str:
        if name not in self._color_map:
            self._color_map[name] = USER_COLORS[self._color_idx % len(USER_COLORS)]
            self._color_idx += 1
        return self._color_map[name]

    def _print_system(self, msg: str):
        c = COLORS
        print(f"\r{c['gray']}  >> {msg}{c['reset']}")

    def _print_chat(self, sender: str, text: str):
        c = COLORS
        color = self._get_color(sender)
        print(f"\r{color}{c['bold']}{sender}{c['reset']}: {text}")

    def _on_view_change(self, view: View):
        members = ", ".join(
            self._names.get(m, f"{m[0]}:{m[1]}") for m in sorted(view.members)
        )
        self._print_system(
            f"View #{view.view_id} installed — members: [{members}]"
        )
        self._prompt()

    def _on_message(self, msg: dict):
        sender_addr = tuple(msg["sender"])
        sender_name = msg.get("sender_name", f"{sender_addr[0]}:{sender_addr[1]}")
        self._names[sender_addr] = sender_name

        if sender_addr == self.gm.addr:
            return

        self._print_chat(sender_name, msg["text"])
        self._prompt()

    def _prompt(self):
        c = COLORS
        print(f"{c['bold']}[{self.name}]{c['reset']} ", end="", flush=True)

    def _send_chat(self, text: str):
        self.gm.broadcast(
            sender=list(self.gm.addr),
            sender_name=self.name,
            text=text,
        )

    def _show_help(self):
        c = COLORS
        print(f"\r{c['cyan']}Commands:{c['reset']}")
        print(f"  {c['bold']}/members{c['reset']}  — show current group members")
        print(f"  {c['bold']}/view{c['reset']}     — show current view details")
        print(f"  {c['bold']}/help{c['reset']}     — show this help")
        print(f"  {c['bold']}/quit{c['reset']}     — leave the chat")

    def _show_members(self):
        view = self.gm.get_view()
        if not view:
            self._print_system("No view installed yet.")
            return
        c = COLORS
        print(f"\r{c['cyan']}Online ({len(view.members)}):{c['reset']}")
        for m in sorted(view.members):
            name = self._names.get(m, "?")
            coord = " (coordinator)" if m == view.coordinator() else ""
            is_me = " (you)" if m == self.gm.addr else ""
            print(f"  {c['bold']}{name}{c['reset']} @ {m[0]}:{m[1]}{coord}{is_me}")

    def _show_view(self):
        view = self.gm.get_view()
        if not view:
            self._print_system("No view installed yet.")
            return
        c = COLORS
        print(f"\r{c['cyan']}{view}{c['reset']}")
        print(f"  Coordinator: {view.coordinator()[0]}:{view.coordinator()[1]}")

    def _input_loop(self):
        self._prompt()
        while True:
            try:
                line = input()
            except EOFError:
                break

            text = line.strip()
            if not text:
                self._prompt()
                continue

            if text == "/quit":
                break
            elif text == "/help":
                self._show_help()
            elif text == "/members":
                self._show_members()
            elif text == "/view":
                self._show_view()
            elif text.startswith("/"):
                self._print_system(f"Unknown command: {text}. Type /help")
            else:
                self._print_chat(self.name, text)
                self._send_chat(text)

            self._prompt()

    def run(self, start: bool, join_target: tuple[str, int] | None = None):
        c = COLORS

        if start:
            self.gm.start()
            print(f"{c['green']}Chat room created!{c['reset']}")
        else:
            host, port = join_target
            print(f"Joining chat via {host}:{port}...")
            self.gm.broadcast(
                sender=list(self.gm.addr),
                sender_name=self.name,
                text="",
            )
            ok = self.gm.join(host, port)
            if not ok:
                print(f"{c['red']}Could not join — is the target node running?{c['reset']}")
                sys.exit(1)
            print(f"{c['green']}Joined!{c['reset']}")

        self.gm.broadcast(
            sender=list(self.gm.addr),
            sender_name=self.name,
            text="",
        )

        print(f"{c['gray']}Type messages and press Enter. /help for commands.{c['reset']}")
        print()

        try:
            self._input_loop()
        except KeyboardInterrupt:
            pass

        print(f"\n{c['yellow']}Leaving chat...{c['reset']}")
        self.gm.leave()


def main():
    parser = argparse.ArgumentParser(
        description="Distributed chat using Group Membership",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--name", required=True, help="Your display name")
    parser.add_argument("--host", default="localhost", help="Bind host (default: localhost)")
    parser.add_argument("--port", type=int, required=True, help="Bind port")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--start", action="store_true", help="Create a new chat room")
    group.add_argument("--join", metavar="HOST:PORT", help="Join via an existing member")

    args = parser.parse_args()

    app = ChatApp(args.name, args.host, args.port)

    join_target = None
    if args.join:
        host, port = args.join.rsplit(":", 1)
        join_target = (host, int(port))

    app.run(start=args.start, join_target=join_target)


if __name__ == "__main__":
    main()
