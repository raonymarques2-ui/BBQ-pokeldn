"""Bounded transport-release gate, independent of the game disband message."""


class HostDeparture:
    """Single-client Session 7/8 exchange observed during normal host disband.

    No captured identity bytes are retained. All location IDs come from the
    live session. Physical behavior outside the tested single-client case is
    not established. Transport release must follow this gate, not precede it.
    """
    def __init__(self, host_id, host_var, host_ip, peer_id, peer_var, now):
        from pokeldn.ldn.pia_connect import (
            build_session_migration_v11, build_session_migration_ack_v11)
        self.body = build_session_migration_v11(
            host_id, host_var, host_ip, peer_id, peer_var, tail=1)
        self.expected_ack = build_session_migration_ack_v11(
            peer_id, peer_var, host_id, host_var)
        self.deadline = now + 5.0
        self.next_send = now
        self.ack_at = None
        self.left_at = None
        self.sent = False
        self.phase = 'waiting'

    def observe_departure(self, now):
        # Some clients leave immediately after type 7 without replying type 8.
        # Only a transport LeaveEvent/removal for this peer may call this hook.
        if self.phase == 'waiting' and self.sent and self.left_at is None:
            self.left_at = now

    def acknowledge(self, payload, now):
        if self.phase != 'waiting' or bytes(payload) != self.expected_ack:
            return False
        if self.ack_at is None:
            self.ack_at = now
        return True

    def tick(self, now):
        if self.phase != 'waiting':
            return None
        if self.left_at is not None:
            if now >= self.left_at + .15:
                self.phase = 'client_left'
            return None
        if self.ack_at is not None:
            if now >= self.ack_at + .15:
                self.phase = 'acknowledged'
            return None
        if now >= self.deadline:
            self.phase = 'timeout'
            return None
        if now >= self.next_send:
            self.next_send = now + 1.0
            self.sent = True
            return self.body
        return None


class ShutdownGate:
    def __init__(self,peers,now,timeout=8.0,settle=.3):
        self.peers=frozenset(peers);self.deadline=now+timeout;self.settle=settle
        self.left_at=None;self.phase='waiting' if self.peers else 'done'

    def tick(self,active_peers,now):
        if self.phase in ('done','timeout'):return self.phase
        remaining=self.peers.intersection(active_peers)
        if not remaining:
            if self.left_at is None:self.left_at=now
            if now-self.left_at>=self.settle:self.phase='done'
        elif now>=self.deadline:self.phase='timeout'
        return self.phase
