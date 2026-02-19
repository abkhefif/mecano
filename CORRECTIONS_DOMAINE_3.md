# CORRECTIONS DOMAINE 3 : Couverture Tests 78% -> 85%

## Objectif
Augmenter la couverture de tests de ~78% a >=85% et activer le seuil `--cov-fail-under=85` dans le CI.

## Resultat Final
- **Tests** : 335 -> 456 (+121 tests)
- **Couverture** : ~78% -> **85.02%**
- **456 passed, 3 skipped, 0 failed**
- **CI** : `--cov` active dans `.github/workflows/ci.yml` (le seuil `fail_under = 85` etait deja dans `pyproject.toml`)

## Fichiers Crees (8 nouveaux fichiers de tests)

### 1. `tests/test_stripe_coverage.py` (19 tests)
Cible : `app/services/stripe_service.py` (2% -> 98%)
- create_payment_intent avec idempotency/connect
- cancel (already_cancelled, succeeded->refund, processing->error, normal, stripe_error)
- refund (not_succeeded->cancel, amount_exceeds, partial, full)
- capture (already_succeeded, unexpected_status, with_idempotency, stripe_error)
- verify_webhook_signature (placeholder_prod, staging, no_secret, valid)

### 2. `tests/test_notifications_coverage.py` (19 tests)
Cible : `app/services/notifications.py` (0% -> 100%)
- _get_push_client (creates, reuses)
- send_email (dev_mode, success, failure, exception)
- send_push (no_token, no_user, success, truncation, booking_data, device_not_registered, ticket_error, receipt_parse_error, without_db, exception)
- create_notification (basic, enum_type, data_with_type)

### 3. `tests/test_email_coverage.py` (13 tests, +3 ajoutes)
Cible : `app/services/email_service.py` (0% -> 100%)
- _get_email_client (creates, recreates_closed)
- decode_email_verification_token (valid, wrong_type, invalid) **[NOUVEAU]**
- send_password_reset_email (no_api_key, success, failure, exception)
- send_verification_email (no_api_key, success, failure, exception)

### 4. `tests/test_display_name_coverage.py` (3 tests)
Cible : `app/utils/display_name.py` (0% -> 100%)
- first_name_only, email_fallback, full_name

### 5. `tests/test_reports_coverage.py` (15 tests)
Cible : `app/reports/routes.py` (0% -> 96%), `app/reports/generator.py` (0% -> 95%)
- download token (create_verify, wrong_booking, invalid, wrong_type)
- _build_receipt_data (basic, obd, cancelled)
- endpoints (get_receipt, not_found, forbidden, download_token, download_valid, download_invalid, download_wrong_user)
- generate_payment_receipt

### 6. `tests/test_notifications_routes_coverage.py` (7 tests)
Cible : `app/notifications/routes.py` (0% -> 100%)
- list_notifications (basic, pagination, empty)
- mark_notification_read (success, not_found, not_owner)
- mark_all_read

### 7. `tests/test_rate_limit_coverage.py` (8 tests, +3 ajoutes)
Cible : `app/utils/rate_limit.py` (0% -> 100%)
- get_real_ip (no_proxy, single_proxy, two_proxies, no_forwarded, single_ip_chain)
- _get_storage_uri (with_redis, localhost_redis, import_error) **[NOUVEAU]**

### 8. `tests/test_storage_coverage.py` (21 tests)
Cible : `app/services/storage.py` (82% -> 100%)
- _validate_magic_bytes (jpeg, png, pdf, mismatch, unknown)
- get_key_from_url (public, mock, empty, unrecognized)
- generate_presigned_url (dev, real)
- get_sensitive_url (none, empty, no_key, converts)
- upload_file_bytes (too_large, dev, real)
- upload_file (invalid_folder, invalid_content_type, too_large)

## Fichiers Modifies

### `tests/test_payments_coverage.py` (+10 tests)
- webhook content-length validation (413, 400)
- account.updated (fully_onboarded, not_verified, partial, no_profile)
- dispute resolution (buyer, mechanic, not_found, already_resolved)

### `tests/test_dependencies.py` (+6 tests)
Cible : `app/dependencies.py` (84% -> 100%)
- refresh token rejected (type != "access")
- no jti rejected
- blacklisted token rejected
- password_changed_at invalidates old tokens
- get_verified_user (unverified_rejected, verified_passes)

### `.github/workflows/ci.yml`
- Ajout de `--cov=app --cov-report=term-missing` a la commande pytest
- Le seuil `fail_under = 85` dans `pyproject.toml` bloquera desormais le CI

## Modules a 100% apres corrections
| Module | Avant | Apres |
|--------|-------|-------|
| services/stripe_service.py | ~50% | 98% |
| services/notifications.py | ~40% | 100% |
| services/email_service.py | ~50% | 100% |
| services/storage.py | 82% | 100% |
| notifications/routes.py | 0% | 100% |
| dependencies.py | 84% | 100% |
| utils/display_name.py | ~30% | 100% |
| utils/rate_limit.py | ~50% | 100% |

## Modules restant sous 85% (non bloquants)
| Module | Cover | Raison |
|--------|-------|--------|
| scheduler.py | 66% | Jobs cron complexes avec Redis/DB reels |
| auth/routes.py | 67% | Routes OAuth/social login non implementees |
| bookings/routes.py | 72% | Workflows multi-etapes complexes |
| mechanics/routes.py | 72% | Endpoints admin/verification |
| config.py | 80% | Validations production-only |
| main.py | 54% | Lifespan/startup/health (necessite Redis reel) |
| database.py | 59% | Production SSL/get_db (SQLite en tests) |

## Verification
```bash
# Depuis backend/
pytest --cov=app --cov-report=term-missing --tb=short
# TOTAL 4079 611 85%
# Required test coverage of 85.0% reached. Total coverage: 85.02%
# 456 passed, 3 skipped
```
