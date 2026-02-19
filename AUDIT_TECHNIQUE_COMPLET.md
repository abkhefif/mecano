# AUDIT TECHNIQUE COMPLET - eMecano
## Fresh Start - 19 Fevrier 2026

---

# RESUME EXECUTIF

| Critere | Score |
|---------|-------|
| **Securite** | 8.5 / 10 |
| **Fiabilite financiere** | 8.0 / 10 |
| **Qualite du code** | 8.5 / 10 |
| **Couverture tests** | 85% (456 tests, 3 skipped) |
| **Infrastructure / CI** | 7.5 / 10 |
| **Production readiness** | 7.0 / 10 |
| **Score global** | **8.0 / 10** |

**Verdict** : Le projet est bien structure pour un MVP et a corrige de nombreux problemes identifies lors des audits precedents. Les fondations de securite sont solides (JWT, Stripe, RBAC). Les points restants concernent principalement le durcissement pour la production et l'observabilite.

---

# PHASE 1 : EXPLORATION

## Architecture

```
backend/
  app/
    auth/          # JWT auth, login, register, GDPR
    bookings/      # Core booking workflow (9 endpoints)
    mechanics/     # Profiles, availability, search
    payments/      # Stripe Connect, webhooks, disputes
    admin/         # Dashboard, verification, suspension
    messages/      # Chat with contact masking
    notifications/ # Push + in-app notifications
    referrals/     # Referral codes
    reports/       # PDF receipt generation
    reviews/       # Buyer/mechanic reviews
    services/      # Stripe, email, notifications, scheduler, storage
    models/        # SQLAlchemy models (12 tables)
    schemas/       # Pydantic validation schemas
    utils/         # Rate limit, geo, display name, contact mask
    middleware.py  # Security headers
    config.py      # Pydantic Settings with production validators
    database.py    # AsyncSession + SSL
    dependencies.py # Auth dependencies (JWT, RBAC)
    main.py        # FastAPI app, CORS, Sentry, health check
  tests/           # 456 tests, 85% coverage
  alembic/         # 27 migrations
mobile/            # React Native + Expo (submodule)
```

## Stack technique

| Composant | Technologie | Version |
|-----------|-------------|---------|
| Backend | FastAPI + Uvicorn/Gunicorn | 0.115.6 |
| Base de donnees | PostgreSQL 16 (asyncpg) | via SQLAlchemy 2.0.36 |
| Cache/Locks | Redis 7 (hiredis) | 5.2.1 |
| Auth | PyJWT + bcrypt | >=2.10.1 / 4.2.1 |
| Paiements | Stripe Connect (manual capture) | 11.4.1 |
| Stockage fichiers | Cloudflare R2 (S3-compatible) | boto3 >=1.36 |
| Email | Resend API (httpx) | httpx 0.28.1 |
| Push | Expo Push API | via httpx |
| PDF | WeasyPrint + Jinja2 | >=68.0 |
| Background jobs | APScheduler (AsyncIO) | 3.10.4 |
| Rate limiting | slowapi | 0.1.9 |
| Logging | structlog (JSON prod, console dev) | 24.4.0 |
| Error tracking | Sentry | 2.52.0 |
| Mobile | React Native + Expo SDK | (submodule) |
| CI/CD | GitHub Actions + Render | - |

---

# PHASE 2 : SECURITE CRITIQUE

## 2.1 Auth / JWT

### Correctement implemente

| ID | Element | Status |
|----|---------|--------|
| SEC-001 | JWT HS256 avec secret >= 32 chars, weak secrets rejetes | OK |
| SEC-002 | Refresh token rotation avec blacklist jti (AUD-014) | OK |
| SEC-003 | Access token 15min, refresh 7j | OK |
| SEC-004 | Login lockout 5 tentatives / 15min (Redis + fallback in-memory) | OK |
| SEC-005 | password_changed_at invalide tous les tokens pre-existants | OK |
| SEC-006 | Changement email => re-verification obligatoire | OK |
| SEC-007 | Dummy hash anti timing oracle sur login (H-01) | OK |
| SEC-008 | Email enumeration prevention (register, forgot-password, resend) | OK |
| SEC-009 | Password reset token single-use via jti blacklist + TOCTOU via UNIQUE constraint | OK |
| SEC-010 | Logout blackliste access + refresh token | OK |
| SEC-011 | bcrypt cost factor 12, async via to_thread | OK |
| SEC-012 | Token type check (access vs refresh vs email_verify) | OK |
| SEC-013 | jti obligatoire pour eviter blacklist bypass | OK |

### Problemes residuels

| ID | Severite | Description | Impact |
|----|----------|-------------|--------|
| **SEC-R01** | MEDIUM | `verify_email` decode le token 2 fois (decode_email_verification_token + jwt.decode) | Performance inutile, pas de risque securite |
| **SEC-R02** | LOW | `get_verified_user` est defini mais jamais utilise par aucun routeur | Code mort. `get_verified_buyer` est utilise a la place |
| **SEC-R03** | LOW | Le cache blacklist Redis (TODO F-018) n'est pas implemente - chaque requete authentifiee fait un SELECT sur blacklisted_tokens | Acceptable pour MVP (access tokens 15min), mais sera un bottleneck a l'echelle |
| **SEC-R04** | INFO | `change_password` invalide seulement le token courant en plus de `password_changed_at` | Le commentaire dit "Other active sessions remain valid until natural expiry" mais `password_changed_at` les invalide aussi. Le code est correct, le commentaire est misleading |

## 2.2 Stripe / Paiements

### Correctement implemente

| ID | Element | Status |
|----|---------|--------|
| PAY-001 | Manual capture (hold then capture) pour le modele marketplace | OK |
| PAY-002 | Connect Express avec application_fee_amount pour commission | OK |
| PAY-003 | Idempotency keys sur create/cancel/refund payment intents | OK |
| PAY-004 | Webhook signature verification (stripe.Webhook.construct_event) | OK |
| PAY-005 | Webhook idempotency via ProcessedWebhookEvent table | OK |
| PAY-006 | Webhook payload size limit (64KB Content-Length + body check) | OK |
| PAY-007 | Placeholder webhook secret rejecte en production/staging | OK |
| PAY-008 | Compensating transaction : cancel Stripe PI si DB insert echoue | OK |
| PAY-009 | Payment release 2h apres validation (one-shot + catch-all cron) | OK |
| PAY-010 | Tiered refund policy (100%/>24h, 50%/>12h, 0%/<12h) | OK |
| PAY-011 | FOR UPDATE sur booking pour prevent race condition | OK |
| PAY-012 | skip_locked=True sur webhook PI handler pour prevent race with scheduler | OK |
| PAY-013 | asyncio.wait_for(timeout=15.0) sur tous les appels Stripe | OK |
| PAY-014 | Mock mode complet quand STRIPE_SECRET_KEY est vide | OK |
| PAY-015 | Stripe key prefix validation (sk_live_ en prod, sk_test_ en staging) | OK |
| PAY-016 | Refund amount validation (PAY-19: ne depasse pas le max refundable) | OK |
| PAY-017 | PI status check avant capture (AUD4-002) | OK |

### Problemes residuels

| ID | Severite | Description | Impact |
|----|----------|-------------|--------|
| **PAY-R01** | MEDIUM | `cancel_payment_intent` catch `stripe.StripeError` et raise `HTTPException(500)` mais dans le contexte scheduler (pas HTTP), cela remontera comme une exception non geree | Le scheduler catch toutes les exceptions donc pas de crash, mais le type d'exception est trompeur |
| **PAY-R02** | LOW | `verify_webhook_signature` retourne `dict` au lieu du type `stripe.Event` - perte de typage | Fonctionnel mais moins type-safe |
| **PAY-R03** | LOW | `charge.dispute.created` webhook ne cree pas de DisputeCase dans la DB - log seulement | Risque de dispute Stripe non trackee cote backend |
| **PAY-R04** | INFO | Pas de webhook `payment_intent.requires_action` (3D Secure) - le mobile gere le flow | OK pour MVP si le SDK mobile gere 3DS |

## 2.3 BOLA / IDOR

### Correctement implemente

| ID | Element | Status |
|----|---------|--------|
| IDOR-001 | Booking access : `booking.mechanic_id != profile.id` / `booking.buyer_id != user.id` | OK |
| IDOR-002 | Notification ownership check : `notification.user_id != user.id` | OK |
| IDOR-003 | Message sending : verify booking participant (`sender is buyer or mechanic of booking`) | OK |
| IDOR-004 | Admin endpoints proteges par `get_current_admin` dependency | OK |
| IDOR-005 | Mechanic profile : `profile.user_id == user.id` pour modification | OK |
| IDOR-006 | Review : verify `reviewer_id` matches booking participant | OK |
| IDOR-007 | Report download : verify user is buyer or mechanic of the booking | OK |

### Probleme residuel

| ID | Severite | Description | Impact |
|----|----------|-------------|--------|
| **IDOR-R01** | MEDIUM | `list_bookings` dans bookings/routes.py filtre par user_id/mechanic_id, mais la route admin `/admin/bookings` ne verifie pas que le `mechanic_id` dans les resultats est masque pour le buyer | Admin panel seulement, pas d'impact buyer-facing |

## 2.4 Injection / XSS

### Correctement implemente

| ID | Element | Status |
|----|---------|--------|
| INJ-001 | SQLAlchemy ORM partout (pas de raw SQL sauf `SELECT 1` health check et alembic version) | OK |
| INJ-002 | Pydantic validation schemas avec Field(min_length, max_length, pattern, ge, le) | OK |
| INJ-003 | Contact masking dans les messages (email, phone, social handles) | OK |
| INJ-004 | CSV injection sanitization dans GDPR export (_sanitize_csv_cell) | OK |
| INJ-005 | X-Request-ID valide par regex `^[a-zA-Z0-9\-]{1,64}$` (log injection prevention) | OK |
| INJ-006 | FastAPI est JSON-only, pas de rendu HTML (sauf PDF) => XSS minimal | OK |
| INJ-007 | Security headers middleware (X-Content-Type-Options, X-Frame-Options, HSTS, Referrer-Policy) | OK |
| INJ-008 | File upload : magic bytes validation (JPEG, PNG, PDF) | OK |
| INJ-009 | File upload : max size check (chunked upload with incremental check) | OK |
| INJ-010 | ReDoS protection : `_MAX_INPUT_LENGTH = 10000` sur contact masking | OK |

### Probleme residuel

| ID | Severite | Description | Impact |
|----|----------|-------------|--------|
| **INJ-R01** | LOW | Le template HTML de receipt (inspection_report.html) utilise Jinja2 mais sans autoescape=True explicite | WeasyPrint ne rend pas de JS, risque XSS nul. Mais bonne pratique d'activer autoescape |
| **INJ-R02** | INFO | Les messages de chat ont max_length dans le schema mais pas de sanitization HTML (juste contact masking) | OK car FastAPI renvoie du JSON, pas du HTML. Le client mobile devrait echapper le rendu |

---

# PHASE 3 : BUGS FINANCIERS ET PERTE DE DONNEES

## 3.1 Race conditions

### Correctement gere

| ID | Element | Status |
|----|---------|--------|
| RACE-001 | Double-booking : `SELECT FOR UPDATE NOWAIT` sur availability | OK |
| RACE-002 | Payment release duplicate : distributed Redis lock + `FOR UPDATE skip_locked` dans webhook | OK |
| RACE-003 | Password reset replay : jti UNIQUE constraint (IntegrityError catch) | OK |
| RACE-004 | Referral code uses_count : `ReferralCode.uses_count + 1` (atomic SQL) | OK |
| RACE-005 | Rating update : subquery atomique (BUG-002 fix) | OK |
| RACE-006 | Buffer slot locking : `with_for_update(skip_locked=True)` pour slots adjacents | OK |
| RACE-007 | Booking state machine : `validate_transition()` avec ALLOWED_TRANSITIONS dict | OK |

### Problemes residuels

| ID | Severite | Description | Impact |
|----|----------|-------------|--------|
| **RACE-R01** | MEDIUM | `check_pending_acceptances` scheduler n'utilise pas `FOR UPDATE` sur les bookings qu'il annule - un acceptation concurrente pourrait passer | Fenetre de race tres etroite car le scheduler commit par booking, mais theoriquement possible |
| **RACE-R02** | LOW | `release_overdue_payments` n'utilise pas `FOR UPDATE` non plus - le lock Redis suffit pour le scheduler mais pas contre l'API si un admin resout un dispute en meme temps | Le webhook handler utilise `skip_locked` donc les 2 ne se chevaucheront pas, mais la route admin `resolve_dispute` n'a pas de lock |
| **RACE-R03** | LOW | `_LOGIN_ATTEMPTS` in-memory dict n'est pas thread-safe (defaultdict shared entre coroutines) | asyncio est single-threaded donc pas de data race, mais si gunicorn multi-worker, chaque worker a son propre dict (Redis resout ca) |

## 3.2 Integrite des donnees

### Correctement implemente

| ID | Element | Status |
|----|---------|--------|
| DATA-001 | CHECK constraints sur booking (price >= 0, commission_rate 0-1, cancelled_by) | OK |
| DATA-002 | RESTRICT FK sur buyer_id et mechanic_id (empeche suppression cascade de records financiers) | OK |
| DATA-003 | UNIQUE constraint sur stripe_payment_intent_id | OK |
| DATA-004 | Booking.cancelled_by = "buyer" | "mechanic" | NULL (check constraint) | OK |
| DATA-005 | Numeric(10,2) pour tous les montants, Numeric(5,4) pour commission_rate | OK |
| DATA-006 | DECIMAL calculation avec ROUND_HALF_UP dans pricing | OK |
| DATA-007 | GPS coordinates : Numeric(9,6) = +-180.000000 | OK |
| DATA-008 | Composite indexes pour queries scheduler (status, updated_at) | OK |
| DATA-009 | GDPR anonymization (email randomise, nom "Utilisateur Supprime", documents nullifies) | OK |
| DATA-010 | Availability slot splitting (left/right pieces preservees apres booking) | OK |

### Problemes residuels

| ID | Severite | Description | Impact |
|----|----------|-------------|--------|
| **DATA-R01** | MEDIUM | `delete_account` ne gere pas les bookings `VALIDATED` (en attente de release payment) | Un utilisateur pourrait supprimer son compte pendant la fenetre 2h pre-release. Le paiement serait quand meme capture par le scheduler, mais le buyer_id pointe vers un user anonymise |
| **DATA-R02** | LOW | `delete_account` supprime les messages (`DELETE FROM messages WHERE sender_id = user.id`) mais pas les messages recus (`receiver_id = user.id`) | Les messages recus restent avec le sender_id intact. Pas de violation GDPR car c'est le contenu de l'expediteur qui est conserve, pas du user supprime |
| **DATA-R03** | INFO | `rating_avg` est stocke en Numeric(4,2) ce qui permet des valeurs >5.0 | La logique metier limite a 1-5 via le schema Pydantic, mais pas de CHECK constraint DB |
| **GDPR-R01** | MEDIUM | `delete_account` ne ferme/desactive pas le compte Stripe Connect du mecanicien | Le compte Stripe Express reste actif chez Stripe. Les payouts en attente pourraient encore etre traites. Appeler `stripe.Account.reject()` ou `stripe.Account.delete()` |

---

# PHASE 4 : CONFIGURATION ET INFRASTRUCTURE

## 4.1 render.yaml

```yaml
# Points positifs
- PostgreSQL 16 + Redis 7 configures
- APP_ENV=staging (pas development)
- JWT_SECRET auto-generated (generateValue: true)
- TRUSTED_PROXY_COUNT=1 (correct pour Render)
- Pre-deploy: alembic upgrade head
- DB_POOL_SIZE=3, WEB_CONCURRENCY=1 (adapte au free tier)
```

| ID | Severite | Description | Impact |
|----|----------|-------------|--------|
| **INFRA-01** | HIGH | `render.yaml` utilise le **free tier** pour tous les services (DB, Redis, Web) | Pas adapte pour la production : free tier DB s'eteint apres 90j d'inactivite, 256MB RAM, pas de backup automatique |
| **INFRA-02** | MEDIUM | Pas de `SENTRY_DSN` dans render.yaml | Pas de monitoring d'erreurs en staging |
| **INFRA-03** | MEDIUM | `CORS_ORIGINS` n'est pas configure dans render.yaml | En staging `is_production=True` donc `cors_origins_list` sera vide => warning log mais CORS bloquant |
| **INFRA-04** | LOW | `STRIPE_WEBHOOK_SECRET` n'est pas dans render.yaml (doit etre configure manuellement) | Pas de secret dans le repo = correct, mais risque d'oubli |
| **INFRA-05** | LOW | Pas de `R2_*` variables dans render.yaml | File uploads en mode mock en staging |

## 4.2 Dockerfile

```dockerfile
# Points positifs
+ Python 3.12.8-slim (recent, petit)
+ Non-root user (appuser)
+ HEALTHCHECK configure
+ Gunicorn avec UvicornWorker
+ max-requests 1000 + jitter (leak prevention)
+ limit-request-body 10MB
+ graceful-timeout 30s
```

| ID | Severite | Description | Impact |
|----|----------|-------------|--------|
| **DOCKER-01** | LOW | Pas de `.dockerignore` pour `tests/`, `alembic/`, `*.md` | Image plus grosse que necessaire |
| **DOCKER-02** | INFO | `--timeout 120` est eleve pour un API JSON | Acceptable si des requetes longues (PDF generation, Stripe calls) |

## 4.3 CI/CD (GitHub Actions)

```yaml
# Points positifs
+ Lint (ruff) + Security (bandit) dans un job separe
+ Tests avec PostgreSQL 16 + Redis 7 (services reels)
+ --cov=app --cov-report=term-missing actif
+ fail_under=85 dans pyproject.toml
+ TypeScript check pour mobile (tsc --noEmit)
+ Deploy conditionnel (main branch + push only)
```

| ID | Severite | Description | Impact |
|----|----------|-------------|--------|
| **CI-01** | MEDIUM | Pas de job de securite dependances (pip-audit, safety) | Vulnerabilites connues non detectees |
| **CI-02** | MEDIUM | Deploy via simple curl sur Render deploy hook | Pas de rollback automatique, pas de health check post-deploy |
| **CI-03** | LOW | Pas de cache pip entre les jobs lint et test (chacun fait `pip install`) | Build plus lent (~1-2 min de plus) |
| **CI-04** | LOW | Mobile check ne fait que `tsc --noEmit`, pas de lint ESLint ni tests | Qualite mobile non verifiee en CI |
| **CI-05** | INFO | Tests CI utilisent `pytest -q` (quiet) ce qui masque les details | Acceptable avec `--cov-report=term-missing` |

---

# PHASE 5 : QUALITE DU CODE

## 5.1 Tests

| Metrique | Valeur |
|----------|--------|
| Tests totaux | 456 |
| Tests passed | 456 |
| Tests skipped | 3 |
| Tests failed | 0 |
| Couverture globale | 85.02% |
| Seuil CI | 85% (fail_under) |

### Modules a haute couverture (>=95%)

| Module | Couverture |
|--------|-----------|
| services/stripe_service.py | 98% |
| services/notifications.py | 100% |
| services/email_service.py | 100% |
| services/storage.py | 100% |
| notifications/routes.py | 100% |
| dependencies.py | 100% |
| utils/display_name.py | 100% |
| utils/rate_limit.py | 100% |
| utils/contact_mask.py | 100% |
| utils/booking_state.py | 100% |
| models/* | 100% |

### Modules sous 85% (points d'attention)

| Module | Couverture | Raison |
|--------|-----------|--------|
| scheduler.py | 66% | Jobs cron avec Redis/DB reels, difficile a mocker |
| auth/routes.py | 67% | OAuth/social login non implemente, GDPR export complexe |
| bookings/routes.py | 72% | Workflows multi-etapes (check-in/out, validation) |
| mechanics/routes.py | 72% | Endpoints admin/verification, file uploads |
| main.py | 54% | Lifespan/startup/health (necessite Redis reel) |
| database.py | 59% | Production SSL/get_db (SQLite en tests) |
| config.py | 80% | Validations production-only |

## 5.2 Architecture du code

### Points positifs

| Aspect | Details |
|--------|---------|
| Separation of concerns | Routes / Services / Models / Schemas bien separes |
| Booking state machine | `validate_transition()` centralise + `ALLOWED_TRANSITIONS` dict |
| Pricing calculation | Module separe `services/pricing.py` |
| Role-based serialization | `_serialize_booking()` retourne des schemas differents par role |
| Error handling | Global exception handler + structured logging |
| Rate limiting | Constantes nommees (AUTH_RATE_LIMIT, LIST_RATE_LIMIT, etc.) |
| Named constants | NO_SHOW_DISTANCE_THRESHOLD_KM, CHECK_IN_CODE_EXPIRY_SECONDS |
| DB session pattern | `get_db()` avec commit/rollback automatique |

### Points d'amelioration

| ID | Severite | Description |
|----|----------|-------------|
| **CODE-01** | LOW | `auth/routes.py` fait 1130 lignes - pourrait etre split (auth, profile, gdpr) |
| **CODE-02** | LOW | `bookings/routes.py` fait 1399 lignes - pourrait etre split (crud, check-in-out, validation) |
| **CODE-03** | LOW | `_serialize_booking()` est dans routes.py au lieu d'un module serialization |
| **CODE-04** | INFO | `get_verified_user` dependency existe mais n'est jamais utilise (code mort) |

## 5.3 Dependencies

| Aspect | Status |
|--------|--------|
| passlib | Supprime (migre vers bcrypt direct) - OK |
| PyJWT | >=2.10.1 avec extras [crypto] - OK |
| Pas de pinning exact pour weasyprint, jinja2, boto3 | Ranges specifies (>=X,<Y) - OK pour MVP |
| requirements-dev.txt existe | Separe des deps prod - OK |
| Bandit dans CI | Severity medium, skips B101 (assert) - OK |
| Ruff linter | E/F/W/I rules, line-length 120 - OK |

---

# PHASE 6 : PRODUCTION READINESS

## 6.1 Scheduler / Background Jobs

### Points positifs
- Distributed lock via Redis SET NX EX
- RedisJobStore pour persistence des one-shot jobs
- Batch size limit (SCHEDULER_BATCH_SIZE = 20)
- Per-booking commit + rollback isolation
- Catch-all cron (release_overdue_payments every 10min)
- Cleanup jobs (webhooks 7j, blacklist expired, notifications 90j, push tokens 6mo)
- Orphaned files detection (R2 vs DB comparison)
- No-show penalty system (progressive: warning -> 30j suspension -> ban)

### Problemes residuels

| ID | Severite | Description | Impact |
|----|----------|-------------|--------|
| **SCHED-01** | MEDIUM | `start_scheduler()` est appele dans `lifespan()` mais si le scheduler crash, il n'est pas restarted | Les cron jobs s'arretent silencieusement |
| **SCHED-02** | LOW | Pas de metriques/alertes sur les jobs scheduler | Impossible de savoir si `release_overdue_payments` a echoue |
| **SCHED-03** | MEDIUM | `detect_orphaned_files` et `_list_r2_keys` utilisent boto3 en mode synchrone (bloquant) dans un contexte async | Bloque l'event loop pendant les appels S3. Devrait utiliser `asyncio.to_thread()` comme stripe_service |

## 6.2 Admin

### Points positifs
- Toutes les routes admin protegees par `get_current_admin`
- Documents mecaniciens servis via presigned URLs
- Impossible de suspendre un admin
- Dernier admin ne peut pas supprimer son compte
- Pagination avec limites (max 200/page)

### Probleme residuel

| ID | Severite | Description | Impact |
|----|----------|-------------|--------|
| **ADMIN-R01** | MEDIUM | Pas d'audit log persistant pour actions admin | Les verifications, suspensions et resolutions de disputes sont loguees via structlog mais pas stockees en DB. Si les logs sont rotatifs ou indisponibles, aucune trace durable pour compliance |

## 6.3 Monitoring / Observabilite

| ID | Severite | Description | Impact |
|----|----------|-------------|--------|
| **OBS-01** | HIGH | Pas de metriques Prometheus/StatsD | Pas de dashboards, pas d'alertes sur latence/erreurs/throughput |
| **OBS-02** | HIGH | Health check ne verifie pas le scheduler | Si scheduler crash, health reste "ok" |
| **OBS-03** | MEDIUM | Sentry configure mais SENTRY_DSN absent de render.yaml | Erreurs non trackees en staging |
| **OBS-04** | LOW | Pas de request duration logging middleware | Impossible d'identifier les slow endpoints |

## 6.3 Mobile (React Native + Expo)

| ID | Severite | Description |
|----|----------|-------------|
| **MOB-01** | INFO | Mobile est un submodule git - les changements sont tracks separement |
| **MOB-02** | LOW | CI ne fait que `tsc --noEmit` - pas de tests, pas de lint |
| **MOB-03** | INFO | Mobile utilise WebView+Leaflet au lieu de react-native-maps (decision deliberee) |

---

# SYNTHESE DES PROBLEMES PAR SEVERITE

## HIGH (3)

| ID | Description | Effort |
|----|-------------|--------|
| INFRA-01 | Free tier Render pour production | 2h + budget mensuel |
| OBS-01 | Pas de metriques (Prometheus/StatsD) | 4h |
| OBS-02 | Health check ne verifie pas le scheduler | 30min |

## MEDIUM (13)

| ID | Description | Effort |
|----|-------------|--------|
| SEC-R01 | verify_email decode le token 2x | 15min |
| PAY-R01 | HTTPException dans scheduler context | 30min |
| PAY-R03 | charge.dispute.created ne cree pas de DisputeCase | 1h |
| IDOR-R01 | Admin bookings expose mechanic_id | 15min |
| RACE-R01 | check_pending_acceptances sans FOR UPDATE | 15min |
| DATA-R01 | delete_account ne gere pas status VALIDATED | 30min |
| GDPR-R01 | delete_account ne ferme pas le compte Stripe Connect du mecanicien | 1h |
| SCHED-03 | detect_orphaned_files utilise boto3 synchrone (bloque l'event loop) | 2h |
| ADMIN-R01 | Pas d'audit log persistant pour actions admin (verification, suspension, disputes) | 3h |
| INFRA-02 | SENTRY_DSN manquant dans render.yaml | 5min |
| INFRA-03 | CORS_ORIGINS manquant dans render.yaml | 5min |
| CI-01 | Pas d'audit securite dependances | 30min |
| CI-02 | Deploy sans rollback/health check | 2h |
| SCHED-01 | Scheduler non-redemarrable si crash | 30min |
| OBS-03 | Sentry non configure en staging | 5min |

## LOW (16)

| ID | Description | Effort |
|----|-------------|--------|
| SEC-R02 | get_verified_user code mort | 5min |
| SEC-R03 | Cache blacklist Redis non implemente | 2h |
| PAY-R02 | verify_webhook_signature retourne dict vs Event | 15min |
| PAY-R05 | Idempotency key collision possible si cancel+rebook meme slot/prix | 30min |
| INJ-R01 | Jinja2 autoescape non explicite | 5min |
| INJ-R03 | slot_start_time "25:99" passe validation regex mais cause 500 sur fromisoformat() | 15min |
| RACE-R02 | resolve_dispute sans FOR UPDATE | 15min |
| RACE-R03 | _LOGIN_ATTEMPTS non thread-safe (mitige par asyncio) | INFO |
| DATA-R02 | Messages recus non supprimes a la deletion | 30min |
| INFRA-04 | STRIPE_WEBHOOK_SECRET config manuelle | INFO |
| INFRA-05 | R2 variables absentes render.yaml | 5min |
| CI-03 | Pas de cache pip entre jobs | 15min |
| CI-04 | Mobile CI minimal (tsc only) | 1h |
| CODE-01 | auth/routes.py trop long (1130 lignes) | 2h |
| CODE-02 | bookings/routes.py trop long (1399 lignes) | 2h |
| OBS-04 | Pas de request duration logging | 30min |

## INFO (8)

| ID | Description |
|----|-------------|
| SEC-R04 | Commentaire misleading change_password |
| PAY-R04 | Pas de webhook 3D Secure |
| INJ-R02 | Messages sans sanitization HTML |
| DATA-R03 | rating_avg sans CHECK constraint 1-5 |
| CODE-03 | _serialize_booking dans routes.py |
| CODE-04 | get_verified_user code mort |
| DOCKER-02 | Timeout 120s eleve |
| CI-05 | pytest -q masque details |

---

# ROADMAP PRIORITAIRE

## Sprint 1 : Quick Wins (1 jour)

Budget : 0EUR, 4h de travail

| # | Action | Effort |
|---|--------|--------|
| 1 | Ajouter SENTRY_DSN, CORS_ORIGINS dans render.yaml | 10min |
| 2 | Health check : verifier `scheduler.running` | 30min |
| 3 | `check_pending_acceptances` : ajouter `with_for_update()` | 15min |
| 4 | `resolve_dispute` : ajouter `with_for_update()` sur booking | 15min |
| 5 | `delete_account` : bloquer si booking VALIDATED | 15min |
| 6 | Supprimer `get_verified_user` (code mort) | 5min |
| 7 | Fix commentaire misleading dans change_password | 5min |
| 8 | Ajouter autoescape=True au template Jinja2 | 5min |
| 9 | Ajouter CHECK constraint rating_avg BETWEEN 0 AND 5 | 15min |
| 10 | Ajouter pip-audit dans CI | 30min |

## Sprint 2 : Securite & Fiabilite (3-4 jours)

Budget : 0EUR, 24h de travail

| # | Action | Effort |
|---|--------|--------|
| 1 | Creer DisputeCase quand charge.dispute.created webhook | 2h |
| 2 | Cache blacklist Redis (SISMEMBER) | 2h |
| 3 | Fermer compte Stripe Connect a la suppression compte mecanicien (GDPR) | 1h |
| 4 | Wrapper asyncio.to_thread() sur boto3 dans detect_orphaned_files | 2h |
| 5 | Table audit_log pour actions admin (verification, suspension, disputes) | 3h |
| 6 | Request duration middleware (structlog) | 1h |
| 7 | Scheduler resilience (try/restart on crash) | 1h |
| 8 | Fix slot_start_time validation (catch ValueError -> 400) | 15min |
| 9 | Split auth/routes.py en modules | 2h |
| 10 | Split bookings/routes.py en modules | 2h |
| 11 | Augmenter couverture scheduler a 80%+ | 3h |
| 12 | CI cache pip entre jobs | 15min |

## Sprint 3 : Production (quand budget disponible)

Budget : ~20-50 EUR/mois

| # | Action | Effort | Cout |
|---|--------|--------|------|
| 1 | Upgrade Render plan (Starter DB, Basic Redis, Standard Web) | 2h | ~25 EUR/mois |
| 2 | Configurer Prometheus/Grafana (ou Render metrics) | 4h | 0-10 EUR/mois |
| 3 | Deploy pipeline avec rollback + health check post-deploy | 4h | 0 EUR |
| 4 | Mobile CI : ESLint + tests unitaires | 2h | 0 EUR |
| 5 | Backup DB automatique + DR procedure | 2h | Inclus Starter plan |

---

# COMPARAISON AVEC AUDIT PRECEDENT

| Critere | Audit precedent (8.1/10) | Cet audit (8.0/10) |
|---------|--------------------------|---------------------|
| Bugs critiques | 6 trouves, tous corriges | 0 nouveau critique |
| Securite auth | Passlib deprecie | Migre vers bcrypt - OK |
| Tests | 335 tests, ~78% | 456 tests, 85.02% |
| CI coverage | Pas enforce | enforce (fail_under=85) |
| Orphaned files | Non detectes | Job scheduler operationnel |
| Race conditions | Plusieurs identifiees | Toutes corrigees sauf 2 LOW |
| Production readiness | Non evaluee | 7.0/10 (monitoring manquant) |

**Note** : Le score global est legerement inferieur car cet audit est plus exigeant sur les criteres production-readiness et observabilite qui n'etaient pas evaluees avant.

---

# CONCLUSION

Le projet eMecano est dans un **bon etat pour un MVP**. Les corrections des 4 domaines precedents (quick wins, migration bcrypt, orphaned files, couverture tests) ont significativement ameliore la qualite.

**Points forts** :
- Architecture securitaire solide (JWT, Stripe, RBAC, rate limiting)
- State machine booking bien definie avec transitions validees
- Tests a 85% avec seuil CI enforce
- GDPR compliance (suppression + export)
- Race condition protection sur les chemins critiques

**Points a adresser avant production** :
1. Monitoring / Observabilite (HIGH) - Indispensable
2. Infrastructure Render upgrade (HIGH) - Free tier inadapte
3. Quelques race conditions residuelles sur scheduler/admin (MEDIUM)
4. Stripe dispute tracking incomplet (MEDIUM)

**Estimation budget total pour production-ready** : ~3-5 jours de travail + ~25-50 EUR/mois d'infrastructure.
