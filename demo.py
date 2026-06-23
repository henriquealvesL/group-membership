#!/usr/bin/env python3
"""
demo.py — Group Membership building block demonstration.

Run each node in a separate terminal:

    # Terminal 1 — create the group (first node)
    python demo.py --port 5001 --start

    # Terminal 2 — join via node 1
    python demo.py --port 5002 --join localhost:5001

    # Terminal 3 — join via any existing member
    python demo.py --port 5003 --join localhost:5001

    Press Ctrl+C on any terminal to see a graceful leave.
    Kill a terminal with Ctrl+Z (or `kill -9`) to simulate a crash.
"""

import argparse
import logging
import sys
import time

from group_membership import GroupMembership, View

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)


def on_view_change(view: View):
    members = ", ".join(f"{h}:{p}" for h, p in sorted(view.members))
    print(f"\n{'='*60}")
    print(f"  VIEW INSTALLED  →  {view}")
    print(f"  Members now: {members}")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Group Membership demo node",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--host",  default="localhost", help="This node's host")
    parser.add_argument("--port",  type=int, required=True, help="This node's port")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--start", action="store_true",
        help="Create a new group (use for the first node only)",
    )
    group.add_argument(
        "--join", metavar="HOST:PORT",
        help="Join an existing group via this member",
    )
    args = parser.parse_args()

    gm = GroupMembership(args.host, args.port)
    gm.on_view_change = on_view_change

    if args.start:
        gm.start()
    else:
        known_host, known_port = args.join.rsplit(":", 1)
        ok = gm.join(known_host, int(known_port))
        if not ok:
            print("ERROR: Could not join — is the known member running?")
            sys.exit(1)

    print(f"\nNode {args.host}:{args.port} running. Ctrl+C = graceful leave.\n")

    try:
        while True:
            time.sleep(5)
            view = gm.get_view()
            if view:
                print(f"[status] current {view}")
    except KeyboardInterrupt:
        print("\nLeaving gracefully...")
        gm.leave()


if __name__ == "__main__":
    main()
