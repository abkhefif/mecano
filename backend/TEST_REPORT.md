# TEST REPORT -- eMecano Backend Audit

**Agent:** TESTEUR (Tester Agent)
**Date:** 2026-02-10
**Backend:** FastAPI + SQLAlchemy 2.0 + PostgreSQL (SQLite for tests)
**Scope:** Full backend audit -- static analysis, comprehensive testing, bug identification

---

## 1. EXECUTIVE SUMMARY

| Metric | Value |
|--------|-------|
| Total tests | **167 passing** + **3 intentionally failing** (bug-proof tests) |
| Test coverage | **94.33%** (target: 85%) |
| Static analysis (ruff) | **34 findings** (6 auto-fixable, 20 false positives for SQLAlchemy) |
| Static analysis (mypy) | **22 errors** (21 forward-ref false positives, 1 real type error) |
| Bugs identified | **41 total** (5 CRITICAL, 12 HIGH, 14 MEDIUM, 10 LOW) |
| Test files | 12 (10 existing + 1 new audit test file) |

---

## 2. STATIC ANALYSIS RESULTS

### 2.1 Ruff (Linting)

**34 errors found, classified by type:**

| Code | Count | Description | Real Bug? |
|------|-------|-------------|-----------|
| F401 | 6 | Unused imports | YES -- dead code |
| E712 | 8 | `== True` / `== False` comparisons | NO -- required for SQLAlchemy `.where()` clauses |
| F821 | 19 | Undefined names in string annotations | NO -- valid SQLAlchemy forward references |
| F401 | 1 | Unused `String` import in types.py | YES -- dead code |

**Real issues (7):**
- `app/bookings/routes.py:27` -- Unused import `CheckOutRequest` (schema exists but is never used by the endpoint)
- `app/dependencies.py:2` -- Unused import `AsyncGenerator`
- `app/mechanics/routes.py:2` -- Unused imports `datetime`, `timezone`
- `app/models/types.py:5` -- Unused import `String`
- `app/services/scheduler.py:6` -- Unused import `AsyncSession`

### 2.2 Mypy (Type Checking)

**22 errors in 10 files:**

| Category | Count | Real? |
|----------|-------|-------|
| Forward reference `name-defined` errors | 21 | NO -- SQLAlchemy `Mapped["Model"]` pattern |
| `arg-type` error in main.py | 1 | YES -- rate limit handler signature mismatch |

**Real type error:**
- `app/main.py:48` -- `add_exception_handler` receives a handler with `RateLimitExceeded` parameter type, but expects `Exception`. Should use a more specific cast or wrapper.

---

## 3. BUG REPORT

### 3.1 CRITICAL (5 bugs)

---

#### BUG-001: Anyone Can Register as Admin
| Field | Value |
|-------|-------|
| **File** | `app/auth/routes.py:42` + `app/schemas/auth.py:12` |
| **Category** | SECURITY |
| **Test** | `test_audit_bugs.py::test_register_as_admin_should_be_blocked` -- **FAILS (bug confirmed)** |

**Description:** The `RegisterRequest` schema accepts `role: UserRole`, and `UserRole` includes `ADMIN`. No validation prevents admin self-registration. Any anonymous user can POST `{"role": "admin", ...}` to `/auth/register` and get a valid admin JWT.

**Impact:** Complete authentication bypass. Attacker gets admin privileges.

**Fix:** Restrict `role` in `RegisterRequest` to `Literal["buyer", "mechanic"]` or add a validator.

---

#### BUG-002: Race Condition -- Double-Booking of Availability Slot
| Field | Value |
|-------|-------|
| **File** | `app/bookings/routes.py:52-60` |
| **Category** | BUG / CONCURRENCY |

**Description:** The `create_booking` endpoint checks `availability.is_booked` (line 59), but between the check and the write (line 134), no database lock is held. Two concurrent requests can both pass the check and book the same slot.

**Impact:** Double charges via Stripe, two conflicting bookings for one slot.

**Fix:** Use `select(...).with_for_update()` for row-level locking, or add a DB UNIQUE constraint on `bookings.availability_id`.

---

#### BUG-003: Orphaned Stripe PaymentIntent on DB Failure
| Field | Value |
|-------|-------|
| **File** | `app/bookings/routes.py:107-135` |
| **Category** | BUG / PAYMENT |
| **Test** | `test_audit_bugs.py::test_booking_creation_stripe_intent_not_cancelled_on_db_error` -- PASSES (documents bug) |

**Description:** The Stripe PaymentIntent is created (line 107) before the booking is persisted (line 135). If `db.flush()` raises, the intent remains active -- funds are held on the buyer's card with no booking record. No compensating `cancel_payment_intent` exists.

**Impact:** Buyer's card charged/held with no service delivered and no way to automatically refund.

**Fix:** Wrap the DB operations in try/except; call `cancel_payment_intent` on failure.

---

#### BUG-004: Check-In Code Brute-Force (No Rate Limiting)
| Field | Value |
|-------|-------|
| **File** | `app/bookings/routes.py:257-282` |
| **Category** | SECURITY |

**Description:** The 4-digit code has only 10,000 possible values. The `enter-code` endpoint has no per-booking rate limiting and no failed-attempt counter. With the global rate limit of 20/second, all 10,000 codes can be tried in ~8 minutes.

**Impact:** Mechanic (or attacker with mechanic account) can bypass the anti-fraud code system.

**Fix:** Add a `check_in_code_attempts` counter; invalidate after 5 failed attempts.

---

#### BUG-005: Hardcoded JWT Secret Default
| Field | Value |
|-------|-------|
| **File** | `app/config.py:14` |
| **Category** | SECURITY |
| **Test** | `test_audit_bugs.py::test_default_jwt_secret_is_insecure` -- PASSES (documents bug) |

**Description:** `JWT_SECRET` defaults to `"change-this-in-production"`. If `.env` is missing/incomplete, the app runs with a known secret, allowing anyone to forge JWT tokens.

**Impact:** Full authentication bypass in production if secret isn't changed.

**Fix:** Remove the default value; require explicit configuration. Add startup validation.

---

### 3.2 HIGH (12 bugs)

---

#### BUG-006: Non-Acceptance Treated as No-Show in Penalty System
| Field | Value |
|-------|-------|
| **File** | `app/services/scheduler.py:73` |
| **Category** | LOGIC |
| **Test** | `test_audit_bugs.py::test_scheduler_penalty_logic` -- PASSES (documents bug) |

**Description:** `check_pending_acceptances()` calls `apply_no_show_penalty()` when a booking times out because the mechanic didn't respond. Non-acceptance and no-show are different -- a mechanic who misses a notification shouldn't get the same progressive ban as one who confirmed and didn't show up.

---

#### BUG-007: Lazy-Load Relationship in Async Scheduler Context
| Field | Value |
|-------|-------|
| **File** | `app/services/scheduler.py:70-73, 111-112` |
| **Category** | BUG / RUNTIME |

**Description:** The scheduler accesses `booking.mechanic` (line 73), `booking.availability` (line 70), `booking.buyer.phone` (line 111), and `booking.mechanic.user.phone` (line 112) within its own async session. These relationships may trigger lazy loads outside the original query context, causing `MissingGreenlet` / `DetachedInstanceError` in async SQLAlchemy.

**Fix:** Add `.options(selectinload(...))` to the scheduler queries.

---

#### BUG-008: Scheduler Loads Entire Confirmed Bookings Table
| Field | Value |
|-------|-------|
| **File** | `app/services/scheduler.py:91-96` |
| **Category** | PERFORMANCE |

**Description:** `send_reminders()` loads ALL confirmed bookings, then filters by time window in Python. Unbounded memory as the system scales.

---

#### BUG-009: No Buyer Cancellation Path After Confirmation
| Field | Value |
|-------|-------|
| **File** | `app/bookings/routes.py` (missing endpoint) |
| **Category** | LOGIC |

**Description:** Once a booking is `CONFIRMED`, the buyer has no endpoint to cancel. Funds remain held indefinitely if neither check-in nor dispute happens.

---

#### BUG-010: Stripe Webhook Does Nothing
| Field | Value |
|-------|-------|
| **File** | `app/payments/routes.py:61-86` |
| **Category** | BUG / PAYMENT |

**Description:** The webhook handler acknowledges all events but only logs `payment_intent.succeeded`. Payment failures, disputes, and other critical events are silently ignored.

---

#### BUG-011: Content-Type Spoofing on File Upload
| Field | Value |
|-------|-------|
| **File** | `app/services/storage.py:41-42` |
| **Category** | SECURITY |

**Description:** File upload validates only the client-supplied `content_type` header. No magic-byte checking. Malicious files can be uploaded with any content.

---

#### BUG-012: CheckOutRequest Schema Never Used -- No Validation
| Field | Value |
|-------|-------|
| **File** | `app/bookings/routes.py:285-297` |
| **Category** | BUG |
| **Test** | `test_audit_bugs.py::test_check_out_no_plate_validation` -- **FAILS (bug confirmed)** |

**Description:** The `CheckOutRequest` schema (with `Field(max_length=20)` for plate, `Field(ge=0)` for odometer) exists but is unused. The endpoint accepts raw form params with no validation. A 500-char plate and negative odometer are accepted.

---

#### BUG-013: Review Model Prevents Both Parties from Reviewing
| Field | Value |
|-------|-------|
| **File** | `app/models/review.py:16` |
| **Category** | BUG / DATA MODEL |
| **Test** | `test_audit_bugs.py::test_both_buyer_and_mechanic_can_review_same_booking` -- **FAILS (bug confirmed)** |

**Description:** `booking_id` has `unique=True`, allowing only ONE review per booking. Both buyer and mechanic should be able to review. The second review triggers an `IntegrityError` (500).

**Fix:** Remove `unique=True`, add composite unique on `(booking_id, reviewer_id)`.

---

#### BUG-014: S3 Upload Blocks the Event Loop
| Field | Value |
|-------|-------|
| **File** | `app/services/storage.py:60-65` |
| **Category** | PERFORMANCE |

**Description:** `boto3.client.put_object()` is synchronous but called in an `async` function. Blocks the entire FastAPI event loop during uploads.

**Fix:** Use `await asyncio.to_thread(client.put_object, ...)` or switch to `aioboto3`.

---

#### BUG-015: All Stripe API Calls Block the Event Loop
| Field | Value |
|-------|-------|
| **File** | `app/services/stripe_service.py:40-86` |
| **Category** | PERFORMANCE |

**Description:** All `stripe.PaymentIntent.*` and `stripe.Account.*` calls are synchronous HTTP calls wrapped in `async` functions. Each call blocks 500ms-2s.

---

#### BUG-016: `cancel_payment_intent` Can't Refund Captured Payments
| Field | Value |
|-------|-------|
| **File** | `app/services/stripe_service.py:45-52` |
| **Category** | BUG / PAYMENT |

**Description:** The docstring claims "full refund if already captured" but `stripe.PaymentIntent.cancel()` only works on uncaptured intents. For captured intents, `stripe.Refund.create()` is needed.

---

#### BUG-017: `is_verified` Field Never Enforced
| Field | Value |
|-------|-------|
| **File** | `app/dependencies.py` + `app/models/user.py:20` |
| **Category** | SECURITY |
| **Test** | `test_audit_bugs.py::test_unverified_user_can_create_booking` -- PASSES (documents bug) |

**Description:** Users get full access immediately after registration. The `is_verified` field exists but is never checked in any auth dependency or endpoint guard.

---

### 3.3 MEDIUM (14 bugs)

| ID | File | Description |
|----|------|-------------|
| BUG-018 | `bookings/routes.py:63` | Timezone assumption -- slots assume UTC but users enter local French time |
| BUG-019 | `schemas/booking.py:30` | `vehicle_year` hardcoded max 2030, will break in 2031 |
| BUG-020 | `bookings/routes.py:107-134` | Availability locked before payment confirmation; no timeout to release |
| BUG-021 | `bookings/routes.py:315` | `except (JSONDecodeError, Exception)` catches ALL exceptions |
| BUG-022 | `tests/conftest.py:22` | SQLite vs PostgreSQL -- different behavior for UUID, JSON, NUMERIC, concurrency |
| BUG-023 | `utils/rate_limit.py:4` | 20/second global limit too permissive for sensitive endpoints |
| BUG-024 | `auth/routes.py:43-51` | Mechanic profile at (0, 0) after registration |
| BUG-025 | `reports/generator.py:95` | Jinja2 without `autoescape=True` |
| BUG-026 | `bookings/routes.py:347` | Mechanic name from email prefix on legal PDF |
| BUG-027 | `bookings/routes.py:386-388` | Dispute without reason/description allowed |
| BUG-028 | `bookings/routes.py:406-434` | Admin gets empty booking list (wrong branch) |
| BUG-029 | `bookings/routes.py` | No dispute resolution workflow; disputed payments stuck forever |
| BUG-030 | `bookings/routes.py:221` | Missing availability silently skips time-window check |
| BUG-031 | `mechanics/routes.py:34-75` | Mechanic coordinates and pricing publicly accessible |

### 3.4 LOW (10 bugs)

| ID | File | Description |
|----|------|-------------|
| BUG-032 | `database.py:21-28` | Auto-commit pattern is fragile with HTTPExceptions |
| BUG-033 | `dependencies.py:2` | Unused `AsyncGenerator` import |
| BUG-034 | `bookings/routes.py:285-297` | 9 form parameters -- code smell |
| BUG-035 | `config.py:31` | `APP_DEBUG=True` by default, logs SQL queries |
| BUG-036 | `bookings/routes.py:406` | No pagination on `list_my_bookings` |
| BUG-037 | `mechanics/routes.py:43-75` | Distance filtering done in Python not SQL |
| BUG-038 | `schemas/auth.py:23` | `token_type` field not actionable (cosmetic) |
| BUG-039 | `tests/conftest.py:124-129` | `buyer_token`/`mechanic_token` are functions, not fixtures |
| BUG-040 | `config.py:32` | CORS defaults include localhost |
| BUG-041 | `models/booking.py` | No index on `status` column (scheduler full table scans) |

---

## 4. COVERAGE REPORT

### 4.1 Overall Coverage: 94.33%

### 4.2 Per-Module Coverage

| Module | Stmts | Miss | Cover | Notes |
|--------|-------|------|-------|-------|
| `app/auth/routes.py` | 40 | 0 | **100%** | |
| `app/auth/service.py` | 13 | 0 | **100%** | |
| `app/bookings/routes.py` | 202 | 0 | **100%** | Most complex module -- fully covered |
| `app/config.py` | 29 | 0 | **100%** | |
| `app/database.py` | 16 | 7 | **56%** | `get_db` not covered (overridden in tests) |
| `app/dependencies.py` | 50 | 0 | **100%** | |
| `app/main.py` | 34 | 6 | **82%** | Lifespan scheduler start + error handler |
| `app/mechanics/routes.py` | 106 | 0 | **100%** | |
| `app/models/*` | 319 | 0 | **100%** | All models fully covered |
| `app/payments/routes.py` | 48 | 10 | **79%** | Webhook handler not fully tested |
| `app/reports/generator.py` | 34 | 0 | **100%** | |
| `app/reviews/routes.py` | 60 | 0 | **100%** | |
| `app/schemas/*` | 190 | 0 | **100%** | |
| `app/services/penalties.py` | 25 | 1 | **96%** | Edge case in reset function |
| `app/services/pricing.py` | 13 | 0 | **100%** | |
| `app/services/scheduler.py` | 66 | 48 | **27%** | Scheduler jobs require full async session |
| `app/services/storage.py` | 40 | 0 | **100%** | |
| `app/services/stripe_service.py` | 43 | 0 | **100%** | |
| `app/utils/*` | 12 | 0 | **100%** | |
| `app/models/types.py` | 25 | 4 | **84%** | PostgreSQL dialect branch not tested |

### 4.3 Critical Business Logic Coverage

| Component | Coverage | Status |
|-----------|----------|--------|
| Booking creation flow | 100% | OK |
| Booking state machine (accept/refuse/check-in/enter-code/check-out/validate) | 100% | OK |
| Pricing calculations | 100% | OK |
| Penalty system | 96% | OK |
| Review system | 100% | OK |
| Authentication (register/login/me) | 100% | OK |
| Mechanic management | 100% | OK |
| File upload | 100% | OK |
| Stripe mock service | 100% | OK |
| PDF generation | 100% | OK |
| Scheduler | **27%** | LOW -- needs integration tests |

---

## 5. TEST INVENTORY

### 5.1 Existing Tests (155 tests)

| File | Tests | Coverage Focus |
|------|-------|----------------|
| `test_auth.py` | 17 | Registration, login, /me endpoint, edge cases |
| `test_bookings.py` | 38 | Full booking lifecycle, authorization, state transitions |
| `test_dependencies.py` | 12 | Auth guards, role checks, suspension |
| `test_mechanics.py` | 25 | Mechanic search, profile update, availability CRUD |
| `test_payments.py` | 9 | Stripe mocks, onboarding, webhooks |
| `test_penalties.py` | 5 | Progressive penalty system |
| `test_reports.py` | 2 | PDF generation |
| `test_reviews.py` | 11 | Review CRUD, rating updates, pagination |
| `test_services.py` | 21 | Storage, Stripe service unit tests |
| `test_validation.py` | 15 | Geo calculations, pricing, code generator |

### 5.2 New Audit Tests (15 tests)

| Test Name | Finding | Result |
|-----------|---------|--------|
| `test_register_as_admin_should_be_blocked` | BUG-001 | **FAIL** (bug confirmed) |
| `test_both_buyer_and_mechanic_can_review_same_booking` | BUG-013 | **FAIL** (bug confirmed) |
| `test_check_out_no_plate_validation` | BUG-012 | **FAIL** (bug confirmed) |
| `test_validate_dispute_without_details` | BUG-027 | PASS (documents bug) |
| `test_list_bookings_as_admin_returns_empty` | BUG-028 | PASS (documents bug) |
| `test_check_out_broad_exception_masks_errors` | BUG-021 | PASS (documents bug) |
| `test_check_in_without_availability_skips_time_window` | BUG-030 | PASS (documents bug) |
| `test_default_jwt_secret_is_insecure` | BUG-005 | PASS (documents bug) |
| `test_scheduler_penalty_logic` | BUG-006 | PASS (documents bug) |
| `test_unverified_user_can_create_booking` | BUG-017 | PASS (documents bug) |
| `test_mechanic_registration_creates_profile_at_null_island` | BUG-024 | PASS (documents bug) |
| `test_booking_creation_stripe_intent_not_cancelled` | BUG-003 | PASS (documents bug) |
| `test_refuse_booking_releases_availability` | -- | PASS (regression test) |
| `test_check_in_generates_valid_4_digit_code` | -- | PASS (verification) |
| `test_full_booking_lifecycle` | -- | PASS (E2E happy path) |

---

## 6. SECURITY CHECKLIST

| Check | Status | Details |
|-------|--------|---------|
| Admin registration blocked | FAIL | BUG-001: Anyone can register as admin |
| JWT secret enforced | FAIL | BUG-005: Default "change-this-in-production" |
| Email verification | FAIL | BUG-017: `is_verified` never checked |
| Rate limiting on auth | WARN | BUG-023: 20/sec too permissive |
| Brute-force protection on code entry | FAIL | BUG-004: No attempt counter |
| File upload validation | FAIL | BUG-011: Content-type only, no magic bytes |
| SQL injection | PASS | SQLAlchemy ORM used correctly |
| XSS in templates | WARN | BUG-025: No Jinja2 autoescape |
| CORS configuration | WARN | BUG-040: Localhost defaults |
| Password hashing | PASS | bcrypt via passlib |
| JWT expiration | PASS | 24h expiration configured |
| Authorization on all endpoints | PASS | Role-based guards present |
| Debug mode defaults | WARN | BUG-035: APP_DEBUG=True by default |

---

## 7. CODE QUALITY CHECKLIST

| Check | Status | Details |
|-------|--------|---------|
| No unused imports | FAIL | 7 unused imports (F401) |
| Type annotations | WARN | Mostly typed, mypy has 1 real error |
| Error handling | FAIL | BUG-021: Broad except in check-out |
| Async correctness | FAIL | BUG-014/015: Blocking I/O in async |
| Database indexes | WARN | BUG-041: Missing index on booking.status |
| Pagination | WARN | BUG-036: list_my_bookings unpaginated |
| Dead code | WARN | CheckOutRequest schema defined but unused |
| Test/prod parity | WARN | BUG-022: SQLite tests vs PostgreSQL prod |

---

## 8. PRIORITIZED FIX LIST FOR BUILDER

### Immediate (Pre-Launch)

1. **BUG-001** -- Block admin self-registration (5 min fix)
2. **BUG-005** -- Remove default JWT secret, add startup validation (10 min)
3. **BUG-013** -- Fix Review unique constraint to composite key (5 min + migration)
4. **BUG-002** -- Add SELECT FOR UPDATE or DB constraint for slot booking (15 min)
5. **BUG-003** -- Add try/except with Stripe cancellation on DB failure (10 min)

### Before Public Launch

6. **BUG-004** -- Add brute-force protection on enter-code endpoint
7. **BUG-012** -- Apply CheckOutRequest validation to form params
8. **BUG-017** -- Enforce is_verified in auth dependency
9. **BUG-011** -- Add magic-byte file validation
10. **BUG-016** -- Handle captured PaymentIntents (use Refund API)

### Near-Term

11. **BUG-006** -- Separate non-acceptance from no-show penalties
12. **BUG-009** -- Add buyer cancellation endpoint
13. **BUG-014/015** -- Fix blocking I/O (asyncio.to_thread or async clients)
14. **BUG-029** -- Implement dispute resolution workflow
15. **BUG-025** -- Enable Jinja2 autoescape

### Maintenance

16. **BUG-007/008** -- Fix scheduler relationship loading and query optimization
17. **BUG-018** -- Implement proper timezone handling (Europe/Paris)
18. **BUG-037** -- Add database-level geo filtering
19. **BUG-041** -- Add index on bookings.status
20. Clean up unused imports (F401 findings)

---

## 9. INFRASTRUCTURE CHECKS

| File | Status | Notes |
|------|--------|-------|
| `docker-compose.yml` | OK | PostgreSQL 16, Redis 7, health checks present |
| `Dockerfile` | OK | Python 3.12-slim, multi-stage not needed for dev |
| `requirements.txt` | OK | All dependencies listed |
| `.env.example` | MISSING | Should be created with all env vars documented |
| `alembic.ini` | OK | Configured correctly |
| `alembic/env.py` | OK | Async migration support |
| `alembic/versions/001_initial.py` | WARN | Uses PostgreSQL-specific types (will need updating after model fixes) |
| `pyproject.toml` | OK | Coverage config correct with greenlet concurrency |

---

*Report generated by Agent Testeur -- 2026-02-10*
