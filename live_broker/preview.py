"""Bind a paper preview to a specific intent, operator, evidence, and expiration."""
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from hmac import compare_digest
import json

from live_broker.contracts import OrderRequest, aware, identifier, integer


@dataclass(frozen=True)
class Preview:
    operator_id: str
    order: OrderRequest
    fee_rial: int
    policy_version: str
    evidence_digest: str
    expires_at: datetime

    def __post_init__(self):
        aware(self.expires_at)
        integer(self.fee_rial)
        for value in (self.operator_id, self.policy_version, self.evidence_digest):
            identifier(value)

    def digest(self) -> str:
        order = self.order
        key = order.client_key
        values = (self.operator_id, key.account.broker_id, key.account.account_id, key.provider_id,
                  order.instrument.key.provider_id, order.side, order.shares, order.limit_rial,
                  self.fee_rial, self.policy_version, self.evidence_digest, self.expires_at.isoformat())
        return sha256(json.dumps(values, separators=(',', ':')).encode()).hexdigest()

    def matches(self, *, operator_id: str, approved_digest: str, now: datetime) -> bool:
        """Verify binding only. Authorization and consumption belong in a transaction."""
        aware(now)
        return (self.operator_id == operator_id and now < self.expires_at
                and compare_digest(self.digest(), approved_digest))
