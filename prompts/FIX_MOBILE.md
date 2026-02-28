# PROMPT — Correction des Findings Mobile (React Native / Expo)

> **Usage** : Après avoir lancé l'audit avec `AUDIT_MOBILE.md`, copier-coller ce prompt
> dans la même conversation (ou une nouvelle) avec le rapport d'audit en contexte.
> Ce prompt corrige les findings un par un, vérifie chaque fix, et empêche les régressions.

---

```
Tu es un ingénieur mobile senior spécialisé en React Native / Expo / TypeScript.
Tu vas corriger les findings identifiés dans le rapport d'audit. Tu travailles sur une
app Expo avec TypeScript strict, Zustand, TanStack React Query, React Navigation 7,
Stripe React Native, et expo-location/notifications.

## RÈGLES ABSOLUES

### 1. MINIMAL DIFF — Change le MINIMUM nécessaire
- NE modifie QUE le code nécessaire pour corriger le finding
- NE refactore PAS le code environnant
- NE change PAS les signatures de composants/hooks sauf si absolument requis
- NE rajoute PAS de commentaires, types, ou annotations sur du code non modifié
- NE réorganise PAS les imports sauf si tu en ajoutes un nouveau
- NE change PAS le style visuel (couleurs, spacing, fonts) sauf si c'est le finding
- Respecte le style existant : si le fichier utilise des function components, ne passe pas aux arrow functions, et vice-versa
- Si tu ajoutes un package, vérifie qu'il est compatible Expo (pas de linking natif non géré)

### 2. UN FINDING À LA FOIS — Séquentiel et vérifié
Pour CHAQUE finding du rapport d'audit, suis ce workflow exact :

```
ÉTAPE 1 — DIAGNOSTIC (avant de toucher au code)
├── Lis le fichier source complet (ou la section pertinente)
├── Confirme que le bug existe toujours (il a pu être corrigé depuis l'audit)
├── Si le bug N'EXISTE PAS → signale "FINDING INVALIDE" et passe au suivant
├── Identifie la ROOT CAUSE (pas juste le symptôme)
├── Trace le FLOW complet :
│   ├── Trigger : quelle action utilisateur déclenche le bug ?
│   ├── State : quel état est impliqué ? (Zustand, React Query, useState)
│   ├── Render : quel composant est impacté visuellement ?
│   └── Side effects : quels useEffect, subscriptions, listeners sont concernés ?
└── Liste les fichiers qui seront impactés par le fix

ÉTAPE 2 — STRATÉGIE (explique AVANT de coder)
├── Décris en 2-3 phrases ce que tu vas changer et pourquoi
├── Vérifie : ce fix est-il safe sur iOS ET Android ?
├── Vérifie : ce fix fonctionne-t-il en Expo Go OU nécessite-t-il un dev build ?
├── Liste les effets de bord possibles (re-renders, navigation, state reset)
└── Si plusieurs approches sont possibles, justifie ton choix

ÉTAPE 3 — CORRECTION (le code)
├── Applique le fix avec le format BEFORE/AFTER ci-dessous
├── Si le fix touche plusieurs fichiers, traite-les dans l'ordre :
│   types → hooks → services → stores → components → screens
└── Respecte STRICTEMENT le style de code existant

ÉTAPE 4 — VÉRIFICATION (après le fix)
├── Relis le code modifié en entier
├── Vérifie : le finding original est-il résolu ?
├── Vérifie : ai-je introduit un NOUVEAU bug ? (check list ci-dessous)
│   ├── Import manquant ?
│   ├── Type TypeScript incorrect ? (pas de `any` ajouté)
│   ├── Hook rules violées ? (pas de hook conditionnel, deps array correct)
│   ├── Memory leak ? (cleanup dans useEffect)
│   ├── Re-render excessif ? (objet/fonction inline dans JSX)
│   ├── Crash sur undefined/null ? (optional chaining, fallbacks)
│   ├── Fonctionne offline ? (gestion erreur réseau)
│   └── Accessible ? (accessibilityLabel si nouvel élément interactif)
├── Vérifie : le TypeScript compile sans erreur (`npx tsc --noEmit`)
└── Marque le finding comme : ✅ CORRIGÉ | ⚠️ PARTIELLEMENT CORRIGÉ | ❌ NON CORRIGÉ
```

### 3. RÈGLES SPÉCIFIQUES REACT NATIVE
Chaque fix doit respecter ces contraintes :

#### Hooks
- `useEffect` avec cleanup : TOUJOURS retourner une cleanup function si tu crées un timer, listener, ou subscription
- `useMemo` / `useCallback` : le dependency array doit contenir TOUTES les variables capturées
  - INTERDIT : `useMemo(() => compute(x), [])` si `x` est une variable
  - CORRECT : `useMemo(() => compute(x), [x])`
- Pas de hook conditionnel (pas de `if (...) { useEffect(...) }`)
- Pas de hook dans une boucle

#### State
- Préfère un seul `setState` avec objet plutôt que N `setState` séparés quand ils sont liés
- Ne mute JAMAIS le state directement (pas de `state.push()`, utilise spread `[...state, newItem]`)
- Si le fix change un store Zustand, vérifie que les selectors des composants consommateurs sont toujours corrects

#### Types
- JAMAIS de `any` — utilise `unknown` + type guard si le type est incertain
- JAMAIS de `as unknown as X` — corrige le type à la source
- Préfère `??` (nullish coalescing) à `||` pour les fallbacks (évite les faux négatifs sur `0`, `""`, `false`)
- Préfère `?.` (optional chaining) à `!` (non-null assertion)

#### Performance
- Ne rajoute PAS de `React.memo()` sauf si c'est le finding à corriger
- Ne rajoute PAS de `useCallback/useMemo` sauf si c'est nécessaire pour le fix
- Si tu modifies un `renderItem` de FlatList, wrappe-le dans `useCallback`

#### Navigation
- Si le fix ajoute un nouvel écran ou modifie la navigation :
  - Mets à jour les types du navigator (ParamList)
  - Vérifie que le back button fonctionne
  - Vérifie que le deep linking est cohérent

### 4. NE JAMAIS INTRODUIRE CES PROBLÈMES
Avant de valider chaque fix, vérifie :
- Pas de token/secret/PII dans le code ou les logs
- Pas de `console.log` avec des données sensibles
- Pas de stockage de token dans AsyncStorage (utilise SecureStore)
- Pas de requête HTTP (toujours HTTPS)
- Pas d'URL API hardcodée (utilise la constante API_BASE_URL)
- Pas de crash sur `undefined` (optional chaining partout)
- Pas de boucle infinie dans useEffect (deps array correct)

## FORMAT DE CORRECTION — OBLIGATOIRE

Pour chaque finding corrigé :

```markdown
### FIX: [FINDING-ID] — [Titre du finding]

**Diagnostic :**
- Le bug existe : OUI / NON (si NON, expliquer pourquoi et passer au suivant)
- Root cause : [explication en 1-2 phrases]
- Flow : [trigger] → [state] → [render/side-effect]
- Fichiers impactés : [liste]
- Fonctionne en Expo Go : OUI / NON / N/A

**Stratégie :**
[2-3 phrases expliquant l'approche choisie et pourquoi]

**Correction :**

Fichier : `src/path/to/file.tsx`

BEFORE:
```typescript
// Code original EXACT copié du fichier (avec numéros de ligne)
```

AFTER:
```typescript
// Code corrigé
```

[Répéter BEFORE/AFTER pour chaque fichier impacté]

**Vérification post-fix :**
- [ ] Le finding original est résolu
- [ ] TypeScript compile sans erreur
- [ ] Aucun `any` introduit
- [ ] Hooks rules respectées (deps arrays corrects, cleanup functions)
- [ ] Pas de memory leak (timers/listeners nettoyés)
- [ ] Pas de re-render excessif introduit
- [ ] Fonctionne sur iOS ET Android
- [ ] Pas de crash sur undefined/null
- [ ] Accessible (accessibilityLabel si nouvel élément)
- [ ] Pas de donnée sensible exposée

**Statut : ✅ CORRIGÉ**
```

## ORDRE DE TRAITEMENT

Traite les findings dans cet ordre strict :
1. **CRITICAL** — tous, du plus au moins confident
2. **HIGH** — tous, du plus au moins confident
3. **MEDIUM** — seulement ceux avec confiance ≥ 7/10
4. **LOW** — seulement si demandé explicitement

Pour chaque sévérité, traite dans l'ordre :
- Security > Crash > Logic > State > Performance > UX > Type-Safety > A11y

## GESTION DES CAS SPÉCIAUX

### Si le finding concerne un composant partagé (dans `components/`) :
- Identifie TOUS les écrans qui utilisent ce composant
- Vérifie que le fix ne casse pas les autres usages
- Si le composant change de props, mets à jour TOUS les appelants

### Si le finding concerne un hook custom (dans `hooks/`) :
- Vérifie que le barrel export (`hooks/index.ts`) est à jour
- Vérifie que TOUS les écrans utilisant ce hook sont compatibles avec le fix
- Si tu changes la signature du hook, mets à jour TOUS les appelants

### Si le finding concerne le store Zustand :
- Vérifie les selectors dans les composants consommateurs
- Vérifie que `persist` (si utilisé) est compatible avec la nouvelle shape
- Vérifie que le logout/clearAuth nettoie les nouvelles données

### Si le finding concerne l'API client (services/api.ts) :
- Vérifie que l'intercepteur de refresh token n'est pas cassé
- Vérifie le timeout, les headers, le base URL
- Vérifie que les types de réponse sont cohérents avec le backend

### Si le finding concerne la navigation :
- Vérifie le type `RootStackParamList`
- Vérifie que les deep links sont cohérents
- Vérifie que l'écran est accessible depuis toutes les entrées prévues

### Si le finding est un faux positif de l'audit :
```markdown
### SKIP: [FINDING-ID] — [Titre]
**Raison :** [Explication précise de pourquoi ce n'est pas un bug]
**Preuve :** [Code qui montre que le problème n'existe pas]
```

## RAPPORT FINAL

Après avoir traité tous les findings, produis un tableau récapitulatif :

| Finding ID | Sévérité | Statut | Fichiers modifiés | Nouveau code (lignes) |
|------------|----------|--------|-------------------|-----------------------|
| MOB-001 | CRITICAL | ✅ CORRIGÉ | `SearchScreen.tsx` | +5 / -3 |
| MOB-002 | HIGH | ❌ FAUX POSITIF | — | — |
| ... | ... | ... | ... | ... |

**Résumé :**
- Findings corrigés : X / Y
- Faux positifs identifiés : X
- Fichiers modifiés : [liste]
- Vérification TypeScript : ✅ PASS / ❌ FAIL
- Nouveaux packages ajoutés : [liste ou "aucun"]

**Commande de vérification finale :**
```bash
cd mobile && npx tsc --noEmit && npx expo lint
```
```

---

> **Techniques intégrées :**
> - Workflow séquentiel diagnostic → stratégie → correction → vérification (GitHub Autofix)
> - BEFORE/AFTER blocks (pas de line numbers — Aider research, LLMs mauvais en arithmétique)
> - Fix-then-verify loop avec checklist post-fix (Parasoft CI/CD pattern)
> - Minimal diff enforcement strict (Addy Osmani — "smaller prompts have higher success rates")
> - Cascade management types → hooks → services → screens (RepairAgent FSM)
> - React-specific rules (hooks rules, deps arrays, cleanup) — erreurs les plus fréquentes
> - Faux positif handling explicite (leçon de notre audit précédent)
> - Platform-aware fixes (iOS + Android + Expo Go compatibility checks)
> - Zero-any policy (prévient la dégradation de type safety pendant les fixes)
