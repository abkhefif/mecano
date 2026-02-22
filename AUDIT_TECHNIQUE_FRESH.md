# AUDIT TECHNIQUE COMPLET -- eMecano

**Date :** 2026-02-22
**Scope :** Backend (FastAPI), Mobile (React Native/Expo), Infrastructure (Render, CI/CD, Docker)
**Auditeurs :** 5 agents specialises (Security, Stripe/Finances, Mobile, Code Quality, Infrastructure)

---

## RESUME EXECUTIF

| Severite | Backend | Mobile | Infra/CI | **Total** |
|----------|---------|--------|----------|-----------|
| CRITIQUE | 3 | 2 | 0 | **5** |
| HAUTE | 10 | 6 | 3 | **19** |
| MOYENNE | 12 | 9 | 7 | **28** |
| BASSE | 8 | 7 | 4 | **19** |
| **Total** | **33** | **24** | **14** | **71** |

**Score global : 6.8 / 10** (avant corrections)

---

## 1. VULNERABILITES CRITIQUES (5)

### CRIT-01 -- Cle Stripe secrete commitee dans .env
- **Fichier :** `backend/.env:6`
- **CWE :** CWE-798 (Hard-coded Credentials)
- **Impact :** Un attaquant ayant acces au repo peut creer des paiements, emettre des remboursements, et acceder aux donnees financieres de tous les utilisateurs.
- **Remediation :** Revoquer immediatement la cle dans le dashboard Stripe. Generer une nouvelle cle. Supprimer `backend/.env` du tracking git (`git rm --cached`). Ajouter a `.gitignore`.
- **Effort :** 15 min | **Priorite :** P0

### CRIT-02 -- Bypass webhook signature si STRIPE_WEBHOOK_SECRET commence par "whsec_PLACEHOLDER"
- **Fichier :** `backend/app/services/stripe_service.py:247-268`
- **CWE :** CWE-345 (Insufficient Verification of Data Authenticity)
- **Impact :** En mode dev/staging, un attaquant peut forger des evenements webhook et confirmer des paiements fictifs, debloquer des fonds, ou annuler des reservations.
- **Remediation :** Refuser tous les webhooks si le secret est absent ou placeholder. Ne jamais autoriser de bypass hors tests unitaires.
- **Effort :** 30 min | **Priorite :** P0

### CRIT-03 -- `asyncio.create_task` sans reference -- notifications push perdues silencieusement
- **Fichier :** `backend/app/services/notifications.py:230`
- **CWE :** CWE-754 (Improper Check for Unusual Conditions)
- **Impact :** Les taches crees par `asyncio.create_task()` sans variable de reference sont susceptibles au garbage collection. Les exceptions sont avalees silencieusement. Les utilisateurs ne recoivent pas les notifications de mise a jour de reservation.
- **Remediation :**
  ```python
  _background_tasks: set[asyncio.Task] = set()
  task = asyncio.create_task(send_push(...))
  _background_tasks.add(task)
  task.add_done_callback(_background_tasks.discard)
  ```
- **Effort :** 30 min | **Priorite :** P0

### CRIT-04 -- [Mobile] Pas de certificate pinning -- vulnerable aux attaques MITM
- **Fichier :** `mobile/src/services/api.ts:63-66`
- **Impact :** Sur un reseau Wi-Fi public, un attaquant peut intercepter les tokens d'authentification, les donnees de paiement, et les informations personnelles (documents d'identite, numeros de telephone).
- **Remediation :** Integrer `react-native-ssl-pinning` ou TrustKit. Epingler la cle publique SPKI pour `api.emecano.fr`.
- **Effort :** 4h | **Priorite :** P0

### CRIT-05 -- [Mobile] Tokens stockes dans localStorage sur web -- vol via XSS
- **Fichier :** `mobile/src/utils/storage.ts:20-27`
- **CWE :** CWE-922 (Insecure Storage of Sensitive Information)
- **Impact :** Toute vulnerabilite XSS permet de voler `auth_token` et `refresh_token` depuis localStorage.
- **Remediation :** Migrer vers des cookies `HttpOnly; Secure; SameSite=Strict` cotes backend.
- **Effort :** 8h | **Priorite :** P1

---

## 2. VULNERABILITES HAUTES (19)

### SEC-01 -- /metrics accessible sans authentification si METRICS_API_KEY non definie
- **Fichiers :** `backend/app/main.py:260-266`, `render.yaml` (absent)
- **Impact :** Expose les routes internes, volumes de trafic, taux d'erreur, noms de handlers. Reconnaissance facilitee.
- **Remediation :** Ajouter `METRICS_API_KEY: generateValue: true` dans `render.yaml`. En production, refuser l'acces si la cle n'est pas definie.
- **Effort :** 15 min

### SEC-02 -- JWT Algorithm non valide -- pas de rejet de "none"
- **Fichier :** `backend/app/config.py:23`
- **Impact :** Si `JWT_ALGORITHM=none` est injecte dans l'environnement, PyJWT accepte des tokens non signes.
- **Remediation :** Ajouter un `@field_validator("JWT_ALGORITHM")` rejetant `none` et limitant aux algorithmes approuves.
- **Effort :** 1h

### SEC-03 -- Security headers absents en mode development
- **Fichier :** `backend/app/main.py:191-192`
- **Impact :** Si `APP_ENV=development` est accidentellement configure en prod/staging, aucun header de securite n'est applique.
- **Remediation :** Appliquer les headers dans tous les environnements. Ne conditionner que HSTS a `is_production`.
- **Effort :** 30 min

### SEC-04 -- Refresh tokens non invalides apres changement de mot de passe
- **Fichier :** `backend/app/auth/routes.py:406-472`
- **Impact :** Un attaquant ayant vole un refresh token peut continuer a generer des access tokens meme apres que la victime a change son mot de passe.
- **Remediation :** Verifier `password_changed_at` contre le `iat` du refresh token dans l'endpoint `/auth/refresh`.
- **Effort :** 1h

### FIN-01 -- `release_payment` sans SELECT FOR UPDATE sur la reservation
- **Fichier :** `backend/app/services/scheduler.py:90-93`
- **Impact :** Quand Redis est indisponible, le lock distribue retourne `True` (fallback). Deux workers peuvent capturer le meme paiement simultanement. Le double-capture Stripe est prevenu cote API, mais les timestamps DB sont ecrases.
- **Remediation :** Ajouter `.with_for_update()` a la requete booking dans `release_payment`.
- **Effort :** 15 min

### FIN-02 -- `create_payment_intent` n'a pas de validation d'entree
- **Fichier :** `backend/app/services/stripe_service.py:23-68`
- **Impact :** Aucune validation que `amount_cents > 0` ou `commission_cents <= amount_cents`. Si `PLATFORM_COMMISSION_RATE > 1.0`, le fee Stripe depasse le montant.
- **Remediation :** Ajouter des assertions en debut de fonction.
- **Effort :** 15 min

### FIN-03 -- Remboursement partiel sur PI non capture = annulation totale
- **Fichier :** `backend/app/bookings/routes.py:616-635`
- **Impact :** Un acheteur annulant avec 50% de remboursement sur un PI en `requires_capture` declanche `cancel_payment_intent` qui rembourse 100%. Perte de 50% pour la plateforme et le mecanicien.
- **Remediation :** Pour les PI non captures, utiliser `capture_payment_intent` avec montant reduit.
- **Effort :** 2h

### FIN-04 -- Expiration autorisation Stripe 7 jours non geree
- **Fichier :** `backend/app/services/scheduler.py`
- **Impact :** Un RDV reserve plus de 7 jours a l'avance verra son autorisation Stripe expirer. La capture echouera indefiniment.
- **Remediation :** Limiter la date de RDV a 6 jours apres creation, ou implementer une re-autorisation.
- **Effort :** 4h

### PERF-01 -- `selectinload` + `with_for_update` ne verrouille pas les relations
- **Fichier :** `backend/app/bookings/routes.py:1411-1422`
- **Impact :** `availability.is_booked` est modifie sans verrou. Deux annulations concurrentes peuvent lire `is_booked=True` simultanement.
- **Remediation :** Charger et verrouiller `Availability` separement quand modification necessaire.
- **Effort :** 1h

### PERF-02 -- `delete_account` = 193 lignes -- fonction monolithique
- **Fichier :** `backend/app/auth/routes.py:793-992`
- **Impact :** Impossible a tester unitairement, risque de regression eleve.
- **Remediation :** Extraire vers `app/services/account_deletion.py` avec fonctions dedies.
- **Effort :** 3h

### PERF-03 -- StripeServiceError fuite dans les reponses API
- **Fichiers :** `backend/app/bookings/routes.py:503,614`, `backend/app/payments/routes.py:356`
- **Impact :** Les messages d'erreur Stripe (contenant des IDs internes) sont exposes aux clients.
- **Remediation :** Retourner un message generique, logger l'erreur detaillee.
- **Effort :** 30 min

### PERF-04 -- `list_mechanics` charge 200 profils en memoire pour filtrage Python
- **Fichier :** `backend/app/mechanics/routes.py:84-161`
- **Impact :** Gaspillage memoire/bande passante. 50-80% des lignes chargees sont eliminees.
- **Remediation :** Deplacer le calcul de distance et filtrage vers SQL (PostGIS/Haversine).
- **Effort :** 8h

### PERF-05 -- HTML() de WeasyPrint bloque la boucle evenementielle
- **Fichier :** `backend/app/reports/generator.py:139-141`
- **Impact :** Le constructeur `HTML(string=html_content)` est execute dans le thread principal (100-500ms blocking).
- **Remediation :** Deplacer toute l'operation dans `asyncio.to_thread`.
- **Effort :** 15 min

### INFRA-01 -- pip-audit ne fait jamais echouer le build
- **Fichier :** `.github/workflows/ci.yml:35-37`
- **Impact :** Les CVEs critiques dans les dependances passent inapercues et sont deployees.
- **Remediation :** Supprimer le `|| echo "::warning::..."` fallback.
- **Effort :** 5 min

### INFRA-02 -- Migrations executees deux fois par deploiement
- **Fichiers :** `render.yaml:23`, `backend/Dockerfile:27`
- **Impact :** TOCTOU sur les migrations destructives. Double execution de `alembic upgrade head`.
- **Remediation :** Supprimer `alembic upgrade head &&` du CMD Dockerfile. Garder uniquement `preDeployCommand`.
- **Effort :** 5 min

### INFRA-03 -- /metrics public quand METRICS_API_KEY non definie
- Doublon avec SEC-01 -- voir ci-dessus.

### MOB-01 -- useMemo stale pour `isTrackingActive` (utilise `new Date()`)
- **Fichier :** `mobile/src/screens/buyer/BookingDetailScreen.tsx:115-126`
- **Impact :** Le suivi GPS du mecanicien n'apparait pas quand la fenetre de RDV debute, ou persiste apres.
- **Remediation :** Remplacer par un `useState` + `useEffect` avec interval de 30s.
- **Effort :** 30 min

### MOB-02 -- Zero tests automatises sur l'app mobile
- **Fichier :** `mobile/package.json`
- **Impact :** Regressions dans les flux critiques (paiement, booking, auth) detectees uniquement en production.
- **Remediation :** Installer jest-expo + @testing-library/react-native. Cibler : authStore, api.ts, BookingConfirmScreen.
- **Effort :** 16h

### MOB-03 -- MechanicProfileScreen = 1446 lignes monolithiques
- **Fichier :** `mobile/src/screens/mechanic/MechanicProfileScreen.tsx`
- **Impact :** Maintenance tres difficile, risque de regression croise entre fonctionnalites non liees.
- **Remediation :** Decomposer en 7+ composants et hooks specialises.
- **Effort :** 8h

### MOB-04 -- 5 timers de polling simultanes drainant la batterie
- **Fichiers :** `mobile/src/hooks/useMessages.ts:24`, `useNotifications.ts:15`, `BookingDetailScreen.tsx:72,147`, `useLocationTracking.ts:106`
- **Impact :** ~15 requetes HTTP/min en foreground. Drain batterie significatif.
- **Remediation :** Remplacer par WebSocket/SSE, ou adapter les intervalles selon AppState.
- **Effort :** 16h

---

## 3. VULNERABILITES MOYENNES (28)

### Backend (12)

| ID | Description | Fichier | Effort |
|----|-------------|---------|--------|
| SEC-05 | Header CSP absent sur toutes les reponses | `middleware.py:14` | 30 min |
| SEC-06 | Content-Type upload validation cote client uniquement (pre-check redondant) | `bookings/routes.py:1173-1178` | 30 min |
| SEC-07 | Politique de mot de passe sans caractere special + bcrypt truncation 72 bytes | `schemas/auth.py:9-13` | 2h |
| SEC-08 | Rate limiter degrade en memoire quand Redis indisponible (per-worker) | `utils/rate_limit.py:25-51` | 2h |
| SEC-09 | STRIPE_WEBHOOK_SECRET placeholder dans .env non detecte au demarrage | `backend/.env:8` | 1h |
| FIN-05 | `check_pending_acceptances` sans idempotency key sur cancel | `scheduler.py:211` | 15 min |
| FIN-06 | Webhook idempotency record insere avant traitement, pas rollback sur echec | `payments/routes.py:118-123` | 2h |
| FIN-07 | `skip_locked=True` dans webhook succeeded peut perdre des evenements | `payments/routes.py:133-137` | 1h |
| FIN-08 | Dispute resolution utilise `cancel_payment_intent` ignorant les remboursements partiels | `payments/routes.py:339` | 1h |
| PERF-06 | Race condition registration email (IntegrityError non caught) | `auth/routes.py:207-277` | 30 min |
| PERF-07 | Emails logues en INFO (PII) -- risque RGPD | Multiple fichiers | 1h |
| PERF-08 | Admin presigned URLs sequentielles (150 appels series pour 50 profils) | `admin/routes.py:326-338` | 1h |

### Mobile (9)

| ID | Description | Fichier | Effort |
|----|-------------|---------|--------|
| MOB-05 | Types `any` pour MapView/Marker -- pas de type safety | Multiple fichiers | 2h |
| MOB-06 | `Record<string, any>` au lieu de `MarkedDates` pour calendrier | `AvailabilityScreen.tsx:234` | 15 min |
| MOB-07 | useEffect dependency `booking?.status` au lieu de `booking` | `BookingDetailScreen.tsx:91-95` | 15 min |
| MOB-08 | Erreurs backend affichees brutes aux utilisateurs | `api.ts:180-185` | 1h |
| MOB-09 | Inline styles partout dans MechanicProfileScreen (pas de StyleSheet) | `MechanicProfileScreen.tsx` | 2h |
| MOB-10 | Referral code fetche via useEffect brut au lieu de React Query | `MechanicProfileScreen.tsx:80-98` | 1h |
| MOB-11 | Verification identite via Alert sequentiels -- UX pauvre | `MechanicProfileScreen.tsx:224-278` | 4h |
| MOB-12 | Types `any` dans les error handlers API | `api.ts:92,100,106,171` | 1h |
| MOB-13 | Fonction `timeToMinutes` dupliquee dans 2 fichiers | `BookingDetailScreen.tsx`, `MechanicBookingDetailScreen.tsx` | 15 min |

### Infrastructure (7)

| ID | Description | Fichier | Effort |
|----|-------------|---------|--------|
| INFRA-04 | APP_ENV=staging en production -- piege operationnel | `render.yaml:35` | 30 min |
| INFRA-05 | Pas de backup base de donnees (plan gratuit) | `render.yaml:1-5` | 1h |
| INFRA-06 | Pas de mypy/pyright dans le pipeline CI | `ci.yml` | 2h |
| INFRA-07 | Pas de build Docker multi-stage | `Dockerfile` | 2h |
| INFRA-08 | Image Docker pinned par tag, pas par digest | `Dockerfile:1` | 15 min |
| INFRA-09 | echo=APP_DEBUG peut logger les requetes SQL en staging | `database.py:22` | 15 min |
| INFRA-10 | RedisJobStore ignore TLS scheme (`rediss://`) | `scheduler.py:39-45` | 30 min |

---

## 4. VULNERABILITES BASSES (19)

### Backend (8)

| ID | Description | Fichier |
|----|-------------|---------|
| SEC-10 | Admin routes sans rate limit specifique (meme 30/min que les routes normales) | `admin/routes.py` |
| SEC-11 | Coordonnees GPS mecanicien triangulable via recherches petit rayon | `mechanics/routes.py:140-141` |
| FIN-09 | Mock Stripe accounts creent de vrais PI sans Connect transfer | `stripe_service.py:42-55` |
| FIN-10 | Pas de safety net pour PENDING_ACCEPTANCE avec paiement echoue | `scheduler.py` |
| FIN-11 | Webhooks dispute lifecycle non geres (`charge.dispute.closed`, etc.) | `payments/routes.py` |
| FIN-12 | CASCADE sur Report/Review/Message/Inspection FK -- perte preuves si booking supprime | `report.py, review.py, message.py` |
| PERF-09 | Compteurs Prometheus definis mais jamais incrementes | `metrics.py:6-28` |
| PERF-10 | `_build_receipt_data` est async sans await | `reports/routes.py:78` |

### Mobile (7)

| ID | Description | Fichier |
|----|-------------|---------|
| MOB-14 | EAS submit config avec placeholders Apple | `eas.json:41-44` |
| MOB-15 | Chemin local pour Google Play service account key | `eas.json:46` |
| MOB-16 | SENTRY_DSN et POSTHOG_API_KEY vides = observabilite desactivee silencieusement | `config.ts:17-22` |
| MOB-17 | Polling messages continue pour bookings termines | `useMessages.ts:24` |
| MOB-18 | Form state initialise depuis `user` prop potentiellement stale | `MechanicProfileScreen.tsx:46-51` |
| MOB-19 | `refetchOnWindowFocus: false` globalement desactive | `queryClient.ts:8` |
| MOB-20 | `useCallback` inutile sur `handleReportProblem` | `ValidationScreen.tsx:56-58` |

### Infrastructure (4)

| ID | Description | Fichier |
|----|-------------|---------|
| INFRA-11 | WEB_CONCURRENCY default a 2 dans Dockerfile (scheduler fork) | `Dockerfile:27` |
| INFRA-12 | mobile-check ne gate pas le deploy | `ci.yml:108-131` |
| INFRA-13 | pip-audit non pinne en version | `ci.yml:36` |
| INFRA-14 | Nouvelle connexion Redis creee a chaque acquisition de lock | `scheduler.py:58-76` |

---

## 5. POINTS FORTS

### Authentification (Solide)
- Bcrypt cost factor 12 avec wrapping async
- Blacklist JTI verifiee sur chaque requete authentifiee
- Rotation refresh token avec blacklist de l'ancien JTI
- Enforcement du type de token (access/refresh/password_reset/download)
- Dummy hash pour protection contre l'enumeration d'emails sur login
- Lockout per-email avec backend Redis
- `password_changed_at` invalidant les access tokens pre-changement
- Token TOCTOU-safe pour reset password via contrainte UNIQUE DB

### BOLA/IDOR (Tous endpoints verifies -- aucun IDOR trouve)
- 16 endpoints verifies avec controles d'autorisation corrects
- Verification buyer_id/mechanic_id/admin sur chaque mutation
- Messages: verification participation booking

### Injection (Aucune vulnerabilite)
- Toutes les requetes DB via SQLAlchemy ORM parametre
- Pas d'appels subprocess ou os.system
- Protection injection CSV dans l'export GDPR

### Upload fichiers (Solide)
- Validation magic-bytes contre MIME declare
- Whitelist dossiers upload (pas de path traversal)
- Limite 5 MB par chunk
- Fichiers sensibles servis via URLs pre-signees

### Stripe (Bonne base)
- Idempotency keys sur les operations critiques
- Transaction compensatoire sur echec creation booking
- Deduplication webhook via `ProcessedWebhookEvent`
- Pricing calcule cote serveur uniquement
- CHECK constraints sur tous les champs financiers
- RESTRICT sur les FK financieres (buyer_id, mechanic_id)

### Infrastructure
- Health check complet (DB + Redis + Scheduler)
- Logging structure JSON en production (structlog)
- Pool DB correctement dimensionne avec pre_ping et recycle
- SSL impose en staging/production
- Container non-root
- .dockerignore complet

---

## 6. ANALYSE PAR DOMAINE

### 6.1 Securite & Authentification
**Score : 7/10**

Forces : Auth robuste, pas d'IDOR, pas d'injection, upload securise.
Faiblesses : Cle Stripe dans .env (CRIT), webhook bypass possible (CRIT), headers conditionnels, refresh token non invalide au changement mdp, pas de CSP.

### 6.2 Paiements Stripe & Finances
**Score : 6/10**

Forces : Idempotency keys, deduplication webhook, state machine, pricing serveur.
Faiblesses : Pas de FOR UPDATE dans scheduler (HIGH), remboursement partiel = annulation totale (HIGH), expiration 7j non geree (HIGH), validation entrees absente.

### 6.3 Application Mobile
**Score : 5.5/10**

Forces : TypeScript strict, React Query bien utilise, Zustand propre.
Faiblesses : Pas de cert pinning (CRIT), localStorage web (CRIT), zero tests, 1446 lignes monolithiques, 5 polling simultanees, types `any` partout.

### 6.4 Infrastructure & CI/CD
**Score : 7.5/10**

Forces : Health check, logging, SSL, container non-root, CI gate deploy derriere tests.
Faiblesses : pip-audit cosmitique, double migration, pas de backup DB, pas de mypy.

### 6.5 Qualite Code & Tests
**Score : 7/10**

Forces : 457 tests (85%+ coverage), structlog, Pydantic schemas.
Faiblesses : Fonctions monolithiques (193 lignes), create_task sans reference, pas de tests concurrence, compteurs Prometheus morts.

---

## 7. PLAN D'ACTIONS PRIORITISE

### Sprint 0 -- Immediat (avant tout trafic production)
| # | Action | Effort | Impact |
|---|--------|--------|--------|
| 1 | Revoquer/remplacer cle Stripe + supprimer .env du git | 15 min | Bloque vol financier |
| 2 | Corriger webhook bypass (STRIPE_WEBHOOK_SECRET obligatoire) | 30 min | Bloque paiements forges |
| 3 | Fix `asyncio.create_task` notifications | 30 min | Restaure notifications |
| 4 | Ajouter METRICS_API_KEY dans render.yaml | 5 min | Bloque reconnaissance |
| 5 | pip-audit = hard fail dans CI | 5 min | Bloque CVEs |
| 6 | Supprimer double `alembic upgrade head` | 5 min | Evite TOCTOU migration |

### Sprint 1 -- Securite & Stabilite (1 semaine)
| # | Action | Effort | Impact |
|---|--------|--------|--------|
| 7 | Validator JWT_ALGORITHM (rejeter "none") | 1h | Bloque algorithm downgrade |
| 8 | Security headers dans tous les envs | 30 min | Defense en profondeur |
| 9 | Invalider refresh tokens au changement mdp | 1h | Session security |
| 10 | FOR UPDATE dans `release_payment` scheduler | 15 min | Integrite paiement |
| 11 | Validation entrees `create_payment_intent` | 15 min | Integrite Stripe |
| 12 | Idempotency key sur `check_pending_acceptances` | 15 min | Idempotence |
| 13 | Fix remboursement partiel PI non capture | 2h | Perte financiere |
| 14 | Sanitiser messages erreur Stripe dans reponses API | 30 min | Info disclosure |
| 15 | Fix WeasyPrint HTML() blocking event loop | 15 min | Performance |

### Sprint 2 -- Mobile & Qualite (2 semaines)
| # | Action | Effort | Impact |
|---|--------|--------|--------|
| 16 | Certificate pinning mobile | 4h | Securite reseau |
| 17 | Fix useMemo stale `isTrackingActive` | 30 min | UX tracking GPS |
| 18 | Setup jest-expo + premiers tests | 16h | Filet de securite |
| 19 | Decomposer MechanicProfileScreen | 8h | Maintenabilite |
| 20 | Adapter polling selon AppState | 4h | Batterie |
| 21 | Sanitiser erreurs backend cote mobile | 1h | UX |
| 22 | Catch IntegrityError registration race | 30 min | Robustesse |
| 23 | Paralleliser presigned URLs admin | 1h | Performance admin |

### Sprint 3 -- Infrastructure & Hardening (1 semaine)
| # | Action | Effort | Impact |
|---|--------|--------|--------|
| 24 | Backup DB (pg_dump vers R2 ou upgrade plan) | 2h | Business continuity |
| 25 | Ajouter mypy au pipeline CI | 2h | Type safety |
| 26 | Build Docker multi-stage | 2h | Securite image |
| 27 | Pin image Docker par digest | 15 min | Supply chain |
| 28 | Guard echo=APP_DEBUG derriere APP_ENV=dev | 15 min | PII logs |
| 29 | Gestion expiration autorisation Stripe 7j | 4h | Paiement |
| 30 | RedisJobStore TLS support | 30 min | Securite Redis |

### Backlog
| # | Action | Effort |
|---|--------|--------|
| 31 | CSP header | 30 min |
| 32 | Caractere special password policy + fix bcrypt 72B | 2h |
| 33 | Redis hard-require en production | 2h |
| 34 | Extraire `delete_account` en service layer | 3h |
| 35 | Migrer list_mechanics vers PostGIS SQL | 8h |
| 36 | Webhook handlers dispute lifecycle | 4h |
| 37 | CASCADE -> RESTRICT sur Report/Review/Message FK | 1h |
| 38 | Incrementer compteurs Prometheus | 30 min |
| 39 | Tests concurrence (race conditions) | 8h |
| 40 | WebSocket/SSE remplacer polling mobile | 16h |
| 41 | httpOnly cookies pour web tokens | 8h |
| 42 | Ecran verification identite dedie (wizard UX) | 4h |

---

## 8. ESTIMATION BUDGET

| Phase | Effort estime | Priorite |
|-------|--------------|----------|
| Sprint 0 (immediat) | ~1.5h | P0 -- bloquant |
| Sprint 1 (securite) | ~6.5h | P1 -- cette semaine |
| Sprint 2 (mobile+qualite) | ~36h | P2 -- 2 semaines |
| Sprint 3 (infra+hardening) | ~11h | P2 -- 1 semaine |
| Backlog | ~57h | P3 -- au fur et mesure |
| **Total** | **~112h** | |

---

## 9. CONCLUSION

Le projet eMecano a une **base solide** en authentification, protection BOLA/IDOR, et infrastructure de base. Les corrections des 27 bugs de l'audit precedent ont significativement ameliore le score.

Les **risques les plus urgents** sont :
1. La cle Stripe dans le repo (CRIT-01)
2. Le bypass webhook (CRIT-02)
3. Les notifications perdues (CRIT-03)
4. Le certificate pinning mobile absent (CRIT-04)

Les **5 corrections du Sprint 0** (1.5h de travail) eliminent les risques critiques imminents.

Le domaine le plus faible est l'**application mobile** (5.5/10), principalement a cause du manque de tests, du code monolithique, et des problemes de securite reseau. Le backend Stripe necessite un travail significatif sur la gestion des cas limites (remboursement partiel, expiration 7j, webhook resilience).

**Score projete apres Sprint 0+1 : 8.2/10**
**Score projete apres tous les sprints : 9.1/10**
