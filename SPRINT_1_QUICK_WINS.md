# SPRINT 1 : QUICK WINS - AUDIT FINAL

## Resultat Final
- **Tests** : 456 -> 457 (+1 net : +3 health tests, -2 dead code tests)
- **Couverture** : 85.02% -> **85.25%**
- **457 passed, 3 skipped, 0 failed**
- **Migration Alembic** : `028_add_rating_avg_check_constraint.py`

---

## FIX 1 : SENTRY_DSN dans render.yaml
**Statut** : DEJA PRESENT

`render.yaml` lignes 48-49 :
```yaml
- key: SENTRY_DSN
  sync: false
```

Aucune modification necessaire.

---

## FIX 2 : CORS_ORIGINS dans render.yaml
**Statut** : DEJA PRESENT

`render.yaml` lignes 40-41 :
```yaml
- key: CORS_ORIGINS
  value: "https://emecano.fr,https://api.emecano.fr"
```

Aucune modification necessaire.

---

## FIX 3 : Health check verifie le scheduler
**Statut** : APPLIQUE
**Fichier** : `app/main.py` (lignes 248-252, 257-262)

Ajout de la verification du scheduler dans `/health` :
```python
# AUDIT-FIX3: Verify scheduler is running
try:
    from app.services.scheduler import scheduler
    result["scheduler"] = "running" if scheduler.running else "stopped"
except Exception:
    result["scheduler"] = "unknown"
```

En mode production, le scheduler est inclus dans le calcul du statut global :
```python
sched_ok = result.get("scheduler") == "running"
overall = "ok" if (db_ok and redis_ok and sched_ok) else "unhealthy"
```

**Tests ajoutes** : `tests/test_health.py` (3 tests)
- `test_health_check_includes_scheduler_status` - scheduler running
- `test_health_check_scheduler_stopped` - scheduler stopped
- `test_health_check_db_connected` - database connected

---

## FIX 4 : check_pending_acceptances avec FOR UPDATE
**Statut** : APPLIQUE
**Fichier** : `app/services/scheduler.py` (ligne 178)

Ajout de `.with_for_update(skip_locked=True)` pour eviter les race conditions entre instances concurrentes du scheduler :
```python
.with_for_update(skip_locked=True)
.limit(SCHEDULER_BATCH_SIZE)
```

`skip_locked=True` permet aux autres instances de traiter les bookings non-verrouilees.

---

## FIX 5 : resolve_dispute avec FOR UPDATE
**Statut** : APPLIQUE
**Fichier** : `app/payments/routes.py` (lignes 282-284, 296-297)

Note : `resolve_dispute` est dans `payments/routes.py` (pas `admin/routes.py`).

Ajout de `.with_for_update()` sur les deux requetes SELECT :
```python
# DisputeCase
select(DisputeCase)
    .where(DisputeCase.id == body.dispute_id)
    .with_for_update()

# Booking
select(Booking)
    .where(Booking.id == dispute.booking_id)
    .options(selectinload(Booking.mechanic))
    .with_for_update()
```

---

## FIX 6 : delete_account bloque VALIDATED
**Statut** : APPLIQUE
**Fichier** : `app/auth/routes.py` (ligne 827)

Ajout de `BookingStatus.VALIDATED` dans la liste `active_statuses` pour empecher la suppression d'un compte qui a un paiement en attente de liberation :
```python
active_statuses = [
    BookingStatus.CONFIRMED,
    BookingStatus.AWAITING_MECHANIC_CODE,
    BookingStatus.CHECK_IN_DONE,
    BookingStatus.CHECK_OUT_DONE,
    BookingStatus.VALIDATED,  # AUDIT-FIX6
]
```

---

## FIX 7 : Supprimer get_verified_user (dead code)
**Statut** : APPLIQUE
**Fichiers** :
- `app/dependencies.py` : Fonction `get_verified_user` supprimee (lignes 99-108)
- `tests/test_dependencies.py` : 2 tests correspondants supprimes

La verification email est deja faite dans les routes qui en ont besoin. Cette fonction n'etait appelee nulle part dans le code de production (confirmee par grep).

---

## FIX 8 : Corriger commentaire trompeur change_password
**Statut** : APPLIQUE
**Fichier** : `app/auth/routes.py` (lignes 767-769)

Ancien commentaire (faux) :
```python
# NOTE: Only the current token is invalidated. Other active sessions (tokens)
# remain valid until their natural expiry (15 min). For a MVP this is acceptable.
```

Nouveau commentaire (correct) :
```python
# AUD-H08: Blacklist the current token. password_changed_at (set above)
# invalidates ALL older tokens at verification time, so every active
# session is effectively revoked — not just this one.
```

La logique `password_changed_at` dans `dependencies.py:get_current_user` invalide effectivement TOUS les tokens emis avant le changement de mot de passe.

---

## FIX 9 : autoescape=True sur Jinja2
**Statut** : DEJA PRESENT

`app/reports/generator.py` ligne 26 :
```python
_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
```

Aucune modification necessaire.

---

## FIX 10 : CHECK constraint rating_avg BETWEEN 0 AND 5
**Statut** : APPLIQUE
**Fichier** : `alembic/versions/028_add_rating_avg_check_constraint.py`

```python
op.create_check_constraint(
    "ck_mechanic_profiles_rating_avg_range",
    "mechanic_profiles",
    "rating_avg >= 0 AND rating_avg <= 5",
)
```

---

## Resume

| FIX | Description | Statut | Fichier(s) |
|-----|-------------|--------|------------|
| 1 | SENTRY_DSN render.yaml | DEJA PRESENT | render.yaml |
| 2 | CORS_ORIGINS render.yaml | DEJA PRESENT | render.yaml |
| 3 | Health check scheduler | APPLIQUE | main.py + test_health.py |
| 4 | FOR UPDATE check_pending | APPLIQUE | scheduler.py |
| 5 | FOR UPDATE resolve_dispute | APPLIQUE | payments/routes.py |
| 6 | delete_account + VALIDATED | APPLIQUE | auth/routes.py |
| 7 | Supprimer get_verified_user | APPLIQUE | dependencies.py + test_dependencies.py |
| 8 | Corriger commentaire | APPLIQUE | auth/routes.py |
| 9 | autoescape Jinja2 | DEJA PRESENT | generator.py |
| 10 | CHECK rating_avg | APPLIQUE | migration 028 |

**7 fixes appliques, 3 deja presents dans le code.**

## Verification
```bash
# Depuis backend/
pytest --cov=app --cov-report=term-missing --tb=short -q
# TOTAL 4081 602 85%
# Required test coverage of 85.0% reached. Total coverage: 85.25%
# 457 passed, 3 skipped
```
