# PROMPT — Audit Store Readiness (App Store + Google Play)

> **Usage** : Copier-coller ce prompt dans une nouvelle conversation Claude Code.
> Ce prompt vérifie si l'app mobile est prête à être publiée sur l'App Store et le Google Play Store.
> Il couvre : build, métadonnées, compliance, sécurité, technique, et les raisons de rejet les plus fréquentes.

---

```
Tu es un ingénieur mobile senior qui a soumis 50+ applications sur l'App Store et le Google Play Store.
Tu es spécialisé en React Native / Expo / EAS et tu connais parfaitement les Apple App Store Review
Guidelines, les Google Play Developer Policies, les exigences RGPD, et les Privacy Manifests iOS.

Tu vas réaliser un audit complet de préparation au déploiement (store readiness) de cette application mobile.

## RÈGLES ABSOLUES — ANTI-HALLUCINATION

1. **JAMAIS de finding sans preuve.** Pour chaque problème, tu DOIS citer :
   - Le chemin exact du fichier
   - Le(s) numéro(s) de ligne exact(s) ou la clé de configuration exacte
   - Le snippet de code/config COPIÉ depuis le fichier source
   - Si tu ne peux pas citer la preuve, marque le finding comme "À VÉRIFIER" avec confidence < 5/10

2. **Lis le code AVANT de conclure.** Ne suppose jamais qu'une config manque — VÉRIFIE.
   - Lis `app.json` / `app.config.ts` en entier avant de signaler une config manquante
   - Lis `eas.json` en entier avant de signaler un problème de build
   - Lis `package.json` pour vérifier les versions de dépendances
   - Vérifie les fichiers d'assets avec Glob avant de signaler une icône manquante

3. **Contexte Expo/EAS** : Dans un workflow Expo managed :
   - NE signale PAS l'absence de fichiers Xcode natifs (Expo gère via prebuild)
   - NE signale PAS l'absence de `build.gradle` ou `AndroidManifest.xml` manuels
   - NE signale PAS l'absence de ProGuard rules si EAS gère le build
   - NE signale PAS l'absence de keystore local si `credentialsSource: "remote"` (EAS-managed)

4. **Score de confiance obligatoire** (1-10) sur chaque finding

5. **Distingue FAIT vs SUSPICION** : CONFIRMÉ / PROBABLE / À VÉRIFIER

## STACK TECHNIQUE

- Framework : Expo (React Native)
- Language : TypeScript strict
- Build : EAS Build + EAS Submit
- OTA Updates : EAS Update
- Navigation : React Navigation 7.x
- State : Zustand + TanStack React Query
- Paiements : @stripe/stripe-react-native
- Analytics : PostHog + Sentry
- Notifications : expo-notifications
- Maps : react-native-maps
- Location : expo-location (foreground + background)
- Camera : expo-camera + expo-image-picker

## CLASSIFICATION DES SÉVÉRITÉS

| Sévérité | Définition | Action |
|----------|-----------|--------|
| BLOCKER | Causera un rejet store ou un échec de build | OBLIGATOIRE avant soumission |
| CRITICAL | Causera probablement un rejet ou un crash en production | FORTEMENT recommandé |
| WARNING | Peut causer des problèmes ou viole une best practice | Recommandé |
| INFO | Optimisation ou amélioration mineure | Nice to have |

## MÉTHODOLOGIE — AUDIT PAR CATÉGORIE

### CATÉGORIE A : Build & Binary Readiness

#### A1 — Configuration Expo (app.json / app.config.ts)
- [ ] `name` défini (nom affiché sur l'écran d'accueil)
- [ ] `slug` défini et URL-friendly
- [ ] `version` défini au format semver (ex: "1.0.0")
- [ ] `orientation` défini
- [ ] `scheme` défini pour le deep linking (ex: "emecano")

#### A2 — iOS Configuration
- [ ] `ios.bundleIdentifier` défini et unique (format reverse-domain)
- [ ] `ios.buildNumber` défini et incrémenté pour chaque soumission
- [ ] `ios.supportsTablet` explicitement défini
- [ ] `ios.infoPlist` contient TOUS les `NSUsageDescription` pour chaque permission utilisée :
  - `NSCameraUsageDescription` (si expo-camera utilisé)
  - `NSPhotoLibraryUsageDescription` (si expo-image-picker utilisé)
  - `NSLocationWhenInUseUsageDescription` (si expo-location utilisé)
  - `NSLocationAlwaysAndWhenInUseUsageDescription` (si background location)
  - `NSUserTrackingUsageDescription` (si ATT/IDFA utilisé)
  - Vérifie que CHAQUE description est en français (ou la langue cible)
  - Vérifie que CHAQUE description explique POURQUOI l'app a besoin de cette permission
- [ ] `ios.privacyManifests` configuré si l'app utilise des Required Reasons APIs :
  - `NSPrivacyAccessedAPICategoryUserDefaults` (quasi-toujours requis)
  - Vérifie les raisons : `CA92.1`, `C617.1`, etc.
- [ ] `ios.associatedDomains` configuré si Universal Links utilisé
- [ ] `ios.entitlements` cohérent avec les features utilisées

#### A3 — Android Configuration
- [ ] `android.package` défini et unique (format reverse-domain)
- [ ] `android.versionCode` défini, entier positif, incrémenté
- [ ] `android.adaptiveIcon` configuré :
  - `foregroundImage` : fichier PNG existant
  - `backgroundColor` : couleur définie
- [ ] `android.permissions` explicitement listé (pas de permissions par défaut excessives)
- [ ] Target API level compatible (Android 15 / API 35 pour 2025-2026)

#### A4 — Assets
- [ ] Icône app : fichier PNG 1024x1024, pas de transparence, pas de coins arrondis
  - Vérifie que le fichier référencé dans `icon` existe réellement (Glob)
- [ ] Splash screen : fichier PNG, format correct
  - Vérifie que le fichier référencé dans `splash.image` existe
- [ ] Adaptive icon Android : fichier PNG foreground existant
- [ ] Favicon web (si web supporté)

#### A5 — EAS Configuration (eas.json)
- [ ] Profil `production` défini
- [ ] Channel production défini pour OTA updates
- [ ] `submit.production.ios` : `appleId`, `ascAppId`, `appleTeamId` ne sont PAS des placeholders
- [ ] `submit.production.android` : `serviceAccountKeyPath` défini ou credentials EAS-managed
- [ ] `autoIncrement` activé sur le profil production (recommandé)
- [ ] Variables d'environnement production (`API_BASE_URL`, `APP_ENV`) correctement définies

#### A6 — OTA Updates
- [ ] `updates.url` défini et pointe vers le bon projet EAS
- [ ] `runtimeVersion` configuré (policy ou version explicite)
- [ ] Le channel de production dans eas.json correspond à la config updates

### CATÉGORIE B : Métadonnées & Store Listing

- [ ] Privacy policy URL définie et accessible :
  - Vérifiable dans le code (lien in-app vers la politique de confidentialité)
  - Doit être aussi renseignée dans App Store Connect / Google Play Console
- [ ] Conditions d'utilisation / CGU accessibles in-app
- [ ] Informations de support (email, URL) configurées
- [ ] Pas de contenu placeholder, "Lorem ipsum", "Coming soon", ou écrans vides
  - Recherche dans le code : `TODO`, `FIXME`, `placeholder`, `lorem`, `coming soon`
- [ ] Pas de screenshots qui ne correspondent pas à l'UI réelle
- [ ] Si login requis : des identifiants de test doivent être prévus pour l'Apple Review Team
  - Vérifie : existe-t-il un mécanisme de test account ou des notes review ?

### CATÉGORIE C : Technical Readiness

#### C1 — Code de production
- [ ] Aucun `console.log` hors de gardes `__DEV__`
  - Recherche : `console.log`, `console.warn`, `console.error` sans `__DEV__`
  - Exception : les error boundaries et crash reporters peuvent logger en prod
- [ ] Aucune URL `localhost`, `127.0.0.1`, `10.0.2.2` hardcodée hors de `__DEV__`
- [ ] L'URL API de production est correcte et accessible (HTTPS)
- [ ] Aucun `debuggerStatement`, `debugger;` dans le code
- [ ] Aucune feature flag laissant des features de debug activées en prod

#### C2 — Stabilité
- [ ] ErrorBoundary global configuré (catch les crashes React)
- [ ] Sentry ou équivalent configuré pour la production
  - Source maps uploadées ? (vérifie la config Sentry dans app.config ou eas.json)
- [ ] Gestion des erreurs réseau : pas d'écran blanc si pas de connexion
  - Vérifie : composant NetworkBanner ou équivalent
- [ ] Gestion des erreurs API : messages user-friendly, pas de stack traces
- [ ] Pas de boucle infinie possible dans useEffect (deps arrays vérifiées)

#### C3 — Navigation
- [ ] Tous les écrans sont atteignables depuis la navigation principale
- [ ] Pas d'écran "dead-end" (sans bouton retour ni navigation)
- [ ] Deep linking configuré et cohérent avec le scheme URL
- [ ] Le splash screen ne reste pas bloqué indéfiniment
- [ ] L'app gère correctement le retour de background (pas de blank screen)

#### C4 — Fonctionnalités requises par les stores
- [ ] Suppression de compte : fonctionnalité accessible in-app (requis Apple depuis 2022)
  - Vérifie : existe-t-il un bouton/écran de suppression de compte ?
- [ ] Si achats in-app : bouton "Restaurer les achats" présent
- [ ] Si contenu utilisateur (UGC) : mécanismes de signalement et blocage
- [ ] Si paiements : pas de redirection vers un site externe pour les achats digitaux
  - Exception : les services physiques (comme une inspection mécanique) peuvent utiliser Stripe directement

#### C5 — Performance
- [ ] Les images sont compressées avant upload (pas de 4000x3000 brut)
- [ ] Les listes utilisent FlatList/FlashList (pas de ScrollView avec .map())
- [ ] Pas de polling excessif (< 5 secondes) sans bonne raison
- [ ] Le temps de démarrage à froid est raisonnable (< 3 secondes objectif)
- [ ] Hermes engine activé (par défaut dans Expo SDK 50+, vérifier)

### CATÉGORIE D : Compliance & Privacy

#### D1 — Apple Privacy
- [ ] Privacy Manifest (`privacyManifests`) configuré dans app.config.ts/app.json
  - Required Reasons APIs utilisées sont déclarées avec les bons reason codes
- [ ] ATT (App Tracking Transparency) implémenté si IDFA est accédé
  - Vérifie : `expo-tracking-transparency` ou `react-native-tracking-transparency`
  - Vérifie : le prompt ATT s'affiche AVANT toute collecte de données
- [ ] Toutes les NSUsageDescription sont :
  - Présentes pour CHAQUE permission demandée
  - Rédigées dans la langue de l'app (français)
  - Explicatives (pas juste "L'app a besoin de la caméra")

#### D2 — RGPD / GDPR
- [ ] Consentement explicite AVANT collecte de données (pas de cases pré-cochées)
  - Vérifie : écran/dialogue de consentement au premier lancement
- [ ] Les SDKs analytics (PostHog, Sentry) ne s'initialisent PAS avant le consentement
  - Vérifie : l'initialisation est conditionnelle au consentement
- [ ] Export de données utilisateur disponible (droit de portabilité)
- [ ] Suppression de données utilisateur disponible (droit à l'oubli)
- [ ] Retrait de consentement possible (settings ou profil)
- [ ] Politique de confidentialité accessible in-app
- [ ] Tiers sous-traitants listés dans la politique de confidentialité

#### D3 — Google Play Data Safety
- [ ] Les données collectées correspondent à ce qui sera déclaré dans le Data Safety section :
  - Données personnelles : email, nom, téléphone, photo
  - Données de localisation : GPS
  - Données financières : informations de paiement (via Stripe)
  - Analytics : PostHog
  - Crash reports : Sentry
- [ ] Le chiffrement des données en transit est implémenté (HTTPS partout)
- [ ] La suppression de données est offerte aux utilisateurs

### CATÉGORIE E : Sécurité

- [ ] Aucune API key, secret, ou token hardcodé dans le code source
  - Recherche : `sk_`, `pk_live`, `Bearer `, `apiKey`, `secret`, `password`
  - Recherche dans `app.config.ts` : les clés Stripe sont-elles en `pk_test_` ou `pk_live_` ?
- [ ] Les tokens JWT sont stockés dans SecureStore (pas AsyncStorage)
- [ ] Le refresh token est aussi dans SecureStore
- [ ] Logout nettoie TOUTES les données sensibles (SecureStore + state + cache)
- [ ] HTTPS enforced sur toutes les requêtes API (pas d'HTTP)
- [ ] Pas de données sensibles dans les logs (`console.log` avec tokens, emails, etc.)
- [ ] Les fichiers de credentials (`.env`, keystores, certificates) sont dans `.gitignore`
- [ ] Certificate pinning : au minimum un TODO documenté ou implémenté
- [ ] Les WebViews n'injectent pas de données non-sanitisées (XSS)

### CATÉGORIE F : Raisons de rejet les plus fréquentes (Apple + Google)

Vérifie spécifiquement ces raisons de rejet les plus courantes :

#### F1 — Apple Guideline 2.1 (Performance)
- [ ] L'app ne crashe pas au lancement
- [ ] Aucun écran incomplet ou en construction
- [ ] Aucun lien mort (URLs qui ne mènent nulle part)
- [ ] Aucune fonctionnalité "coming soon" visible

#### F2 — Apple Guideline 2.3 (Metadata)
- [ ] Les screenshots correspondent à l'app réelle
- [ ] La description n'est pas trompeuse
- [ ] Le nom de l'app ne contient pas de mots-clés spam

#### F3 — Apple Guideline 5.1.1 (Privacy)
- [ ] Politique de confidentialité complète et accessible
- [ ] Toutes les collectes de données déclarées
- [ ] Suppression de compte disponible

#### F4 — Apple Guideline 4.0 (Design)
- [ ] Pas d'erreurs de grammaire/orthographe majeures dans l'UI
- [ ] L'app fonctionne sur différentes tailles d'écran (iPhone SE → iPhone 16 Pro Max)
- [ ] Les éléments tactiles font minimum 44x44 points
- [ ] Le texte est lisible (contraste suffisant, taille minimum)

#### F5 — Google Play Policy (Data Safety)
- [ ] Data Safety section reflete la réalité de l'app
- [ ] Pas de permissions excessives (demander uniquement ce qui est utilisé)

## FORMAT DE SORTIE — OBLIGATOIRE

### Pour chaque finding :

```markdown
#### [SEVERITY] FINDING-ID : Titre court

- **Statut** : CONFIRMÉ | PROBABLE | À VÉRIFIER
- **Confiance** : X/10
- **Fichier** : `path/to/file` ou N/A (config store)
- **Catégorie** : Build | Metadata | Technical | Compliance | Security | Rejection-Risk
- **Guideline** : Apple X.Y.Z / Google Play Policy Z / RGPD Art. X / N/A
- **Code/Config actuel** :
  ```
  // Copié exactement du fichier source
  ```
- **Problème** : Ce qui manque ou est incorrect
- **Conséquence** : Rejet store / crash / non-compliance / UX dégradée
- **Correction** :
  ```
  // Configuration ou code corrigé
  ```
```

### Structure du rapport :

1. **Résumé exécutif** (5 lignes max)
   - Verdict : PRÊT / PRESQUE PRÊT / PAS PRÊT
   - Nombre de BLOCKERS, CRITICAL, WARNING, INFO
   - Top 3 des actions prioritaires

2. **Checklist rapide** (tableau visuel ✅/❌/⚠️)

| Catégorie | Statut | Détail |
|-----------|--------|--------|
| A. Build & Binary | ✅/❌/⚠️ | résumé |
| B. Metadata | ✅/❌/⚠️ | résumé |
| C. Technical | ✅/❌/⚠️ | résumé |
| D. Compliance | ✅/❌/⚠️ | résumé |
| E. Security | ✅/❌/⚠️ | résumé |
| F. Rejection Risks | ✅/❌/⚠️ | résumé |

3. **Findings BLOCKER** (empêchent la soumission)
4. **Findings CRITICAL** (risque élevé de rejet)
5. **Findings WARNING** (améliorations recommandées)
6. **Findings INFO** (optimisations)

7. **Auto-review** : Relis chaque BLOCKER et CRITICAL, confirme ou supprime

8. **Tableau récapitulatif**

| ID | Sévérité | Catégorie | Guideline | Statut | Description |
|----|----------|-----------|-----------|--------|-------------|

9. **Plan d'action avant soumission** (ordonné par priorité, effort estimé)

| Priorité | Finding | Effort | Action |
|----------|---------|--------|--------|
| 1 | SR-001 | 5 min | Corriger X |
| 2 | SR-002 | 1h | Implémenter Y |

10. **Verdict final**

```
VERDICT : PRÊT À SOUMETTRE / CORRECTIONS MINEURES REQUISES / CORRECTIONS MAJEURES REQUISES
Estimation : X heures/jours de travail avant soumission
```
```

---

> **Techniques intégrées :**
> - Anti-hallucination : Chain-of-Verification, Evidence Anchoring, Confidence Scoring
> - Contexte Expo : exceptions explicites pour le managed workflow (évite les faux positifs)
> - Apple App Store Review Guidelines 2025 (top rejection reasons : 2.1, 2.3, 5.1.1, 4.0)
> - Google Play Developer Policies 2025 (Data Safety, target API 35, permissions)
> - RGPD/GDPR compliance mobile (consentement explicite, droit à l'oubli, portabilité)
> - Apple Privacy Manifest (Required Reasons APIs, NSUsageDescription)
> - Sévérités orientées store : BLOCKER (rejet certain) vs CRITICAL (rejet probable)
> - Checklist consolidée de 100+ points issus de la documentation officielle Apple/Google/Expo
