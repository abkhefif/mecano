# SPRINT 2 : SECURITE & OBSERVABILITE

**Date :** 2026-02-19
**Tests :** 457 passed, 3 skipped, 0 failed
**Couverture :** 85.23% (seuil 85% atteint)
**Migrations :** 029_add_audit_log_table.py

---

## CORRECTIONS APPLIQUEES

### FIX 1 : verify_email decode token 2x (SEC-R01)
**Statut :** APPLIQUE
**Fichiers :** `app/services/email_service.py`, `app/auth/routes.py`

- Ajout de `decode_email_verification_token_full()` qui retourne le payload complet (incluant `jti`)
- `verify_email` utilise maintenant un seul decode au lieu de deux
- L'ancien `decode_email_verification_token()` delegue a la nouvelle fonction (retro-compatible)

**Avant :**
```python
email = decode_email_verification_token(body.token)  # decode #1
token_payload = jwt.decode(body.token, ...)           # decode #2 (redondant)
verify_jti = token_payload.get("jti")
```

**Apres :**
```python
token_payload = decode_email_verification_token_full(body.token)  # un seul decode
email = token_payload["sub"]
verify_jti = token_payload.get("jti")
```

---

### FIX 2 : StripeServiceError custom exception (PAY-R01)
**Statut :** APPLIQUE
**Fichiers :** `app/services/stripe_service.py`, `app/bookings/routes.py`, `app/payments/routes.py`, `tests/test_stripe_coverage.py`

- Ajout de `StripeServiceError(Exception)` dans stripe_service.py
- `cancel_payment_intent` et `capture_payment_intent` levent `StripeServiceError` au lieu de `HTTPException`
- Les routes HTTP catchent `StripeServiceError` et le convertissent en `HTTPException(500)`
- Le scheduler (contexte non-HTTP) recoit une exception propre sans semantique HTTP
- 3 tests mis a jour pour attendre `StripeServiceError`

**Callers impactes :**
| Fichier | Appel | Traitement |
|---------|-------|------------|
| bookings/routes.py (refuse) | cancel_payment_intent | try/except -> HTTPException |
| bookings/routes.py (cancel) | cancel/refund | try/except -> HTTPException |
| payments/routes.py (dispute) | cancel/capture | try/except -> HTTPException |
| scheduler.py | cancel/capture | Deja dans try/except Exception |
| auth/routes.py (delete) | cancel_payment_intent | Deja dans try/except Exception |

---

### FIX 3 : DisputeCase webhook charge.dispute.created (PAY-R03)
**Statut :** APPLIQUE
**Fichier :** `app/payments/routes.py`

Le webhook `charge.dispute.created` cree maintenant un `DisputeCase` automatiquement :
- Recherche le booking via `payment_intent` du dispute Stripe
- Verifie qu'aucun DisputeCase n'existe deja pour ce booking (idempotence)
- Mappe les raisons Stripe vers notre enum : `product_not_received` -> `NO_SHOW`, `product_unacceptable` -> `WRONG_INFO`, autres -> `OTHER`
- Le DisputeCase est auto-ouvert avec description contenant l'ID dispute Stripe

---

### FIX 4 : Cache blacklist Redis (SEC-R03)
**Statut :** REPORTE (LOW, MVP acceptable)

Le TODO F-018 dans dependencies.py est deja documente. Les access tokens ont une expiration de 15 min et la table blacklist reste petite. Implementation reportee a un sprint ulterieur.

---

### FIX 5 : Fermer compte Stripe Connect GDPR (GDPR-R01)
**Statut :** APPLIQUE
**Fichier :** `app/auth/routes.py`

Lors de la suppression de compte mecanicien (`DELETE /auth/me`) :
- Appel `stripe.Account.delete()` via `asyncio.to_thread` (best-effort)
- Le `stripe_account_id` est efface du profil apres fermeture
- Les comptes mock (`acct_mock_*`) sont ignores
- En cas d'erreur, la suppression continue (best-effort, log d'erreur)

---

### FIX 6 : detect_orphaned_files asyncio.to_thread (SCHED-03)
**Statut :** APPLIQUE
**Fichier :** `app/services/scheduler.py`

- `_list_r2_keys_sync()` : nouvelle fonction synchrone extraite
- `_list_r2_keys()` : wrapper async via `asyncio.to_thread()`
- `head_object()` et `delete_object()` dans `detect_orphaned_files` : wrapes via `asyncio.to_thread()`
- L'event loop asyncio n'est plus bloque par les appels boto3 synchrones

---

### FIX 7 : Table audit_log admin (ADMIN-R01)
**Statut :** APPLIQUE
**Fichiers :** `app/models/audit_log.py` (nouveau), `app/models/__init__.py`, `app/admin/routes.py`, `app/payments/routes.py`, `alembic/versions/029_add_audit_log_table.py`

**Schema audit_logs :**
| Colonne | Type | Description |
|---------|------|-------------|
| id | UUID PK | Identifiant unique |
| action | String(50) | verify_mechanic, reject_mechanic, suspend_user, unsuspend_user, resolve_dispute_buyer, resolve_dispute_mechanic |
| admin_user_id | UUID FK | Admin ayant effectue l'action |
| target_user_id | UUID FK (nullable) | Utilisateur cible |
| detail | Text | Description/raison |
| metadata_json | JSON | Donnees supplementaires |
| created_at | DateTime(tz) | Horodatage |

**Actions tracees :**
- `verify_mechanic` / `reject_mechanic` (admin/routes.py)
- `suspend_user` / `unsuspend_user` (admin/routes.py)
- `resolve_dispute_buyer` / `resolve_dispute_mechanic` (payments/routes.py)

---

### FIX 8 : Request duration middleware (OBS-04)
**Statut :** APPLIQUE
**Fichier :** `app/main.py`

- Ajout de mesure de duree dans le middleware `request_id_middleware`
- Header `X-Process-Time` ajoute a chaque reponse
- Requetes lentes (>1s) loggees en WARNING avec methode, path, duree, status_code
- Utilise `time.monotonic()` pour precision

---

### FIX 9 : verify_webhook_signature typage (TYPE-01)
**Statut :** APPLIQUE
**Fichier :** `app/services/stripe_service.py`

```python
# Avant
def verify_webhook_signature(payload: bytes, sig_header: str) -> dict:
# Apres
def verify_webhook_signature(payload: bytes, sig_header: str) -> stripe.Event:
```

---

### FIX 10-11 : Split auth/routes.py et bookings/routes.py
**Statut :** REPORTE

Refactoring de structure de fichiers necessitant une reorganisation des imports et tests. Reporte a un sprint dedie refactoring.

---

### FIX 12 : CI cache pip
**Statut :** DEJA PRESENT

`.github/workflows/ci.yml` utilise deja `cache: pip` dans `actions/setup-python@v5`.

---

### FIX 13 : Scheduler resilience
**Statut :** APPLIQUE
**Fichier :** `app/services/scheduler.py`

- Ajout d'un listener `EVENT_JOB_ERROR` sur le scheduler APScheduler
- Les erreurs de jobs sont loggees avec `job_id` et message d'erreur
- Le scheduler continue de fonctionner meme si un job individuel echoue

---

## RESUME

| FIX | Description | Statut |
|-----|-------------|--------|
| 1 | verify_email single decode | APPLIQUE |
| 2 | StripeServiceError exception | APPLIQUE |
| 3 | DisputeCase webhook auto-create | APPLIQUE |
| 4 | Cache blacklist Redis | REPORTE (LOW) |
| 5 | Stripe Connect close GDPR | APPLIQUE |
| 6 | boto3 asyncio.to_thread | APPLIQUE |
| 7 | Table audit_log admin | APPLIQUE |
| 8 | Request duration middleware | APPLIQUE |
| 9 | Webhook return type | APPLIQUE |
| 10-11 | Split routes files | REPORTE |
| 12 | CI cache pip | DEJA PRESENT |
| 13 | Scheduler error listener | APPLIQUE |

**9 fixes appliques, 1 deja present, 3 reportes.**

---

## IMPACT

**Securite :**
- GDPR Stripe Connect : compte ferme a la suppression
- StripeServiceError : exceptions propres hors contexte HTTP
- Single token decode : surface d'attaque reduite

**Observabilite :**
- Request duration : `X-Process-Time` header + slow request warnings
- Audit log admin : tracabilite complete des actions sensibles
- Scheduler error listener : erreurs de jobs loggees

**Fiabilite :**
- DisputeCase auto-cree depuis webhooks Stripe
- boto3 async : event loop libere pour les appels R2
- Scheduler resilient : continue malgre les erreurs individuelles

---

## VERIFICATION

```bash
# Depuis backend/
pytest --cov=app --cov-report=term-missing --tb=short -q
# TOTAL 4149 613 85%
# Required test coverage of 85.0% reached. Total coverage: 85.23%
# 457 passed, 3 skipped
```

---

## FICHIERS MODIFIES

### Source (10 fichiers)
- `app/auth/routes.py` - FIX 1 (single decode), FIX 5 (Stripe Connect close)
- `app/services/stripe_service.py` - FIX 2 (StripeServiceError), FIX 9 (type hint)
- `app/services/email_service.py` - FIX 1 (decode_email_verification_token_full)
- `app/payments/routes.py` - FIX 2 (catch StripeServiceError), FIX 3 (webhook dispute), FIX 7 (audit)
- `app/bookings/routes.py` - FIX 2 (catch StripeServiceError)
- `app/services/scheduler.py` - FIX 6 (asyncio.to_thread), FIX 13 (error listener)
- `app/admin/routes.py` - FIX 7 (audit log)
- `app/main.py` - FIX 8 (request duration)
- `app/models/__init__.py` - FIX 7 (AuditLog import)

### Nouveaux fichiers (2)
- `app/models/audit_log.py` - FIX 7
- `alembic/versions/029_add_audit_log_table.py` - FIX 7

### Tests (1 modifie)
- `tests/test_stripe_coverage.py` - FIX 2 (StripeServiceError expectations)
