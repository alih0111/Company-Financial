from dataclasses import replace
from datetime import datetime, timedelta, timezone

from live_broker.contracts import AccountKey, Instrument, OrderRequest, ProviderKey, Side
from live_broker.preview import Preview


def test_preview_binds_operator_order_and_evidence_and_expires_at_boundary():
    now = datetime(2026, 11, 13, tzinfo=timezone.utc)
    account = AccountKey('fake', 'demo')
    instrument = Instrument(ProviderKey(account, 'one'), None, 'One')
    order = OrderRequest(ProviderKey(account, 'intent'), instrument, Side.BUY, 2, 100)
    preview = Preview('operator', order, 10, 'paper-v1', 'evidence-v1', now + timedelta(minutes=1))
    approval = dict(operator_id='operator', approved_digest=preview.digest(), now=now)
    assert preview.matches(**approval)
    assert not preview.matches(**(approval | {'operator_id': 'other'}))
    assert not preview.matches(**(approval | {'now': preview.expires_at}))
    assert not replace(preview, evidence_digest='evidence-v2').matches(**approval)
    assert not replace(preview, order=replace(order, shares=3)).matches(**approval)
