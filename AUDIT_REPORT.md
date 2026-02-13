# Audit de Publication - eMecano

**Date :** 13 février 2026
**Version :** Post-corrections de production readiness
**Stack :** FastAPI + SQLAlchemy + PostgreSQL + Stripe Connect + Redis (Backend) | React Native / Expo SDK 54 + TypeScript (Frontend)

---

## Résumé Exécutif

L'application a fait des progrès significatifs vers la production. La majorité des fonctionnalités critiques sont implémentées : authentification complète (inscription, connexion, réinitialisation mot de passe, changement mot de passe), conformité RGPD (suppression compte Art.17, export données Art.20), vérification email, notifications push, gestion des réservations, paiement Stripe Connect, système d'avis, messagerie, admin API, etc.

**Score global : ~85% prêt pour la publication**

Cependant, **7 BLOCKERS** et plusieurs points HIGH empêchent la mise en production.

---

## BLOCKERS (Publication impossible sans correction)

### BLOCKER-1 : Intégration Stripe désactivée côté mobile
- **Fichier :** `mobile/src/screens/buyer/BookingConfirmScreen.tsx`
- **Problème :** L'import Stripe est commenté (`// import { useStripe } from "@stripe/stripe-react-native"; // TODO: re-enable with dev build`). Les réservations sont créées **sans paiement réel**.
- **Impact :** Les utilisateurs peuvent réserver sans payer — faille business critique.
- **Correction :** Réactiver `@stripe/stripe-react-native`, implémenter le flow de paiement (PaymentSheet / confirmPayment) avant confirmation de réservation. Nécessite un dev build EAS (pas Expo Go).

### BLOCKER-2 : Clés de production manquantes (EAS / Apple / Google)
- **Fichiers :** `mobile/app.config.ts`, `mobile/eas.json`
- **Problème :**
  - Stripe publishable key : `"pk_test_REPLACE_ME"` (placeholder)
  - EAS Project ID : `"REPLACE_WITH_EAS_PROJECT_ID"`
  - Apple credentials : `appleId`, `ascAppId`, `appleTeamId` = `"REPLACE_ME"`
  - Google Play : `google-services.json` manquant
- **Correction :** Configurer toutes les clés via variables d'environnement EAS et fichiers de credentials.

### BLOCKER-3 : Icônes et splash screen par défaut Expo
- **Dossier :** `mobile/assets/`
- **Problème :** Les fichiers d'icônes ont des timestamps placeholder (Oct 26, 1985), probablement les icônes par défaut Expo.
- **Impact :** Rejet immédiat par Apple et Google Play.
- **Correction :** Remplacer par les vrais assets de marque eMecano (icon 1024x1024, adaptive-icon, splash).

### BLOCKER-4 : Dockerfile sans HEALTHCHECK
- **Fichier :** `backend/Dockerfile`
- **Problème :** Pas d'instruction HEALTHCHECK. Les orchestrateurs (K8s, ECS, Docker Swarm) ne peuvent pas détecter un container mort.
- **Impact :** Le load balancer enverra du trafic à des containers crashés.
- **Correction :**
```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health', timeout=3.0)" || exit 1
```

### BLOCKER-5 : Uvicorn en mode single-worker
- **Fichier :** `backend/Dockerfile`
- **Problème :** Un seul process `uvicorn` = 1 seul CPU utilisé, aucune redondance, pas de graceful restart.
- **Impact :** Ne peut pas gérer le trafic de production.
- **Correction :** Passer à Gunicorn + Uvicorn workers :
```dockerfile
CMD ["gunicorn", "app.main:app", "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "120", "--graceful-timeout", "30", "--max-requests", "1000", "--max-requests-jitter", "100"]
```

### BLOCKER-6 : Aucune stratégie de backup base de données
- **Fichier :** `docker-compose.yml`
- **Problème :** Aucun backup automatisé, aucun pg_dump, aucune politique de rétention, aucune procédure de disaster recovery.
- **Impact :** Perte de données irréversible en cas de panne. RGPD Art.32 exige la résilience des données.
- **Correction :** Ajouter un script `backup.sh` avec pg_dump quotidien + rétention 30 jours, ou utiliser une base managée (AWS RDS, Google Cloud SQL) avec backups automatiques.

### BLOCKER-7 : Société non encore immatriculée
- **Fichiers :** `mobile/src/screens/shared/LegalScreen.tsx`
- **Problème :** SIRET mentionné comme "en cours d'obtention". Les CGU/CGV référencent une entité légale inexistante.
- **Impact :** Publication impossible sur les stores sans entité légale valide (Apple et Google exigent un compte développeur rattaché à une entité). Pas de contrat valide avec les utilisateurs.
- **Correction :** Obtenir l'immatriculation SIRET, mettre à jour les mentions légales.

---

## HIGH (À corriger avant le lancement)

### HIGH-1 : iOS Privacy Manifest manquant
- **Impact :** Requis par Apple depuis iOS 17 (printemps 2024). Sans `PrivacyInfo.xcprivacy`, l'app sera rejetée.
- **Correction :** Créer le fichier déclarant NSPrivacyAccessedAPITypes, NSPrivacyTracking, NSPrivacyTrackingDomains (PostHog, Sentry).

### HIGH-2 : App Tracking Transparency (ATT) manquant
- **Fichier :** `mobile/app.json`
- **Impact :** Requis par Apple si PostHog ou Sentry collectent des données.
- **Correction :** Ajouter `NSUserTrackingUsageDescription` dans infoPlist.

### HIGH-3 : Commentaire TODO trompeur dans main.py
- **Fichier :** `backend/app/main.py` (lignes 1-3)
- **Problème :** Le commentaire dit "il n'y a pas d'admin API" alors qu'elle existe (`backend/app/admin/routes.py` avec stats, users, mechanics, bookings, disputes, revenue).
- **Correction :** Supprimer les lignes 1-3 du fichier.

### HIGH-4 : Validation CORS_ORIGINS en production manquante
- **Fichier :** `backend/app/config.py`
- **Problème :** Si `CORS_ORIGINS=""` en production, `cors_origins_list` retourne `[]` → toutes les requêtes cross-origin échouent.
- **Correction :** Ajouter validation dans `validate_production_settings`.

### HIGH-5 : Validation R2/S3 en production manquante
- **Fichier :** `backend/app/config.py`
- **Problème :** Si les credentials R2 ne sont pas configurés, les uploads (photos d'inspection, documents, PDF) crasheront silencieusement.
- **Correction :** Valider la présence de R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_PUBLIC_URL en production.

### HIGH-6 : APScheduler non compatible multi-worker
- **Fichier :** `backend/app/services/scheduler.py`
- **Problème :** `AsyncIOScheduler` avec job store en mémoire → chaque worker Gunicorn lance son propre scheduler = jobs dupliqués, emails en double, race conditions.
- **Correction :** Extraire le scheduler dans un container dédié ou utiliser Celery + Redis.

### HIGH-7 : alembic.ini avec placeholder DATABASE_URL
- **Fichier :** `backend/alembic.ini:4`
- **Problème :** `sqlalchemy.url = driver://user:pass@localhost/dbname` — `alembic upgrade head` échouera.
- **Correction :** Configurer la vraie URL ou modifier `alembic/env.py` pour lire depuis les settings.

### HIGH-8 : SSL Certificate Pinning non implémenté
- **Fichier :** `mobile/src/services/api.ts`
- **Problème :** TODO indique que le certificate pinning n'est pas configuré.
- **Impact :** Vulnérable aux attaques MITM.
- **Correction :** Implémenter avec `react-native-ssl-pinning` ou TrustKit pour les builds de production.

---

## MEDIUM (À corriger dans le premier mois)

### MEDIUM-1 : .env.example avec JWT_SECRET faible
- **Fichier :** `backend/.env.example:8`
- **Problème :** `JWT_SECRET=change-this-to-a-long-random-string-in-production` est dans la liste `KNOWN_WEAK_SECRETS`.
- **Correction :** Remplacer par `JWT_SECRET=REPLACE_WITH_OUTPUT_OF_openssl_rand_base64_32`.

### MEDIUM-2 : Localhost hardcodé dans l'API mobile
- **Fichier :** `mobile/src/services/api.ts`
- **Problème :** Plusieurs fallbacks `http://localhost:8001`. En production, si les variables d'environnement ne sont pas définies, l'app se connectera à localhost.
- **Correction :** Ajouter une vérification runtime ou lever une erreur si API_BASE_URL n'est pas configuré en production.

### MEDIUM-3 : Rate limit headers manquants
- **Problème :** Les rate limits sont appliqués mais pas visibles aux consommateurs API (pas de `X-RateLimit-Remaining`, `Retry-After`).
- **Correction :** Configurer SlowAPI pour inclure les headers.

### MEDIUM-4 : Adresse email expéditeur hardcodée
- **Fichiers :** `backend/app/services/email_service.py`, `backend/app/services/notifications.py`
- **Problème :** `"eMecano <noreply@emecano.fr>"` hardcodé.
- **Correction :** Déplacer dans `config.py` : `EMAIL_FROM: str`.

### MEDIUM-5 : Pas de monitoring du pool de connexions DB
- **Fichier :** `backend/app/database.py`
- **Problème :** Pool configuré (`pool_size=10, max_overflow=20`) mais pas de monitoring.
- **Correction :** Ajouter des event listeners SQLAlchemy ou des métriques Prometheus.

### MEDIUM-6 : Documentation environnement manquante (mobile)
- **Problème :** Pas de `.env.example` ni de README documentant les variables requises pour le mobile.
- **Correction :** Documenter `API_BASE_URL`, `STRIPE_PUBLISHABLE_KEY`, `SENTRY_DSN`, `POSTHOG_API_KEY`, `EAS_PROJECT_ID`.

---

## LOW (Nice to have)

| # | Issue | Détail |
|---|-------|--------|
| LOW-1 | Pas de endpoint `/metrics` | Prometheus/monitoring non disponible |
| LOW-2 | Pas de versioning API | `/bookings` au lieu de `/v1/bookings` |
| LOW-3 | Pas de documentation de rollback migration | `alembic downgrade -1` non documenté |
| LOW-4 | console.warn en prod (web) | `storage.ts:23` — warning non gardé par `__DEV__` (mais gardé en réalité, LOW) |
| LOW-5 | Build version management | Synchroniser versions entre `app.json` et `package.json` |

---

## Ce qui est DÉJÀ PRÊT ✅

### Backend
- [x] Authentification complète (inscription, connexion, vérification email, logout)
- [x] Réinitialisation mot de passe (forgot-password + reset-password)
- [x] Changement mot de passe (change-password avec validation complexité)
- [x] RGPD : Suppression de compte (Art.17) avec anonymisation
- [x] RGPD : Export des données personnelles (Art.20)
- [x] Token blacklisting (logout sécurisé)
- [x] Vérification email via Resend API
- [x] Headers de sécurité (HSTS, X-Frame-Options, CSP)
- [x] Rate limiting (SlowAPI) sur tous les endpoints sensibles
- [x] Logging structuré (structlog en JSON)
- [x] Sentry intégré
- [x] Middleware Request ID (X-Request-ID)
- [x] Admin API complète (stats, users, mechanics, bookings, disputes, revenue)
- [x] Stripe Connect marketplace (capture manuelle, commission 20%)
- [x] Webhook Stripe idempotent (account.updated)
- [x] Pool de connexions DB configuré (pool_size=10, max_overflow=20)
- [x] Validation JWT secret (32+ chars, rejet des secrets faibles)
- [x] Jobs de nettoyage (notifications, push tokens)
- [x] Tests : 297 passent, 3 skipped, 1 échec pré-existant (test_messages)

### Frontend
- [x] Écran de réinitialisation mot de passe (ForgotPasswordScreen)
- [x] Écran de changement mot de passe (ChangePasswordScreen)
- [x] Suppression de compte dans les deux profils (buyer + mechanic)
- [x] CGU/CGV avec contenu réel en français
- [x] Case à cocher CGU à l'inscription
- [x] Accents français corrigés partout
- [x] Notifications push avec navigation au tap
- [x] Bannière de connectivité réseau (NetworkBanner)
- [x] Consentement RGPD avant initialisation PostHog
- [x] Error boundaries et optimisations React.memo
- [x] Permissions iOS correctement déclarées (localisation, caméra, photos)
- [x] Permissions Android correctement déclarées
- [x] Sentry configuré (natif uniquement, web-safe)
- [x] PostHog analytics avec consentement
- [x] Écrans légaux (CGU, Confidentialité, Mentions légales)
- [x] TypeScript compilé sans erreur
- [x] UI/UX professionnelle et cohérente

---

## Checklist de Déploiement

Avant la mise en production :

1. [ ] Corriger les 7 BLOCKERS
2. [ ] Corriger les 8 HIGH
3. [ ] Configurer les variables d'environnement de production :
   - `JWT_SECRET` (32+ chars, aléatoire — `openssl rand -base64 32`)
   - `STRIPE_SECRET_KEY` et `STRIPE_WEBHOOK_SECRET`
   - `STRIPE_PUBLISHABLE_KEY` (côté mobile)
   - `R2_*` credentials stockage
   - `RESEND_API_KEY`
   - `SENTRY_DSN` (backend + mobile)
   - `POSTHOG_API_KEY`
   - `CORS_ORIGINS` (URLs frontend production)
   - `APP_ENV=production`
4. [ ] Configurer les credentials EAS (Apple + Google Play)
5. [ ] Remplacer les assets (icônes, splash screen) par la marque eMecano
6. [ ] Créer le Privacy Manifest iOS (`PrivacyInfo.xcprivacy`)
7. [ ] Lancer les migrations : `alembic upgrade head`
8. [ ] Créer un utilisateur admin : `python scripts/create_admin.py admin@emecano.fr <password>`
9. [ ] Tester le flow Stripe Connect end-to-end
10. [ ] Préparer les métadonnées App Store (captures d'écran, descriptions, catégorie)
11. [ ] Préparer la fiche Google Play (descriptions, captures, politique de confidentialité URL)
12. [ ] Load test avec trafic réaliste (100+ réservations simultanées)
13. [ ] Configurer le monitoring (Sentry erreurs + métriques)
14. [ ] Documenter le runbook d'incidents (restore DB, rollback deploy, etc.)

---

## Estimation

| Catégorie | Nombre | Effort estimé |
|-----------|--------|---------------|
| BLOCKERS | 7 | 3-5 jours |
| HIGH | 8 | 2-3 jours |
| MEDIUM | 6 | 1-2 jours |
| LOW | 5 | < 1 jour |
| **Total** | **26** | **~7-10 jours** |

> **Note :** Le BLOCKER-7 (immatriculation société) est un prérequis administratif qui ne dépend pas du développement. Le BLOCKER-1 (intégration Stripe) est le plus critique côté code — sans paiement, l'app n'a pas de modèle économique.
