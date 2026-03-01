# AUDIT SECURITE BACKEND — RAPPORT COMBINE (Pass 1 + Pass 2)

**Projet :** eMecano API
**Date :** 2026-03-01
**Auditeur :** Claude Sonnet 4.6 — Senior Application Security Auditor
**Scope :** `/home/bouzelouf/secret_project/backend/app/`
**Stack :** FastAPI / SQLAlchemy 2.0 async / PostgreSQL / Redis / Stripe Connect / Cloudflare R2
**Pass 1 :** 25 findings (CRITICAL x1, HIGH x3, MEDIUM x9, LOW x6, INFO x6)
**Pass 2 :** 9 nouveaux findings nets + 1 correction de faux positif Pass 1

---

## 1. RESUME EXECUTIF

### Score global : **6.8 / 10**

Ce backend présente un niveau de sécurité globalement solide pour un MVP en phase de lancement. L'architecture démontre une maturité réelle dans la gestion des tokens JWT (blacklist par `jti`, rotation, invalidation post-changement de mot de passe via `password_changed_at`), la protection BOLA sur les bookings, et la sécurité Stripe (signature webhook, idempotency, capture manuelle). Les efforts de défense en profondeur sont visibles dans la quasi-totalité des modules.

Le Pass 2 a cependant révélé plusieurs failles supplémentaires non couvertes par le Pass 1, dont une HIGH d'impact DoS sur le module `demands`, et quatre MEDIUM touchant des flux métier critiques (email change sans invalidation de token, fichiers locaux accessibles sans authentification, proposal sans Stripe Customer, suspension sans annulation des bookings pendants). Le score passe de 7.3/10 (Pass 1) à **6.8/10** après intégration des nouveaux findings.

### Correction du faux positif Pass 1 — FINDING-M06

**FINDING-M06** (Pass 1) déclarait que `GET /auth/me/export` (RGPD Article 20) n'était pas implémenté. Cette affirmation était **incorrecte** : l'endpoint est présent et fonctionnel aux lignes 1103-1247 de `auth/routes.py`. Le finding est **corrigé** : le statut passe de "CONFIRMÉ — non implémenté" à "CORRIGE — implémenté, mais avec une nouvelle vulnérabilité distincte" (voir FINDING-P2-N06).

### Nombre de findings par sévérité (Pass 1 + Pass 2 combinés)

| Severite      | Pass 1 | Pass 2 nets | Total |
|--------------|--------|-------------|-------|
| CRITICAL      | 1      | 0           | **1** |
| HIGH          | 3      | 1           | **4** |
| MEDIUM        | 9      | 4           | **13**|
| LOW           | 6      | 2           | **8** |
| INFORMATIONAL | 6      | 2           | **8** |
| ANNULE        | 1      | 0           | 1     |
| **TOTAL**     | **25** | **9**       | **34**|

### Top 5 risques business (Pass 1 + Pass 2)

1. **[CRITICAL — P1]** Cle Stripe de test (`sk_test_*`) et webhook placeholder commites dans `.env` — risque de compromission financiere directe (FINDING-C01).
2. **[HIGH — P2]** `create_demand` charge TOUS les mecaniciens actifs sans LIMIT + boucle de notifications non bornee — vecteur DoS applicable des la mise en production (FINDING-P2-N01).
3. **[HIGH — P1]** Absence de limite globale de taille de corps de requete — vecteur DoS par saturation memoire des workers (FINDING-H04).
4. **[HIGH — P1]** Filtre `accepted_vehicle_types` via `LIKE` sans index GIN — full table scan potentiel a l'echelle (FINDING-H02).
5. **[MEDIUM — P2]** Changement d'email dans `update_me` sans invalidation des tokens JWT existants — fenetre de 15 minutes d'acces post-changement (FINDING-P2-N02).

---

## 2. POINTS FORTS

Les elements suivants attestent d'une approche de securite proactive et constituent des bonnes pratiques a preserver :

- **JWT robuste** : Token blacklisting par `jti` (`dependencies.py:60-68`), validation de l'emetteur (`iss: "emecano"`), rejet de l'algorithme `none` (`config.py:38`), invalidation globale par `password_changed_at` (`dependencies.py:92-101`), rotation des refresh tokens avec blacklist immediate.
- **Anti-timing oracle** : Utilisation d'un hash factice `_DUMMY_HASH` pour les tentatives de connexion sur un email inexistant (`auth/routes.py:70, 442`) — prevention d'enumeration d'emails par timing.
- **Protection BOLA systematique** : Tous les endpoints `/{booking_id}` verifient `booking.buyer_id == user.id` ou `booking.mechanic_id == profile.id` avant toute modification.
- **Idempotency Stripe complete** : Cles d'idempotency sur create/cancel/capture/refund ; deduplication webhook via `ProcessedWebhookEvent` avec contrainte UNIQUE et flush-avant-traitement (`payments/routes.py:110-135`).
- **Securite des uploads** : Validation magic bytes, whitelist MIME, limite 5 MB, whitelist de dossiers contre path traversal (`services/storage.py`).
- **Rate limiting distribue** : slowapi + Redis avec fallback in-memory ; IP reelle extraite via `TRUSTED_PROXY_COUNT` configurable (`config.py:121`).
- **Security headers exhaustifs** : `X-Content-Type-Options`, `X-Frame-Options`, `CSP`, `HSTS` (production uniquement), `Referrer-Policy`, `Permissions-Policy` — middleware dedie (`middleware.py`).
- **Validation de configuration stricte** : `pydantic-settings` avec validators en production (cles Stripe, DSN Sentry, longueur JWT_SECRET >= 32, HTTPS pour FRONTEND_URL, RESEND_API_KEY, METRICS_API_KEY).
- **RGPD** : Anonymisation des comptes (Article 17), suppression des documents sensibles, nettoyage des push tokens expires, retention bornee a 3 ans pour les logs d'audit (`services/scheduler.py`).
- **Check-in code HMAC** : Cle dediee separee du JWT, comparaison `secrets.compare_digest` pour eviter les timing attacks.
- **Tests de securite dedies** : `test_audit_bugs.py` documente 8 bugs historiques avec tests de regression. CI mature avec `bandit`, `pip-audit`, `ruff`, couverture >= 85%, PostgreSQL 16 et Redis 7 reels.
- **Jinja2 autoescape=True** : Protection XSS systematique dans les templates PDF ; timeout `asyncio.wait_for(30s)` sur WeasyPrint.
- **Locking base de donnees** : `with_for_update()`, `with_for_update(nowait=True)`, `with_for_update(skip_locked=True)` sur les operations critiques de booking pour eviter les race conditions.
- **Sanitisation CSV** : `_sanitize_csv_cell()` dans `export_data` previent les injections de formules CSV/Excel (`auth/routes.py:1118-1122`).

---

## 3. FINDINGS CRITICAL

---

### [CRITICAL] [P1] FINDING-C01 : Cle Stripe de test et webhook placeholder commites dans `.env`

- **Statut :** CONFIRME
- **Confiance :** 10/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/.env:6-8`
- **Categorie :** Config / Secrets
- **CWE :** CWE-312 — Cleartext Storage of Sensitive Information
- **OWASP :** A02:2021 — Cryptographic Failures
- **Code actuel :**
```
STRIPE_SECRET_KEY=sk_test_REDACTED_FOR_SECURITY
STRIPE_WEBHOOK_SECRET=whsec_PLACEHOLDER_will_generate_later
```
- **Condition :** Le fichier `.env` contient une vraie cle Stripe (`sk_test_*`) et un placeholder de webhook nomme explicitement `PLACEHOLDER`. Le `.gitignore` declare ignorer `.env`, mais si ce fichier a ete commite a un moment quelconque, il sera present dans l'historique git.
- **Consequence :** Un acces lecture au depot (ou a un worker CI/CD) permet de recuperer la cle Stripe pour creer des remboursements, lister des customers, ou acceder aux donnees de paiement. Le placeholder webhook desactive la verification de signature si non remplace.
- **Correction :**
  1. Revoquer immediatement la cle `sk_test_REDACTED...` dans le dashboard Stripe.
  2. Verifier l'historique git : `git log --all --full-history -- .env` ; si commite, purger avec `git filter-repo --path .env --invert-paths`.
  3. Utiliser uniquement des variables d'environnement injectees par le systeme de deploiement (Render env vars, Kubernetes Secrets, HashiCorp Vault).
  4. Ajouter `.env` au `.gitignore` global et verifier avec `git check-ignore -v .env`.

---

## 4. FINDINGS HIGH

---

### [HIGH] [P2] FINDING-P2-N01 : `create_demand` charge tous les mecaniciens actifs sans LIMIT et notifie sans bornage — vecteur DoS

- **Statut :** CONFIRME
- **Confiance :** 9/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/demands/routes.py:112-156`
- **Categorie :** Perf / DoS
- **CWE :** CWE-400 — Uncontrolled Resource Consumption
- **OWASP :** API4:2023 — Unrestricted Resource Consumption
- **Code actuel :**
```python
# demands/routes.py:112-119
mechanics_result = await db.execute(
    select(MechanicProfile).where(
        MechanicProfile.is_active == True,
        MechanicProfile.is_identity_verified == True,
    )
    # Pas de .limit() — charge TOUS les mecaniciens actifs
)
mechanics = mechanics_result.scalars().all()

# demands/routes.py:121-155 — boucle O(N) avec await create_notification() sur chaque mechanic
for mechanic in mechanics:
    if mechanic.city_lat is None or mechanic.city_lng is None:
        continue
    if body.vehicle_type.value not in mechanic.accepted_vehicle_types:
        continue
    dist_km = calculate_distance_km(...)
    if dist_km > mechanic.max_radius_km:
        continue
    await create_notification(db=db, user_id=mechanic.user_id, ...)
```
- **Condition :** La requete SQL ne comporte aucun `.limit()`. Avec N mecaniciens actifs et verifies, l'endpoint charge N profils entiers en memoire, puis effectue N appels `await create_notification()` sequentiels dans une boucle. Chaque `create_notification()` insere une ligne en base. Un buyer verifie peut declencher cette boucle en soumettant une demande, soit de facon legitime, soit de facon malveillante en soumettant 10 demandes/minute (la limite actuelle est `10/minute`).
- **Consequence :** Avec 1 000 mecaniciens actifs : 1 requete = 1 000 rows chargees en memoire + 1 000 INSERTs sequentiels dans la meme transaction. Avec le rate limit `10/minute`, un seul acheteur peut generer 10 000 INSERTs/minute. L'event loop asyncio est bloque pendant chaque `await create_notification()`, rendant le worker non-repondant pour les autres requetes.
- **Correction :**
```python
# Option 1 : Bounding box + LIMIT avant filtrage Python
from math import cos, radians

MAX_NOTIFICATIONS_PER_DEMAND = 200
lat_delta = 150.0 / 111.0  # Rayon max absolu : 150 km
lng_delta = 150.0 / (111.0 * max(cos(radians(body.meeting_lat)), 0.01))

mechanics_result = await db.execute(
    select(MechanicProfile).where(
        MechanicProfile.is_active == True,
        MechanicProfile.is_identity_verified == True,
        MechanicProfile.city_lat >= body.meeting_lat - lat_delta,
        MechanicProfile.city_lat <= body.meeting_lat + lat_delta,
        MechanicProfile.city_lng >= body.meeting_lng - lng_delta,
        MechanicProfile.city_lng <= body.meeting_lng + lng_delta,
    ).limit(MAX_NOTIFICATIONS_PER_DEMAND)
)

# Option 2 : Deporter la notification dans une tache de fond (Celery / APScheduler)
# pour ne pas bloquer la reponse HTTP
```
Ajouter un index composite : `Index("ix_mechanic_profile_active_geo", "is_active", "is_identity_verified", "city_lat", "city_lng")`.

---

### [HIGH] [P1] FINDING-H02 : Filtre `accepted_vehicle_types` via `cast(String).contains()` — absence d'index GIN et correspondance partielle

- **Statut :** CONFIRME
- **Confiance :** 9/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/mechanics/routes.py:82`
- **Categorie :** Logic / Perf
- **CWE :** CWE-20 — Improper Input Validation
- **OWASP :** API4:2023 — Unrestricted Resource Consumption
- **Code actuel :**
```python
cast(MechanicProfile.accepted_vehicle_types, String).contains(vehicle_type.value),
```
- **Condition :** La colonne `accepted_vehicle_types` est de type JSON. Le cast en String suivi de `.contains()` genere un `LIKE '%value%'` en SQL. En l'absence d'index GIN, PostgreSQL effectue un full table scan sur la table `mechanic_profiles`. Pour un `vehicle_type.value = "car"`, ce filtre matcherait aussi `"racing_car"` si ce type existait dans l'enum.
- **Consequence :** Full table scan en production avec un grand nombre de mecaniciens. La correspondance partielle est theorique avec l'enum actuelle mais reste une dette.
- **Correction :**
```python
# Utiliser l'operateur JSON @> de PostgreSQL
from sqlalchemy.dialects.postgresql import JSONB

MechanicProfile.accepted_vehicle_types.cast(JSONB).contains([vehicle_type.value]),

# Migration Alembic : index GIN
# CREATE INDEX ix_mechanic_vehicle_types_gin
#   ON mechanic_profiles USING GIN (accepted_vehicle_types);
```

---

### [HIGH] [P1] FINDING-H03 : Exception catch-all sur `payment_method` retrieve — masque les erreurs reseau Stripe

- **Statut :** CONFIRME
- **Confiance :** 8/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/payments/routes.py:493-511`
- **Categorie :** Auth / Logic
- **CWE :** CWE-390 — Detection of Error Condition Without Action
- **OWASP :** API3:2023 — Broken Object Property Level Authorization
- **Code actuel :**
```python
pm = await asyncio.wait_for(
    asyncio.to_thread(stripe.PaymentMethod.retrieve, payment_method_id, ...),
    timeout=15.0,
)
# ...
except Exception:
    raise HTTPException(status_code=404, detail="Payment method not found")
```
- **Consequence :** Une erreur reseau transitoire sur Stripe (timeout) retourne 404 "not found" a l'utilisateur, sans retry ni log. Les erreurs d'autorisation Stripe sont indiscernables d'une absence de ressource.
- **Correction :**
```python
except asyncio.TimeoutError:
    logger.error("stripe_pm_retrieve_timeout", pm_id=payment_method_id)
    raise HTTPException(status_code=503, detail="Payment service temporarily unavailable")
except stripe.InvalidRequestError:
    raise HTTPException(status_code=404, detail="Payment method not found")
except Exception as e:
    logger.error("stripe_pm_retrieve_error", error=str(e), pm_id=payment_method_id)
    raise HTTPException(status_code=500, detail="Internal error")
```

---

### [HIGH] [P1] FINDING-H04 : Absence de limite globale de taille du corps de requete

- **Statut :** CONFIRME
- **Confiance :** 9/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/main.py` (absence de middleware)
- **Categorie :** Config / DoS
- **CWE :** CWE-400 — Uncontrolled Resource Consumption
- **OWASP :** API4:2023 — Unrestricted Resource Consumption
- **Code actuel :**
```python
# Aucun middleware de limitation de taille de corps global dans main.py
# Seul payments/routes.py:91-101 limite le payload webhook a 64 KB
MAX_WEBHOOK_PAYLOAD_BYTES = 65_536
```
- **Consequence :** Un attaquant peut envoyer des requetes de plusieurs GB pour saturer la memoire des workers Uvicorn/Gunicorn, causant un DoS.
- **Correction :**
```python
# Dans main.py, ajouter avant les autres middlewares
from starlette.middleware.base import BaseHTTPMiddleware

class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    MAX_BODY_SIZE = 10 * 1024 * 1024  # 10 MB global

    async def dispatch(self, request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.MAX_BODY_SIZE:
            from starlette.responses import JSONResponse
            return JSONResponse({"detail": "Payload too large"}, status_code=413)
        return await call_next(request)

app.add_middleware(MaxBodySizeMiddleware)
```

---

## 5. FINDINGS MEDIUM

---

### [MEDIUM] [P2] FINDING-P2-N02 : Changement d'email dans `update_me` sans invalidation des tokens JWT existants

- **Statut :** CONFIRME
- **Confiance :** 9/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/auth/routes.py:584-601`
- **Categorie :** Auth / Session Management
- **CWE :** CWE-613 — Insufficient Session Expiration
- **OWASP :** API2:2023 — Broken Authentication
- **Code actuel :**
```python
# auth/routes.py:596-601
if email_changed:
    user.is_verified = False
    verification_token = create_email_verification_token(user.email)
    await send_verification_email(user.email, verification_token)

await db.flush()
# ABSENT : user.password_changed_at = datetime.now(timezone.utc)
# ABSENT : blacklisting du jti du token courant
```
- **Condition :** Lorsqu'un utilisateur change son email via `PATCH /auth/me`, `is_verified` est remis a `False` et un email de re-verification est envoye. Cependant, `password_changed_at` n'est pas mis a jour, et le token JWT courant n'est pas blackliste. Le mecanisme d'invalidation par `password_changed_at` dans `get_current_user` (lignes 92-101 de `dependencies.py`) n'est donc pas declenche. Les tokens access existants (duree de vie 15 min) restent valides pendant toute la duree de leur expiration. Un attaquant qui aurait derobe un token d'acces avant le changement d'email continue d'acceder a l'API avec les nouvelles donnees de l'utilisateur.
- **Preuve de reachability :** Chemin HTTP complet : `PATCH /auth/me` -> `update_me()` -> `email_changed = True` -> `user.is_verified = False` -> `db.flush()`. Aucun des appels intermediaires ne blackliste le token actuel ni ne met a jour `password_changed_at`.
- **Consequence :** Fenetre d'acces post-changement d'email de 0 a 15 minutes. Si un token a ete derobe (XSS, fuite de logs), le changement d'email ne revoque pas l'acces de l'attaquant.
- **Correction :**
```python
# auth/routes.py — dans update_me(), apres email_changed = True
if email_changed:
    user.is_verified = False
    # Invalider tous les tokens existants via le mecanisme password_changed_at
    user.password_changed_at = datetime.now(timezone.utc)
    verification_token = create_email_verification_token(user.email)
    await send_verification_email(user.email, verification_token)
```
Note : `password_changed_at` est le mecanisme centralise d'invalidation de tokens. Le renommer en `credentials_changed_at` ou `session_invalidated_at` clarifierait son usage semantique au-dela du changement de mot de passe.

---

### [MEDIUM] [P2] FINDING-P2-N03 : `/uploads` StaticFiles expose tous les fichiers locaux sans authentification (mode developpement)

- **Statut :** CONFIRME
- **Confiance :** 9/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/main.py:298-305`
- **Categorie :** Auth / Config
- **CWE :** CWE-284 — Improper Access Control
- **OWASP :** API1:2023 — Broken Object Level Authorization
- **Code actuel :**
```python
# main.py:298-305
if not settings.R2_ENDPOINT_URL:
    from pathlib import Path
    from fastapi.staticfiles import StaticFiles

    _uploads_dir = Path("uploads")
    _uploads_dir.mkdir(exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(_uploads_dir)), name="uploads")
```
- **Condition :** Lorsque `R2_ENDPOINT_URL` n'est pas configure (typiquement en developpement, mais aussi potentiellement dans un environnement de staging mal configure), FastAPI monte le repertoire `uploads/` comme un endpoint public sans aucune authentification. N'importe qui connaissant ou devinant l'URL d'un fichier peut le telecharger directement via `GET /uploads/<path>`. Cela inclut les documents sensibles uploades via les endpoints de mecanique (diplomes, pieces d'identite, photos de rapports d'inspection).
- **Preuve de reachability :** Si `R2_ENDPOINT_URL = ""` (valeur par defaut dans `config.py:66`), la condition `not settings.R2_ENDPOINT_URL` est `True`. Le montage StaticFiles est effectue au demarrage. Tout fichier dans `uploads/` est accessible via `GET /uploads/<filename>` sans token ni credentials.
- **Consequence :** En developpement ou staging sans R2 configure, des documents sensibles (identite, photos de vehicules, rapports d'inspection) sont publiquement accessibles par enumeration de noms de fichiers. Si l'application tourne en production sans R2 (mise en production rapide sans configuration complete), tous les uploads sont exposes publiquement.
- **Correction :**
```python
# Option 1 (recommandee) : Supprimer le StaticFiles et remplacer par un
# endpoint authentifie pour servir les fichiers locaux en dev
if not settings.R2_ENDPOINT_URL:
    from pathlib import Path

    _uploads_dir = Path("uploads")
    _uploads_dir.mkdir(exist_ok=True)

    @app.get("/uploads/{file_path:path}")
    async def serve_local_upload(
        file_path: str,
        user: User = Depends(get_current_user),  # Authentification obligatoire
    ):
        import aiofiles
        full_path = (_uploads_dir / file_path).resolve()
        # Protection path traversal
        if not str(full_path).startswith(str(_uploads_dir.resolve())):
            raise HTTPException(status_code=400, detail="Invalid path")
        if not full_path.exists():
            raise HTTPException(status_code=404, detail="File not found")
        # Servir le fichier
        ...

# Option 2 : Bloquer explicitement le demarrage si R2 non configure en production
# (deja present via config.py warnings, mais pas en erreur fatale)
```

---

### [MEDIUM] [P2] FINDING-P2-N04 : `accept_proposal` cree un PaymentIntent sans `customer_id` — cartes sauvegardees inutilisables

- **Statut :** CONFIRME
- **Confiance :** 9/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/proposals/routes.py:351-358`
- **Categorie :** Logic / Paiement
- **CWE :** CWE-657 — Violation of Secure Design Principles
- **OWASP :** API4:2023 — Unrestricted Resource Consumption (fonctionnalite degradee)
- **Code actuel :**
```python
# proposals/routes.py:351-358
intent = await create_payment_intent(
    amount_cents=amount_cents,
    mechanic_stripe_account_id=mechanic.stripe_account_id,
    commission_cents=commission_cents,
    metadata={
        "buyer_id": str(buyer_id),
        "mechanic_id": str(mechanic.id),
        "proposal_id": str(proposal.id),
    },
    idempotency_key=f"proposal_{proposal.id}_{uuid.uuid4().hex[:8]}",
    # customer_id ABSENT — buyer.stripe_customer_id non passe
)
```
- **Condition :** `create_payment_intent` dans `stripe_service.py:156-158` attache le `customer_id` au PaymentIntent uniquement si passe en parametre. La fonction `accept_proposal` ne passe pas `customer_id`, contrairement a `create_booking` dans `bookings/routes.py:346-362` qui appelle `get_or_create_customer()` puis passe `customer_id=customer_id`. Sans `customer_id`, le PaymentIntent n'a pas `setup_future_usage = "off_session"` et ne permet pas l'utilisation des cartes sauvegardees dans le Stripe PaymentSheet mobile.
- **Consequence :** Les bookings crees via la voie "proposal -> accept" ne peuvent pas utiliser les cartes sauvegardees de l'acheteur dans l'app mobile, contrairement aux bookings directs. Inconsistance d'experience utilisateur et impossibilite d'utiliser les cartes pre-enregistrees pour environ 50% des flux de paiement si les proposals sont frequemment utilisees.
- **Correction :**
```python
# proposals/routes.py — dans accept_proposal()
# Recuperer le buyer pour obtenir/creer son Stripe Customer
buyer_result = await db.execute(select(User).where(User.id == buyer_id))
buyer = buyer_result.scalar_one()

customer_id = await get_or_create_customer(
    email=buyer.email,
    user_id=str(buyer.id),
    existing_customer_id=buyer.stripe_customer_id,
)
if not buyer.stripe_customer_id:
    buyer.stripe_customer_id = customer_id
    await db.flush()

intent = await create_payment_intent(
    amount_cents=amount_cents,
    mechanic_stripe_account_id=mechanic.stripe_account_id,
    commission_cents=commission_cents,
    metadata={...},
    idempotency_key=f"proposal_{proposal.id}_{uuid.uuid4().hex[:8]}",
    customer_id=customer_id,  # Ajoute
)

# Retourner ephemeral_key + customer_id dans la reponse pour le PaymentSheet
ephemeral_key = await create_ephemeral_key(customer_id)
```

---

### [MEDIUM] [P2] FINDING-P2-N05 : `suspend_user` ne cancelle pas les bookings PENDING_ACCEPTANCE du mecanicien suspendu

- **Statut :** CONFIRME
- **Confiance :** 9/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/admin/routes.py:257-277`
- **Categorie :** Logic / Business
- **CWE :** CWE-362 — Concurrent Execution Using Shared Resource with Improper Synchronization (state inconsistency)
- **OWASP :** API5:2023 — Broken Function Level Authorization
- **Code actuel :**
```python
# admin/routes.py:257-277
if user.role == UserRole.MECHANIC:
    profile_result = await db.execute(...)
    profile = profile_result.scalar_one_or_none()
    if profile:
        if body.suspended:
            profile.suspended_until = datetime.now(timezone.utc) + timedelta(days=body.suspension_days)
            profile.is_active = False
        else:
            ...

# ABSENT : Pas de cancellation des bookings PENDING_ACCEPTANCE ou CONFIRMED
# ABSENT : Pas de remboursement des PaymentIntents associes
```
- **Condition :** Lorsqu'un admin suspend un mecanicien, seul le profil est mis a jour (`is_active = False`, `suspended_until = ...`). Les bookings dans l'etat `PENDING_ACCEPTANCE` ou `CONFIRMED` pour ce mecanicien ne sont ni annules ni rembourses. Les acheteurs ayant des bookings pendants pour un mecanicien suspendu devront attendre jusqu'a l'expiration automatique par le scheduler (`MECHANIC_ACCEPTANCE_TIMEOUT_HOURS = 2h`). Pour les bookings `CONFIRMED`, aucun mecanisme automatique ne les annule — ils resteront indefiniment dans cet etat.
- **Consequence :** Apres suspension, un mecanicien avec des bookings `CONFIRMED` peut theroriquement encore executer le check-in. Les acheteurs ne sont pas notifies de la suspension. Inconsistance d'etat : `profile.is_active = False` mais `booking.status = CONFIRMED`.
- **Correction :**
```python
# admin/routes.py — dans suspend_user(), apres profile.is_active = False
if body.suspended and profile:
    # Annuler les bookings actifs du mecanicien suspendu
    from app.models.booking import Booking, BookingStatus
    from app.services.stripe_service import cancel_payment_intent

    bookings_to_cancel = await db.execute(
        select(Booking).where(
            Booking.mechanic_id == profile.id,
            Booking.status.in_([
                BookingStatus.PENDING_ACCEPTANCE,
                BookingStatus.CONFIRMED,
            ]),
        ).with_for_update()
    )
    for booking in bookings_to_cancel.scalars().all():
        # Rembourser le PaymentIntent
        if booking.stripe_payment_intent_id:
            try:
                await cancel_payment_intent(booking.stripe_payment_intent_id)
            except Exception as e:
                logger.error("suspend_cancel_stripe_failed",
                             booking_id=str(booking.id), error=str(e))
        booking.status = BookingStatus.CANCELLED
        # Notifier l'acheteur
        await create_notification(db=db, user_id=booking.buyer_id, ...)

    logger.info("mechanic_suspended_bookings_cancelled",
                mechanic_id=str(profile.id),
                cancelled_count=len(bookings_to_cancel.scalars().all()))
```

---

### [MEDIUM] [P2] FINDING-P2-N06 : `GET /auth/me/export` effectue des requetes non bornees — risque DoS sur comptes anciens

- **Statut :** CONFIRME
- **Confiance :** 9/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/auth/routes.py:1128-1231`
- **Categorie :** Perf / DoS
- **CWE :** CWE-400 — Uncontrolled Resource Consumption
- **OWASP :** API4:2023 — Unrestricted Resource Consumption
- **Note :** Ce finding corrige et remplace FINDING-M06 (Pass 1). L'endpoint IS implemented (FINDING-M06 etait un faux positif). La vulnerabilite reelle est distincte.
- **Code actuel :**
```python
# auth/routes.py:1128-1130 — aucun .limit() sur aucune des 5+ requetes
bookings_result = await db.execute(
    select(Booking).where(Booking.buyer_id == user.id)
    # Pas de .limit()
)
# Meme pattern pour reviews (L1146), messages (L1161),
# notifications (L1176), availability (L1220), diplomas (L1235)
```
- **Condition :** L'endpoint `GET /auth/me/export` execute 5 a 7 requetes SELECT sans aucun `.limit()`. Un utilisateur avec 5 ans d'historique pourrait avoir : 200 bookings, 200 reviews, 2 000 messages, 10 000 notifications, 500 disponibilites. Chaque element est serialise en JSON en memoire avant d'etre retourne. Le rate limit est `AUTH_RATE_LIMIT = "20/minute"`, permettant 20 appels/minute par utilisateur.
- **Consequence :** Un compte avec de nombreuses notifications/messages peut generer une reponse JSON de plusieurs MB, chargeant tous les objets en memoire simultanement. Avec 20 appels/minute, 20 reponses de 5 MB = 100 MB de memoire/minute pour un seul utilisateur.
- **Correction :**
```python
# Ajouter des limites sur chaque requete d'export
MAX_EXPORT_ITEMS = 1000  # Par categorie

bookings_result = await db.execute(
    select(Booking)
    .where(Booking.buyer_id == user.id)
    .order_by(Booking.created_at.desc())
    .limit(MAX_EXPORT_ITEMS)
)

# Meme pattern pour reviews, messages, notifications, availability, diplomas

# Indiquer dans la reponse si des elements ont ete tronques
export["_metadata"] = {
    "export_date": datetime.now(timezone.utc).isoformat(),
    "truncated": bookings_count > MAX_EXPORT_ITEMS,
    "note": "Export limited to the most recent 1000 items per category.",
}
```
Baisser le rate limit de `AUTH_RATE_LIMIT` a `2/hour` specifiquement pour cet endpoint (comme recommande dans l'ancienne correction de FINDING-M06).

---

### [MEDIUM] [P1] FINDING-H01 : Dockerfile sans multi-stage build — outils de build presents dans l'image finale

- **Statut :** CONFIRME (severite reclassee de HIGH a MEDIUM — mitigation `.dockerignore` confirmee)
- **Confiance :** 9/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/Dockerfile:17`
- **Categorie :** Config / Infra
- **Code actuel :**
```dockerfile
COPY . .
```
- **Consequence :** En cas de RCE sur le conteneur, un attaquant dispose des outils de build (pip, compilateurs) pour faciliter la post-exploitation. Le `.dockerignore` exclut correctement `.env`, `tests/`, `venv/`, `.coverage` — le vecteur d'exposition de secrets est donc attenue.
- **Correction :**
```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
```

---

### [MEDIUM] [P1] FINDING-M01 : Utilisateur non verifie peut se connecter et obtenir des tokens JWT valides

- **Statut :** CONFIRME
- **Confiance :** 9/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/auth/routes.py:424-467`
- **Categorie :** Auth / Logic
- **CWE :** CWE-287 — Improper Authentication
- **OWASP :** API2:2023 — Broken Authentication
- **Code actuel :**
```python
# Aucune verification de user.is_verified dans le handler login
if not await verify_password_async(body.password, user.password_hash):
    await _record_login_attempt(body.email)
    raise HTTPException(...)
await _clear_login_attempts(body.email)
# Retourne des tokens sans verifier is_verified
return TokenResponse(access_token=..., refresh_token=...)
```
- **Consequence :** Un compte cree avec l'email d'une autre personne peut acceder aux endpoints de profil sans confirmation de possession de l'email.
- **Correction :**
```python
if not user.is_verified:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Email not verified. Please check your inbox.",
    )
```

---

### [MEDIUM] [P1] FINDING-M02 : Upload photo de profil sans verification `is_verified`

- **Statut :** CONFIRME
- **Confiance :** 9/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/auth/routes.py:614-630`
- **Categorie :** Auth / Upload
- **Code actuel :**
```python
async def upload_user_photo(
    photo: UploadFile,
    user: User = Depends(get_current_user),  # Pas get_verified_buyer
    ...
):
```
- **Consequence :** Un compte non verifie peut uploader du contenu dans le bucket R2, consommant du stockage et contournant les politiques de moderation.
- **Correction :** Remplacer `get_current_user` par une verification explicite `if not user.is_verified: raise HTTPException(403, ...)`.

---

### [MEDIUM] [P1] FINDING-M03 : `is_active` verifie apres `clear_login_attempts` dans `login`

- **Statut :** CONFIRME
- **Confiance :** 10/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/auth/routes.py:459-460`
- **Categorie :** Auth / Logic
- **Code actuel :**
```python
if not await verify_password_async(body.password, user.password_hash):
    await _record_login_attempt(body.email)
    raise HTTPException(...)
await _clear_login_attempts(body.email)  # <- Reset AVANT is_active check
if not user.is_active:
    raise HTTPException(status_code=403, ...)
```
- **Consequence :** Un compte desactive peut reinitialiser indefiniment son compteur de lockout en fournissant le bon mot de passe, invalidant la protection anti-brute-force pour ce compte.
- **Correction :** Deplacer le check `is_active` avant `verify_password_async` et `_clear_login_attempts`.

---

### [MEDIUM] [P1] FINDING-M04 : `list_nearby_demands` charge jusqu'a 200 demandes sans filtre geospatial SQL

- **Statut :** CONFIRME
- **Confiance :** 9/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/demands/routes.py:216-256`
- **Categorie :** Perf
- **Code actuel :**
```python
result = await db.execute(
    select(BuyerDemand).where(
        BuyerDemand.status == DemandStatus.OPEN,
        BuyerDemand.expires_at > now,
        BuyerDemand.desired_date >= today,
    ).limit(200)
)
# Filtrage par distance en Python pur ensuite
```
- **Consequence :** Jusqu'a 200 demandes chargees en Python puis filtrees par distance. Inefficace a grande echelle.
- **Correction :** Ajouter un bounding box SQL + index composite `(status, expires_at, meeting_lat, meeting_lng)`.

---

### [MEDIUM] [P1] FINDING-M05 : Boucle `while parent_id` sans protection contre les cycles

- **Statut :** CONFIRME
- **Confiance :** 8/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/proposals/routes.py:203-220`
- **Categorie :** Logic
- **CWE :** CWE-835 — Loop with Unreachable Exit Condition
- **Code actuel :**
```python
while current.parent_id:
    parent = await db.execute(...)
    if not parent:
        break
    history.append(...)
    current = parent
```
- **Consequence :** Boucle infinie potentielle si une reference circulaire existe en base (migration ratee, manipulation directe).
- **Correction :** Ajouter `visited_ids: set[uuid.UUID] = {proposal.id}` et verifier `if current.parent_id in visited_ids: break` a chaque iteration.

---

### [MEDIUM] [P1] FINDING-M06 : (CORRIGE — FAUX POSITIF)

- **Statut :** ANNULE — Ce finding affirmait que `GET /auth/me/export` n'etait pas implemente. La relecture approfondie de `auth/routes.py:1103-1247` confirme que l'endpoint est present et fonctionnel. La vulnerabilite reelle de cet endpoint est documentee dans FINDING-P2-N06 (voir ci-dessus).

---

### [MEDIUM] [P1] FINDING-T01 : Absence de tests de regression pour FINDING-M01, M02, M03

- **Statut :** CONFIRME
- **Confiance :** 9/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/tests/test_auth.py`
- **Categorie :** Tests / Auth
- **Consequence :** Les vulnerabilites M01, M02, M03 pourraient regresser silencieusement.
- **Correction :** Ajouter dans `test_auth.py` :
```python
async def test_login_unverified_user_blocked(client, db): ...
async def test_login_inactive_user_does_not_reset_lockout_counter(client, db): ...
async def test_upload_photo_unverified_user_blocked(client, db): ...
```

---

### [MEDIUM] [P1] FINDING-T05 : `generate_payment_receipt` avec `**booking_data` non valide

- **Statut :** CONFIRME
- **Confiance :** 8/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/reports/generator.py:158`
- **Categorie :** Injection / Logic
- **Code actuel :**
```python
html_content = template.render(**booking_data)
```
- **Consequence :** Dict non valide passe au contexte Jinja2 — cles inattendues pourraient ecraser des variables de template. Mitigue par `autoescape=True` mais pratique risquee.
- **Correction :** Definir un schema Pydantic `PaymentReceiptData` et valider `booking_data` avant `template.render()`.

---

## 6. FINDINGS LOW

---

### [LOW] [P2] FINDING-P2-N07 : `CHECK_IN_HMAC_KEY` sans valeur par defaut securisee et sans validation en production

- **Statut :** CONFIRME
- **Confiance :** 8/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/config.py:59`
- **Categorie :** Config / Crypto
- **CWE :** CWE-326 — Inadequate Encryption Strength
- **Code actuel :**
```python
# config.py:59
CHECK_IN_HMAC_KEY: str = ""
```
- **Condition :** `CHECK_IN_HMAC_KEY` a une valeur par defaut vide `""`. Aucun validator dans `config.py` ne verifie que cette cle est non-vide en production (contrairement a `JWT_SECRET` qui a un validator strict avec longueur minimale de 32 caracteres). Si cette cle n'est pas definie dans le `.env` de production, les codes HMAC de check-in seront calcules avec une cle vide, rendant les codes previsibles et reproductibles par n'importe qui connaissant l'algorithme HMAC utilise.
- **Preuve de reachability :** `config.py:59` `CHECK_IN_HMAC_KEY: str = ""`. La validation en production (`validate_production_settings`, lignes 157-231) ne verifie pas `CHECK_IN_HMAC_KEY`. Un deploiement en production sans cette variable dans `.env` utilisera silencieusement une cle vide.
- **Consequence :** Un attaquant connaissant l'algorithme HMAC et le format du code de check-in pourrait calculer des codes valides sans connaitre la cle secrete, compromettant le mecanisme d'entree de check-in.
- **Correction :**
```python
# config.py
CHECK_IN_HMAC_KEY: str = ""

@field_validator("CHECK_IN_HMAC_KEY")
@classmethod
def validate_check_in_hmac_key(cls, v: str) -> str:
    if not v:
        import warnings
        warnings.warn(
            "CHECK_IN_HMAC_KEY is empty — check-in HMAC will use an empty key (insecure).",
            stacklevel=2,
        )
    return v

@model_validator(mode="after")
def validate_check_in_hmac_key_production(self) -> "Settings":
    if self.is_production and not self.CHECK_IN_HMAC_KEY:
        raise ValueError(
            "CHECK_IN_HMAC_KEY must be set in production for check-in code security."
        )
    if self.is_production and len(self.CHECK_IN_HMAC_KEY) < 32:
        raise ValueError(
            "CHECK_IN_HMAC_KEY must be at least 32 characters in production."
        )
    return self
```

---

### [LOW] [P2] FINDING-P2-N08 : Admin ne peut pas acceder aux proposals via les endpoints standards — inconsistance de role

- **Statut :** CONFIRME
- **Confiance :** 7/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/proposals/routes.py:599-624`
- **Categorie :** Auth / Logic
- **CWE :** CWE-284 — Improper Access Control
- **Code actuel :**
```python
# proposals/routes.py:599-624
def _get_proposal_for_user(proposal, user):
    if user.role == UserRole.BUYER:
        if proposal.buyer_id != user.id:
            raise HTTPException(403, "Access denied")
    elif user.role == UserRole.MECHANIC:
        if proposal.mechanic_profile_id != user.mechanic_profile.id:
            raise HTTPException(403, "Access denied")
    else:
        # Role ADMIN : pas de cas specifique -> tombe dans le else
        # Selon la logique, un admin avec role != BUYER et != MECHANIC
        # se verra refuser l'acces avec une 403
        raise HTTPException(403, "Access denied")
```
- **Condition :** `_get_proposal_for_user` ne gere pas le role `ADMIN`. Un admin appelant `GET /proposals/{proposal_id}` recevra une 403 car il n'est ni buyer ni mechanic du proposal. En comparaison, le module admin dispose d'un endpoint dedie `GET /admin/bookings` avec acces complet. L'inconsistance entre les modules cree de la confusion et empeche les admins d'investiguer des disputes impliquant des proposals sans acces direct a la base de donnees.
- **Consequence :** Les admins ne peuvent pas acceder aux details des proposals via l'API — limitation operationnelle pour la resolution de disputes et le support.
- **Correction :**
```python
def _get_proposal_for_user(proposal, user):
    if user.role == UserRole.ADMIN:
        return  # Admin a acces en lecture a toutes les proposals
    if user.role == UserRole.BUYER:
        if proposal.buyer_id != user.id:
            raise HTTPException(403, "Access denied")
    elif user.role == UserRole.MECHANIC:
        if proposal.mechanic_profile_id != user.mechanic_profile_id:
            raise HTTPException(403, "Access denied")
    else:
        raise HTTPException(403, "Access denied")
```

---

### [LOW] [P1] FINDING-L01 : `generate_verification_code()` exclut les codes commencant par 0

- **Statut :** CONFIRME
- **Confiance :** 10/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/services/email_service.py:37`
- **Code actuel :**
```python
return str(secrets.randbelow(900000) + 100000)
# Produit [100000, 999999] — exclut [000000, 099999]
```
- **Consequence :** Reduction d'entropie de ~3.3 bits. Negligeable avec 5 tentatives max mais trivial a corriger.
- **Correction :** `return f"{secrets.randbelow(1000000):06d}"`

---

### [LOW] [P1] FINDING-L02 : Ping Redis bloquant sans log d'avertissement au demarrage

- **Statut :** CONFIRME
- **Confiance :** 10/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/utils/rate_limit.py:33-44`
- **Consequence :** Si Redis repond lentement (>200ms au demarrage), le rate limiting tombe silencieusement en mode in-memory sans avertissement.
- **Correction :** Augmenter le timeout a 0.5s et logger un warning si le fallback in-memory est utilise.

---

### [LOW] [P1] FINDING-L03 : Tentatives malformees de code check-in non comptabilisees

- **Statut :** CONFIRME
- **Confiance :** 9/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/bookings/routes.py:914-923`
- **Consequence :** Un attaquant peut envoyer des milliers de requetes malformees sans epuiser le compteur de 5 tentatives.
- **Correction :** Incrementer `booking.check_in_code_attempts` avant de rejeter une requete malformee.

---

### [LOW] [P1] FINDING-L04 : WeasyPrint sans `base_url=None` — risque SSRF de second ordre

- **Statut :** CONFIRME (statut revise de PROBABLE a CONFIRME)
- **Confiance :** 8/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/reports/generator.py:141`
- **Code actuel :**
```python
pdf_bytes = await asyncio.wait_for(
    asyncio.to_thread(lambda: HTML(string=html_content).write_pdf()),
    timeout=30,
)
```
- **Consequence :** Si une URL photo corrompue en DB pointe vers un service interne, WeasyPrint ferait une requete HTTP SSRF lors de la generation PDF.
- **Correction :** `HTML(string=html_content, base_url=None).write_pdf()` + validation du prefixe R2 sur les URLs photo.

---

### [LOW] [P1] FINDING-L05 : Email sans `max_length` dans `UserUpdateRequest`

- **Statut :** CONFIRME
- **Confiance :** 7/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/schemas/auth.py:119-124`
- **Correction :** `email: EmailStr | None = Field(None, max_length=255)`

---

### [LOW] [P1] FINDING-T02 : CI sans secret scanning (trufflehog/gitleaks)

- **Statut :** CONFIRME
- **Confiance :** 9/10
- **Fichier :** `/home/bouzelouf/secret_project/.github/workflows/ci.yml`
- **Consequence :** Des secrets commites (comme FINDING-C01) ne sont pas detectes automatiquement a chaque push.
- **Correction :**
```yaml
- name: Secret scanning
  uses: gitleaks/gitleaks-action@v2
```

---

## 7. FINDINGS INFORMATIONAL

---

### [INFO] [P2] FINDING-P2-N09 : `export_data` accessible aux mecaniciens et aux comptes non verifies

- **Statut :** CONFIRME
- **Confiance :** 7/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/auth/routes.py:1103-1107`
- **Categorie :** Auth / RGPD
- **Code actuel :**
```python
@router.get("/me/export")
@limiter.limit(AUTH_RATE_LIMIT)
async def export_data(
    request: Request,
    user: User = Depends(get_current_user),  # PAS get_verified_buyer
    db: AsyncSession = Depends(get_db),
):
```
- **Condition :** L'endpoint utilise `get_current_user` sans verifier `is_verified`. Conformement au RGPD, l'export de donnees personnelles doit etre possible pour tous les utilisateurs (verification de l'identite recommandee mais non obligatoire pour l'acces). Ce comportement est donc coherent avec le RGPD mais merite une note : un compte cree frauduleusement (email non possede) peut exporter les donnees de ce compte.
- **Recommandation :** Envisager d'exiger `is_verified = True` pour l'export afin de s'assurer que l'utilisateur est bien le proprietaire de l'email.

---

### [INFO] [P1] FINDING-I01 : Pagination in-memory dans `list_mechanics`

- **Statut :** CONFIRME
- **Confiance :** 9/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/mechanics/routes.py:158-161`
- **Recommandation :** Migrer vers PostGIS (`ST_Distance`) pour filtrer et ordonner en SQL pur.

---

### [INFO] [P1] FINDING-I02 : `_redis_client` global par worker Gunicorn

- **Statut :** CONFIRME
- **Confiance :** 7/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/auth/routes.py:86-110`
- **Recommandation :** Documenter explicitement ce comportement et envisager une connexion Redis partagee via le lifespan.

---

### [INFO] [P1] FINDING-I03 : Blacklisted tokens non nettoyes proactivement lors d'un reset-password

- **Statut :** CONFIRME
- **Confiance :** 8/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/auth/routes.py:806-835`
- **Recommandation :** Comportement actuel acceptable. Le scheduler `cleanup_expired_blacklisted_tokens` nettoie periodiquement.

---

### [INFO] [P1] FINDING-I04 : `_RE_PHONE_GENERIC` faux positifs sur prix ou codes postaux

- **Statut :** CONFIRME
- **Confiance :** 8/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/app/utils/contact_mask.py:11`
- **Recommandation :** Affiner le pattern pour les numeros de telephone standards.

---

### [INFO] [P1] FINDING-T03 : Deploy sans verification d'integrite de l'image Docker

- **Statut :** CONFIRME
- **Confiance :** 7/10
- **Fichier :** `/home/bouzelouf/secret_project/.github/workflows/ci.yml:91-105`
- **Recommandation :** Envisager Docker Content Trust ou SBOM dans le CI.

---

### [INFO] [P1] FINDING-T04 : Tests HTTP sur SQLite — comportements PostgreSQL non couverts

- **Statut :** CONFIRME
- **Confiance :** 8/10
- **Fichier :** `/home/bouzelouf/secret_project/backend/tests/conftest.py:25`
- **Recommandation :** Migrer `conftest.py` pour utiliser PostgreSQL via `DATABASE_URL` du CI pour les tests d'integration.

---

### [INFO] [P1] FINDING-L06 : (ANNULE — faux positif)

- **Statut :** ANNULE. La verification `verification_code_attempts = 0` est presente dans `resend_verification` (auth/routes.py:414).

---

## 8. AUTO-REVIEW DES FINDINGS CRITICAL ET HIGH (Pass 1 + Pass 2)

### Verification FINDING-C01 (Cle Stripe dans .env)

**Verification effectuee :** Lecture directe du fichier `/home/bouzelouf/secret_project/backend/.env`. La cle `sk_test_REDACTED...` est presente in extenso. **Verdict : CONFIRME — Confiance 10/10.**

### Verification FINDING-P2-N01 (create_demand boucle non bornee)

**Verification effectuee :** Lecture de `demands/routes.py:112-119`. La requete `select(MechanicProfile).where(is_active==True, is_identity_verified==True)` est confirmee sans `.limit()`. La boucle `for mechanic in mechanics:` avec `await create_notification(...)` a chaque iteration est confirmee. Le rate limit `10/minute` ne protege pas contre le caractere non borne de la boucle par requete. **Verdict : CONFIRME HIGH — Confiance 9/10.**

### Verification FINDING-H02 (accepted_vehicle_types LIKE)

**Verification effectuee :** Lecture de `mechanics/routes.py:82`. `cast(MechanicProfile.accepted_vehicle_types, String).contains(vehicle_type.value)` confirme. Absence d'index GIN sur la colonne `accepted_vehicle_types` verifiee dans les modeles. **Verdict : CONFIRME — Confiance 9/10.**

### Verification FINDING-H03 (catch-all Stripe)

**Verification effectuee :** Lecture de `payments/routes.py:493-511`. Le bloc `except Exception` capture toutes les exceptions. **Verdict : CONFIRME — Confiance 8/10.**

### Verification FINDING-H04 (body size limit)

**Verification effectuee :** Lecture complete de `main.py` — aucun middleware de limitation de taille globale. **Verdict : CONFIRME — Confiance 9/10.**

### Verification FINDING-H01 (Dockerfile COPY .)

**Verification effectuee :** Lecture de `.dockerignore` — confirme que `.env`, `.env.*`, `tests/`, `venv/`, `.coverage`, `seed.py` sont exclus. Le vecteur d'exposition de `.env` est attenue. **Verdict revise : CONFIRME MEDIUM — Confiance 9/10.**

### Correction FINDING-M06 (export non implemente)

**Verification effectuee :** Lecture de `auth/routes.py:1103-1247`. L'endpoint `GET /auth/me/export` est present, fonctionnel, avec sanitisation CSV et export multi-entites. **Verdict : FAUX POSITIF PASS 1 — L'endpoint est implemente. La vulnerabilite reelle est FINDING-P2-N06 (requetes non bornees).**

---

## 9. TABLEAU RECAPITULATIF

> Legende : [P1] = finding issu du Pass 1 | [P2] = finding issu du Pass 2
> FINDING-M06 marque comme ANNULE (faux positif remplace par P2-N06).

| ID              | Titre court                                                      | Severite  | Pass | Statut   | Confiance | Categorie          | Fichier                                    |
|-----------------|------------------------------------------------------------------|-----------|------|----------|-----------|--------------------|--------------------------------------------|
| FINDING-C01     | Cle Stripe + webhook placeholder dans .env                       | CRITICAL  | P1   | CONFIRME | 10/10     | Config/Secrets     | `backend/.env:6-8`                         |
| FINDING-P2-N01  | create_demand boucle O(N) sans LIMIT — DoS                       | HIGH      | P2   | CONFIRME | 9/10      | Perf/DoS           | `demands/routes.py:112-156`                |
| FINDING-H02     | accepted_vehicle_types LIKE sans index GIN                       | HIGH      | P1   | CONFIRME | 9/10      | Logic/Perf         | `mechanics/routes.py:82`                   |
| FINDING-H03     | Exception catch-all sur payment method retrieve                  | HIGH      | P1   | CONFIRME | 8/10      | Auth/Logic         | `payments/routes.py:493-511`               |
| FINDING-H04     | Absence de limite globale de taille de corps                     | HIGH      | P1   | CONFIRME | 9/10      | Config/DoS         | `main.py` (absence)                        |
| FINDING-P2-N02  | Email change sans invalidation des tokens JWT                    | MEDIUM    | P2   | CONFIRME | 9/10      | Auth/Session       | `auth/routes.py:584-601`                   |
| FINDING-P2-N03  | /uploads StaticFiles sans auth en mode dev                       | MEDIUM    | P2   | CONFIRME | 9/10      | Auth/Config        | `main.py:298-305`                          |
| FINDING-P2-N04  | accept_proposal PaymentIntent sans customer_id                   | MEDIUM    | P2   | CONFIRME | 9/10      | Logic/Paiement     | `proposals/routes.py:351-358`              |
| FINDING-P2-N05  | suspend_user ne cancelle pas les bookings actifs                 | MEDIUM    | P2   | CONFIRME | 9/10      | Logic/Business     | `admin/routes.py:257-277`                  |
| FINDING-P2-N06  | export_data requetes non bornees — DoS memoire                   | MEDIUM    | P2   | CONFIRME | 9/10      | Perf/DoS           | `auth/routes.py:1128-1231`                 |
| FINDING-H01     | Dockerfile sans multi-stage build (reclasse MEDIUM)              | MEDIUM    | P1   | CONFIRME | 9/10      | Config/Infra       | `backend/Dockerfile:17`                    |
| FINDING-M01     | Login sans verification is_verified                              | MEDIUM    | P1   | CONFIRME | 9/10      | Auth/Logic         | `auth/routes.py:424-467`                   |
| FINDING-M02     | Upload photo profil sans is_verified                             | MEDIUM    | P1   | CONFIRME | 9/10      | Auth/Upload        | `auth/routes.py:614-630`                   |
| FINDING-M03     | is_active verifie apres clear_login_attempts                     | MEDIUM    | P1   | CONFIRME | 10/10     | Auth/Logic         | `auth/routes.py:459-460`                   |
| FINDING-M04     | list_nearby_demands sans filtre geo SQL                          | MEDIUM    | P1   | CONFIRME | 9/10      | Perf               | `demands/routes.py:216-256`                |
| FINDING-M05     | Boucle parent_id sans protection cycle                           | MEDIUM    | P1   | CONFIRME | 8/10      | Logic              | `proposals/routes.py:203-220`              |
| FINDING-T01     | Absence de tests de regression M01/M02/M03                       | MEDIUM    | P1   | CONFIRME | 9/10      | Tests/Auth         | `tests/test_auth.py`                       |
| FINDING-T05     | generate_payment_receipt avec **dict non valide                  | MEDIUM    | P1   | CONFIRME | 8/10      | Injection/Logic    | `reports/generator.py:158`                 |
| FINDING-P2-N07  | CHECK_IN_HMAC_KEY sans validation production                     | LOW       | P2   | CONFIRME | 8/10      | Config/Crypto      | `config.py:59`                             |
| FINDING-P2-N08  | Admin ne peut pas acceder aux proposals                          | LOW       | P2   | CONFIRME | 7/10      | Auth/Logic         | `proposals/routes.py:599-624`              |
| FINDING-L01     | OTP code exclut les codes 0xxxxx                                 | LOW       | P1   | CONFIRME | 10/10     | Logic              | `email_service.py:37`                      |
| FINDING-L02     | Ping Redis bloquant sans log d'avertissement                     | LOW       | P1   | CONFIRME | 10/10     | Perf/Config        | `utils/rate_limit.py:33-44`                |
| FINDING-L03     | Tentatives malformees check-in non comptabilisees                | LOW       | P1   | CONFIRME | 9/10      | Logic              | `bookings/routes.py:914-923`               |
| FINDING-L04     | WeasyPrint sans base_url=None — SSRF second ordre                | LOW       | P1   | CONFIRME | 8/10      | Injection/Config   | `reports/generator.py:141`                 |
| FINDING-L05     | email sans max_length dans UserUpdateRequest                     | LOW       | P1   | CONFIRME | 7/10      | Data               | `schemas/auth.py:119-124`                  |
| FINDING-T02     | CI sans secret scanning (trufflehog/gitleaks)                    | LOW       | P1   | CONFIRME | 9/10      | CI/CD              | `.github/workflows/ci.yml`                 |
| FINDING-P2-N09  | export_data accessible sans is_verified                          | INFO      | P2   | CONFIRME | 7/10      | Auth/RGPD          | `auth/routes.py:1103-1107`                 |
| FINDING-I01     | Pagination in-memory list_mechanics                              | INFO      | P1   | CONFIRME | 9/10      | Perf               | `mechanics/routes.py:158-161`              |
| FINDING-I02     | _redis_client global par worker                                  | INFO      | P1   | CONFIRME | 7/10      | Config/Arch        | `auth/routes.py:86-110`                    |
| FINDING-I03     | Blacklisted tokens non nettoyes a reset-password                 | INFO      | P1   | CONFIRME | 8/10      | Auth               | `auth/routes.py:806-835`                   |
| FINDING-I04     | _RE_PHONE_GENERIC faux positifs                                  | INFO      | P1   | CONFIRME | 8/10      | Logic              | `utils/contact_mask.py:11`                 |
| FINDING-T03     | Deploy sans verification integrite image Docker                  | INFO      | P1   | CONFIRME | 7/10      | CI/CD              | `.github/workflows/ci.yml:91-105`          |
| FINDING-T04     | Tests HTTP sur SQLite non PostgreSQL                             | INFO      | P1   | CONFIRME | 8/10      | Tests              | `tests/conftest.py:25`                     |
| FINDING-M06     | (ANNULE — faux positif, remplace par P2-N06)                    | —         | P1   | ANNULE   | —         | —                  | —                                          |
| FINDING-L06     | (ANNULE — faux positif)                                          | —         | P1   | ANNULE   | —         | —                  | —                                          |

---

## 10. PLAN DE REMEDIATION PRIORISE

### Sprint 1 — IMMEDIAT (< 24h)

| Priorite | Finding        | Action                                                                                    | Effort |
|----------|----------------|-------------------------------------------------------------------------------------------|--------|
| P0       | C01            | **Revoquer la cle Stripe `sk_test_REDACTED...` dans le dashboard Stripe**               | 5 min  |
| P0       | C01            | Auditer l'historique git : `git log --all --full-history -- .env`                         | 30 min |
| P0       | C01            | Purger `.env` de l'historique git si commite (`git filter-repo`)                          | 1h     |
| P1       | C01            | Basculer vers des secrets injectes par l'environnement (Render env vars)                  | 2h     |

### Sprint 2 — COURT TERME (< 1 semaine)

| Priorite | Finding        | Action                                                                                    | Effort |
|----------|----------------|-------------------------------------------------------------------------------------------|--------|
| P1       | P2-N01         | Ajouter bounding box SQL + `.limit(MAX_NOTIFICATIONS)` dans `create_demand`               | 2h     |
| P1       | H04            | Ajouter `MaxBodySizeMiddleware` dans `main.py` (10 MB global)                             | 30 min |
| P1       | P2-N02         | Ajouter `user.password_changed_at = datetime.now(...)` dans `update_me` (email change)   | 15 min |
| P1       | T02            | Ajouter `gitleaks` ou `trufflehog` dans le CI                                             | 30 min |
| P2       | M03            | Deplacer `is_active` check avant `verify_password_async` dans `login`                    | 15 min |
| P2       | M01            | Ajouter verification `is_verified` dans l'endpoint `login`                               | 30 min |
| P2       | P2-N07         | Ajouter validator `CHECK_IN_HMAC_KEY` dans `config.py` (non-vide en production)          | 30 min |
| P2       | T01            | Ajouter tests de regression pour M01, M02, M03 dans `test_auth.py`                       | 2h     |

### Sprint 3 — MOYEN TERME (< 1 mois)

| Priorite | Finding        | Action                                                                                    | Effort |
|----------|----------------|-------------------------------------------------------------------------------------------|--------|
| P2       | P2-N03         | Remplacer `StaticFiles` par un endpoint authentifie pour les uploads locaux en dev        | 1h     |
| P2       | P2-N04         | Ajouter `get_or_create_customer()` + `customer_id` dans `accept_proposal`                | 1h     |
| P2       | P2-N05         | Annuler les bookings actifs lors de la suspension d'un mecanicien                         | 3h     |
| P2       | P2-N06         | Ajouter `.limit(1000)` sur les requetes de `export_data` + baisser le rate limit a 2/h   | 1h     |
| P2       | H02            | Migrer le filtre `accepted_vehicle_types` vers JSON `@>` + index GIN                     | 4h     |
| P2       | H03            | Differencer les exceptions Stripe dans `delete_payment_method`                            | 1h     |
| P2       | M02            | Exiger `is_verified` sur `POST /auth/me/photo`                                            | 15 min |
| P2       | T05            | Typer `booking_data` avec un schema Pydantic dans `generate_payment_receipt`              | 1h     |
| P3       | H01            | Reecrire le Dockerfile en multi-stage                                                     | 2h     |
| P3       | M04            | Ajouter bounding box SQL dans `list_nearby_demands`                                       | 2h     |
| P3       | M05            | Proteger la boucle `while parent_id` avec `visited_ids`                                   | 30 min |
| P3       | L01            | Corriger `generate_verification_code()` -> `f"{secrets.randbelow(1000000):06d}"`         | 5 min  |
| P3       | L03            | Comptabiliser les tentatives malformees dans `enter_code`                                 | 15 min |
| P3       | L02            | Ajouter log de warning si Redis indisponible au demarrage                                 | 15 min |
| P3       | L04            | Passer `base_url=None` a WeasyPrint + valider prefixe R2 sur les URLs photo              | 1h     |
| P3       | L05            | Ajouter `max_length=255` sur `email` dans `UserUpdateRequest`                             | 5 min  |
| P3       | P2-N08         | Ajouter gestion du role ADMIN dans `_get_proposal_for_user`                              | 15 min |

### Sprint 4 — LONG TERME (< 3 mois)

| Priorite | Finding        | Action                                                                                    | Effort |
|----------|----------------|-------------------------------------------------------------------------------------------|--------|
| P3       | T04            | Migrer les tests HTTP vers PostgreSQL (utiliser `DATABASE_URL` du CI)                    | 1 jour |
| P4       | I01            | Migrer vers PostGIS pour `list_mechanics` et `list_nearby_demands`                       | 3 jours|
| P4       | I04            | Affiner `_RE_PHONE_GENERIC` pour reduire les faux positifs                               | 1h     |
| P4       | T03            | Ajouter verification de signature d'image Docker avant deploiement                       | 1 jour |

---

## 11. POINTS FORTS SUPPLEMENTAIRES (Pass 2)

La relecture approfondie de Pass 2 a confirme plusieurs pratiques de securite avancees non mises en avant dans le Pass 1 :

- **Locks transactionnels corrects :** `with_for_update(nowait=True)` sur les slots de disponibilite dans `create_booking` (`bookings/routes.py:321`) — protection contre les double-bookings en race condition.
- **Transaction compensatrice Stripe :** Si la creation du booking echoue en base apres la creation du PaymentIntent, `cancel_payment_intent()` est appele pour eviter les PaymentIntents orphelins (`bookings/routes.py:392-397`).
- **Deduplication webhook Stripe** : L'insertion de `ProcessedWebhookEvent` est effectuee AVANT le traitement (`payments/routes.py:114`), avec une contrainte UNIQUE — garantie idempotente meme en cas de livraison multiple par Stripe.
- **Sanitisation CSV dans export RGPD :** `_sanitize_csv_cell()` prefixe les cellules commencant par `=`, `+`, `-`, `@` pour prevenir les injections de formules Excel/Google Sheets (`auth/routes.py:1118-1122`).
- **Scheduler distribue avec locks Redis :** Toutes les taches APScheduler utilisent `with client.lock(...)` pour eviter les executions paralleles sur plusieurs instances (`scheduler.py`).
- **Mode mock Stripe coherent :** Toutes les fonctions Stripe verifient `if not settings.STRIPE_SECRET_KEY` et retournent des donnees mock coherentes — pas de crash en developpement sans Stripe configure.
- **Validation CORS stricte en production :** `cors_origins_list` retourne `[]` si `CORS_ORIGINS` est vide, et le `CORSMiddleware` avec `allow_origins=[]` bloque par defaut toutes les origines inconnues.

---

*Rapport genere le 2026-03-01 par Claude Sonnet 4.6 — Audit COMBINE Pass 1 + Pass 2 complet.*
*Score global final : **6.8 / 10** (revision a la baisse de 7.3/10 apres identification de 9 nouveaux findings et correction d'un faux positif Pass 1).*
*Prochaine etape recommandee : Executer Sprint 1 (< 24h) puis Sprint 2 (< 1 semaine) pour adresser les risques CRITICAL et HIGH.*
