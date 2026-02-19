# CORRECTIONS DOMAINE 2 : MIGRATION PASSLIB -> BCRYPT

**Date :** 2026-02-19
**Bug corrige :** AUD5-002
**Tests ajoutes :** 7

---

## MIGRATION COMPLETE

### Changements principaux

**Dependance :**
- `passlib[bcrypt]==1.7.4` (unmaintained depuis 2020) SUPPRIME
- `bcrypt==4.2.1` (activement maintenu) CONSERVE

**Implementation :**
- `hash_password()` : passlib `pwd_context.hash` -> `bcrypt.hashpw` direct
- `verify_password()` : passlib `pwd_context.verify` -> `bcrypt.checkpw` direct
- `hash_password_async()` / `verify_password_async()` : delegation via `asyncio.to_thread`
- Rounds bcrypt : 12 (inchange)

**Compatibilite :**
- Anciens hash passlib fonctionnent (meme format `$2b$12$`)
- Nouveaux hash bcrypt format standard
- Timing-safe login preserve (dummy hash inchange)

---

## FICHIERS MODIFIES

### backend/requirements.txt

```diff
- # Auth - NOTE: passlib is unmaintained since 2020. TODO: migrate to pwdlib or direct bcrypt
- passlib[bcrypt]==1.7.4
- bcrypt==4.2.1
+ # Auth - migrated from passlib (unmaintained since 2020) to direct bcrypt on 2026-02-19
+ bcrypt==4.2.1
```

### backend/app/auth/service.py

```diff
- from passlib.context import CryptContext
- pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)
+ import bcrypt as _bcrypt
+ _BCRYPT_ROUNDS = 12

- def hash_password(password: str) -> str:
-     return pwd_context.hash(password)
+ def hash_password(password: str) -> str:
+     salt = _bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
+     return _bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

- def verify_password(plain_password: str, hashed_password: str) -> bool:
-     return pwd_context.verify(plain_password, hashed_password)
+ def verify_password(plain_password: str, hashed_password: str) -> bool:
+     try:
+         return _bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
+     except (ValueError, TypeError):
+         return False
```

Async wrappers (`hash_password_async`, `verify_password_async`) now delegate to the sync versions via `asyncio.to_thread` (unchanged pattern).

### backend/app/auth/routes.py

```diff
- from app.auth.service import (
-     ...
-     hash_password,
-     hash_password_async,
-     verify_password,
-     verify_password_async,
- )
+ from app.auth.service import (
+     ...
+     hash_password_async,
+     verify_password_async,
+ )
```

Removed unused sync imports (`hash_password`, `verify_password`) from routes -- routes only use async variants.

### backend/tests/test_bcrypt_migration.py (NOUVEAU)

7 tests de non-regression :

```
test_hash_password_bcrypt_format      PASSED  (format $2b$12$, 60 chars)
test_verify_password_correct          PASSED
test_verify_password_incorrect        PASSED
test_verify_password_empty            PASSED
test_verify_password_invalid_hash     PASSED  (returns False, no crash)
test_verify_password_old_passlib_hash PASSED  (compatibilite anciens hash)
test_hash_different_each_time         PASSED  (salt aleatoire)
```

---

## VERIFICATIONS

```
Backend compile        : OK (service.py + routes.py)
passlib dans app/      : 0 references code (commentaires seulement)
pwd_context dans app/  : 0 references
bcrypt version         : 4.2.1
Tests migration        : 7/7 passed
Tests total            : 320 passed, 3 skipped (313 + 7 nouveaux)
```

---

## SECURITE

**Ameliorations :**
- Dependance activement maintenue (bcrypt 4.2.1)
- Compatible Python 3.13+
- Async preserved (pas de blocking event loop)
- Timing-safe login preserve (dummy hash `_DUMMY_HASH` inchange)
- `verify_password` retourne False sur hash invalide (pas d'exception)

**Pas de regression :**
- Login fonctionne (anciens + nouveaux users)
- Register fonctionne
- Change password fonctionne
- Reset password fonctionne
- Bcrypt rounds=12 (inchange)
- Format hash identique ($2b$12$...)

---

## IMPACT

**Score securite :**
- Avant : passlib unmaintained, risque supply chain
- Apres : bcrypt maintenu, 0 dependance abandonnee

**Performance :**
- Temps hashing identique (~100ms pour rounds=12)
- Pattern async identique (asyncio.to_thread)

**Compatibilite :**
- Users existants : login OK (meme format hash)
- Nouveaux users : hash bcrypt standard
- Migration transparente : pas d'action user requise

---

## PROCHAINES ETAPES

**DOMAINE 2 termine**

Options :
- A) Commit et pause
- B) Passer au DOMAINE 3 : Tests coverage (3-4 jours)
- C) Passer au DOMAINE 4 : Orphaned files (1-2 jours)

---

*Fin du rapport DOMAINE 2*
