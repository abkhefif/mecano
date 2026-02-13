# AUDIT COMPLET - eMecano

**Date**: 2026-02-11
**Auditeur**: Claude Opus 4.6
**Scope**: Backend FastAPI + Frontend React Native (Expo)

---

## RESUME EXECUTIF

| Severite   | Backend Security | Backend Arch/Errors | DB/Performance | Frontend | Tests | TOTAL |
|------------|:---:|:---:|:---:|:---:|:---:|:---:|
| CRITICAL   | 3   | 5   | 6   | 0   | 0   | **14** |
| HIGH       | 2   | 8   | 4   | 1   | 1   | **16** |
| MEDIUM     | 10  | 6   | 4   | 5   | 0   | **25** |
| LOW        | 10  | 4   | 4   | 8   | 0   | **26** |
| **TOTAL**  | **25** | **23** | **18** | **14** | **1** | **81** |

**Tests**: 170/170 passing, 0 TypeScript errors
**Coverage**: 77.30% (seuil: 85%) - FAIL

---

## 1. SECURITE

### CRITICAL

- [ ] **SEC-001** | `backend/app/config.py:11,14` | Credentials DB hardcoded dans defaults
  - Impact: Acces DB non autorise si .env manquant
  - Fix: Supprimer defaults, valider au demarrage

- [ ] **SEC-002** | `backend/app/payments/routes.py:72-82` | Webhook Stripe: bare except masque erreurs signature
  - Impact: Webhooks forge possibles si secret vide
  - Fix: Exception specifique + logging + validation secret au startup

- [ ] **SEC-003** | `backend/app/config.py:31-33` | STRIPE_SECRET_KEY et WEBHOOK_SECRET default vides
  - Impact: Mode mock silencieux en production
  - Fix: Valider au demarrage comme JWT_SECRET

### HIGH

- [ ] **SEC-004** | `backend/app/config.py:11-14` | DATABASE_URL/REDIS_URL pas valides au startup
  - Impact: Config silencieusement fausse
  - Fix: Validators comme JWT_SECRET

- [ ] **SEC-005** | `backend/app/bookings/routes.py:579` | Check-in code: comparaison non constant-time
  - Impact: Timing attack sur code 4 digits
  - Fix: `hmac.compare_digest()`

### MEDIUM

- [ ] **SEC-006** | `backend/app/main.py:76-83` | CORS wildcard "*" en dev
- [ ] **SEC-007** | `backend/app/config.py:28` | Refresh token 30 jours (standard: 7j)
- [ ] **SEC-008** | `backend/app/auth/routes.py:124-148` | Pas d'invalidation ancien refresh token
- [ ] **SEC-009** | `backend/app/mechanics/routes.py:50-59` | Vehicle type non valide contre enum
- [ ] **SEC-010** | `backend/app/bookings/routes.py:656` | Exception details leakees dans response
- [ ] **SEC-011** | `backend/app/payments/routes.py:173` | Donnees sensibles dans logs webhook
- [ ] **SEC-012** | `backend/app/referrals/routes.py:90-100` | Pas de rate limit sur validation referral
- [ ] **SEC-013** | `backend/app/main.py:70-75` | allow_credentials=True en prod
- [ ] **SEC-014** | `backend/app/utils/contact_mask.py` | Regex contournables (wa.me, 06.xx.xx)
- [ ] **SEC-015** | `backend/app/auth/routes.py:56` | is_verified=True hardcode (pas de verif email)

### LOW

- [ ] **SEC-016** | Pas de rate limit sur endpoints list
- [ ] **SEC-017** | `auth/service.py` | Bcrypt rounds non explicites
- [ ] **SEC-018** | `referrals/routes.py` | Info disclosure sur validation code
- [ ] **SEC-019** | `schemas/message.py` | Pas de min_length sur contenu message
- [ ] **SEC-020** | `reports/generator.py` | Risque template injection Jinja2
- [ ] **SEC-021** | `bookings/routes.py` | Check-in code non efface apres usage
- [ ] **SEC-022** | Pas d'admin endpoints (verification identite, moderation)
- [ ] **SEC-023** | `bookings/routes.py` | Folder upload non whitelist
- [ ] **SEC-024** | `mechanics/routes.py` | GPS coords mechanics visibles sans auth
- [ ] **SEC-025** | `config.py:28` | JWT access 15min (OWASP recommande 5min)

---

## 2. ARCHITECTURE & ERREURS

### CRITICAL

- [ ] **ARCH-001** | `bookings/routes.py:93-323` | create_booking = 230 lignes, multiple responsabilites
  - Fix: Extraire vers services (split_slot, validate, setup_payment)

- [ ] **ERR-001** | `bookings/routes.py:313-316` | Compensation transaction insuffisante si Stripe echoue
  - Fix: Logging detaille + re-raise avec contexte

- [ ] **ERR-002** | `bookings/routes.py:273-312` | Pas de rollback si buffer zone processing echoue
  - Fix: Wrap dans try/catch avec logging

- [ ] **ERR-003** | `bookings/routes.py:587` | Code brute-force: counter non persiste avant exception
  - Fix: `await db.flush()` avant raise

- [ ] **EDGE-001** | `bookings/routes.py:273-284` | Race condition: buffer zone query sans lock
  - Fix: Etendre `with_for_update()` aux buffer zones

### HIGH

- [ ] **ARCH-002** | `bookings/routes.py:113-174` | Magic numbers (30min, 15min buffer, 2h advance)
  - Fix: Centraliser dans config.py

- [ ] **ARCH-003** | `services/scheduler.py:133-246` | Code duplique 24h/2h reminders (113 lignes)
  - Fix: Extraire helper partage

- [ ] **ERR-004** | `payments/routes.py:74-179` | Webhook handler: pas logging erreur, pas validation etat
  - Fix: validate_transition() + logging

- [ ] **ERR-005** | `services/scheduler.py:44-49` | release_payment catch all sans retry
  - Fix: Distinguer erreurs temporaires/permanentes

- [ ] **ERR-006** | `services/scheduler.py:75-86` | Batch processing sans commit par booking
  - Fix: Commit apres chaque payment reussi

- [ ] **ERR-007** | `bookings/routes.py:689-700` | PDF genere apres flush = etat inconsistant si PDF echoue
  - Fix: Reordonner: PDF d'abord, puis save

- [ ] **ERR-008** | `bookings/routes.py:429-440` | Cancel refund: timezone safety manquante
  - Fix: UTC explicite sur tous datetime

- [ ] **ARCH-004** | `_get_display_name` duplique entre bookings/routes.py et messages/routes.py
  - Fix: Extraire vers utils/

### MEDIUM

- [ ] **ARCH-005** | `messages/routes.py:22-54` | Templates messages hardcodes en Python
- [ ] **ARCH-006** | `referrals/routes.py:44-55` | Magic number 10 (max retries generation code)
- [ ] **ERR-009** | `bookings/routes.py:101-106` | with_for_update sans timeout = deadlock possible
- [ ] **ERR-010** | `services/storage.py:44-103` | Upload: fichier entier en memoire avant validation taille
- [ ] **ERR-011** | `auth/routes.py:37-60` | User cree sans profil si flush echoue mid-registration
- [ ] **ERR-012** | `messages/routes.py:121-133` | 1 message custom jamais modifiable/supprimable

### LOW

- [ ] **ARCH-007** | `_serialize_booking` retourne dict au lieu de Pydantic model
- [ ] **ARCH-008** | `stripe_service.py` metadata pas type
- [ ] **LOG-001** | Exception types pas captures dans logs scheduler
- [ ] **LOG-002** | Stripe dispute: pas assez de details dans logs

---

## 3. BASE DE DONNEES & PERFORMANCE

### CRITICAL

- [ ] **DB-001** | Tous les models | Aucun ON DELETE CASCADE/SET NULL sur foreign keys
  - Impact: Orphelins en cascade si suppression
  - Fix: Migration ajoutant ondelete sur toutes les FK

- [ ] **DB-002** | `booking.py:33-35`, `mechanic_profile.py:19-20` | Float pour GPS coords
  - Impact: Perte precision GPS (7 decimales au lieu de 8+)
  - Fix: Numeric(9,6) pour lat/lng

- [ ] **DB-003** | `review.py:27` | Pas de CHECK constraint rating 1-5
  - Impact: Ratings invalides possibles
  - Fix: CheckConstraint("rating >= 1 AND rating <= 5")

- [ ] **DB-004** | `booking.py:36-41` | Pas de CHECK constraint prices >= 0
  - Impact: Prix negatifs possibles
  - Fix: CheckConstraint sur tous les champs prix

- [ ] **PERF-001** | `mechanics/routes.py:35-127` | N+1 query sur mechanic list
  - Fix: Eager loading avec selectinload

- [ ] **PERF-002** | `booking.py` | Index composites manquants (buyer_id+status+created_at)
  - Fix: Migration ajoutant index composites

### HIGH

- [ ] **DB-005** | `bookings/routes.py:100-116` | Race condition double booking - pas de UNIQUE constraint sur availability slot
  - Fix: UNIQUE(mechanic_id, date, start_time, end_time)

- [ ] **DB-006** | Multiples models | Nullable inconsistants (cancelled_by null quand status=cancelled)
  - Fix: Check constraints conditionnels

- [ ] **PERF-003** | Multiples models | lazy="raise" fragile, crash runtime si eager load oublie
  - Fix: Documenter ou changer en lazy="select"

- [ ] **PERF-004** | `mechanics/routes.py:60,127` | Pagination en Python apres fetch 500 records
  - Fix: Pagination DB-level

### MEDIUM

- [ ] **DB-007** | `review.py` | Pas d'index sur booking_id
- [ ] **DB-008** | `mechanic_profile.py` | JSON vehicle_types: cast(String).contains non indexable
  - Fix: Index GIN sur JSON
- [ ] **PERF-005** | `scheduler.py:58-88` | Batch processing charge tout en memoire
- [ ] **PERF-006** | `reviews/routes.py:108-131` | 2 queries au lieu de 1 JOIN

### LOW

- [ ] **DB-009** | `message.py:21` | is_template default=True contre-intuitif
- [ ] **DB-010** | Migration 004 header comment incorrect (dit revises 001, devrait etre 003)
- [ ] **DB-011** | `validation_proof.py:23-24` | GPS lat/lng nullable independamment
- [ ] **PERF-007** | Enum stockes en VARCHAR au lieu de PG ENUM

---

## 4. FRONTEND

### HIGH

- [ ] **FE-001** | `app.config.ts:9` | Cle Stripe test reelle hardcodee
  - Fix: Utiliser uniquement placeholder "pk_test_REPLACE_ME"

### MEDIUM

- [ ] **FE-002** | `utils/storage.ts:10-26` | localStorage pour tokens web (vulnerable XSS)
- [ ] **FE-003** | `BookingConfirmScreen.tsx:134-145` | Pas de validation range coords GPS
- [ ] **FE-004** | 33 occurrences de `catch (err: any)` au lieu de `unknown`
- [ ] **FE-005** | `SearchScreen.tsx:100-104` | Fallback silencieux sur coords Paris si permission refusee
- [ ] **FE-006** | `BookingConfirmScreen.tsx:49-64` | Reverse geocoding echoue silencieusement

### LOW

- [ ] **FE-007** | `LoginScreen.tsx:56` | Message debug avec status code expose a l'utilisateur
- [ ] **FE-008** | `MechanicProfileScreen.tsx:45-54` | Erreur API referral avalee silencieusement
- [ ] **FE-009** | `CheckOutScreen.tsx:91-150` | Validation formulaire incomplete avant API
- [ ] **FE-010** | `SearchScreen.tsx` | 338 lignes, extractable en sous-composants
- [ ] **FE-011** | `BookingConfirmScreen.tsx:111-114` | Validation annee permet futur (+1)
- [ ] **FE-012** | `MechanicDetailScreen.tsx:67` | Pas de check null sur mechanicId
- [ ] **FE-013** | Pas de JSDoc sur fonctions complexes
- [ ] **FE-014** | Pas de tests unitaires frontend

---

## 5. TESTS & COVERAGE

### HIGH

- [ ] **TEST-001** | Coverage globale 77.30% < seuil 85%
  - Modules critiques sous-couverts:
    - `services/scheduler.py`: **19%** (quasi entierement non teste)
    - `payments/routes.py`: **34%**
    - `services/notifications.py`: **38%**
    - `messages/routes.py`: **40%**
    - `referrals/routes.py`: **43%**
    - `middleware.py`: **42%**
    - `bookings/routes.py`: **70%** (gaps epars)

### STATUS ACTUEL

- Tests: **170/170 passing**
- TypeScript: **0 erreurs**
- Coverage: **77.30%** (FAIL)

---

## PRIORITES DE FIX

### P0 (BLOCKER - a fixer IMMEDIATEMENT): 14 issues

1. **SEC-001**: Credentials DB hardcoded
2. **SEC-002**: Webhook Stripe sans verification fiable
3. **SEC-003**: Stripe secrets default vides
4. **DB-001**: Pas de ON DELETE CASCADE/SET NULL
5. **DB-003**: Pas de CHECK constraint rating
6. **DB-004**: Pas de CHECK constraint prix
7. **PERF-002**: Index composites manquants
8. **ERR-001**: Transaction compensation insuffisante
9. **ERR-003**: Brute-force counter non persiste
10. **EDGE-001**: Race condition buffer zones
11. **DB-005**: UNIQUE constraint availability manquante
12. **DB-002**: Float pour GPS (precision)
13. **PERF-001**: N+1 queries mechanics
14. **ARCH-001**: create_booking 230 lignes (refactor)

### P1 (HIGH - a fixer avant production): 16 issues

Tous les issues HIGH des sections ci-dessus.

### P2 (MEDIUM - a fixer quand possible): 25 issues

Tous les issues MEDIUM des sections ci-dessus.

### P3 (LOW - nice to have): 26 issues

Tous les issues LOW des sections ci-dessus.

---

## RAPPORT FINAL (pre-fix)

```
AUDIT TERMINE - PRE-FIX

Problemes trouves: 81
  - CRITICAL: 14
  - HIGH: 16
  - MEDIUM: 25
  - LOW: 26

Tests: 170/170 passing
Coverage: 77.30% (FAIL - seuil 85%)
TypeScript errors: 0

Le projet necessite des corrections P0/P1 avant toute mise en production.
```
