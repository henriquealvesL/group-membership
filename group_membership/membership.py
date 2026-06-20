import socket
import threading
import logging
from typing import Callable, List, Optional

from .view import View, Member
from .messages import MsgType, encode, decode
from .failure_detector import FailureDetector

log = logging.getLogger(__name__)


class GroupMembership:
    """
    Group Membership building block — primary component model.

    Maintains a consistent, ordered sequence of views of the group.
    Each view records exactly which processes are alive and in the group.

    ── Algorithm overview ────────────────────────────────────────────────
    Failure detection:
        Every process sends heartbeats to all members (FailureDetector).
        A missing heartbeat triggers a LEAVE notification to the coordinator.

    Coordinator election:
        No explicit election is needed. The member with the smallest (host, port)
        in the current view is deterministically chosen as coordinator by all members.
        When that member leaves or fails, the next-smallest becomes coordinator.

    View change protocol (coordinator-driven):
        1. Coordinator receives a trigger (join request / leave / suspected crash).
        2. Coordinator builds the proposed next view and sends VIEW_PROPOSAL
           to every member in the new view.
        3. Each member replies with VIEW_ACK.
        4. Coordinator collects all ACKs and broadcasts VIEW_INSTALL.
        5. Every member installs the new view and notifies the application.

    ── Public API ────────────────────────────────────────────────────────
        gm = GroupMembership("localhost", 5001)
        gm.on_view_change = lambda view: print("New view:", view)

        gm.start()                         # create group (first node only)
        # OR
        gm.join("localhost", 5000)         # join via any existing member

        view = gm.get_view()               # current View object
        gm.leave()                         # graceful departure
    """

    def __init__(self, host: str, port: int):
        self.addr: Member = (host, port)

        self._view:    Optional[View] = None
        self._lock     = threading.Lock()

        # Coordinator-side view change state
        self._pending:     Optional[View] = None
        self._acks:        set            = set()
        self._acks_needed: int            = 0

        # Signals the joining process that it has been accepted into a view
        self._joined_event = threading.Event()

        # Callback fired on the application layer whenever the view changes
        self.on_view_change: Optional[Callable[[View], None]] = None

        self._fd = FailureDetector(
            self_addr      = self.addr,
            members_getter = self._get_members,
            send_fn        = self._send_heartbeat,
            on_suspect_fn  = self._on_suspect,
        )
        self._fd_started = False

        self._server  = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((host, port))
        self._running = False

    # ── Public API ────────────────────────────────────────────────────

    def start(self):
        """
        Start as the first (and only) member of a new group.
        Creates the initial view V0 = {self}.
        """
        self._running = True
        self._start_server()
        self._install_view(View(view_id=0, members=[self.addr]))
        log.info(f"[GM] {self.addr[0]}:{self.addr[1]} — created new group")

    def join(self, known_host: str, known_port: int, timeout: float = 10.0) -> bool:
        """
        Join an existing group through any known member.
        Blocks until the new view is installed or timeout expires.
        Returns True on success, False on timeout.
        """
        self._running = True
        self._start_server()
        self._send(
            (known_host, known_port),
            MsgType.JOIN_REQUEST,
            requester=list(self.addr),
        )
        log.info(
            f"[GM] {self.addr[0]}:{self.addr[1]}"
            f" — sent JOIN_REQUEST to {known_host}:{known_port}"
        )
        ok = self._joined_event.wait(timeout=timeout)
        if not ok:
            log.error(f"[GM] Join timed out after {timeout}s")
        return ok

    def leave(self):
        """
        Gracefully leave the group.
        Notifies all current members so the view can be updated without waiting
        for the failure detector to time out.
        """
        with self._lock:
            members = list(self._view.members) if self._view else []
        for member in members:
            if member != self.addr:
                self._send(member, MsgType.LEAVE, leaver=list(self.addr))
        self._shutdown()
        log.info(f"[GM] {self.addr[0]}:{self.addr[1]} — left the group")

    def get_view(self) -> Optional[View]:
        """Return the current membership view (thread-safe)."""
        with self._lock:
            return self._view

    # ── Internal: TCP server ──────────────────────────────────────────

    def _start_server(self):
        self._server.listen(20)
        threading.Thread(
            target=self._accept_loop, daemon=True, name="gm-server"
        ).start()

    def _accept_loop(self):
        while self._running:
            try:
                conn, _ = self._server.accept()
                threading.Thread(
                    target=self._handle_conn, args=(conn,), daemon=True
                ).start()
            except OSError:
                break

    def _handle_conn(self, conn: socket.socket):
        """Read one newline-delimited JSON message and dispatch it."""
        try:
            data = b""
            while b"\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            if data:
                self._dispatch(decode(data))
        except Exception as e:
            log.debug(f"[GM] Error in connection handler: {e}")
        finally:
            conn.close()

    # ── Internal: message dispatch ────────────────────────────────────

    def _dispatch(self, msg: dict):
        t = msg["type"]

        if t == MsgType.HEARTBEAT:
            self._fd.record(tuple(msg["sender"]))

        elif t == MsgType.JOIN_REQUEST:
            self._on_join_request(tuple(msg["requester"]))

        elif t == MsgType.LEAVE:
            self._on_leave(tuple(msg["leaver"]))

        elif t == MsgType.VIEW_PROPOSAL:
            self._on_view_proposal(
                View.from_dict(msg["view"]), tuple(msg["coordinator"])
            )

        elif t == MsgType.VIEW_ACK:
            self._on_view_ack(tuple(msg["acker"]), msg["view_id"])

        elif t == MsgType.VIEW_INSTALL:
            self._install_view(View.from_dict(msg["view"]))

    # ── Internal: membership protocol ────────────────────────────────

    def _on_join_request(self, requester: Member):
        """
        If I am the current coordinator, add the requester to the group.
        Otherwise, forward the request to the coordinator.
        """
        with self._lock:
            if self._view is None:
                return
            coord = self._view.coordinator()

        if coord == self.addr:
            log.info(f"[GM] Handling JOIN from {requester[0]}:{requester[1]}")
            self._propose_view_change(adding=requester)
        else:
            self._send(coord, MsgType.JOIN_REQUEST, requester=list(requester))

    def _on_leave(self, leaver: Member):
        """
        Determine the coordinator of the proposed view (without the leaver).
        If that is me, initiate the view change.
        """
        with self._lock:
            if self._view is None or leaver not in self._view:
                return
            proposed = self._view.without(leaver)
            if not proposed.members:
                return
            new_coord = proposed.coordinator()

        # Only the future coordinator drives the change — avoids duplicate proposals
        if new_coord == self.addr:
            log.info(f"[GM] Handling LEAVE from {leaver[0]}:{leaver[1]}")
            self._propose_view_change(without=leaver)

    def _on_suspect(self, member: Member):
        """
        Called by the failure detector. Same logic as _on_leave: only the
        future coordinator of the new view initiates the change.
        """
        with self._lock:
            if self._view is None or member not in self._view:
                return
            proposed = self._view.without(member)
            if not proposed.members:
                return
            new_coord = proposed.coordinator()

        if new_coord == self.addr:
            log.info(f"[GM] Removing suspected member {member[0]}:{member[1]}")
            self._propose_view_change(without=member)

    def _propose_view_change(self, *, adding: Member = None, without: Member = None):
        """
        Coordinator builds and broadcasts a VIEW_PROPOSAL.
        Waits for ACKs from all new-view members, then broadcasts VIEW_INSTALL.
        """
        with self._lock:
            if self._view is None:
                return
            # Ignore if a view change is already in progress
            if self._pending is not None:
                log.debug("[GM] View change in progress — ignoring concurrent request")
                return

            if adding:
                if adding in self._view:
                    return
                proposed = self._view.with_member(adding)
            else:
                if without not in self._view:
                    return
                proposed = self._view.without(without)

            if not proposed.members:
                return

            self._pending     = proposed
            self._acks        = {self.addr}   # coordinator counts its own ACK
            self._acks_needed = len(proposed.members)

        log.info(f"[GM] Proposing {proposed}")

        if adding:
            self._fd.init_member(adding)

        for member in proposed.members:
            if member != self.addr:
                self._send(
                    member,
                    MsgType.VIEW_PROPOSAL,
                    view=proposed.to_dict(),
                    coordinator=list(self.addr),
                )

        # If we are now the only member, install immediately (no ACKs needed)
        if len(proposed.members) == 1:
            self._install_view(proposed)

    def _on_view_proposal(self, proposed: View, coordinator: Member):
        """Non-coordinator accepts a VIEW_PROPOSAL and sends ACK."""
        log.info(f"[GM] Accepted proposal {proposed} — sending ACK")
        self._send(
            coordinator,
            MsgType.VIEW_ACK,
            acker=list(self.addr),
            view_id=proposed.view_id,
        )

    def _on_view_ack(self, acker: Member, view_id: int):
        """Coordinator collects ACKs; broadcasts VIEW_INSTALL once all replied."""
        with self._lock:
            if self._pending is None or self._pending.view_id != view_id:
                return
            self._acks.add(acker)
            all_acked = len(self._acks) >= self._acks_needed
            pending   = self._pending

        if all_acked:
            log.info(f"[GM] All ACKs received — installing {pending}")
            for member in pending.members:
                if member != self.addr:
                    self._send(member, MsgType.VIEW_INSTALL, view=pending.to_dict())
            self._install_view(pending)

    def _install_view(self, view: View):
        """Install a new view and notify the application layer via callback."""
        with self._lock:
            self._view    = view
            self._pending = None

        # Start the failure detector the first time a view is installed
        if not self._fd_started:
            self._fd_started = True
            self._fd.start()

        # Seed FD timestamps so existing members are not immediately suspected
        for member in view.members:
            if member != self.addr:
                self._fd.init_member(member)

        log.info(f"[GM] *** Installed {view} ***")
        self._joined_event.set()

        if self.on_view_change:
            # Run callback in a separate thread to avoid blocking the protocol
            threading.Thread(
                target=self.on_view_change, args=(view,), daemon=True
            ).start()

    # ── Internal: networking helpers ──────────────────────────────────

    def _send(self, dest: Member, msg_type: str, **payload):
        """
        Open a short-lived TCP connection (Berkeley Sockets), send one JSON
        message, and close. This makes the socket usage explicit and stateless.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect(dest)
                s.sendall(encode(msg_type, **payload))
        except (ConnectionRefusedError, OSError, TimeoutError) as e:
            log.debug(f"[GM] Could not send {msg_type} to {dest}: {e}")

    def _send_heartbeat(self, dest: Member):
        self._send(dest, MsgType.HEARTBEAT, sender=list(self.addr))

    def _get_members(self) -> List[Member]:
        with self._lock:
            return list(self._view.members) if self._view else []

    def _shutdown(self):
        self._running = False
        self._fd.stop()
        try:
            self._server.close()
        except OSError:
            pass
