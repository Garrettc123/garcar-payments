"""Verified one-time Checkout -> durable work order + mapped HubSpot update."""
import os
import time
import httpx
import stripe
import psycopg
from psycopg.rows import dict_row


def connect():
    return psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row)


def valid_payment(session, order, live):
    return (session.get('id') == order['session_id']
            and session.get('mode') == 'payment'
            and session.get('livemode') is live
            and session.get('payment_status') == 'paid'
            and session.get('amount_total') == order['amount_cents']
            and session.get('currency') == order['currency']
            and bool(session.get('payment_intent')))


def handle_stripe_webhook(payload: bytes, sig_header: str) -> dict:
    secret = os.environ['STRIPE_WEBHOOK_SECRET']
    key = os.environ['STRIPE_SECRET_KEY']
    mode = os.environ['STRIPE_LIVEMODE']
    if not secret or not key or mode not in ('true', 'false'):
        raise RuntimeError('Stripe configuration missing or invalid')
    stripe.api_key = key
    event = stripe.Webhook.construct_event(payload, sig_header, secret)
    live = mode == 'true'
    if event.get('livemode') is not live:
        raise ValueError('Wrong Stripe mode')
    kind = event['type']
    paid_types = ('checkout.session.completed', 'checkout.session.async_payment_succeeded')
    risk_types = ('charge.refunded', 'charge.dispute.created')
    if kind not in paid_types + risk_types:
        return {'status': 'ignored', 'event': kind}
    obj = event['data']['object']
    session = None
    if kind in paid_types:
        # Stripe API lookup occurs before taking database locks.
        session = stripe.checkout.Session.retrieve(obj['id'])
        if session.get('payment_status') != 'paid':
            return {'status': 'awaiting_payment'}
    with connect() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('garcar_payment_events_v1'))")
        if conn.execute('SELECT 1 FROM payment_bridge_events WHERE id=%s', (event['id'],)).fetchone():
            return {'status': 'duplicate'}
        if kind in risk_types:
            pi = obj.get('payment_intent')
            if not pi:
                raise RuntimeError('Risk event requires payment reconciliation')
            conn.execute('INSERT INTO payment_bridge_holds(payment_intent) VALUES(%s) ON CONFLICT DO NOTHING', (pi,))
            conn.execute('UPDATE payment_bridge_orders SET held=true WHERE payment_intent=%s', (pi,))
            conn.execute('INSERT INTO payment_bridge_reviews(event_id,payment_intent,reason) VALUES(%s,%s,%s)', (event['id'], pi, kind))
        else:
            order = conn.execute('SELECT * FROM payment_bridge_orders WHERE session_id=%s FOR UPDATE', (session['id'],)).fetchone()
            if not order:
                raise RuntimeError('Unmapped session: reconciliation required; no effects performed')
            if not valid_payment(session, order, live):
                raise ValueError('Payment does not match trusted order')
            pi = session['payment_intent']
            held = conn.execute('SELECT 1 FROM payment_bridge_holds WHERE payment_intent=%s', (pi,)).fetchone()
            if held or order['held']:
                raise RuntimeError('Payment on hold; operator review required')
            conn.execute('UPDATE payment_bridge_orders SET paid=true,payment_intent=%s WHERE session_id=%s', (pi,session['id']))
            # A durable service work order is NOT a completed audit/deliverable.
            conn.execute('INSERT INTO payment_bridge_fulfillment(session_id) VALUES(%s) ON CONFLICT DO NOTHING', (session['id'],))
            conn.execute('INSERT INTO payment_bridge_jobs(session_id) VALUES(%s) ON CONFLICT DO NOTHING', (session['id'],))
        conn.execute('INSERT INTO payment_bridge_events(id,event_type) VALUES(%s,%s)', (event['id'],kind))
    return {'status': 'durably_recorded', 'event': kind}


def work_once():
    """One bounded CRM update; retry the same target/property, never create a deal."""
    token = os.environ['HUBSPOT_TOKEN']
    with connect() as conn:
        job = conn.execute("""SELECT j.* FROM payment_bridge_jobs j
            JOIN payment_bridge_orders o USING(session_id)
            WHERE j.state='pending' AND j.next_attempt<=now() AND o.paid AND NOT o.held
            ORDER BY j.id FOR UPDATE OF j SKIP LOCKED LIMIT 1""").fetchone()
        if not job:
            return False
        order = conn.execute('SELECT * FROM payment_bridge_orders WHERE session_id=%s', (job['session_id'],)).fetchone()
        code = None
        try:
            response = httpx.patch(
                'https://api.hubapi.com/crm/v3/objects/deals/' + order['hubspot_deal_id'],
                headers={'Authorization': 'Bearer ' + token},
                json={'properties': {'dealstage': order['paid_stage_id']}}, timeout=20,
                follow_redirects=False)
            code = response.status_code
            response.raise_for_status()
            conn.execute("UPDATE payment_bridge_jobs SET state='done',attempts=attempts+1,last_http_status=%s WHERE id=%s", (code,job['id']))
        except Exception:
            attempt = job['attempts'] + 1
            conn.execute("""UPDATE payment_bridge_jobs SET attempts=%s,state=%s,
                next_attempt=now()+(%s * interval '1 second'),last_http_status=%s WHERE id=%s""",
                (attempt,'review' if attempt>=12 else 'pending',min(3600,2**attempt),code,job['id']))
    return True


if __name__ == '__main__':
    while True:
        try:
            if not work_once():
                time.sleep(2)
        except Exception:
            # No payloads/tokens logged. Supervisor/SQL monitoring must alert on failures.
            import logging
            logging.error('CRM worker unavailable; check database and configuration')
            time.sleep(10)
