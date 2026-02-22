"""FIX-1: Custom Prometheus metrics for eMecano business observability."""

from prometheus_client import Counter, Histogram

# Booking lifecycle counters
BOOKINGS_CREATED = Counter(
    "emecano_bookings_created_total",
    "Total bookings created",
    ["status"],
)
BOOKINGS_CANCELLED = Counter(
    "emecano_bookings_cancelled_total",
    "Total bookings cancelled",
    ["cancelled_by"],
)
BOOKINGS_COMPLETED = Counter(
    "emecano_bookings_completed_total",
    "Total bookings completed",
)

# Payment counters
PAYMENTS_CAPTURED = Counter(
    "emecano_payments_captured_total",
    "Total payments captured",
)
PAYMENTS_REFUNDED = Counter(
    "emecano_payments_refunded_total",
    "Total payments refunded",
)

# Stripe API call duration
STRIPE_CALL_DURATION = Histogram(
    "emecano_stripe_call_duration_seconds",
    "Duration of Stripe API calls",
    ["operation"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 15.0),
)

# Scheduler job counters
SCHEDULER_JOB_RUNS = Counter(
    "emecano_scheduler_job_runs_total",
    "Total scheduler job executions",
    ["job_name", "status"],
)

# Registration counters
USERS_REGISTERED = Counter(
    "emecano_users_registered_total",
    "Total users registered",
    ["role"],
)
