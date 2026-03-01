# AUDIT COMBINE — Pass 1 + Pass 2
## Rapport de Securite Applicative — eMecano

**Auditeur** : Senior Application Security Auditor (Claude Sonnet 4.6)
**Pass 1** : 2026-03-01
**Pass 2** : 2026-03-01
**Perimetre** : `/home/bouzelouf/secret_project/backend/` + `/home/bouzelouf/secret_project/mobile/`
**Version analysee** : branche `master`, commit `07c76cc`

---

## 1. Resume Executif Final

### Score global : 7.4 / 10

Le projet eMecano presente une architecture de securite solide et mature. Les mecanismes de defense en profondeur sont en place sur la grande majorite des surfaces d'attaque critiques : JWT robuste (blacklist JTI, rotation refresh, dummy hash anti-timing), protections BOLA/IDOR systematiques, idempotence Stripe, SELECT FOR UPDATE sur la concurrence des slots. Le second passage a revele trois nouveaux findings complementaires aux sept identifies en Pass 1, portant le total a 10 findings.

### Distribution des findings par severite (cumule)

| Severite | Pass 1 | Pass 2 | Total |
|----------|--------|--------|-------|
| CRITICAL | 0      | 0      | 0     |
| HIGH     | 2      | 1      | 3     |
| MEDIUM   | 3      | 2      | 5     |
| LOW      | 2      | 0      | 2     |
| **Total**| **7**  | **3**  | **10**|

### Top 3 risques (mis a jour)

1. **[HIGH-01][P1]** Enumeration non-authentifiee des disponibilites mecaniciens sans controle d'acces — collecte massive de plannings possible sans compte.
2. **[HIGH-02][P1]** `CHECK_IN_HMAC_KEY` tombe en fallback silencieux sur `JWT_SECRET` — separation des cles HMAC annulee si la variable n'est pas configuree en production.
3. **[HIGH-03][P2]** Login ne verifie pas `is_verified` — un utilisateur non-verifie obtient des tokens JWT valides et peut acceder aux endpoints proteger uniquement par `get_current_user` (messages, profil, liste des bookings).

---

## 2. Architecture Overview

### Flux d'authentification

```
Mobile App (Expo/React Native)
    |
    | HTTPS / Bearer JWT
    v
FastAPI (gunicorn + uvicorn workers)
    |
    |-- /auth/login  --> bcrypt verify --> access_token (15 min, jti) + refresh_token (7j, jti)
    |                    [ATTENTION: is_verified NON verifie ici -- voir HIGH-03]
    |-- /auth/refresh --> blacklist old jti --> new pair
    |-- /auth/logout  --> blacklist access_token jti + optionnel refresh_token jti
    |
    +-- get_current_user (Depends)
           |-- decode JWT (HS256, verify_iss, verify_exp)
           |-- type == "access" uniquement
           |-- jti present obligatoire
           |-- SELECT BlacklistedToken WHERE jti=?
           |-- SELECT User WHERE id=?
           |-- user.is_active == True
           |-- iat >= password_changed_at - 500ms

Tokens stockes mobile :
    - iOS/Android : expo-secure-store (chiffrement natif Keychain / Keystore)
    - Web         : sessionStorage (fallback non-securise, documente)
```

### Modele de roles

```
UserRole.BUYER     --> get_current_buyer   (role check)
                       get_verified_buyer  (role + is_verified)
UserRole.MECHANIC  --> get_current_mechanic (role + profil + suspended_until)
UserRole.ADMIN     --> get_current_admin   (role check)
```

### Flux de donnees sensibles

- **Tokens JWT** : Bearer header HTTPS uniquement, Cache-Control: no-store sur les reponses token
- **Mots de passe** : bcrypt rounds=12, async (asyncio.to_thread), dummy hash anti-timing
- **Codes OTP** : `secrets.randbelow` (CSPRNG), 6 chiffres, TTL 24h, stockes en clair (voir MED-02)
- **Code check-in** : HMAC-SHA256 avec cle separee, `secrets.compare_digest`
- **Documents PII** : pre-signed URLs 15 min, dossiers sensibles isoles (identity, cv, proofs)
- **GPS mechanic** : efface apres check-out et etats terminaux, arrondi a 3 decimales en lecture
- **GPS demandes** : masque a 2 decimales (~1.1 km) pour les mecaniciens sans interet actif

---

## 3. Points Forts (preuves fichier:ligne)

| # | Mecanisme | Evidence |
|---|-----------|----------|
| F1 | Dummy hash anti-timing-oracle sur login echec | `backend/app/auth/routes.py:70,442` |
| F2 | Blacklist JTI via UNIQUE constraint + IntegrityError | `backend/app/auth/routes.py:810-818`, `backend/app/dependencies.py:60-68` |
| F3 | Invalidation globale des sessions apres changement de mot de passe | `backend/app/dependencies.py:92-101` |
| F4 | Verrouillage de compte sur tentatives de login (Redis + in-memory fallback) | `backend/app/auth/routes.py:78-187` |
| F5 | SELECT FOR UPDATE avec nowait=True sur les slots de disponibilite | `backend/app/bookings/routes.py:144-153` |
| F6 | Rotation des refresh tokens avec blacklist | `backend/app/auth/routes.py:488-523` |
| F7 | Validation magic bytes sur les uploads (JPEG, PNG, PDF) | `backend/app/services/storage.py:32-38,114-118` |
| F8 | Whitelist de dossiers d'upload (path traversal impossible) | `backend/app/services/storage.py:22,82-83` |
| F9 | BOLA sur bookings : verifications owner systematiques | `backend/app/bookings/routes.py:500,634,888,957,1153,1225` |
| F10 | Masquage des coordonnees GPS pour les demandes (2 decimales ~1.1 km) | `backend/app/demands/routes.py:251-253` |
| F11 | Idempotence Stripe webhook via ProcessedWebhookEvent + IntegrityError | `backend/app/payments/routes.py:119-137` |
| F12 | Token de telechargement PDF a usage unique (JTI blacklist) | `backend/app/reports/routes.py:209-258` |
| F13 | Suppression des document_url dans la reponse publique mechanic | `backend/app/mechanics/routes.py:590-595` |
| F14 | Validation CORS stricte en production (liste explicite) | `backend/app/main.py:167-197` |
| F15 | Security headers (CSP, X-Frame-Options, HSTS prod) | `backend/app/middleware.py:13-22` |
| F16 | Suppression de la stack trace en production | `backend/app/main.py:152-162` |
| F17 | send_default_pii=False dans Sentry | `backend/app/main.py:57-61` |
| F18 | Expo SecureStore sur natif, fallback sessionStorage documente | `mobile/src/utils/storage.ts:1-44` |
| F19 | Interception Axios thread-safe (queue des requetes pendant refresh) | `mobile/src/services/api.ts:101-186` |
| F20 | Masquage email dans les logs (mask_email) | `backend/app/services/email_service.py:87,122` |
| F21 | Validation format Expo push token (regex strict) | `backend/app/schemas/auth.py:144-150` |
| F22 | Sanitisation CSV contre formula injection (admin export) | `backend/app/utils/csv_sanitize.py:1-12` |
| F23 | Contremesure injection HTML dans les emails de rappel | `backend/app/services/notifications.py:171-174` (`html.escape`) |
| F24 | Validation UUID stricte sur deep links notifications push | `mobile/src/services/pushNotifications.ts:24,34,38` |
| F25 | Lock distribue Redis pour les jobs du scheduler (anti double-execution) | `backend/app/services/scheduler.py:63-81` |
| F26 | Verification propriete payment_method avant detach (anti IDOR Stripe) | `backend/app/payments/routes.py:493-505` |
| F27 | BOLA sur notifications : filtre user_id sur mark-as-read | `backend/app/notifications/routes.py:62-66` |
| F28 | Transition d'etat booking validee par machine d'etat explicite | `backend/app/utils/booking_state.py:6-52` |
| F29 | Idempotence Stripe sur annulation/capture (cles idempotency_key) | `backend/app/services/stripe_service.py:168,198,344` |
| F30 | Anonymisation RGPD des bookings apres 3 ans (scheduler cron) | `backend/app/services/scheduler.py:878-915` |

---

## 4. Findings

---

### [HIGH-01][P1] — Enumeration non-authentifiee des disponibilites mecaniciens
**Statut** : CONFIRME
**OWASP API Security** : API5 — Broken Function Level Authorization
**CWE** : CWE-862 Missing Authorization

#### Description
L'endpoint `GET /mechanics/availabilities` est accessible sans authentification. Il accepte n'importe quel `mechanic_id` et retourne l'integralite des creneaux libres (non bookes) dans une plage de 90 jours. Un attaquant peut enumerer les emplois du temps de tous les mecaniciens sans aucun compte.

#### Data Flow
```
Source  : HTTP GET /mechanics/availabilities?mechanic_id=<uuid>&date_from=...&date_to=...
          sans header Authorization
Sink    : backend/app/mechanics/routes.py:479-511
          -> SELECT Availability WHERE mechanic_id = ? AND is_booked = FALSE
          -> retourne liste[AvailabilityResponse] (date, start_time, end_time)
```

#### Code verbatim
```python
# backend/app/mechanics/routes.py:479-511
@router.get("/availabilities", response_model=list[AvailabilityResponse])
@limiter.limit(LIST_RATE_LIMIT)
async def list_availabilities(
    request: Request,
    mechanic_id: uuid.UUID = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    # ABSENCE DE : user: User = Depends(get_current_user)
):
```

#### Scenario d'exploitation
1. L'attaquant recupere la liste des mechanic UUIDs via `GET /mechanics?lat=...&lng=...` (public).
2. Pour chaque UUID, il appelle `GET /mechanics/availabilities?mechanic_id=<uuid>&date_from=2026-01-01&date_to=2026-03-31`.
3. Il reconstruit le planning complet de tous les mecaniciens sans s'authentifier.

**Impact metier** : divulgation de donnees de planning concurrentiels, scraping de la base mecaniciens, social engineering.

#### Verification CoVe
1. Code source lu et copie : OUI (`routes.py` ligne 479, absence de `Depends(get_current_user)`)
2. Data flow complet : OUI (aucune dependance auth dans la signature)
3. Protection manquee : OUI, `GET /mechanics/availabilities` est le seul endpoint exposant 90 jours de planning sans auth
4. Pattern safe : NON
5. Actionable : OUI

#### Remediation
```python
# backend/app/mechanics/routes.py
@router.get("/availabilities", response_model=list[AvailabilityResponse])
@limiter.limit(LIST_RATE_LIMIT)
async def list_availabilities(
    request: Request,
    mechanic_id: uuid.UUID = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),  # AJOUTER
):
```

---

### [HIGH-02][P1] — Fallback silencieux CHECK_IN_HMAC_KEY vers JWT_SECRET
**Statut** : CONFIRME
**OWASP API Security** : API8 — Security Misconfiguration
**CWE** : CWE-321 Use of Hard-coded Cryptographic Key

#### Description
La fonction `hash_check_in_code` dans `code_generator.py` utilise `CHECK_IN_HMAC_KEY` si presente, sinon tombe en fallback sur `JWT_SECRET`. Si `CHECK_IN_HMAC_KEY` n'est pas defini en production (sa valeur par defaut est `""` dans `config.py`), le code check-in est HMAC-e avec la meme cle que les JWT. La separation des cles voulue est nulle en pratique.

#### Data Flow
```
Source  : settings.CHECK_IN_HMAC_KEY = "" (defaut dans config.py:59)
          si variable non definie en production

Transformation :
  backend/app/utils/code_generator.py:15
    key = settings.CHECK_IN_HMAC_KEY or settings.JWT_SECRET
    # Si CHECK_IN_HMAC_KEY == "" (falsy), cle = JWT_SECRET

Sink    : HMAC-SHA256 du code check-in signe avec la cle JWT
```

#### Code verbatim
```python
# backend/app/config.py:59
CHECK_IN_HMAC_KEY: str = ""   # valeur par defaut vide

# backend/app/utils/code_generator.py:13-16
def hash_check_in_code(code: str) -> str:
    """Hash a check-in code with HMAC-SHA-256 + dedicated secret key."""
    key = settings.CHECK_IN_HMAC_KEY or settings.JWT_SECRET
    return hmac.new(key.encode(), code.encode(), hashlib.sha256).hexdigest()
```

#### Scenario d'exploitation
Violation du principe de separation des cles : compromettre `JWT_SECRET` compromet aussi les codes check-in. Aucune validation de startup ne detecte cette misconfiguration.

#### Verification CoVe
1. Code source lu : OUI, `config.py:59` et `code_generator.py:15`
2. Data flow : OUI, `""` est falsy en Python
3. Protection manquee : aucune dans `validate_production_settings`
4. Pattern safe : NON
5. Actionable : OUI

#### Remediation
```python
# backend/app/config.py — dans validate_production_settings
if self.is_production and not self.CHECK_IN_HMAC_KEY:
    raise ValueError(
        "CHECK_IN_HMAC_KEY must be set in production for key separation."
    )

# backend/app/utils/code_generator.py — supprimer le fallback
def hash_check_in_code(code: str) -> str:
    key = settings.CHECK_IN_HMAC_KEY
    if not key:
        raise RuntimeError("CHECK_IN_HMAC_KEY is not configured")
    return hmac.new(key.encode(), code.encode(), hashlib.sha256).hexdigest()
```

---

### [HIGH-03][P2] — Login ne verifie pas is_verified — tokens JWT emis pour comptes non-confirmes
**Statut** : CONFIRME
**OWASP API Security** : API2 — Broken Authentication
**CWE** : CWE-306 Missing Authentication for Critical Function

#### Description
L'endpoint `POST /auth/login` ne verifie pas `user.is_verified` avant d'emettre une paire de tokens JWT. Un utilisateur qui s'est inscrit mais n'a pas encore confirme son email (ou qui a ete desinscrit apres un changement d'email qui remet `is_verified = False`) peut obtenir des tokens d'acces valides. Il peut alors appeler tous les endpoints protects uniquement par `get_current_user` (sans `get_verified_buyer`) : liste de bookings (`GET /bookings`), messages (`GET /bookings/{id}/messages`), notifications, profil, etc.

#### Data Flow
```
Source  : POST /auth/login { email, password }
          -> auth/routes.py:424-467

Verifications presentes :
  1. email existant + password bcrypt verify  OK
  2. user.is_active == True                   OK
  3. user.is_verified == True                 ABSENT

Tokens emis inconditionnellement :
  -> create_access_token(user_id)  <- JWT valide 15 min
  -> create_refresh_token(user_id) <- JWT valide 7j

Endpoints accessibles avec ces tokens SANS is_verified :
  - GET  /bookings                   (Depends(get_current_user))
  - GET  /bookings/{id}/messages     (Depends(get_current_user))
  - GET  /notifications              (Depends(get_current_user))
  - GET  /auth/me                    (Depends(get_current_user))
  - PATCH /auth/me                   (Depends(get_current_user))
  - GET  /proposals                  (Depends(get_current_user))
  - POST /bookings/{id}/messages     (Depends(get_current_user) -> MESSAGING)
```

#### Code verbatim
```python
# backend/app/auth/routes.py:424-467
@router.post("/login", response_model=TokenResponse)
@limiter.limit(AUTH_RATE_LIMIT)
async def login(request: Request, response: Response, body: LoginRequest,
                db: AsyncSession = Depends(get_db)):
    ...
    if not await verify_password_async(body.password, user.password_hash):
        await _record_login_attempt(body.email)
        raise HTTPException(status_code=401, detail="Invalid email or password")

    await _clear_login_attempts(body.email)

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account has been deactivated...")

    # ABSENT : if not user.is_verified: raise HTTPException(...)

    logger.info("user_login", user_id=str(user.id))
    return TokenResponse(
        access_token=create_access_token(user_id_str),   # emis sans is_verified
        refresh_token=create_refresh_token(user_id_str),
    )
```

#### Scenario d'exploitation
1. Attaquant enregistre un compte (email fictif ou adresse quelconque) sans confirmer.
2. Attaquant appelle `POST /auth/login` — obtient un access_token + refresh_token valides.
3. Avec l'access_token, l'attaquant accede a `GET /bookings`, `GET /notifications`, peut envoyer des messages dans un booking existant s'il a ete invite (cas edge), et lit son profil complet.
4. Les endpoints critiques (creation booking, check-in, validation paiement) sont proteges par `get_verified_buyer` et ne sont PAS accessibles.

**Impact** : Medium-High en scenario normal. La surface accessible sans verification est limitee (pas de transactions financieres). Mais cela casse le contrat de securite attendu (un utilisateur non-verifie ne devrait pas avoir de session active) et expose les endpoints de lecture a des comptes dont l'email n'a pas ete valide. Impact eleve dans le cas du changement d'email : apres `PATCH /auth/me` avec un nouvel email, `is_verified` repasse a `False` mais les tokens pre-existants permettent toujours d'appeler tous les endpoints `get_current_user`.

#### Verification CoVe
1. Code source lu et copie : OUI (`auth/routes.py:424-467`, aucun check `is_verified`)
2. Data flow complet : OUI — `create_access_token` est appele sans condition sur `is_verified`
3. Protection manquee : `get_verified_buyer` protege les transactions, mais pas les endpoints read-only
4. Pattern safe : NON — c'est une absence de controle deliberee non documentee
5. Actionable : OUI, une ligne de code corrige le probleme

#### Remediation
```python
# backend/app/auth/routes.py — dans la fonction login, apres le check is_active
if not user.is_verified:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Email verification required. Please verify your email before logging in.",
    )
```

**Note** : Verifier l'impact sur le flux de changement d'email (`PATCH /auth/me`) : apres le changement, `is_verified` est remis a `False` et un nouveau code est envoye. Les tokens existants restent valides jusqu'a leur expiration naturelle (15 min pour l'access). Ce comportement est acceptable si le check `is_verified` est ajoute au login (il empeche de generer de *nouveaux* tokens sans verification).

---

### [MED-01][P1] — Token de telechargement PDF non invalide apres changement de mot de passe
**Statut** : CONFIRME
**OWASP API Security** : API2 — Broken Authentication
**CWE** : CWE-613 Insufficient Session Expiration

#### Description
Le token `type=download` (TTL 5 min, usage unique par JTI) est verifie par `_verify_download_token` dans `reports/routes.py`. Ce verificateur ne passe pas par `get_current_user`, donc le controle `iat < password_changed_at` n'est pas applique. Un attaquant qui a obtenu un token de telechargement peut l'utiliser dans la fenetre de 5 minutes meme si la victime a change son mot de passe entre-temps.

#### Data Flow
```
Source  : token genere par _create_download_token (jti, type="download", TTL 5 min)
          -> token transmis dans URL ?token=...

Verifications dans download_receipt_with_token (reports/routes.py:197-261) :
  1. _verify_download_token -> type=="download", booking_id match, PyJWT exp  OK
  2. jti dans BlacklistedToken ?                                               OK
  3. booking.buyer_id == user_id                                               OK

Verification MANQUANTE :
  user.password_changed_at vs token iat   <- absent
```

#### Code verbatim
```python
# backend/app/reports/routes.py:59-75
def _verify_download_token(token: str, booking_id: str) -> dict | None:
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            issuer="emecano",
            options={"verify_iss": True},
        )
        if payload.get("type") != "download": return None
        if payload.get("booking_id") != booking_id: return None
        return payload
    except jwt.PyJWTError:
        return None
# ABSENT : controle iat < user.password_changed_at
```

#### Scenario d'exploitation
1. Attaquant obtient l'acces a la session de la victime.
2. Attaquant appelle `GET /reports/receipt/{booking_id}/token` -> download token (5 min).
3. Victime change son mot de passe (invalidation globale JWT).
4. Dans les 5 minutes, l'attaquant telecharge le PDF de recu (donnees vehicule, adresse, dates).

**Note** : Fenetre limitee a 5 minutes, token a usage unique — criticite MEDIUM.

#### Remediation
```python
# backend/app/reports/routes.py — dans download_receipt_with_token
user_result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
user_obj = user_result.scalar_one_or_none()
if user_obj and user_obj.password_changed_at:
    token_iat = token_payload.get("iat")
    if token_iat:
        issued_at = datetime.fromtimestamp(token_iat, tz=timezone.utc)
        if issued_at < user_obj.password_changed_at:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token invalidated by password change",
            )
```

---

### [MED-02][P1] — OTP de verification email stocke en clair en base de donnees
**Statut** : CONFIRME
**OWASP API Security** : API3 — Broken Object Property Level Authorization
**CWE** : CWE-312 Cleartext Storage of Sensitive Information

#### Description
Le code OTP de verification email (6 chiffres, TTL 24h) est stocke en texte clair dans `user.verification_code`. Si la base de donnees est compromise (backup, SQL injection sur un autre vecteur), tous les codes OTP en attente sont immediatement exploitables.

#### Data Flow
```
Source  : generate_verification_code() -> secrets.randbelow(900000) + 100000

Transformation :
  backend/app/auth/routes.py:268-270
    code = generate_verification_code()
    user.verification_code = code          # CLAIR en DB
    user.verification_code_expires_at = ...

Storage :
  Colonne users.verification_code : VARCHAR(6), valeur en clair

Verification (routes.py:320) :
    hmac.compare_digest(user.verification_code, body.code)
    # compare_digest correct mais compare les valeurs en clair
```

#### Scenario d'exploitation
Acces en lecture a la table `users` -> extraction de tous les `verification_code` non-null -> verification de comptes non encore verifies -> acces non autorise.

#### Remediation
```python
# backend/app/auth/routes.py — lors de la generation
import hmac as _hmac, hashlib

def _hash_otp(code: str) -> str:
    key = settings.CHECK_IN_HMAC_KEY or settings.JWT_SECRET
    return _hmac.new(key.encode(), code.encode(), hashlib.sha256).hexdigest()

# Stockage :
user.verification_code = _hash_otp(code)  # hash, pas le code en clair

# Verification :
if not _hmac.compare_digest(_hash_otp(body.code), user.verification_code):
    ...
```

---

### [MED-03][P1] — Mecanicien desactive acces aux demandes nearby
**Statut** : CONFIRME
**OWASP API Security** : API1 — BOLA (indirect)
**CWE** : CWE-200 Exposure of Sensitive Information to an Unauthorized Actor

#### Description
L'endpoint `GET /demands/nearby` est protege par `get_current_mechanic` qui verifie `suspended_until` mais ne verifie pas `is_active`. Un mechanic dont `is_active == False` (desactive manuellement par admin sans date de suspension) peut toujours voir les demandes environnantes.

#### Data Flow
```
Source  : GET /demands/nearby
          -> Depends(get_current_mechanic) : verifie suspended_until
             mais ne bloque pas si is_active == False

Sink    : backend/app/demands/routes.py:216-222
    result = await db.execute(
        select(BuyerDemand).where(
            BuyerDemand.status == DemandStatus.OPEN,
            BuyerDemand.expires_at > now,
            BuyerDemand.desired_date >= today,
        ).limit(200)
    )
```

#### Code verbatim
```python
# backend/app/dependencies.py:127-133
if profile.suspended_until and profile.suspended_until > datetime.now(timezone.utc):
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Account suspended. Contact support for more information.",
    )
# MANQUE : if not profile.is_active: raise HTTPException(...)
```

#### Remediation
```python
# backend/app/dependencies.py:116 (apres recuperation du profil)
if not profile.is_active:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Mechanic profile is not active.",
    )
```

---

### [MED-04][P2] — Endpoints proteges par get_current_user accessibles sans verification d'email
**Statut** : CONFIRME
**OWASP API Security** : API2 — Broken Authentication / API5 — Broken Function Level Authorization
**CWE** : CWE-287 Improper Authentication

#### Description
Ce finding est complementaire a HIGH-03. Independamment de la correction du login, plusieurs endpoints utilisent `get_current_user` sans `get_verified_buyer`, ce qui signifie que meme si le login etait corrige, les tokens emis avant un changement d'email (qui remet `is_verified = False`) restent valides pour ces endpoints jusqu'a leur expiration naturelle (15 min access / 7j refresh). Le systeme de messagerie est particulierement sensible : `POST /bookings/{id}/messages` utilise uniquement `get_current_user`, permettant theoriquement a un compte avec email change d'envoyer des messages.

#### Data Flow
```
Source  : PATCH /auth/me { email: "nouvelle@adresse.com" }
          -> auth/routes.py:596-600
             user.is_verified = False
             # token existant reste valide !

Sink    : POST /bookings/{id}/messages
          -> Depends(get_current_user)  # pas get_verified_buyer
          -> messages/routes.py:86-91

Impact :
  - Messages envoyes avec un compte a email non verifie (changed)
  - GET /bookings: liste bookings accessible
  - GET /notifications: notifications accessibles
  - TTL limitation : 15 min access_token, 7j refresh_token
```

#### Code verbatim
```python
# backend/app/messages/routes.py:80-91
@router.post(
    "/bookings/{booking_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def send_message(
    request: Request,
    booking_id: uuid.UUID,
    body: MessageCreate,
    user: User = Depends(get_current_user),  # PAS get_verified_buyer
    db: AsyncSession = Depends(get_db),
):
```

#### Scenario d'exploitation
1. Utilisateur authentifie change son email via `PATCH /auth/me`.
2. `is_verified` repasse a `False`.
3. Dans les 15 minutes suivantes (duree de vie du token), l'utilisateur peut encore envoyer des messages (non-transactionnels).
4. Avec le refresh_token (7 jours), il peut generer de nouveaux access_tokens — mais le refresh/login recheckera `is_active` seulement, pas `is_verified`.

**Note** : Impact operationnel limite (messagerie dans bookings existants uniquement). Criticite MEDIUM car la fenetre est courte pour l'access_token, mais le refresh_token de 7 jours maintient la possibilite de regenerer des tokens.

#### Remediation
La remediation principale est sur HIGH-03 (ajouter le check `is_verified` au login ET au refresh). En complement, ajouter le check `is_verified` dans `get_current_user` pour les endpoints sensibles, ou invalider les refresh tokens lors du changement d'email :

```python
# backend/app/auth/routes.py — dans update_me, apres email_changed = True
if email_changed:
    user.is_verified = False
    # Invalider les refresh tokens en incrementant password_changed_at
    # (reutilise le mecanisme existant de SEC-005)
    user.password_changed_at = datetime.now(timezone.utc)
    verification_token = create_email_verification_token(user.email)
    await send_verification_email(user.email, verification_token)
```

---

### [LOW-01][P1] — Tokens JWT dans les URL de telechargement (query parameter)
**Statut** : CONFIRME
**OWASP API Security** : API8 — Security Misconfiguration
**CWE** : CWE-598 Use of GET Request Method with Sensitive Query Strings

#### Description
L'endpoint `GET /reports/receipt/{booking_id}/download?token=...` place le token JWT dans un query parameter. Ce token peut apparaitre dans les logs du serveur reverse-proxy, l'historique du navigateur, ou les entetes `Referer`. La criticite est faible car le token expire en 5 minutes et est a usage unique.

#### Code verbatim
```python
# backend/app/reports/routes.py:189-196
@router.get("/receipt/{booking_id}/download")
async def download_receipt_with_token(
    request: Request,
    booking_id: uuid.UUID,
    token: str = Query(..., description="Short-lived download token"),
    db: AsyncSession = Depends(get_db),
):
```

#### Remediation
Utiliser un header HTTP custom (`X-Download-Token`) ou une requete POST. Alternativement, s'assurer que les logs proxy ne loguent pas les query strings des chemins `/reports/`.

---

### [LOW-02][P1] — console.error avec donnees d'erreur potentiellement sensibles en mode __DEV__
**Statut** : CONFIRME
**OWASP MASTG** : M9 — Insecure Data Storage
**CWE** : CWE-532 Insertion of Sensitive Information into Log File

#### Description
Plusieurs ecrans mobiles appellent `console.error` conditionne a `__DEV__`. En mode developpement, les messages d'erreur peuvent contenir des details de reponse API (tokens, body). Dans une build de production Expo, `__DEV__ == false` et ces appels sont supprimes, ce qui limite l'impact aux environnements de developpement.

#### Code verbatim
```typescript
// mobile/src/stores/authStore.ts:92
if (__DEV__) console.error("[AUTH] fetchUser error (attempt " + (attempt + 1) + "):", err);

// mobile/src/screens/auth/LoginScreen.tsx:62
if (__DEV__) console.error("Login error:", err);
```

#### Remediation
Remplacer `console.error` par un logger de production qui filtre les donnees sensibles, ou s'assurer que les objets `err` ne sont pas serialises en entier (utiliser `err.message` uniquement).

---

## 5. Auto-review des Findings HIGH

### Auto-review HIGH-01 [P1]

**Q1 — Code source exact copie ?**
OUI. `mechanics/routes.py:479` — la signature de `list_availabilities` ne contient aucun `Depends(get_current_user)`.

**Q2 — Data flow complet ?**
OUI. La route renvoie directement le resultset SQL sans aucun guard auth. Le limiter (`LIST_RATE_LIMIT`) existe mais n'est pas une protection d'authentification.

**Q3 — Protection manquee ailleurs ?**
Verifie : `GET /mechanics` (liste) et `GET /mechanics/{id}` sont publics intentionnellement. `GET /mechanics/availabilities` est le seul endpoint exposant 90 jours de planning qui devrait etre protege.

**Q4 — Dans la liste des exclusions/safe patterns ?**
NON.

**Q5 — Actionable ?**
OUI. Un seul parametre `Depends(get_current_user)` suffit.

**Conclusion** : Finding maintenu, severite HIGH confirmee.

---

### Auto-review HIGH-02 [P1]

**Q1 — Code source exact copie ?**
OUI. `config.py:59` : `CHECK_IN_HMAC_KEY: str = ""`. `code_generator.py:15` : `key = settings.CHECK_IN_HMAC_KEY or settings.JWT_SECRET`.

**Q2 — Data flow complet ?**
OUI. En Python, `"" or settings.JWT_SECRET` retourne `settings.JWT_SECRET`.

**Q3 — Protection manquee ?**
`validate_production_settings` (config.py:157-230) ne contient pas de verification sur `CHECK_IN_HMAC_KEY`. Verifie integralement.

**Q4 — Exclusions ?**
NON.

**Q5 — Actionable ?**
OUI.

**Conclusion** : Finding maintenu, severite HIGH confirmee.

---

### Auto-review HIGH-03 [P2]

**Q1 — Code source exact copie ?**
OUI. `auth/routes.py:424-467` — apres le check `is_active`, aucun check `is_verified` avant emission des tokens.

**Q2 — Data flow complet ?**
OUI. `create_access_token(user_id_str)` est appele sans condition sur `is_verified`. Verifie que `get_verified_buyer` protege les transactions financieres (creation booking, check-in, validation) mais PAS les endpoints `get_current_user`.

**Q3 — Protection manquee ailleurs ?**
Confirmation : `GET /bookings`, `GET/POST /bookings/{id}/messages`, `GET /notifications`, `GET /proposals`, `GET /auth/me`, `PATCH /auth/me` utilisent uniquement `get_current_user` — accessibles avec un token emis pour un compte non-verifie.

**Q4 — Dans la liste des exclusions/safe patterns ?**
NON — l'absence de verification `is_verified` au login est une faille de design.

**Q5 — Actionable ?**
OUI. Une seule ligne de code corrige le comportement principal.

**Conclusion** : Finding maintenu, severite HIGH confirmee (perimetre etendu par MED-04 qui documente l'impact sur le changement d'email).

---

## 6. Tableau Recapitulatif Complet

| ID | Pass | Titre | Severite | Statut | Composant | Ligne(s) |
|----|------|-------|----------|--------|-----------|---------|
| HIGH-01 | P1 | Enumeration non-authentifiee des disponibilites | HIGH | CONFIRME | `mechanics/routes.py` | 479 |
| HIGH-02 | P1 | Fallback CHECK_IN_HMAC_KEY -> JWT_SECRET | HIGH | CONFIRME | `config.py`, `code_generator.py` | 59 / 15 |
| HIGH-03 | P2 | Login sans verification is_verified | HIGH | CONFIRME | `auth/routes.py` | 424-467 |
| MED-01 | P1 | Token download PDF non invalide apres changement MDP | MEDIUM | CONFIRME | `reports/routes.py` | 197-261 |
| MED-02 | P1 | OTP email verification stocke en clair | MEDIUM | CONFIRME | `auth/routes.py` | 268-270 |
| MED-03 | P1 | Mecanicien desactive acces aux demandes nearby | MEDIUM | CONFIRME | `demands/routes.py`, `dependencies.py` | 201 / 127 |
| MED-04 | P2 | Tokens valides apres changement d'email (is_verified bypass) | MEDIUM | CONFIRME | `auth/routes.py`, `messages/routes.py` | 596 / 86 |
| LOW-01 | P1 | JWT de telechargement en query parameter | LOW | CONFIRME | `reports/routes.py` | 189 |
| LOW-02 | P1 | console.error avec objets erreur en DEV | LOW | CONFIRME | `mobile/src/stores/authStore.ts` | 92 |

**Total : 9 findings** (1 finding P2 fusionne avec HIGH-03 en MED-04 comme complement)

---

## 7. Plan de Remediation Priorise Final

### Priorite 1 — Immediat (avant prochaine release)

| Finding | Effort | Risque si non corrige |
|---------|--------|----------------------|
| **HIGH-01** — Ajouter `Depends(get_current_user)` sur `list_availabilities` | 15 min | Scraping massif des plannings mecaniciens |
| **HIGH-02** — Validation startup + suppression fallback HMAC | 30 min | Violation separation des cles en prod |
| **HIGH-03** — Ajouter check `is_verified` dans `login` | 5 min | Acces tokens pour comptes non-confirmes |

```python
# HIGH-03 : correction minimale dans auth/routes.py
if not user.is_active:
    raise HTTPException(status_code=403, detail="Account deactivated.")

# AJOUTER ICI :
if not user.is_verified:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Email verification required.",
    )
```

### Priorite 2 — Sprint suivant

| Finding | Effort | Impact |
|---------|--------|--------|
| **MED-01** — Verification `password_changed_at` dans `download_receipt_with_token` | 1h | Ferme la fenetre de 5 min apres changement MDP |
| **MED-02** — Stocker HMAC de l'OTP au lieu du texte clair | 2h | Protege les codes OTP en cas de dump DB |
| **MED-03** — Ajouter controle `is_active` dans `get_current_mechanic` | 30 min | Coherence du modele de suspension |
| **MED-04** — Invalider refresh tokens lors du changement d'email | 1h | Ferme la fenetre de 7j apres changement email |

### Priorite 3 — Hygiene (prochain cycle)

| Finding | Effort | Impact |
|---------|--------|--------|
| **LOW-01** — Migrer le token download vers un header HTTP | 2h | Elimine l'exposition en logs proxy |
| **LOW-02** — Logger structure avec filtrage des champs sensibles | 2h | Hygiene securite en dev/staging |

---

## 8. Annexe — Fichiers analyses (Pass 1 + Pass 2)

### Backend (hors .venv, hors tests)

**Pass 1 :**
- `app/auth/routes.py` (integralite, ~1050 lignes)
- `app/auth/service.py`
- `app/dependencies.py`
- `app/config.py`
- `app/main.py`
- `app/middleware.py`
- `app/admin/routes.py`
- `app/bookings/routes.py` (integralite, ~1570 lignes)
- `app/payments/routes.py`
- `app/mechanics/routes.py`
- `app/messages/routes.py`
- `app/demands/routes.py`
- `app/proposals/routes.py`
- `app/reviews/routes.py`
- `app/reports/routes.py`
- `app/services/email_service.py`
- `app/services/storage.py`
- `app/services/stripe_service.py`
- `app/utils/rate_limit.py`
- `app/utils/code_generator.py`

**Pass 2 (nouveaux fichiers) :**
- `app/notifications/routes.py`
- `app/referrals/routes.py`
- `app/services/notifications.py`
- `app/services/penalties.py`
- `app/services/pricing.py`
- `app/services/scheduler.py` (integralite, ~1070 lignes)
- `app/utils/booking_state.py`
- `app/utils/contact_mask.py`
- `app/utils/csv_sanitize.py`
- `app/utils/display_name.py`
- `app/utils/geo.py`
- `app/utils/log_mask.py`
- `app/models/user.py`
- `app/schemas/auth.py` (PushTokenRequest)

### Mobile

**Pass 1 :**
- `App.tsx`
- `src/stores/authStore.ts`
- `src/services/api.ts`
- `src/utils/storage.ts`
- `src/navigation/RootNavigator.tsx`
- `src/screens/auth/LoginScreen.tsx`

**Pass 2 (nouveaux fichiers) :**
- `src/config.ts`
- `src/services/analytics.ts`
- `src/services/pushNotifications.ts`
- `src/services/trackingConsent.ts`
- `src/utils/escapeHtml.ts`
- `src/utils/fileUtils.ts`
- `src/utils/formData.ts`
- `src/screens/buyer/CheckInScreen.tsx`
- `src/screens/buyer/PaymentMethodsScreen.tsx`
- `src/screens/auth/RegisterScreen.tsx`
- `app.config.ts`
