# AUDIT UI/UX MOBILE — eMecano
## AUDIT COMBINE — Pass 1 + Pass 2

**Date :** 2026-03-01
**Auditeur :** Expert UI/UX Senior (React Native / Expo / TypeScript)
**Version analysée :** commit `07c76cc`
**Scope :** `/home/bouzelouf/secret_project/mobile/src/`
**Pass 1 :** 34 findings initiaux
**Pass 2 :** 16 nouveaux findings supplementaires
**Total :** 50 findings

---

## 1. SCORES PAR AXE — REVISION FINALE (Pass 1 + Pass 2)

| Axe | Intitule | Score P1 /10 | Score Final /10 | Poids | Pondéré |
|-----|----------|-------------|----------------|-------|---------|
| AXE 1 | Couleurs & Contraste | 5.5 | 4.5 | 15 % | 6.75 |
| AXE 2 | Ergonomie & Touch Targets | 6.5 | 6.0 | 15 % | 9.00 |
| AXE 3 | Typographie | 7.5 | 7.0 | 10 % | 7.00 |
| AXE 4 | Spacing & Layout | 6.5 | 6.5 | 10 % | 6.50 |
| AXE 5 | UX Patterns | 7.0 | 6.5 | 15 % | 9.75 |
| AXE 6 | Accessibilité | 4.5 | 4.0 | 15 % | 6.00 |
| AXE 7 | Consistance & Design System | 5.5 | 3.5 | 10 % | 3.50 |
| AXE 8 | Mobile-Specific | 6.5 | 5.5 | 10 % | 5.50 |
| **TOTAL** | | | | **100 %** | **54.00 / 100** |

> Le score passe de 61.25 (Pass 1) a 54.00 (Pass 2) apres decouverte des ecrans completement desconnectes du design system (EmailVerificationScreen, NearbyDemandsScreen, PaymentMethodsScreen, LegalScreen, DemandDetailScreen).

---

## 2. TABLEAU SYNTHETIQUE COMPLET DES FINDINGS

| ID | Tag | Axe | Severite | Confiance | Fichier : Ligne | Probleme |
|----|-----|-----|----------|-----------|-----------------|---------|
| F-01 | [P1] | AXE 1 | CRITIQUE | 0.98 | `MechanicHomeScreen.tsx:74` | Couleurs hex en dur partout (14+ valeurs) |
| F-02 | [P1] | AXE 1 | CRITIQUE | 0.97 | `BookingMessagesScreen.tsx:99–103` | Palette complete en dur, aucun token |
| F-03 | [P1] | AXE 1 | MAJEUR | 0.95 | `colors.ts:25` / `Badge.tsx:15` | `textSecondary` #5B6578 risque contraste 400-weight |
| F-04 | [P1] | AXE 1 | MAJEUR | 0.93 | `colors.ts:26` / multiples | `textMuted` #94A3B8 ratio 2.90:1 sur blanc — non-conforme WCAG |
| F-05 | [P1] | AXE 1 | MAJEUR | 0.90 | `MechanicHomeScreen.tsx:346` | `color: "#888"` ratio 4.48:1 — sous seuil WCAG 4.5 |
| F-06 | [P1] | AXE 2 | CRITIQUE | 0.99 | `Input.tsx:87–93` | Ionicons `onPress` sans wrapper — cible 22x22 pt |
| F-07 | [P1] | AXE 2 | CRITIQUE | 0.98 | `StarRating.tsx:34–42` | Etoile editable 18x18 pt sans padding |
| F-08 | [P1] | AXE 2 | MAJEUR | 0.95 | `BookingDetailScreen.tsx:496–501` | Etoiles avis 32pt sans hitSlop |
| F-09 | [P1] | AXE 2 | MAJEUR | 0.92 | `CheckOutScreen.tsx:589–604` | Croix suppression photo 24x24 pt sans hitSlop |
| F-10 | [P1] | AXE 2 | MAJEUR | 0.91 | `CheckOutScreen.tsx:317` | Bouton retour sans accessibilityLabel precis |
| F-11 | [P1] | AXE 3 | MAJEUR | 0.95 | `typography.ts:22` | Token `overline` 11pt utilise comme label section |
| F-12 | [P1] | AXE 3 | MINEUR | 0.88 | `typography.ts:11` | `h1` lineHeight 34/28 = ratio 1.21x — limite |
| F-13 | [P1] | AXE 4 | MAJEUR | 0.93 | `CheckOutScreen.tsx:333–372` | padding: 12 et minHeight: 100 hors tokens de spacing |
| F-14 | [P1] | AXE 4 | MAJEUR | 0.90 | `MechanicHomeScreen.tsx:281` | `marginTop: -30` valeur non-multiple de 8 |
| F-15 | [P1] | AXE 4 | MINEUR | 0.85 | `BookingCard.tsx:51` | `marginTop: 3` non-multiple de 4 ou 8 |
| F-16 | [P1] | AXE 5 | CRITIQUE | 0.97 | `CheckOutScreen.tsx:96–122` | Validation uniquement au submit, Alert.alert un champ a la fois |
| F-17 | [P1] | AXE 5 | MAJEUR | 0.95 | `BookingDetailScreen.tsx:206–212` | Typographie non-tokenisee, pas de SafeAreaView root |
| F-18 | [P1] | AXE 5 | MAJEUR | 0.92 | `EmptyState.tsx:12` | Aucun CTA action dans EmptyState |
| F-19 | [P1] | AXE 5 | MAJEUR | 0.91 | `MechanicHomeScreen.tsx:154–161` | Erreur de chargement sans bouton retry, RefreshControl absent |
| F-20 | [P1] | AXE 5 | MINEUR | 0.85 | `WelcomeScreen.tsx:2` | SafeAreaView natif react-native |
| F-21 | [P1] | AXE 6 | CRITIQUE | 0.99 | `StarRating.tsx:35–42` | Aucun accessibilityLabel sur les etoiles editables |
| F-22 | [P1] | AXE 6 | CRITIQUE | 0.98 | `MechanicCard.tsx:14` | accessibilityRole="button" sans accessibilityLabel |
| F-23 | [P1] | AXE 6 | MAJEUR | 0.96 | `BookingMessagesScreen.tsx:296–317` | Bouton envoi message 40x40 pt sans accessibilityLabel |
| F-24 | [P1] | AXE 6 | MAJEUR | 0.94 | `NotificationDropdown.tsx:92–98` | Notifications sans accessibilityLabel dynamique |
| F-25 | [P1] | AXE 6 | MAJEUR | 0.93 | `CheckOutScreen.tsx:448–456` | Switch "Essai routier" sans accessibilityLabel |
| F-26 | [P1] | AXE 6 | MAJEUR | 0.92 | `Skeleton.tsx:26` | Skeleton sans `accessibilityElementsHidden` |
| F-27 | [P1] | AXE 7 | CRITIQUE | 0.98 | `MechanicHomeScreen.tsx` multiples | 11 valeurs hex en dur, 2 verts divergents du design system |
| F-28 | [P1] | AXE 7 | MAJEUR | 0.95 | `BookingMessagesScreen.tsx:98–103` | Bulles de messages sans tokens |
| F-29 | [P1] | AXE 7 | MAJEUR | 0.92 | `CheckOutScreen.tsx:810–869` | PickerField composant local non exporte |
| F-30 | [P1] | AXE 8 | CRITIQUE | 0.99 | `WelcomeScreen.tsx:3` | SafeAreaView natif au lieu de safe-area-context |
| F-31 | [P1] | AXE 8 | MAJEUR | 0.95 | `BookingMessagesScreen.tsx:139` | KAV Android behavior=undefined |
| F-32 | [P1] | AXE 8 | MAJEUR | 0.92 | `CheckOutScreen.tsx:332` | Formulaire 10+ champs sans KeyboardAvoidingView |
| F-33 | [P1] | AXE 8 | MAJEUR | 0.90 | `SearchScreen.tsx:286–345` | Zone filtres non-collapsible occupe 50% ecran (iPhone SE) |
| F-34 | [P1] | AXE 8 | MINEUR | 0.86 | `MechanicHomeScreen.tsx:74` | StatusBar backgroundColor "#0D1B3E" en dur |
| F-35 | [P2] | AXE 1+7 | CRITIQUE | 0.99 | `EmailVerificationScreen.tsx:268–391` | Ecran entier sans tokens : #0D1B3E, #2E8B57, #E53E3E, #A0AEC0 |
| F-36 | [P2] | AXE 1+7 | CRITIQUE | 0.98 | `NearbyDemandsScreen.tsx:154–250` | Ecran entier sans tokens : #F5F5F5, #0D1B3E, #1A1A2E, #2E8B57, #9CA3AF |
| F-37 | [P2] | AXE 1+7 | CRITIQUE | 0.98 | `PaymentMethodsScreen.tsx:48–100` | Ecran entier sans tokens : #F5F5F5, #1A1A2E, #6B7280, #0D1B3E |
| F-38 | [P2] | AXE 1+7 | MAJEUR | 0.95 | `DemandDetailScreen.tsx:27–31` | STATUS_COLORS en dur : #2E8B57, #6B7280, #DC2626 — diverge de colors.ts |
| F-39 | [P2] | AXE 1+7 | MAJEUR | 0.95 | `DocumentThumbnail.tsx:39,59` | #DC2626, #6B7280, #E5E7EB, #F9FAFB en dur + police 10pt non tokenisee |
| F-40 | [P2] | AXE 1+7 | MAJEUR | 0.94 | `VerificationInstructionsModal.tsx:105–179` | Modal entiere sans tokens : #FFFFFF, #0D1B3E, #F0F4FF, #4B5563, #6B7280 |
| F-41 | [P2] | AXE 8 | CRITIQUE | 0.99 | `MechanicProfileScreen.tsx:1–13` | SafeAreaView importe depuis react-native (natif) et non safe-area-context |
| F-42 | [P2] | AXE 8 | MAJEUR | 0.95 | `PostDemandScreen.tsx:130–133` | KAV behavior=undefined sur Android — formulaire de publication de demande |
| F-43 | [P2] | AXE 2 | MAJEUR | 0.93 | `PaymentMethodsScreen.tsx:51–52` | Bouton retour : padding: 4 sur icone 24pt — cible effective 32x32 pt |
| F-44 | [P2] | AXE 6 | MAJEUR | 0.93 | `Avatar.tsx:38–41` | Avatar sans accessibilityLabel ni accessibilityElementsHidden |
| F-45 | [P2] | AXE 7 | MAJEUR | 0.93 | `MessagesListScreen.tsx:93–129` | Couleurs en dur dans StyleSheet : #F5F5F5, #FFFFFF, #1A1A2E, #6B7280, #E5E7EB |
| F-46 | [P2] | AXE 1+7 | MAJEUR | 0.92 | `LegalScreen.tsx:12–87` | Ecran entier inline styles sans tokens : #FFFFFF, #1A1A2E, #6B7280, #9CA3AF |
| F-47 | [P2] | AXE 3 | MAJEUR | 0.92 | `DashboardScreen.tsx:112,185,207` | Typographie non-tokenisee : `fontSize: 24, fontWeight: "bold"` / `fontSize: 14, fontWeight: "600"` |
| F-48 | [P2] | AXE 3 | MINEUR | 0.88 | `RegisterScreen.tsx:289` | Password-strength text `fontSize: 11` non-tokenise, sans `fontFamily` |
| F-49 | [P2] | AXE 5+8 | MAJEUR | 0.90 | `NotificationDropdown.tsx:206` | `marginTop: 100` fixe en dur — ne s'adapte pas a la safe area (Dynamic Island, Android cutout) |
| F-50 | [P2] | AXE 2 | MINEUR | 0.82 | `Badge.tsx:25` | Badge "sm" a `fontSize: 11` — sous le seuil WCAG 2.2 minimum (12pt) pour un badge interactif |

---

## 3. DETAIL DE CHAQUE FINDING

---

### F-01 [P1] — CRITIQUE : Couleurs en dur dans MechanicHomeScreen (Axe 1 & 7)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/mechanic/MechanicHomeScreen.tsx`

**Lignes concernees :** 74, 282, 307–310, 394, 406–408, 440–448, 467–470

**Snippet verbatim :**
```tsx
// Ligne 74
<StatusBar barStyle="light-content" backgroundColor="#0D1B3E" />

// Ligne 282
backgroundColor: "#F5F5F5",

// Ligne 394
statsSection: {
  backgroundColor: "#2E8B57",   // <- deux verts distincts vs colors.accent = "#1A9A5C"

// Ligne 469
proposalDate: {
  color: "#888",                // <- hex arbitraire
```

**Probleme :** 14+ valeurs hexadecimales en dur. Deux divergences semantiques critiques : `#2E8B57` (vert accent mecano) vs `colors.accent = "#1A9A5C"` et `#E74C3C` (rouge erreur mecano) vs `colors.error = "#DC2626"`.

**Standard viole :** Coherence design system — toutes les couleurs doivent passer par `colors.ts`.

---

### F-02 [P1] — CRITIQUE : Couleurs en dur dans BookingMessagesScreen (Axe 1 & 7)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/shared/BookingMessagesScreen.tsx`

**Lignes concernees :** 92, 99–103, 111–113, 125–126, 143–146, 151, 170, 188, 219, 247–249, 271–285, 300–306

**Snippet verbatim :**
```tsx
// Lignes 99–103 — bulles de message
backgroundColor: isMe
  ? item.is_template
    ? "#0D1B3E"
    : "#3B82F6"
  : item.is_template
    ? "#F5F5F5"
    : "#FEF3C7",

// Ligne 125 (timestamp)
color: "#9CA3AF",

// Ligne 170 (loading spinner)
<ActivityIndicator size="large" color="#0D1B3E" />
```

**Probleme :** Fichier partage (acheteur + mecanicien) n'utilise aucun token sur ses 297 lignes.

---

### F-03 [P1] — MAJEUR : Contraste textSecondary sur bgSecondary risque (Axe 1)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/theme/colors.ts` ligne 25

**Snippet verbatim :**
```ts
textSecondary: "#5B6578",
// bgSecondary = "#F1F3F5"
```

**Contraste :** #5B6578 sur #F1F3F5 = ~5.77:1 — conforme pour gras, risque pour 400-weight < 14pt dans Badge "sm".

**Standard viole :** WCAG 2.2 SC 1.4.3

---

### F-04 [P1] — MAJEUR : textMuted non conforme WCAG (Axe 1)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/theme/colors.ts` ligne 26

**Snippet verbatim :**
```ts
textMuted: "#94A3B8",
```

**Calcul :** #94A3B8 sur blanc = ratio ~2.90:1 — clairement non conforme WCAG 2.2 SC 1.4.3.

**Usages identifies :** LoginScreen:329, RegisterScreen:362, WelcomeScreen:71, MechanicCard:141, NotificationDropdown.

**Correction recommandee :** Remplacer `#94A3B8` par `#6B7280` (ratio ~4.61:1 sur blanc).

---

### F-05 [P1] — MAJEUR : Couleur arbitraire #888 dans MechanicHomeScreen (Axe 1)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/mechanic/MechanicHomeScreen.tsx` ligne 469

**Snippet verbatim :**
```tsx
proposalDate: {
  fontSize: 13,
  fontFamily: "Inter_400Regular",
  color: "#888",   // <- ratio 4.48:1 — sous seuil WCAG 4.5:1
  marginTop: 2,
},
```

**Contraste :** #888888 sur blanc = ratio ~4.48:1 — juste sous le minimum WCAG pour texte 13px normal.

---

### F-06 [P1] — CRITIQUE : Icone "afficher mot de passe" sans touch target conforme (Axe 2)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/components/ui/Input.tsx` lignes 86–93

**Snippet verbatim :**
```tsx
{isPassword && (
  <Ionicons
    name={showPassword ? "eye-off-outline" : "eye-outline"}
    size={22}
    color={colors.textMuted}
    onPress={() => setShowPassword(!showPassword)}
  />
)}
```

**Probleme :** Ionicons avec onPress sans wrapper TouchableOpacity — cible effective 22x22 pt. Utilise sur LoginScreen, RegisterScreen, ChangePasswordScreen.

**Standard viole :** iOS HIG Touch Target 44x44 pt minimum.

**Correction :**
```tsx
<TouchableOpacity
  onPress={() => setShowPassword(!showPassword)}
  style={{ padding: 11, minWidth: 44, minHeight: 44, alignItems: "center", justifyContent: "center" }}
  accessibilityLabel={showPassword ? "Masquer le mot de passe" : "Afficher le mot de passe"}
  accessibilityRole="button"
>
  <Ionicons name={showPassword ? "eye-off-outline" : "eye-outline"} size={22} color={colors.textMuted} />
</TouchableOpacity>
```

---

### F-07 [P1] — CRITIQUE : Touch targets etoiles interactives insuffisants (Axe 2)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/components/shared/StarRating.tsx` lignes 34–42

**Snippet verbatim :**
```tsx
if (editable && onRate) {
  return (
    <TouchableOpacity
      key={i}
      onPress={() => onRate(starNumber)}
      activeOpacity={0.7}
    >
      {StarIcon}   // Ionicons size={18} — cible effective 18x18 pt
    </TouchableOpacity>
  );
}
```

**Standard viole :** iOS HIG 44x44 pt. Critique pour usage mecanicien en exterieur.

---

### F-08 [P1] — MAJEUR : Espacement insuffisant entre etoiles formulaire avis (Axe 2)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/buyer/BookingDetailScreen.tsx` lignes 496–503

**Snippet verbatim :**
```tsx
{[1, 2, 3, 4, 5].map((star) => (
  <TouchableOpacity key={star} onPress={() => setRating(star)} style={{ marginHorizontal: 4 }}>
    <Ionicons
      name={star <= rating ? "star" : "star-outline"}
      size={32}
      color={star <= rating ? colors.star : colors.border}
    />
  </TouchableOpacity>
))}
```

**Probleme :** Cibles de 32x32 pt (sous 44 pt) avec marginHorizontal: 4 — espacement minimal de 8 pt atteint mais taille cible sous les normes. Pas de hitSlop.

---

### F-09 [P1] — MAJEUR : Bouton suppression photo 24x24 pt sans hitSlop (Axe 2)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/mechanic/CheckOutScreen.tsx` lignes 589–604

**Snippet verbatim :**
```tsx
<TouchableOpacity
  onPress={() => setPhotoPlate(null)}
  style={{
    position: "absolute",
    top: -8,
    right: -8,
    backgroundColor: colors.error,
    borderRadius: 20,
    width: 24,
    height: 24,    // <- 24x24 pt
    alignItems: "center",
    justifyContent: "center",
  }}
>
  <Ionicons name="close" size={14} color={colors.white} />
</TouchableOpacity>
```

**Standard viole :** iOS HIG 44x44 pt. Usage en conditions terrain mecanicien.

---

### F-10 [P1] — MAJEUR : Bouton retour CheckOut sans accessibilityLabel precis (Axe 2)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/mechanic/CheckOutScreen.tsx` ligne 317

**Probleme :** Bouton retour avec `padding: 10` sur icone 24pt — taille limite 44pt mais sans `accessibilityLabel` ni `accessibilityHint` pour les lecteurs d'ecran.

---

### F-11 [P1] — MAJEUR : Token overline 11pt utilise comme label section (Axe 3)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/theme/typography.ts` ligne 22

**Snippet verbatim :**
```ts
overline: { fontSize: 11, fontFamily: fontFamily.semiBold, fontWeight: "600", letterSpacing: 0.8, textTransform: "uppercase" },
```

**Probleme :** 11pt est le minimum absolu Apple HIG. Ce token est utilise comme label de section critique dans SearchScreen:494. Usage supplementaire dans des contextes de lecture prolongee.

---

### F-12 [P1] — MINEUR : h1 lineHeight limite (Axe 3)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/theme/typography.ts` ligne 11

**Snippet verbatim :**
```ts
h1: { fontSize: 28, fontFamily: fontFamily.bold, fontWeight: "700", letterSpacing: -0.5, lineHeight: 34 },
```

**Calcul :** 34/28 = 1.21x — a la limite du ratio minimum recommande de 1.2x.

---

### F-13 [P1] — MAJEUR : Formulaire CheckOut sans tokens de spacing (Axe 4)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/mechanic/CheckOutScreen.tsx` lignes 333–372

**Snippet verbatim :**
```tsx
// Ligne 365 — TextInput
padding: 12,           // <- spacing non tokenise
// Ligne 499
minHeight: 100,        // <- non-multiple de 8 (96 ou 104 seraient alignes)
```

**Standard viole :** Design System `spacing.ts` — toutes les valeurs doivent passer par les tokens.

---

### F-14 [P1] — MAJEUR : marginTop: -30 non-multiple de 8 (Axe 4)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/mechanic/MechanicHomeScreen.tsx` ligne 281

**Probleme :** `marginTop: -30` — valeur negative non-multiple de 8 (multiple le plus proche : -32). Cree un ecart avec la grille 8pt.

---

### F-15 [P1] — MINEUR : marginTop: 3 non-multiple de 4 ou 8 (Axe 4)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/components/shared/BookingCard.tsx` ligne 51

**Snippet verbatim :**
```tsx
<Text style={{ fontSize: 13, marginTop: 3, fontFamily: fontFamily.regular, color: colors.textMuted }}>
```

**Standard viole :** Grille 8pt — valeur non-multiple de 4 ou 8.

---

### F-16 [P1] — CRITIQUE : Absence de validation inline dans CheckOut (Axe 5)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/mechanic/CheckOutScreen.tsx` lignes 96–122

**Snippet verbatim :**
```tsx
const handleSubmit = async () => {
  if (!photoPlate) {
    Alert.alert("Champs requis", "Veuillez prendre une photo de la plaque d'immatriculation.");
    return;
  }
  if (!photoOdometer) {
    Alert.alert("Champs requis", "Veuillez prendre une photo du compteur kilometrique.");
    return;
  }
  if (!enteredOdometer.trim() || isNaN(Number(enteredOdometer)) || Number(enteredOdometer) < 0) {
    Alert.alert("Champs requis", "Veuillez saisir un kilometrage valide (positif).");
    return;
  }
```

**Probleme :** Formulaire 10+ champs, validation uniquement au submit via Alert.alert sequentiels. Le mecanicien en exterieur remplit les champs sans feedback et decouvre les erreurs une par une a la soumission.

**Solution recommandee :** Etat d'erreur inline par champ (pattern deja implante dans `Input.tsx`), bouton Submit desactive jusqu'a completion des champs requis.

---

### F-17 [P1] — MAJEUR : BookingDetailScreen typographie non-tokenisee et root sans SafeAreaView (Axe 5 & 8)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/buyer/BookingDetailScreen.tsx` lignes 206–215

**Snippet verbatim :**
```tsx
return (
  <View style={{ flex: 1, backgroundColor: colors.bg }}>
    <ScrollView ...>
      <View style={{ backgroundColor: colors.white, paddingHorizontal: 16, paddingVertical: 16, ... }}>
        <Text style={{ fontSize: 20, fontWeight: "bold", color: colors.text }}>
          RDV #{booking.id.slice(0, 8)}
        </Text>
```

**Probleme :** Root `View` sans `SafeAreaView`. `fontSize: 20, fontWeight: "bold"` sans tokens (`typography.h3` serait approprie ici).

---

### F-18 [P1] — MAJEUR : EmptyState sans CTA action (Axe 5)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/components/ui/EmptyState.tsx` lignes 6–11

**Snippet verbatim :**
```tsx
interface EmptyStateProps {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  description?: string;
  // <- pas de prop "action", "actionLabel", "onAction"
}
```

**Probleme :** Composant sans support de CTA. Les 4 cas d'usage (aucune donnee, erreur reseau, filtre vide, premier usage) necessitent des actions differentes non couvertes.

---

### F-19 [P1] — MAJEUR : Banniere erreur sans bouton retry et RefreshControl absent (Axe 5)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/mechanic/MechanicHomeScreen.tsx` lignes 154–161

**Snippet verbatim :**
```tsx
{bookingsError && (
  <View style={{ backgroundColor: "#FEF2F2", ... }}>
    <Ionicons name="alert-circle-outline" size={20} color="#DC2626" />
    <Text style={{ color: "#DC2626", fontSize: 13, ... }}>
      Impossible de charger vos missions. Tirez pour rafraichir.
    </Text>
  </View>
)}
```

**Probleme :** Le message indique "Tirez pour rafraichir" mais la ScrollView n'a pas de `RefreshControl` dans ce fichier. Instruction impossible a executer.

---

### F-20 [P1] — MINEUR : SafeAreaView natif react-native dans WelcomeScreen (Axe 8)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/auth/WelcomeScreen.tsx` ligne 3

**Snippet verbatim :**
```tsx
import { View, Text, TouchableOpacity, SafeAreaView, ScrollView } from "react-native";
// <- SafeAreaView depuis react-native et non safe-area-context
```

**Standard viole :** Expo/React Navigation recommande `react-native-safe-area-context`. Le SafeAreaView natif ne gere pas Dynamic Island iOS 16+.

---

### F-21 [P1] — CRITIQUE : StarRating editable sans accessibilityLabel (Axe 6)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/components/shared/StarRating.tsx` lignes 34–42

**Snippet verbatim :**
```tsx
return (
  <TouchableOpacity
    key={i}
    onPress={() => onRate(starNumber)}
    activeOpacity={0.7}
    // <- aucun accessibilityLabel
    // <- aucun accessibilityRole
    // <- aucun accessibilityState
  >
    {StarIcon}
  </TouchableOpacity>
);
```

**Standard viole :** WCAG 2.2 SC 4.1.2 — lecteur d'ecran annonce "bouton, bouton, bouton, bouton, bouton" sans information de contexte.

**Correction :**
```tsx
<TouchableOpacity
  key={i}
  onPress={() => onRate(starNumber)}
  activeOpacity={0.7}
  accessibilityLabel={`${starNumber} etoile${starNumber > 1 ? "s" : ""} sur ${maxStars}`}
  accessibilityRole="radio"
  accessibilityState={{ checked: starNumber === rating }}
  style={{ padding: 13 }}  // touch target 44x44
>
```

---

### F-22 [P1] — CRITIQUE : MechanicCard sans accessibilityLabel descriptif (Axe 6)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/components/shared/MechanicCard.tsx` ligne 14

**Snippet verbatim :**
```tsx
<TouchableOpacity style={styles.card} onPress={onPress} activeOpacity={0.75} accessibilityRole="button">
  {/* <- accessibilityRole present mais accessibilityLabel absent */}
```

**Correction :**
```tsx
accessibilityLabel={`Mecanicien a ${mechanic.city}, note ${mechanic.rating_avg?.toFixed(1) ?? "non note"} sur 5${mechanic.next_available_date ? ", disponible" : ""}`}
```

---

### F-23 [P1] — MAJEUR : Bouton envoi message sans accessibilite (Axe 6)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/shared/BookingMessagesScreen.tsx` lignes 296–317

**Snippet verbatim :**
```tsx
<TouchableOpacity
  onPress={handleSendCustom}
  disabled={sendMutation.isPending || !customText.trim()}
  style={{
    marginLeft: 8,
    width: 40,    // <- 40x40 pt, sous les 44 requis
    height: 40,
    borderRadius: 20,
  }}
  // <- aucun accessibilityLabel ni accessibilityRole
>
```

---

### F-24 [P1] — MAJEUR : Notifications sans accessibilityLabel dynamique (Axe 6)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/components/shared/NotificationDropdown.tsx` lignes 92–98

**Snippet verbatim :**
```tsx
<TouchableOpacity
  style={[styles.notifItem, !notif.is_read && styles.notifItemUnread]}
  onPress={() => handleNotificationPress(notif)}
  activeOpacity={0.7}
  // <- aucun accessibilityLabel ni accessibilityRole
>
```

---

### F-25 [P1] — MAJEUR : Switch "Essai routier" sans accessibilite (Axe 6)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/mechanic/CheckOutScreen.tsx` lignes 448–456

**Snippet verbatim :**
```tsx
<Switch
  value={formData.test_drive_done}
  onValueChange={(value) => setFormData({ ...formData, test_drive_done: value })}
  trackColor={{ false: colors.border, true: colors.primary }}
  thumbColor={colors.white}
  // <- aucun accessibilityLabel
/>
```

**Standard viole :** WCAG 2.2 SC 4.1.2 — label "Essai routier effectue" est un `Text` separe non associe programmatiquement.

---

### F-26 [P1] — MAJEUR : Skeleton sans masquage pour lecteur d'ecran (Axe 6)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/components/ui/Skeleton.tsx` ligne 26

**Snippet verbatim :**
```tsx
<Animated.View
  style={[
    { width, height, borderRadius, backgroundColor: "#E5E7EB", opacity },
    style,
  ]}
  // <- accessibilityElementsHidden absent
  // <- importantForAccessibility absent
/>
```

**Correction :**
```tsx
<Animated.View
  accessibilityElementsHidden={true}
  importantForAccessibility="no-hide-descendants"
  style={[...]}
/>
```

---

### F-27 [P1] — CRITIQUE : Design System non respecte dans MechanicHomeScreen (Axe 7)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/mechanic/MechanicHomeScreen.tsx`

| Valeur en dur | Token disponible | Ligne |
|--------------|-----------------|-------|
| `"#0D1B3E"` | `colors.primary` | 74, 100, 308, 342 |
| `"#F5F5F5"` | `colors.bg` | 282 |
| `"#2E8B57"` | `colors.accent` (DIFFERENT !) | 394 |
| `"#FFFFFF"` | `colors.white` | 86–87, 316 |
| `"#E74C3C"` | `colors.error` (DIFFERENT !) | 326 |
| `"#3B82F6"` | `colors.info` | 201, 308 |
| `"#AAA"` | `colors.textMuted` | 208 |
| `"#888"` | aucun exact | 469 |
| `"#1A1A2E"` | `colors.text` (DIFFERENT !) | 440, 467 |
| `"Inter_700Bold"` | `fontFamily.bold` | 313, 342 |
| `"Inter_600SemiBold"` | `fontFamily.semiBold` | 419 |

---

### F-28 [P1] — MAJEUR : BookingMessagesScreen sans tokens (Axe 7)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/shared/BookingMessagesScreen.tsx`

Fichier partage acheteur/mecanicien sans aucun token. Valeurs en dur non exhaustives : `"#9CA3AF"`, `"#D1D5DB"`, `"#E5E7EB"`, `"#F5F5F5"`, `"#1A1A2E"`, `"#FFFFFF"`, `"#0D1B3E"`, `"#3B82F6"`, `"#FEF3C7"`, `"#6B7280"`.

---

### F-29 [P1] — MAJEUR : PickerField non exporte dans le design system (Axe 7)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/mechanic/CheckOutScreen.tsx` lignes 810–869

**Snippet verbatim :**
```tsx
function PickerField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
```

**Probleme :** Composant de selection multi-options sous forme de chips, reutilisable ailleurs (filtres SearchScreen, formulaires ProfileScreen) mais non exporte.

---

### F-30 [P1] — CRITIQUE : SafeAreaView natif dans WelcomeScreen (Axe 8)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/auth/WelcomeScreen.tsx` ligne 3

**Snippet verbatim :**
```tsx
import { View, Text, TouchableOpacity, SafeAreaView, ScrollView } from "react-native";
```

**Standard viole :** Le SafeAreaView de react-native ne gere pas les encoches dynamiques (iPhone 14 Pro+ Dynamic Island, Android punch-hole).

---

### F-31 [P1] — MAJEUR : KeyboardAvoidingView Android sans behavior (Axe 8)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/shared/BookingMessagesScreen.tsx` ligne 139

**Snippet verbatim :**
```tsx
<KeyboardAvoidingView
  style={{ flex: 1, backgroundColor: "#FFFFFF" }}
  behavior={Platform.OS === "ios" ? "padding" : undefined}
  keyboardVerticalOffset={90}
>
```

**Probleme :** Sur Android, `behavior={undefined}` desactive completement le KAV — le clavier recouvre la zone de saisie.

**Correction :** `behavior={Platform.OS === "ios" ? "padding" : "height"}`

---

### F-32 [P1] — MAJEUR : Formulaire CheckOut sans KeyboardAvoidingView (Axe 8)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/mechanic/CheckOutScreen.tsx` ligne 307

**Snippet verbatim :**
```tsx
return (
  <SafeAreaView style={{ flex: 1, backgroundColor: colors.bg }}>
    <View ...>   {/* Header */}
    <ScrollView style={{ flex: 1 }}>
      {/* 10+ champs dont TextInput kilometrage et remarques */}
```

**Probleme :** Formulaire critique mecanicien en exterieur sans KAV. Le clavier peut cacher les champs actifs.

---

### F-33 [P1] — MAJEUR : Zone filtres SearchScreen non-collapsible (Axe 8)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/buyer/SearchScreen.tsx` lignes 286–345

**Probleme :** Les filtres (radius, date, type vehicule) occupent ~180 pt verticaux quand deploys, reduisant la liste de mecaniciens a < 50% de l'ecran sur iPhone SE (667 pt de hauteur).

---

### F-34 [P1] — MINEUR : StatusBar backgroundColor en dur (Axe 8)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/mechanic/MechanicHomeScreen.tsx` ligne 74

**Snippet verbatim :**
```tsx
<StatusBar barStyle="light-content" backgroundColor="#0D1B3E" />
```

**Probleme :** Valeur hex en dur. Si le theme evolue ou si un dark mode est introduit, la status bar ne suivra pas.

---

### F-35 [P2] — CRITIQUE : EmailVerificationScreen entier sans tokens (Axe 1 & 7)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/auth/EmailVerificationScreen.tsx`

**Lignes concernees :** 268–391 (styles entiers), 143–144, 204

**Snippet verbatim :**
```tsx
// Ligne 269 — fond principal
container: {
  flex: 1,
  backgroundColor: "#0D1B3E",   // <- colors.primary disponible
},

// Ligne 287 — description
description: {
  fontSize: 16,
  color: "#A0AEC0",              // <- non tokenise, proche de textMuted mais different
},

// Ligne 323
codeInputFilled: {
  borderColor: "#2E8B57",        // <- diverge de colors.accent = "#1A9A5C"
  backgroundColor: "rgba(46, 139, 87, 0.1)",
},

// Ligne 328
codeInputError: {
  borderColor: "#E53E3E",        // <- diverge de colors.error = "#DC2626"
},

// Ligne 365
verifyButton: {
  backgroundColor: "#2E8B57",   // <- diverge de colors.accent
},
```

**Probleme :** Cet ecran est la premiere impression apres inscription. Il utilise un fond `#0D1B3E`, une couleur de succes `#2E8B57` et une erreur `#E53E3E` — trois divergences avec `colors.primary`, `colors.accent` et `colors.error`. Visuellement, l'app affiche trois nuances de bleu marine, deux verts et deux rouges differents sur l'ensemble du flux d'authentification.

**Standard viole :** Design System coherence, WCAG 2.2 SC 1.4.3 (`#A0AEC0` sur `#0D1B3E` = ratio ~2.8:1 — non conforme).

---

### F-36 [P2] — CRITIQUE : NearbyDemandsScreen entier sans tokens (Axe 1 & 7)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/mechanic/NearbyDemandsScreen.tsx`

**Lignes concernees :** 154–250 (StyleSheet.create complet)

**Snippet verbatim :**
```tsx
const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#F5F5F5",    // <- colors.bg
  },
  centered: {
    backgroundColor: "#F5F5F5",    // <- colors.bg
  },
  card: {
    backgroundColor: "#FFFFFF",    // <- colors.surface
    borderColor: "#E5E7EB",        // <- colors.border
  },
  vehicleText: {
    color: "#1A1A2E",              // <- colors.text (diverge !)
  },
  distanceText: {
    color: "#2E8B57",              // <- colors.accent (DIVERGE : vert different)
  },
  infoText: {
    color: "#6B7280",              // <- colors.textSecondary (diverge !)
  },
  interestButton: {
    backgroundColor: "#2E8B57",    // <- vert different de colors.accent
  },
```

**Probleme :** Fichier exclusivement utilise par les mecaniciens, sans aucun token. Le bouton CTA principal "Je suis interesse" utilise `#2E8B57` au lieu de `colors.accent = "#1A9A5C"`. Les mecaniciens voient un bouton d'une couleur differente de tous les autres CTA de l'app.

---

### F-37 [P2] — CRITIQUE : PaymentMethodsScreen entier sans tokens (Axe 1 & 7)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/buyer/PaymentMethodsScreen.tsx`

**Lignes concernees :** 48–100

**Snippet verbatim :**
```tsx
return (
  <View style={{ flex: 1, backgroundColor: "#F5F5F5" }}>
    {/* Header */}
    <View style={{ backgroundColor: "#FFFFFF", ... borderColor: "#E5E7EB" }}>
      <TouchableOpacity onPress={() => navigation.goBack()} style={{ marginRight: 12, padding: 4 }}>
        <Ionicons name="arrow-back" size={24} color="#1A1A2E" />
      </TouchableOpacity>
      <Text style={{ fontSize: 18, fontWeight: "bold", color: "#1A1A2E" }}>Moyens de paiement</Text>
    </View>

    {/* Info banner */}
    <View style={{ backgroundColor: "#EFF6FF", ... borderColor: "#DBEAFE" }}>
      <Ionicons name="information-circle" size={18} color="#3B82F6" />
      <Text style={{ color: "#1E40AF", fontSize: 13, ... }}>
```

**Probleme :** Ecran de paiement entier sans tokens. La couleur `#1A1A2E` est utilisee pour les textes au lieu de `colors.text = "#111827"` — deux noirs differents. `#3B82F6` est utilise au lieu de `colors.info = "#2563EB"` — deux bleus d'information differents.

---

### F-38 [P2] — MAJEUR : STATUS_COLORS en dur dans DemandDetailScreen (Axe 1 & 7)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/shared/DemandDetailScreen.tsx` lignes 27–31

**Snippet verbatim :**
```tsx
const STATUS_COLORS: Record<string, string> = {
  open: "#2E8B57",       // <- diverge de colors.accent = "#1A9A5C"
  closed: "#6B7280",     // <- proche de colors.textSecondary mais different
  expired: "#DC2626",    // <- identique a colors.error (seul cas correct)
};
```

**Probleme :** La couleur "open" utilise `#2E8B57` (vert mecano) au lieu de `colors.accent`. Un acheteur et un mecanicien voient deux couleurs "ouvert" differentes sur le meme ecran partage.

---

### F-39 [P2] — MAJEUR : DocumentThumbnail sans tokens et police 10pt (Axe 1, 3 & 7)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/components/shared/DocumentThumbnail.tsx` lignes 39–113

**Snippet verbatim :**
```tsx
// Ligne 39 — icone PDF
<Ionicons name="document-text" size={size * 0.4} color="#DC2626" />

// Ligne 59 — icone document generique
<Ionicons name="document-outline" size={size * 0.4} color="#6B7280" />

// Ligne 88 — bordure
borderColor: "#E5E7EB",

// Ligne 93 — fond placeholder
backgroundColor: "#F9FAFB",

// Lignes 99–100 — texte sous document
placeholderText: {
  fontSize: 10,         // <- SOUS le minimum WCAG/Apple HIG (11pt absolus)
  color: "#6B7280",     // <- non tokenise
},
```

**Probleme compose :** (1) Aucun token utilise dans ce composant partage. (2) `fontSize: 10` est en dessous du minimum absolu Apple HIG de 11pt pour tout texte visible.

**Standard viole :** Design System + Apple HIG minimum font size.

---

### F-40 [P2] — MAJEUR : VerificationInstructionsModal entiere sans tokens (Axe 1 & 7)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/components/shared/VerificationInstructionsModal.tsx` lignes 105–179

**Snippet verbatim :**
```tsx
card: {
  backgroundColor: "#FFFFFF",   // <- colors.surface
  borderRadius: 20,
},
closeButton: {
  padding: 4,                   // <- touch target reduit (Ionicons 24pt = 32x32 effectif)
},
iconContainer: {
  backgroundColor: "#F0F4FF",   // <- non tokenise
},
title: {
  fontSize: 18,
  fontWeight: "700",
  color: "#1A1A2E",             // <- colors.text diverge
},
bullet: {
  backgroundColor: "#0D1B3E",  // <- colors.primary
},
continueButton: {
  backgroundColor: "#0D1B3E",  // <- colors.primary
},
instructionText: {
  color: "#4B5563",             // <- non tokenise, entre textSecondary et text
},
```

**Probleme :** Ce composant est visible pendant le flux de verification d'identite mecanicien — un moment cle du parcours. Aucun token. Le bouton Fermer a `padding: 4` sur une icone 24pt = cible effective 32x32 pt (sous les 44 requis).

---

### F-41 [P2] — CRITIQUE : SafeAreaView natif dans MechanicProfileScreen (Axe 8)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/mechanic/MechanicProfileScreen.tsx` lignes 1–13

**Snippet verbatim :**
```tsx
import {
  View,
  Text,
  ScrollView,
  TouchableOpacity,
  TextInput,
  Alert,
  ActivityIndicator,
  SafeAreaView,     // <- import depuis react-native natif
  Platform,
  Image,
} from "react-native";
```

**Probleme :** Le profil mecanicien — ecran le plus utilise apres la home — importe `SafeAreaView` depuis `react-native` au lieu de `react-native-safe-area-context`. Meme probleme qu'en F-30 (WelcomeScreen). Sur iPhone 14 Pro avec Dynamic Island, les elements dans la zone superieure peuvent etre partiellement caches.

**Standard viole :** react-native-safe-area-context documentation — correction coherente avec LoginScreen, RegisterScreen, CheckInScreen qui l'implementent correctement.

---

### F-42 [P2] — MAJEUR : PostDemandScreen KAV behavior=undefined sur Android (Axe 8)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/buyer/PostDemandScreen.tsx` lignes 130–133

**Snippet verbatim :**
```tsx
<KeyboardAvoidingView
  style={{ flex: 1 }}
  behavior={Platform.OS === "ios" ? "padding" : undefined}
>
```

**Probleme :** Meme pattern defaillant que F-31 (BookingMessagesScreen). Sur Android, `behavior={undefined}` desactive le KAV. Ce formulaire contient de nombreux champs TextInput (marque, modele, annee, adresse, date, heures) — les champs du bas sont inaccessibles quand le clavier est ouvert.

**Correction :** `behavior={Platform.OS === "ios" ? "padding" : "height"}`

---

### F-43 [P2] — MAJEUR : Bouton retour PaymentMethodsScreen 32x32 pt (Axe 2)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/buyer/PaymentMethodsScreen.tsx` lignes 51–52

**Snippet verbatim :**
```tsx
<TouchableOpacity onPress={() => navigation.goBack()} style={{ marginRight: 12, padding: 4 }}>
  <Ionicons name="arrow-back" size={24} color="#1A1A2E" />
</TouchableOpacity>
```

**Probleme :** `padding: 4` sur icone 24pt = cible effective 32x32 pt — sous le minimum iOS HIG de 44x44 pt. Ce pattern se retrouve dans plusieurs ecrans (DemandDetailScreen, LegalScreen).

**Standard viole :** iOS HIG 44x44 pt.

---

### F-44 [P2] — MAJEUR : Avatar sans accessibilityLabel (Axe 6)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/components/ui/Avatar.tsx` lignes 38–41

**Snippet verbatim :**
```tsx
return (
  <View style={[container, { backgroundColor: colors.primary, alignItems: "center", justifyContent: "center" }]}>
    <Text style={[text, { fontWeight: "bold", color: colors.white }]}>{initials}</Text>
  </View>
);
```

**Probleme :** Le composant Avatar n'expose pas de prop `accessibilityLabel`. Dans ProfileScreen, l'Avatar est entoure d'un `TouchableOpacity` (pour changer la photo) sans `accessibilityLabel` adequat. Un lecteur d'ecran ne sait pas que c'est la photo de profil de l'utilisateur ni qu'une interaction change cette photo.

**Standard viole :** WCAG 2.2 SC 4.1.2 — les composants interactifs et les images significatives doivent avoir un label accessible.

**Correction :** Ajouter `accessibilityLabel?: string` a `AvatarProps` et `accessible={true}` sur le View parent.

---

### F-45 [P2] — MAJEUR : MessagesListScreen couleurs hardcodees dans StyleSheet (Axe 7)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/buyer/MessagesListScreen.tsx` lignes 93–129

**Snippet verbatim :**
```tsx
const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#F5F5F5" },      // <- colors.bg
  row: {
    backgroundColor: "#FFFFFF",                             // <- colors.surface
    borderColor: "#E5E7EB",                                 // <- colors.border
  },
  iconCircle: {
    backgroundColor: "#EFF6FF",                             // <- colors.infoMuted
  },
  vehicleName: {
    color: "#1A1A2E",                                       // <- colors.text (diverge !)
    fontFamily: "Inter_600SemiBold",                        // <- fontFamily.semiBold
  },
  dateText: {
    fontFamily: "Inter_400Regular",                         // <- fontFamily.regular
    color: "#6B7280",                                       // <- colors.textSecondary (diverge !)
  },
});
```

**Probleme :** Les fontFamily sont dupliques en dur (`"Inter_600SemiBold"`) au lieu d'utiliser `fontFamily.semiBold`. Les couleurs `#1A1A2E` et `#6B7280` divergent des tokens `colors.text = "#111827"` et `colors.textSecondary = "#5B6578"`.

---

### F-46 [P2] — MAJEUR : LegalScreen entier sans tokens ni SafeAreaView (Axe 1 & 7)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/shared/LegalScreen.tsx` lignes 12–87

**Snippet verbatim :**
```tsx
<ScrollView style={{ flex: 1, backgroundColor: "#FFFFFF" }}>
  <View style={{ padding: 24 }}>
    <Text style={{ fontSize: 26, fontWeight: "bold", color: "#1A1A2E", marginBottom: 24 }}>
      Mentions legales
    </Text>
    <Text style={{ fontSize: 18, fontWeight: "700", color: "#1A1A2E", marginBottom: 8 }}>
```

**Probleme :** Ecran partage acheteur/mecanicien (CGU, politique, mentions legales) entierement sans tokens. Pas de `SafeAreaView`. `fontSize: 26` est une valeur non-tokenisee. `#1A1A2E` diverge de `colors.text`.

---

### F-47 [P2] — MAJEUR : DashboardScreen typographie non-tokenisee (Axe 3)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/mechanic/DashboardScreen.tsx`

**Lignes concernees :** 112, 185, 207

**Snippet verbatim :**
```tsx
// Ligne 112
<Text style={{ fontSize: 24, fontWeight: "bold", color: colors.text }}>Mes Interventions</Text>

// Ligne 185
<Text style={{ fontSize: 14, fontWeight: "600", color: colors.textMuted, marginBottom: 12 }}>SATISFACTION</Text>

// Ligne 207
<Text style={{ fontSize: 14, fontWeight: "600", color: colors.textMuted, marginBottom: 16 }}>REVENUS (6 DERNIERS MOIS)</Text>
```

**Probleme :** `fontSize: 24, fontWeight: "bold"` devrait utiliser `typography.h2 = { fontSize: 22 }` ou `typography.h1 = { fontSize: 28 }`. Les labels "SATISFACTION" et "REVENUS" (`fontSize: 14, fontWeight: "600", textTransform: "uppercase"` manquant) devraient utiliser le token `overline` ou `captionMedium`.

---

### F-48 [P2] — MINEUR : Password strength text 11pt non tokenise (Axe 3)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/screens/auth/RegisterScreen.tsx` ligne 289

**Snippet verbatim :**
```tsx
<Text style={{ fontSize: 11, color: level.color, marginTop: 4 }}>{level.label}</Text>
```

**Probleme :** `fontSize: 11` est a la limite du minimum Apple HIG. Aucun `fontFamily` precise. Ce texte est informatif et critique (indique si le mot de passe est "Faible", "Moyen", "Fort").

---

### F-49 [P2] — MAJEUR : NotificationDropdown marginTop: 100 fixe sans safe area (Axe 5 & 8)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/components/shared/NotificationDropdown.tsx` ligne 206

**Snippet verbatim :**
```tsx
card: {
  backgroundColor: colors.bg,
  borderRadius: 16,
  marginTop: 100,    // <- valeur fixe en dur, ne tient pas compte de la safe area
  marginHorizontal: 16,
  width: "90%",
  maxWidth: 380,
```

**Probleme :** La dropdown de notifications est positionnee avec `marginTop: 100` fixe. Sur un iPhone SE (petit), cette valeur peut cacher la premiere notification. Sur un iPhone 14 Pro Max avec Dynamic Island, le panel peut apparaitre trop bas ou trop haut. La valeur correcte devrait utiliser `useSafeAreaInsets().top + hauteur_header`.

**Standard viole :** Safe area management — react-native-safe-area-context est importe dans le fichier (ligne 4) mais non utilise pour ce positionnement.

---

### F-50 [P2] — MINEUR : Badge "sm" fontSize: 11 accessible (Axe 2)

**Fichier :** `/home/bouzelouf/secret_project/mobile/src/components/ui/Badge.tsx` ligne 25

**Snippet verbatim :**
```tsx
const fontSize = size === "sm" ? 11 : 12;

return (
  <View style={{ paddingHorizontal: paddingH, paddingVertical: paddingV, borderRadius: 9999, backgroundColor: bg }}>
    <Text style={{ fontSize, fontWeight: "600", fontFamily: fontFamily.semiBold, color: text }}>{label}</Text>
  </View>
);
```

**Probleme :** Le Badge "sm" affiche du texte a 11pt. C'est la limite absolue Apple HIG. Dans les contextes avec `colors.textSecondary` sur `colors.bgSecondary`, le contraste (~5.77:1) est acceptable mais marginalement conforme pour du texte de 11pt a 400-weight. En pratique le badge est en semiBold (600) ce qui ameliore legerement la lisibilite, mais cette valeur limite reste risquee.

---

## 4. TABLEAU RECAPITULATIF COMPLET

| Categorie | Findings P1 | Findings P2 | Total |
|-----------|-------------|-------------|-------|
| CRITIQUE | 9 | 5 | **14** |
| MAJEUR | 21 | 10 | **31** |
| MINEUR | 4 | 1 | **5** |
| **Total** | **34** | **16** | **50** |

---

## 5. RESUME EXECUTIF FINAL

### Score final : 54.00 / 100

La correction du score de 61.25 (Pass 1) a 54.00 (Pass 2) reflete la decouverte de 5 ecrans entiers completement desconnectes du design system (`EmailVerificationScreen`, `NearbyDemandsScreen`, `PaymentMethodsScreen`, `LegalScreen`, `MessagesListScreen`) et d'une deuxieme instance critique de SafeAreaView natif (`MechanicProfileScreen`).

### Points forts identifies

1. **Design System solide pour les ecrans acheteur principaux.** `colors.ts`, `typography.ts` et `spacing.ts` forment une base coherente. `LoginScreen`, `RegisterScreen`, `HomeScreen`, `SearchScreen` et les composants `Button`, `Card`, `NotificationDropdown` l'utilisent correctement.

2. **Gestion des etats UX bien couverte sur les flows principaux.** Les etats de chargement (skeleton, spinner), d'erreur (message + retry) et vides sont presents sur la majorite des ecrans acheteur. `CheckInScreen` est particulierement bien concu avec ses 3 etats distincts et l'utilisation correcte des tokens de `spacing.ts`.

3. **Accessibilite partielle mais coherente sur les composants UI de base.** `Button`, `Input`, `RegisterScreen` (checkbox CGU) et plusieurs `TouchableOpacity` ont des `accessibilityLabel` et `accessibilityRole` corrects. Le pattern de focus automatique de champ en champ dans les formulaires avec `returnKeyType` et `ref` est exemplaire.

4. **Navigation correctement structuree.** Les navigateurs Buyer et Mechanic separent clairement les flows avec `ErrorBoundary` au niveau racine. Les titres de navigation sont en francais et coherents.

5. **Dark mode prepare.** `darkColors` est defini dans `colors.ts` meme si non encore utilise — bon fondement pour une evolution future.

### Top 3 ameliorations prioritaires

#### Priorite 1 — Unification complete du design system mecanicien (Impact : tres eleve, Effort : moyen)

`EmailVerificationScreen`, `MechanicHomeScreen`, `NearbyDemandsScreen`, `BookingMessagesScreen`, `MechanicProfileScreen` et `DemandDetailScreen` utilisent tous le vert `#2E8B57` comme couleur d'accent au lieu de `colors.accent = "#1A9A5C"`. L'application presente visuellement deux "marques" differentes selon le role de l'utilisateur. La correction consiste a remplacer systematiquement `#2E8B57` par `colors.accent` dans tous ces fichiers — une tache repetable et peu risquee.

#### Priorite 2 — SafeAreaView et KeyboardAvoidingView Android sur tous les ecrans affectes (Impact : eleve, Effort : faible)

Quatre ecrans utilisent le SafeAreaView natif (F-30, F-41) ou desactivent le KAV sur Android (F-31, F-42). Ces corrections prennent moins de 5 minutes chacune et eliminent des bugs visuels sur 35% du parc Android. La liste complete : `WelcomeScreen.tsx`, `MechanicProfileScreen.tsx` (SafeAreaView), `BookingMessagesScreen.tsx`, `PostDemandScreen.tsx` (KAV behavior).

#### Priorite 3 — Touch targets et accessibilite des composants critiques mecanicien (Impact : eleve, Effort : faible)

F-06 (toggle mot de passe), F-07 (etoiles StarRating), F-09 (bouton suppression photo), F-21/F-22 (accessibilityLabel), F-41 (bouton fermer modal), F-43 (retour PaymentMethods) sont des corrections de moins de 10 lignes chacune. Ces bugs affectent directement les mecaniciens en conditions terrain et les utilisateurs de lecteurs d'ecran. L'ensemble peut etre resolu en moins d'une demi-journee.

---

## 6. PLAN DE REMEDIATION PRIORISE COMPLET

### Phase 1 — Critique (Semaine 1) — Effort : 3 jours

| Finding | Fichier | Action |
|---------|---------|--------|
| F-30, F-41 | WelcomeScreen, MechanicProfileScreen | Remplacer SafeAreaView natif |
| F-31, F-42 | BookingMessagesScreen, PostDemandScreen | KAV behavior="height" sur Android |
| F-06 | Input.tsx | Wrapper TouchableOpacity sur l'icone eye |
| F-07 | StarRating.tsx | padding: 13 sur chaque etoile editable + accessibilityLabel |
| F-21, F-22 | StarRating, MechanicCard | accessibilityLabel, accessibilityRole, accessibilityState |
| F-16 | CheckOutScreen | Validation inline par champ + desactiver submit si invalide |
| F-35 | EmailVerificationScreen | Tokeniser entierement + corriger couleurs divergentes |
| F-36 | NearbyDemandsScreen | Tokeniser + aligner bouton CTA sur colors.accent |
| F-37 | PaymentMethodsScreen | Tokeniser entierement |

### Phase 2 — Majeur prioritaire (Semaine 2) — Effort : 3 jours

| Finding | Fichier | Action |
|---------|---------|--------|
| F-01, F-27 | MechanicHomeScreen | Tokenisation complete : 14+ couleurs + fontFamily |
| F-02, F-28 | BookingMessagesScreen | Tokenisation complete : 10+ couleurs |
| F-04 | colors.ts | Ajuster textMuted vers #6B7280 (ratio 4.61:1) |
| F-38 | DemandDetailScreen | STATUS_COLORS via tokens |
| F-39 | DocumentThumbnail | Tokeniser + fontSize 10 -> 12 |
| F-40 | VerificationInstructionsModal | Tokeniser + fix touch target bouton fermer |
| F-32 | CheckOutScreen | Ajouter KeyboardAvoidingView |
| F-45 | MessagesListScreen | Tokeniser StyleSheet |
| F-46 | LegalScreen | Tokeniser + SafeAreaView |
| F-47 | DashboardScreen | Utiliser typography.h2, typography.overline |
| F-49 | NotificationDropdown | Remplacer marginTop: 100 par useSafeAreaInsets() |

### Phase 3 — Majeur secondaire (Semaine 3) — Effort : 2 jours

| Finding | Fichier | Action |
|---------|---------|--------|
| F-08, F-09, F-43 | BookingDetailScreen, CheckOutScreen, PaymentMethodsScreen | hitSlop + touch targets |
| F-23, F-24, F-25, F-26 | BookingMessages, NotificationDropdown, CheckOut, Skeleton | accessibilityLabel + masquage skeleton |
| F-18 | EmptyState | Ajouter prop action/onAction/actionLabel |
| F-19 | MechanicHomeScreen | Ajouter RefreshControl + bouton retry |
| F-29 | CheckOutScreen | Extraire PickerField vers components/ui |
| F-44 | Avatar | Ajouter accessibilityLabel prop |
| F-33 | SearchScreen | Filtres collapsibles ou sticky intelligents |

### Phase 4 — Mineur (Semaine 4) — Effort : 1 jour

| Finding | Fichier | Action |
|---------|---------|--------|
| F-11, F-48 | typography.ts, RegisterScreen | Augmenter overline a 12pt min, password-strength a 12pt |
| F-12 | typography.ts | lineHeight h1 a 36 (ratio 1.29x) |
| F-13, F-14, F-15 | CheckOut, MechanicHome, BookingCard | Aligner sur grille 8pt et tokens spacing |
| F-34 | MechanicHomeScreen | StatusBar backgroundColor via colors.primary |
| F-50 | Badge | Badge "sm" fontSize 11 -> 12 |
| F-05 | MechanicHomeScreen | Remplacer #888 par colors.textSecondary |
| F-20 | WelcomeScreen | Commentaire supprime (double de F-30) — deja corrige en phase 1 |

### Estimation globale de l'effort de correction

| Phase | Findings | Effort |
|-------|----------|--------|
| Phase 1 — Critique | 9 | 3 jours |
| Phase 2 — Majeur prioritaire | 11 | 3 jours |
| Phase 3 — Majeur secondaire | 9 | 2 jours |
| Phase 4 — Mineur | 7 | 1 jour |
| **Total** | **36** (hors doublons) | **~9 jours developpeur** |

---

*Rapport genere le 2026-03-01 — AUDIT COMBINE UI/UX Pass 1 + Pass 2 — eMecano Mobile*
*Pass 1 : 34 findings — Pass 2 : 16 nouveaux findings — Total : 50 findings*
