from app.db import FulfillmentJob, IntegrationAction
from app.e2e_worker import _action


def test_action_is_unique_per_job_and_stage(db_session):
    job = FulfillmentJob(stripe_event_id="evt_test", checkout_session_id="cs_test", plan="audit", customer_email="test@example.com")
    db_session.add(job)
    db_session.commit()

    first = _action(db_session, job, "hubspot_match")
    second = _action(db_session, job, "hubspot_match")

    assert first.id == second.id
    assert db_session.query(IntegrationAction).filter_by(job_id=job.id, stage="hubspot_match").count() == 1
