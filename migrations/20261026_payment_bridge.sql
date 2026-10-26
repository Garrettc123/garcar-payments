-- Additive migration. Run as database owner; never expose these tables to clients.
CREATE TABLE public.payment_bridge_orders (
 session_id text PRIMARY KEY CHECK(session_id ~ '^cs_[A-Za-z0-9_]+$'),
 hubspot_deal_id text NOT NULL UNIQUE CHECK(hubspot_deal_id ~ '^[0-9]+$'),
 paid_stage_id text NOT NULL, sku_id text NOT NULL,
 amount_cents bigint NOT NULL CHECK(amount_cents>0),
 currency text NOT NULL CHECK(currency ~ '^[a-z]{3}$'),
 payment_intent text UNIQUE, paid boolean NOT NULL DEFAULT false,
 held boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.payment_bridge_events (
 id text PRIMARY KEY, event_type text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.payment_bridge_holds (payment_intent text PRIMARY KEY);
CREATE TABLE public.payment_bridge_reviews (
 event_id text PRIMARY KEY, payment_intent text NOT NULL, reason text NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public.payment_bridge_fulfillment (
 session_id text PRIMARY KEY REFERENCES public.payment_bridge_orders(session_id),
 state text NOT NULL DEFAULT 'awaiting_scope' CHECK(state IN ('awaiting_scope','ready','in_progress','delivered','held')),
 assigned_to text, deliverable_reference text,
 created_at timestamptz NOT NULL DEFAULT now(),
 CHECK(state <> 'delivered' OR deliverable_reference IS NOT NULL)
);
CREATE TABLE public.payment_bridge_jobs (
 id bigserial PRIMARY KEY, session_id text NOT NULL UNIQUE REFERENCES public.payment_bridge_orders(session_id),
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','done','review')),
 attempts integer NOT NULL DEFAULT 0, next_attempt timestamptz NOT NULL DEFAULT now(), last_http_status integer
);
CREATE INDEX payment_bridge_pending ON public.payment_bridge_jobs(next_attempt) WHERE state='pending';
ALTER TABLE public.payment_bridge_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payment_bridge_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payment_bridge_holds ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payment_bridge_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payment_bridge_fulfillment ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payment_bridge_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.payment_bridge_orders,public.payment_bridge_events,public.payment_bridge_holds,
 public.payment_bridge_reviews,public.payment_bridge_fulfillment,public.payment_bridge_jobs FROM anon,authenticated;
REVOKE ALL ON SEQUENCE public.payment_bridge_jobs_id_seq FROM anon,authenticated;
