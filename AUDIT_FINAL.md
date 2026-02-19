# AUDIT TECHNIQUE COMPLET - eMecano

**Date :** 2026-02-19
**Auditeur :** Claude Opus 4.6
**Version :** v5.0 - Fresh Audit
**Scope :** Backend (FastAPI/Python), Mobile (React Native/Expo), Infrastructure (Render), CI/CD (GitHub Actions)

---

## 1. RESUME EXECUTIF

eMecano est une marketplace française connectant des acheteurs de voitures d'occasion avec des mécaniciens indépendants pour des inspections pré-achat. Le backend est en FastAPI + PostgreSQL 16 + Redis 7, le mobile en React Native/Expo SDK, les paiements via Stripe Connect, et l'hébergement sur Render.com.

**Score global : 8.1 / 10**

L'application est bien architecturée avec une sécurité solide (auth JWT, rate limiting, OWASP protections). Les patterns de concurrence (FOR UPDATE, Redis locks) et la gestion Stripe (idempotency, compensating transactions) sont matures. Les principaux axes d'amélioration concernent la couverture de tests (78% vs 85% requis), la dépendance unmaintained passlib, et les placeholders EAS pour le déploiement mobile.

---

## 2. MATRICE DES CONSTATS

| ID | Sévérité | Domaine | Titre | Statut |
|---|---|---|---|---|
| AUD5-001 | HIGH | Tests/CI | Couverture 78% < seuil 85%, non-appliqué en CI | OUVERT |
| AUD5-002 | HIGH | Supply Chain | passlib[bcrypt] unmaintained depuis 2020 | OUVERT |
| AUD5-003 | HIGH | Mobile/Stores | EAS submit placeholders bloquent soumission stores | OUVERT |
| AUD5-004 | MEDIUM | Infra | Render free tier inadapté production | OUVERT |
| AUD5-005 | MEDIUM | CI | Coverage gate non-appliqué dans pipeline CI | OUVERT |
| AUD5-006 | MEDIUM | Mobile | app.json updates.url manquant (OTA disabled) | OUVERT |
| AUD5-007 | LOW | Perf | Regex _REQUEST_ID_RE compilé a chaque requete | OUVERT |
| AUD5-008 | LOW | Data | Orphaned file detection est un placeholder | OUVERT |
| AUD5-009 | LOW | Infra | Health check masque Redis status en production | OUVERT |
| AUD5-010 | LOW | CI | mobile-check job sans needs: test | INFO |

---

## 3. SCORES PAR DOMAINE

| Domaine | Score | Details |
|---|---|---|
| Backend Security (OWASP) | 9.0/10 | JWT solide, rate limiting, file validation, CSRF, XSS safe |
| Stripe Payments | 9.0/10 | Idempotency, compensating txn, webhook sig, status checks |
| Auth & Sessions | 9.5/10 | Timing-safe login, lockout, refresh rotation, password_changed_at |
| Race Conditions | 9.0/10 | FOR UPDATE, Redis locks, atomic updates, TOCTOU protections |
| CI/CD & Tests | 6.5/10 | 313 tests passent, mais coverage gate non-applique, 78% < 85% |
| Mobile (React Native) | 7.5/10 | Auth store correct, EAS placeholders, OTA non-configure |
| Infrastructure & Config | 7.0/10 | Free tier, config validators solides mais env staging |
| Code Quality | 8.5/10 | Structlog, type hints, Pydantic schemas, clean architecture |

---

## 4. CONSTATS DETAILLES

### AUD5-001 - Couverture tests 78.12% sous le seuil de 85% [HIGH]

**Fichier :** `backend/pyproject.toml:16` / Resultats `pytest --cov`

Le `pyproject.toml` definit `fail_under = 85` mais la couverture reelle est de **78.12%** (313 tests passent, 3 skipped). Plusieurs modules critiques ont une couverture insuffisante :

| Module | Couverture | Impact |
|---|---|---|
| `app/reports/routes.py` | 35% | PDF generation endpoints non-testes |
| `app/services/email_service.py` | 40% | Email sending non-teste |
| `app/services/notifications.py` | 54% | Push notifications non-testees |
| `app/notifications/routes.py` | 54% | Notification CRUD non-teste |
| `app/services/stripe_service.py` | 60% | Refund/cancel paths partiels |
| `app/services/scheduler.py` | 68% | Cron jobs non-testes (cleanup, reminders) |

**Risque :** Regression non-detectee sur les flows critiques (paiements, notifications, rapports PDF).

**Remediation :**
```
# Priorite 1 : Modules financiers (stripe_service, payments/routes)
# Priorite 2 : Modules user-facing (notifications, email)
# Priorite 3 : Cron jobs (scheduler cleanup, reminders)
```

**Effort estime :** 3-4 jours dev

---

### AUD5-002 - passlib[bcrypt] unmaintained depuis 2020 [HIGH]

**Fichier :** `backend/requirements.txt:18`

```
passlib[bcrypt]==1.7.4
```

passlib n'a pas eu de release depuis octobre 2020. Le projet est effectivement abandonne. Le code commente dans `requirements.txt` le mentionne deja : `# Auth - NOTE: passlib is unmaintained since 2020. TODO: migrate to pwdlib or direct bcrypt`.

**Risque :** Vulnerabilites non-corrigees, incompatibilite future avec Python 3.13+, dependance a `bcrypt==4.2.1` qui peut casser la compat.

**Remediation :**
```python
# Option 1 : Migration vers pwdlib (drop-in replacement)
# pip install pwdlib[bcrypt]
# from pwdlib import PasswordHash
# pwd_context = PasswordHash((BcryptHasher(rounds=12),))

# Option 2 : bcrypt direct
# import bcrypt
# hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12))
```

**Effort estime :** 1 jour dev + tests de non-regression sur login/register/change-password

---

### AUD5-003 - EAS submit placeholders bloquent App Store/Play Store [HIGH]

**Fichier :** `mobile/eas.json:40-44`

```json
"ios": {
  "appleId": "APPLE_ID_EMAIL",
  "ascAppId": "APP_STORE_CONNECT_APP_ID",
  "appleTeamId": "APPLE_TEAM_ID"
}
```

Les identifiants Apple sont des placeholders. `eas submit` echouera en production.

Cote Android, `google-services.json` est reference mais probablement absent du repo (non committe pour raison de securite, ce qui est correct).

**Risque :** Impossible de publier sur les stores sans correction.

**Remediation :** Remplacer les placeholders par les vraies valeurs obtenues via Apple Developer Portal, et configurer `google-services.json` via EAS Secrets.

**Effort estime :** Action manuelle (1h), necessite un compte Apple Developer ($99/an).

---

### AUD5-004 - Render free tier inadapte pour la production [MEDIUM]

**Fichier :** `render.yaml`

| Service | Plan | Limitation |
|---|---|---|
| emecano-db | free | 256 MB storage, 90 jours retention |
| emecano-redis | free | 25 MB, pas de persistence |
| emecano-api | free | Sleep apres 15min inactivite, 750h/mois |

**Risques :**
- Cold start de ~30s apres inactivite (UX degradee)
- DB limitee a 256 MB (estimee saturee a ~5000 bookings avec photos)
- Redis sans persistence = perte des jobs APScheduler au redemarrage
- `WEB_CONCURRENCY=1` : un seul worker, pas de parallelisme

**Remediation :** Migrer vers Render Starter ($7/mois DB, $7/mois service) avant lancement. `WEB_CONCURRENCY=2` minimum.

**Effort estime :** Configuration Render + mise a jour render.yaml (2h)

---

### AUD5-005 - Coverage gate non-applique dans pipeline CI [MEDIUM]

**Fichier :** `.github/workflows/ci.yml:86`

```yaml
run: pytest --tb=short -q
```

Le CI execute `pytest` sans `--cov` ni `--cov-fail-under`. Le seuil de 85% dans `pyproject.toml` n'est jamais verifie en CI. Un dev peut merger du code qui fait baisser la couverture sans que le CI ne bloque.

**Remediation :**
```yaml
run: pytest --tb=short -q --cov=app --cov-report=term-missing --cov-fail-under=85
```

Note : Ceci casserait le CI immediatement car la couverture actuelle est 78%. Il faut d'abord remonter la couverture (AUD5-001) avant d'activer le gate.

**Effort estime :** 5 minutes (une ligne de CI), mais bloque par AUD5-001

---

### AUD5-006 - app.json updates.url manquant [MEDIUM]

**Fichier :** `mobile/app.json:10-13`

```json
"updates": {
  "enabled": true,
  "fallbackToCacheTimeout": 0
}
```

Le champ `url` manque dans le bloc `updates`. Sans cette URL pointant vers l'EAS project, les OTA updates (expo-updates) ne fonctionneront pas. Cela a ete observe comme un TODO dans le git log (`REPLACE_WITH_EAS_PROJECT_ID` etait present anteriurement).

**Remediation :**
```json
"updates": {
  "enabled": true,
  "url": "https://u.expo.dev/YOUR_EAS_PROJECT_ID",
  "fallbackToCacheTimeout": 0
}
```

**Effort estime :** 5 minutes apres `eas project:init`

---

### AUD5-007 - Regex _REQUEST_ID_RE compile a chaque requete [LOW]

**Fichier :** `backend/app/main.py:196`

```python
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    _REQUEST_ID_RE = _re.compile(r"^[a-zA-Z0-9\-]{1,64}$")
```

Le pattern regex est compile a chaque requete HTTP. Devrait etre compile une seule fois au niveau module.

**Remediation :** Deplacer `_REQUEST_ID_RE = _re.compile(...)` avant la fonction.

**Effort estime :** 2 minutes

---

### AUD5-008 - Orphaned file detection est un placeholder [LOW]

**Fichier :** `backend/app/services/scheduler.py:503-523`

La fonction `detect_orphaned_files()` ne fait que logger un message. Les fichiers orphelins (uploads de check-out echoues, suppressions RGPD, etc.) s'accumulent dans R2/S3 sans nettoyage.

**Impact :** Cout de stockage croissant, donnees personnelles potentiellement non-supprimees (RGPD Article 17).

**Remediation :** Implementer la detection avec listing S3 bucket vs URLs en DB. Ajouter un grace period de 7 jours avant suppression.

**Effort estime :** 1-2 jours dev

---

### AUD5-009 - Health check masque Redis status en production [LOW]

**Fichier :** `backend/app/main.py:245-248`

```python
if settings.is_production:
    overall = "ok" if result.get("database") == "connected" else "unhealthy"
    return {"status": overall}
```

En production, le health check retourne uniquement `{"status": "ok"}` sans information sur Redis. Si Redis tombe, le monitoring ne le detectera pas via le health endpoint.

**Remediation :** Inclure `redis_status` dans la reponse production (sans exposer les details internes).

**Effort estime :** 15 minutes

---

### AUD5-010 - mobile-check CI job sans dependency [INFO]

**Fichier :** `.github/workflows/ci.yml:92`

Le job `mobile-check` (TypeScript) tourne en parallele avec `lint` et `test`. Il n'a pas de `needs:` dependency. C'est un choix delibere de performance (pas de blocage croise), mais signifie qu'un echec mobile ne bloque pas le deploy backend.

**Impact :** Aucun impact direct. Architecture de CI acceptable pour un monorepo avec deploy backend-only.

---

## 5. ANALYSE DE CONFORMITE

### 5.1 Backend Security (OWASP Top 10)

| Check | Status | Details |
|---|---|---|
| A01: Broken Access Control | OK | Role-based auth, FOR UPDATE, ownership checks |
| A02: Cryptographic Failures | OK | bcrypt rounds=12, JWT HS256 with strong secret |
| A03: Injection | OK | SQLAlchemy ORM, Pydantic validation |
| A04: Insecure Design | OK | State machine, compensating transactions |
| A05: Security Misconfiguration | OK | Production validators, security headers |
| A06: Vulnerable Components | WARN | passlib unmaintained (AUD5-002) |
| A07: Auth Failures | OK | Timing-safe login, lockout, token rotation |
| A08: Data Integrity | OK | Webhook signature, magic byte validation |
| A09: Logging & Monitoring | OK | Structlog + Sentry, structured JSON in prod |
| A10: SSRF | OK | No user-controlled URL fetching |

### 5.2 Stripe Payments

| Check | Status | Details |
|---|---|---|
| Manual capture workflow | OK | create(manual) -> hold -> capture/cancel |
| PI status check before capture | OK | Retrieve + check requires_capture |
| Webhook signature verification | OK | stripe.Webhook.construct_event |
| Webhook idempotency | OK | ProcessedWebhookEvent table |
| Compensating cancellation | OK | cancel_payment_intent on DB failure |
| FOR UPDATE on webhook handler | OK | skip_locked=True on payment_intent.succeeded |
| Refund flow | OK | Status-aware (cancel uncaptured, refund captured) |
| Connect onboarding | OK | Express accounts, account_link |
| Placeholder secret rejection | OK | Fails in prod/staging with PLACEHOLDER prefix |

### 5.3 Auth & Sessions

| Check | Status | Details |
|---|---|---|
| JWT type enforcement | OK | Only "access" tokens accepted |
| JTI blacklisting | OK | BlacklistedToken table, checked on every request |
| Refresh token rotation | OK | Old JTI blacklisted on rotation |
| Password change invalidation | OK | password_changed_at with 2s tolerance |
| Timing-safe login | OK | Dummy hash on user-not-found |
| Account lockout | OK | Redis-backed, 5 attempts / 15min window |
| Email enumeration prevention | OK | Same response for existing/non-existing |
| Single-use tokens | OK | Verification, reset tokens blacklisted after use |
| Admin registration blocked | OK | 403 on role=admin |
| GDPR Article 17 | OK | Anonymization, document deletion |
| GDPR Article 20 | OK | Data export endpoint with CSV sanitization |

### 5.4 Race Conditions

| Check | Status | Details |
|---|---|---|
| Double-booking prevention | OK | SELECT FOR UPDATE NOWAIT on availability |
| Booking state machine | OK | validate_transition() enforces valid transitions |
| Concurrent check-in code entry | OK | FOR UPDATE on booking row |
| Scheduler TOCTOU | OK | Lock acquired BEFORE db read |
| Webhook + scheduler race | OK | FOR UPDATE skip_locked on PI succeeded |
| Rating update race | OK | Atomic UPDATE with subquery |
| Referral code race | OK | Atomic INCR on uses_count |
| Password reset replay | OK | UNIQUE constraint on jti + blacklist-first |

### 5.5 Infrastructure & Config

| Check | Status | Details |
|---|---|---|
| Production config validators | OK | DATABASE_URL, STRIPE, SENTRY required |
| Stripe key prefix validation | OK | sk_live_ for prod, sk_test_ for staging |
| JWT_SECRET validation | OK | >= 32 chars, weak secret blacklist |
| CORS configuration | OK | Explicit origins in prod, localhost-only in dev |
| Security headers | OK | HSTS, X-Frame-Options, X-Content-Type-Options |
| DB SSL | OK | ssl=require for prod/staging |
| Docker non-root user | OK | appuser in Dockerfile |
| Request body limit | OK | gunicorn --limit-request-body 10485760 |
| Healthcheck | OK | DB + Redis check, timeout configured |

### 5.6 Mobile

| Check | Status | Details |
|---|---|---|
| Token storage | OK | expo-secure-store via setItem/getItem |
| Auth state management | OK | Zustand store, register persists tokens |
| Logout cleanup | OK | Push token revoked, local tokens deleted |
| Form validation | OK | Client-side + server-side |
| Password requirements | OK | 8+ chars, uppercase, lowercase, digit |
| iOS permissions | OK | All usage descriptions present |
| Android permissions | OK | Fine/coarse/background location declared |
| Privacy manifests | OK | NSPrivacyAccessedAPITypes configured |
| EAS build profiles | OK | dev/preview/production channels configured |

---

## 6. RESULTATS DES TESTS

```
Backend: 313 passed, 3 skipped, 0 failed
Coverage: 78.12% (seuil: 85%)
TypeScript: 0 errors (npx tsc --noEmit)
```

---

## 7. ROADMAP DE REMEDIATION

### Sprint 1 (Priorite Haute - 1 semaine)

| Action | Effort | Constat |
|---|---|---|
| Ecrire tests pour remonter coverage a 85% | 3-4j | AUD5-001 |
| Activer `--cov-fail-under=85` en CI | 5min | AUD5-005 |
| Deplacer regex au niveau module | 2min | AUD5-007 |
| Inclure Redis dans health check prod | 15min | AUD5-009 |

### Sprint 2 (Pre-lancement - 1-2 semaines)

| Action | Effort | Constat |
|---|---|---|
| Migrer passlib vers pwdlib ou bcrypt direct | 1j | AUD5-002 |
| Configurer EAS submit credentials | 1h | AUD5-003 |
| Configurer app.json updates.url | 5min | AUD5-006 |
| Migrer Render vers Starter plan | 2h | AUD5-004 |

### Sprint 3 (Post-lancement)

| Action | Effort | Constat |
|---|---|---|
| Implementer orphaned file detection | 1-2j | AUD5-008 |

---

## 8. POINTS POSITIFS NOTABLES

Le code presente plusieurs pratiques exemplaires :

1. **Architecture auth solide** : timing-safe login, dummy hash, lockout Redis-backed, refresh token rotation avec blacklist
2. **Stripe Connect bien implemente** : manual capture, status checks, compensating transactions, idempotency keys
3. **Race conditions maitrisees** : FOR UPDATE (NOWAIT/skip_locked), Redis distributed locks, atomic updates
4. **RGPD conforme** : suppression de compte avec anonymisation, export de donnees, nettoyage des documents
5. **Observabilite** : structlog JSON en prod, Sentry integration, request_id tracing
6. **Contact masking** : prevention de fuite de coordonnees dans le chat avec regex pre-compilees et anti-ReDoS
7. **State machine stricte** : `validate_transition()` empeche les transitions invalides du booking
8. **Configuration validators** : Pydantic field/model validators qui empechent le deploy avec des secrets faibles
9. **Docker securise** : non-root user, healthcheck, request body limit
10. **Code quality** : type hints, structured logging, Pydantic schemas, clean separation of concerns
