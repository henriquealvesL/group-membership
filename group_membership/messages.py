import json


class MsgType:
    """All message types exchanged between group members."""
    HEARTBEAT     = "HEARTBEAT"      # failure detector probe
    JOIN_REQUEST  = "JOIN_REQUEST"   # new process wants to enter
    LEAVE         = "LEAVE"          # process is departing (graceful or suspected)
    VIEW_PROPOSAL = "VIEW_PROPOSAL"  # coordinator proposes a new view
    VIEW_ACK      = "VIEW_ACK"       # member accepts the proposal
    VIEW_INSTALL  = "VIEW_INSTALL"   # coordinator orders installation
    APP_MESSAGE   = "APP_MESSAGE"    # application-layer message (chat, etc.)


def encode(msg_type: str, **payload) -> bytes:
    """Serialize a message to JSON bytes with a newline delimiter."""
    return (json.dumps({"type": msg_type, **payload}) + "\n").encode()


def decode(data: bytes) -> dict:
    """Deserialize a JSON message from bytes."""
    return json.loads(data.decode().strip())
