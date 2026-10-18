"""Session-local BP accounting; no transport or console-balance access.

The runtime adapter must supply delivery and quest-specific application evidence.
An arbitrary peer snapshot is not sufficient evidence. This module deliberately
does not decide how that evidence is obtained from the experimental protocol.
"""
from dataclasses import dataclass


@dataclass
class PendingReward:
    token: str
    reward: int
    delivered: bool = False
    processed: bool = False


class BPGoal:
    """One logical quest in flight, counted once, with bounded target overshoot."""

    def __init__(self, target):
        if type(target) is not int or target <= 0:
            raise ValueError('BP target must be a positive integer')
        self.target = target
        self.earned = 0
        self.completed = 0
        self.pending = None
        self.uncertain = False
        self._committed = set()

    @property
    def reached(self):
        return self.earned >= self.target

    @property
    def can_schedule(self):
        return not self.reached and self.pending is None and not self.uncertain

    def begin(self, token, reward):
        if not isinstance(token, str) or not token:
            raise ValueError('A session-scoped logical completion token is required')
        if type(reward) is not int or reward <= 0:
            raise ValueError('Reward must be a positive integer')
        if token in self._committed:
            raise ValueError('Completion was already accounted for')
        if self.pending is not None and self.pending.token == token:
            if self.pending.reward != reward:
                raise ValueError('Retry changed the reward')
            return False
        if not self.can_schedule:
            raise ValueError('Another completion cannot be scheduled')
        self.pending = PendingReward(token, reward)
        return True

    def record_evidence(self, token, *, delivered=False, processed=False):
        """Commit only after both kinds of evidence refer to this logical quest.

        `delivered` means every required frame (including both red messages) was
        acknowledged. `processed` is supplied only after the adapter correlates
        a game-level response with this quest. Neither flag measures console BP.
        Late, duplicate and unrelated receipts cannot add rewards.
        """
        if self.uncertain or self.pending is None or self.pending.token != token:
            return False
        if type(delivered) is not bool or type(processed) is not bool:
            raise ValueError('Evidence flags must be booleans')
        item = self.pending
        item.delivered |= delivered
        item.processed |= processed
        if not (item.delivered and item.processed):
            return False
        self.earned += item.reward
        self.completed += 1
        self._committed.add(item.token)
        self.pending = None
        return True

    def interrupt(self):
        """An in-flight result is unknown after a timeout or disconnection.

        Keep it visible, prohibit new sends and do not guess whether it paid out.
        A reconnect requires a new run, rather than automatic replay.
        """
        if self.pending is not None:
            self.uncertain = True
