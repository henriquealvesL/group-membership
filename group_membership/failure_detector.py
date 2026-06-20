import threading
import time
import logging

log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 1.0  # seconds between heartbeat probes
SUSPECT_TIMEOUT    = 4.0  # seconds without heartbeat before suspecting a crash


class FailureDetector:
    """
    Heartbeat-based distributed failure detector.

    Each process periodically sends HEARTBEAT to every known group member.
    If no heartbeat arrives from a member within SUSPECT_TIMEOUT seconds,
    that member is suspected of having crashed, and on_suspect_fn is called.

    Properties achieved (Chandra & Toueg, Journal of ACM, 1996):
      - Strong completeness: every crashed process is eventually suspected.
      - Weak accuracy:       correct processes may be transiently suspected
                             (e.g., during network congestion or high load).

    In practice, accuracy can be tuned by adjusting SUSPECT_TIMEOUT: a larger
    timeout reduces false positives at the cost of slower failure detection.
    """

    def __init__(self, self_addr, members_getter, send_fn, on_suspect_fn):
        """
        Args:
            self_addr:       (host, port) of this process — never probed.
            members_getter:  () -> List[Member]  current group members.
            send_fn:         (member) -> None    sends a heartbeat to member.
            on_suspect_fn:   (member) -> None    called when a member is suspected.
        """
        self._self         = self_addr
        self._members      = members_getter
        self._send         = send_fn
        self._on_suspect   = on_suspect_fn

        self._last_seen: dict = {}   # member -> monotonic timestamp
        self._suspected: set  = set()
        self._lock            = threading.Lock()
        self._running         = False

    # ── Public ────────────────────────────────────────────────────────

    def start(self):
        self._running = True
        threading.Thread(target=self._sender_loop,  daemon=True, name="fd-sender").start()
        threading.Thread(target=self._checker_loop, daemon=True, name="fd-checker").start()

    def stop(self):
        self._running = False

    def record(self, member: tuple):
        """Register receipt of a heartbeat from member."""
        with self._lock:
            self._last_seen[member] = time.monotonic()
            if member in self._suspected:
                self._suspected.discard(member)
                log.info(f"[FD] {member[0]}:{member[1]} recovered")

    def init_member(self, member: tuple):
        """Seed the timestamp for a new member so it is not immediately suspected."""
        with self._lock:
            self._last_seen[member] = time.monotonic()

    # ── Internal loops ────────────────────────────────────────────────

    def _sender_loop(self):
        """Periodically send heartbeats to all current group members."""
        while self._running:
            for member in self._members():
                if member != self._self:
                    self._send(member)
            time.sleep(HEARTBEAT_INTERVAL)

    def _checker_loop(self):
        """Check whether any member has exceeded the heartbeat timeout."""
        time.sleep(SUSPECT_TIMEOUT)   # grace period: let first heartbeats arrive
        while self._running:
            now = time.monotonic()
            for member in self._members():
                if member == self._self:
                    continue
                with self._lock:
                    last     = self._last_seen.get(member, 0.0)
                    already  = member in self._suspected
                if not already and now - last > SUSPECT_TIMEOUT:
                    with self._lock:
                        self._suspected.add(member)
                    log.warning(
                        f"[FD] Suspecting {member[0]}:{member[1]}"
                        f" — no heartbeat for >{SUSPECT_TIMEOUT}s"
                    )
                    self._on_suspect(member)
            time.sleep(HEARTBEAT_INTERVAL)
