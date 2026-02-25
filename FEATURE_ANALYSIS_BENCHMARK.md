# ANALYSE FEATURES : BENCHMARKING & RECOMMANDATIONS eMecano

**Date :** 2026-02-19
**Auteur :** Claude (Analyse automatisee)
**Version :** 1.0

---

## TABLE DES MATIERES

1. [Resume Executif](#1-resume-executif)
2. [Methodologie](#2-methodologie)
3. [Inventaire Complet eMecano](#3-inventaire-complet-emecano)
4. [Analyse des Concurrents](#4-analyse-des-concurrents)
5. [Tableau Comparatif (50+ Features)](#5-tableau-comparatif-50-features)
6. [Analyse des Gaps](#6-analyse-des-gaps)
7. [Analyse UX/UI](#7-analyse-uxui)
8. [Recommandations Priorisees (25)](#8-recommandations-priorisees-25)
9. [Features a Ameliorer (12)](#9-features-a-ameliorer-12)
10. [Features a Supprimer ou Simplifier](#10-features-a-supprimer-ou-simplifier)
11. [Idees d'Innovation (7)](#11-idees-dinnovation-7)
12. [Roadmap 3-6 Mois](#12-roadmap-3-6-mois)
13. [Insights Business](#13-insights-business)
14. [Sources](#14-sources)

---

## 1. RESUME EXECUTIF

### Positionnement eMecano
eMecano est une marketplace mobile-first connectant des mecaniciens independants avec des acheteurs de vehicules d'occasion en France. Le service propose une inspection avant achat avec rapport PDF, paiement securise via Stripe Connect, messagerie integree, et gestion complete du cycle de vie des reservations.

### Verdict Global
eMecano possede une **base technique solide** (auth JWT, GDPR, Stripe Connect, GPS tracking, push notifications) mais presente des **gaps significatifs sur le coeur de metier** (inspection) par rapport aux leaders du marche. Le checklist a 9 items est insuffisant face aux 150-200 points de controle des concurrents. Les principales opportunites sont :

- **Court terme** : Enrichir le checklist d'inspection (x10-20 items)
- **Moyen terme** : Ajouter historique vehicule, diagnostic OBD, estimation de valeur
- **Long terme** : IA d'analyse photo, inspection video live, inspection VE

### Score de Maturite par Domaine

| Domaine | eMecano | Moyenne Concurrents | Ecart |
|---------|---------|--------------------|----|
| Inspection (profondeur) | 3/10 | 8/10 | -5 |
| Rapport qualite | 6/10 | 8/10 | -2 |
| UX Booking | 7/10 | 7/10 | 0 |
| Paiement | 8/10 | 6/10 | +2 |
| Communication | 7/10 | 5/10 | +2 |
| GPS/Tracking | 8/10 | 4/10 | +4 |
| GDPR/Legal | 9/10 | 5/10 | +4 |
| Admin/Ops | 7/10 | 6/10 | +1 |
| Garantie post-achat | 0/10 | 7/10 | -7 |
| Historique vehicule | 0/10 | 8/10 | -8 |

---

## 2. METHODOLOGIE

### Sources analysees
- **10 concurrents directs** analyses en profondeur (sites web, Trustpilot, presse)
- **Code source eMecano** : 40+ fichiers backend, 24 ecrans mobile, 27 migrations DB
- **Standards UX** : Baymard Institute, Booking UX Best Practices 2025
- **Tendances marche** : IA inspection, VE, video live

### Perimetre geographique
- **France** (marche primaire) : AutoJust, Trustoo, MonInspection.fr, Chekoto, WheelScanner
- **UK** (reference) : ClickMechanic, Fixter
- **US** (innovation) : YourMechanic, Lemon Squad, Wrench

---

## 3. INVENTAIRE COMPLET eMecano

### 3.1 Features Actuelles — Backend

#### Authentification & Securite
| Feature | Detail |
|---------|--------|
| Inscription | Email + mot de passe, roles buyer/mechanic |
| Verification email | JWT token single-use via Resend |
| Login | Access token (15min) + refresh token (7j) |
| Rotation tokens | Refresh token blackliste a chaque rotation |
| Lockout | 5 tentatives/15min par email (Redis + fallback memoire) |
| Timing attack prevention | Comparaison constante + dummy hash si email inconnu |
| Forgot/Reset password | Token email single-use avec blacklist anti-TOCTOU |
| Change password | Invalide tous les tokens anterieurs via `password_changed_at` |
| Push token | Enregistrement/suppression ExponentPushToken |
| GDPR Delete | Anonymisation complete (messages, reviews, PII) |
| GDPR Export | JSON complet (profil, bookings, reviews, messages, notifications) |

#### Booking & Paiement
| Feature | Detail |
|---------|--------|
| Creation booking | Stripe PaymentIntent manual capture + slot splitting |
| Buffer zone | 15 min entre creneaux adjacents |
| Advance minimum | 2h avant rendez-vous |
| Accept/Refuse | Mecanicien avec raison + proposition alternative |
| Auto-cancel | Timeout 2h si non accepte (scheduler) |
| Check-in code | Code 4 chiffres, max 5 tentatives, expire 15min |
| Check-in tolerance | +/- 30min autour du RDV |
| Check-out | Photos (plaque + odometre + max 10 defauts) + checklist + PDF |
| Validation | Buyer valide ou ouvre dispute (avec photos si besoin) |
| Annulation | Politique degradee : 100% (>24h), 50% (12-24h), 0% (<12h) |
| GPS tracking | Position mecanicien en temps reel |
| Paiement differe | Capture 2h apres validation buyer |
| Idempotency keys | Sur toutes les operations Stripe (avec timestamp) |
| Contact disclosure | Telephone visible quand confirme et <2h du RDV |
| Plate masking | Plaque masquee pour mecanicien sur bookings termines |

#### Inspection
| Feature | Detail |
|---------|--------|
| Checklist | 9 items : brakes, tires, fluids, battery, suspension, body, exhaust, lights, test_drive |
| Statuts composants | ok/warning/critical (ou variantes par type) |
| Essai routier | Boolean + comportement (normal/suspect/dangerous) |
| Remarques | Texte libre max 500 caracteres |
| Recommendation | BUY / NEGOTIATE / AVOID |
| Photos | Plaque (obligatoire), odometre (obligatoire), max 10 photos defauts |
| Rapport PDF | WeasyPrint HTML->PDF, uploade sur R2, timeout 30s |
| ID rapport | Format #EM-XXXXXXXX |

#### Communication
| Feature | Detail |
|---------|--------|
| Chat in-booking | Disponible en CONFIRMED/AWAITING_CODE/CHECK_IN_DONE |
| Messages templates | 12 buyer + 12 mecanicien (francais) en 4 categories |
| Messages custom | Max 30 par user par booking, contact masking |
| Contact masking | Telephone, email, reseaux sociaux rediges |
| Push notifications | 10 types via Expo Push API |
| Email notifications | Reminders 24h/2h, verification, reset password |

#### Reviews & Referrals
| Feature | Detail |
|---------|--------|
| Review buyer->mecanicien | Publique, rating + commentaire |
| Review mecanicien->buyer | Privee |
| Rating agrege | Mis a jour atomiquement (race-condition safe) |
| Code parrainage | Format EMECANO-XXXXXX, mecaniciens uniquement |

#### Admin & Ops
| Feature | Detail |
|---------|--------|
| Stats plateforme | Users, bookings, revenue, disputes |
| Revenue analytics | Breakdown quotidien sur N jours |
| Gestion users | Liste, detail, suspension (30j) |
| Verification identite | Workflow upload -> review -> approve/reject |
| Gestion disputes | Liste, resolution (buyer ou mechanic) |
| Audit log | Toutes actions admin loguees |
| Scheduler | 10 cron jobs + 1 one-shot (payment release) |
| Prometheus metrics | HTTP, bookings, payments, stripe, scheduler |
| Sentry | Error tracking en production |

#### Mecanicien
| Feature | Detail |
|---------|--------|
| Profil | Photo, CV, diplomes, ville, rayon, vehicules acceptes |
| Verification identite | Piece d'identite + selfie + review admin |
| Disponibilites | Creneaux avec detection overlap, max 100 non-reserves |
| Search geo | Bounding-box + Haversine, rayon 1-200km |
| Stats | Missions, earnings, rating, acceptance rate |
| Service location | Mobile / garage / both |
| No-show tracking | Compteur + penalite + reset hebdomadaire |
| Stripe Connect | Express account, onboarding, dashboard |

### 3.2 Features Actuelles — Mobile (24 ecrans)

| Zone | Ecrans | Fonctionnalites cles |
|------|--------|---------------------|
| Auth (5) | Welcome, Login, Register, EmailVerification, ForgotPassword | Onboarding, connexion, inscription |
| Buyer (9) | Home, Search, MechanicDetail, BookingConfirm, BookingDetail, CheckIn, Validation, MyBookings, MessagesListScreen, Profile | Recherche geo, booking, check-in, validation |
| Mechanic (6) | MechanicHome, Dashboard, MechanicBookingDetail, CheckOut, Availability, MechanicProfile | Gestion bookings, checkout inspection, disponibilites |
| Shared (4+) | BookingMessages, ChangePassword, Legal, Privacy, Terms | Chat, paramètres |

### 3.3 Stack Technique
- **Backend** : FastAPI 0.115.6, SQLAlchemy async, PostgreSQL 16, Redis 7
- **Mobile** : React Native (Expo SDK), Zustand, WebView+Leaflet
- **Infra** : Render.com, Cloudflare R2, Stripe Connect, Resend, Sentry, Prometheus
- **Tests** : 457 passed, 85.21% coverage, CI GitHub Actions

---

## 4. ANALYSE DES CONCURRENTS

### 4.1 AutoJust (France) — Leader historique

| Critere | Detail |
|---------|--------|
| **Fondation** | ~2019, French Tech Paris-Saclay |
| **Inspection** | 200 points de controle |
| **Couverture** | France, Belgique, Luxembourg, Suisse, Allemagne |
| **Inspecteurs** | 500+ professionnels certifies |
| **Prix** | ~EUR249-300 (selon vehicule) |
| **Rapport** | Digital detaille avec historique vehicule |
| **Garantie** | "Garantie Serenite" 6 mois / 6000 km, 8 organes, jusqu'a 1000 EUR/intervention |
| **Historique** | Retrace le vehicule de sa sortie d'usine (km trafique, accidents, etc.) |
| **Negociation** | Aide a la negociation du prix incluse |
| **Trustpilot** | Avis positifs majoritaires |
| **Forces** | Couverture europeenne, garantie mecanique, historique complet |
| **Faiblesses** | Trafic web en baisse (-18.22%), pas d'app mobile dediee |

### 4.2 Trustoo (France) — Le plus complet

| Critere | Detail |
|---------|--------|
| **Fondation** | 2018, Lyon |
| **Inspection** | 200+ points de controle |
| **Couverture** | France + 7 pays europeens (DE, BE, CH, ES, IT, LU, NL) |
| **Inspecteurs** | 800+ specialistes |
| **Prix** | EUR199-349 TTC (luxe/collection sur devis) |
| **Rapport** | Digital immediat, ~50 photos, commentaires expert, avis achat |
| **Garantie** | 3 mois inclus (RPM Warranty), prolongeable 9.99 EUR/mois sans limite |
| **Delai** | 24-48h dans 95% des cas |
| **Innovation** | **Lucius AI** (2025) : inspection automatisee par IA pour flottes/revendeurs |
| **Trustpilot** | 1148+ avis, tres positifs |
| **Forces** | Couverture 8 pays, IA, ~50 photos, garantie prolongeable, volume |
| **Faiblesses** | Pas d'app mobile native, prix eleve pour luxe |

### 4.3 MonInspection.fr (ex-MonPoteMecano) — Focus tech

| Critere | Detail |
|---------|--------|
| **Inspection** | 200+ points de controle |
| **Couverture** | France, Belgique, Suisse |
| **Prix** | EUR188-300 TTC |
| **Rapport** | Digital detaille avec diagnostic electronique |
| **Garantie** | Jusqu'a 12 mois |
| **Innovation** | **Diagnostic electronique** (codes defaut OBD), **Inspection VE** (batterie SoH avec EV Market) |
| **Satisfaction** | 98% |
| **Forces** | Diagnostic electronique, VE/batterie, garantie longue |
| **Faiblesses** | Couverture limitee a 3 pays |

### 4.4 Chekoto (France) — Freemium innovant

| Critere | Detail |
|---------|--------|
| **Modele** | Freemium : QCM gratuit (note /20) + expertise payante |
| **Inspecteurs** | 600 experts agrees |
| **Prix** | Gratuit (QCM) / EUR249-299 (expertise) |
| **Garantie** | 3 mois base, extensible 6-60 mois (pannes mecaniques sans franchise) |
| **Vehicules** | Voitures, motos, VU, camping-cars |
| **B2B** | Badge certification pour garages partenaires (annonces VO) |
| **Forces** | Modele freemium unique, camping-cars, garantie longue, B2B |
| **Faiblesses** | Moins de notoriete que AutoJust/Trustoo |

### 4.5 WheelScanner (France) — Low-cost

| Critere | Detail |
|---------|--------|
| **Modele** | Reseau d'inspecteurs en contact direct |
| **Formules** | Standard + Premium |
| **Couverture** | France + USA (wheelscanner.com) |
| **Rapport** | Electronique personnalise avec diagnostic usure |
| **Forces** | Prix competitif, transparence, double presence FR/US |
| **Faiblesses** | Moins de features avancees, pas de garantie mentionnee |

### 4.6 ClickMechanic (UK) — Marketplace reference

| Critere | Detail |
|---------|--------|
| **Modele** | Marketplace mecaniciens mobiles |
| **Inspection** | 185 points (Basic), 3 niveaux (Basic/Standard/Premium) |
| **Prix** | GBP79-137 (50% moins cher que AA/RAC) |
| **Booking** | Same-day / next-day, creneau 2h |
| **Rapport** | Email avec photos (Premium uniquement) |
| **Support** | 24/7 |
| **Partenariat** | Motors.co.uk (2025) — inspection depuis les annonces |
| **Mecaniciens** | 1600+ |
| **Forces** | 3 niveaux de service, same-day, partenariat classifieds |
| **Faiblesses** | Pas de garantie, pas de Cat S/N ou imports, pas de warranty |

### 4.7 Fixter (UK) — Premium all-in-one

| Critere | Detail |
|---------|--------|
| **Modele** | Plateforme garage management |
| **Prix PPI** | GBP99 (flat, tous modeles) |
| **Garantie** | 12 mois pieces et main d'oeuvre |
| **Service** | Collection/delivery gratuite, top 5% garages |
| **Trustpilot** | 7137+ avis |
| **Forces** | Warranty 12 mois, collection gratuite, services multiples (MOT, entretien, reparation) |
| **Faiblesses** | Focus UK uniquement, pas de marketplace mecaniciens independants |

### 4.8 YourMechanic (US) — Scale reference

| Critere | Detail |
|---------|--------|
| **Modele** | Marketplace mecaniciens mobiles |
| **Inspection** | 150 points + diagnostic OBD + photos |
| **Prix** | USD150-250 (~USD200 moyenne) |
| **Couverture** | 2000+ villes US |
| **Disponibilite** | 7j/7, 7h-21h |
| **Mecaniciens** | 10+ ans experience moyenne, ASE certifies, background check |
| **Rapport** | Digital avec photos + estimation couts reparation |
| **Forces** | Scale massive, estimation reparations, profils detailles mecaniciens |
| **Faiblesses** | US uniquement, pas de garantie post-achat |

### 4.9 Lemon Squad (US) — Innovation live

| Critere | Detail |
|---------|--------|
| **Modele** | Service d'inspection nationale |
| **Inspection** | 150+ points, bumper-to-bumper |
| **Prix Standard** | USD119.95 |
| **Lemon Squad LIVE** | USD59.99 — inspection video en direct avec expert certifie |
| **EV** | Inspections VE specialisees (Tesla, Rivian, Lucid, etc.) |
| **Couverture** | 50 etats US (incl. Alaska/Hawaii) |
| **Partenariat** | Cars & Bids (encheres VO en ligne) |
| **Forces** | **Live video inspection** (innovation unique), EV, couverture totale US |
| **Faiblesses** | Pas de week-end, delai 2 jours ouvrables |

### 4.10 Wrench (US) — Video chat

| Critere | Detail |
|---------|--------|
| **Modele** | Mecaniciens mobiles ASE certifies |
| **Innovation** | Video chat inspection avec mecanicien |
| **Garantie** | 12 mois / 12 000 miles |
| **Forces** | Garantie longue, video chat |

---

## 5. TABLEAU COMPARATIF (50+ FEATURES)

### Legende
- **Y** = Present / Oui
- **N** = Absent / Non
- **P** = Partiel / Basique
- **?** = Non confirme

| # | Feature | eMecano | AutoJust | Trustoo | MonInsp. | Chekoto | WheelSc. | ClickMech | Fixter | YourMech | LemonSq |
|---|---------|---------|----------|---------|----------|---------|----------|-----------|--------|----------|---------|
| | **INSPECTION** | | | | | | | | | | |
| 1 | Points de controle | 9 | 200 | 200+ | 200+ | 50(free)+200 | ~100 | 185 | ~100 | 150 | 150+ |
| 2 | Essai routier | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y |
| 3 | Diagnostic OBD/electronique | N | P | P | **Y** | P | N | Y | Y | Y | P |
| 4 | Historique vehicule (km, accidents) | N | **Y** | **Y** | Y | P | N | N | N | N | N |
| 5 | Estimation valeur marche | N | **Y** | P | P | N | P | N | N | **Y** | N |
| 6 | Estimation cout reparations | N | P | P | P | N | P | N | N | **Y** | N |
| 7 | Aide a la negociation | N | **Y** | **Y** | P | N | **Y** | N | N | P | N |
| 8 | Photos dans rapport | Y (12 max) | Y (20+) | Y (~50) | Y | Y | Y | Y(Premium) | Y | Y | Y |
| 9 | Inspection VE (batterie SoH) | N | N | N | **Y** | N | N | P | P | P | **Y** |
| 10 | Inspection moto | Y | N | P | P | N | N | N | N | N | N |
| 11 | Inspection VU/utilitaire | Y | P | P | P | **Y** | N | N | N | Y | Y |
| 12 | Inspection camping-car | N | N | N | N | **Y** | N | N | N | N | N |
| 13 | Video live inspection | N | N | N | N | N | N | N | N | N | **Y** |
| 14 | IA analyse photos | N | N | **Y**(Lucius) | N | P(algo) | N | N | N | N | N |
| | **RAPPORT** | | | | | | | | | | |
| 15 | Rapport PDF | Y | Y | Y | Y | Y | Y | Y | Y | Y | Y |
| 16 | Rapport digital interactif | N | Y | **Y** | Y | Y | Y | N | N | Y | Y |
| 17 | ~50 photos dans rapport | N | P | **Y** | P | P | P | P | P | P | P |
| 18 | Commentaires expert detailles | P (500 car) | Y | **Y** | Y | Y | Y | Y | Y | Y | Y |
| 19 | Recommendation achat/negocier/eviter | **Y** | Y | Y | Y | Y | Y | N | N | P | P |
| 20 | Score/note globale | N | P | P | P | **Y** (/20) | P | N | N | N | N |
| | **BOOKING & LOGISTIQUE** | | | | | | | | | | |
| 21 | Booking en ligne | **Y** | Y | Y | Y | Y | Y | **Y** | **Y** | **Y** | Y |
| 22 | App mobile native | **Y** | N | N | N | N | N | N | N | P | N |
| 23 | Same-day booking | P | N | N | N | N | N | **Y** | P | Y | N |
| 24 | Creneaux horaires selectionnables | **Y** | P | P | P | N | N | **Y** | P | **Y** | N |
| 25 | GPS tracking mecanicien | **Y** | N | N | N | N | N | N | N | N | N |
| 26 | Check-in code verification | **Y** | N | N | N | N | N | N | N | N | N |
| 27 | Buffer zone entre creneaux | **Y** | ? | ? | ? | ? | ? | P | ? | P | ? |
| 28 | Auto-cancel non-accepte | **Y** (2h) | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| 29 | Collection/delivery vehicule | N | N | N | N | N | N | N | **Y** | N | N |
| 30 | Inspection sans presence acheteur | Y | **Y** | **Y** | **Y** | Y | Y | Y | Y | Y | Y |
| | **PAIEMENT** | | | | | | | | | | |
| 31 | Paiement en ligne | **Y** (Stripe) | Y | Y | Y | Y | ? | **Y** | **Y** | **Y** | Y |
| 32 | Pre-autorisation (capture differee) | **Y** | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| 33 | Remboursement automatique | **Y** | Y | Y | Y | Y | ? | Y | Y | Y | Y |
| 34 | Politique annulation graduee | **Y** | P | P | P | P | ? | P | P | P | P |
| 35 | Payout mecanicien automatique | **Y** (Connect) | N/A | N/A | N/A | N/A | N/A | Y | N/A | Y | N/A |
| 36 | Commission plateforme | 20% | N/A | N/A | N/A | N/A | N/A | ~30% | N/A | ~20-30% | N/A |
| | **COMMUNICATION** | | | | | | | | | | |
| 37 | Chat in-app | **Y** | N | N | N | N | N | N | N | N | N |
| 38 | Messages templates | **Y** (24) | N | N | N | N | N | N | N | N | N |
| 39 | Contact masking | **Y** | N/A | N/A | N/A | N/A | N/A | N | N/A | N | N/A |
| 40 | Push notifications | **Y** (10 types) | N | N | N | N | N | P | P | Y | N |
| 41 | Email notifications | **Y** | Y | Y | Y | Y | Y | Y | Y | Y | Y |
| 42 | SMS notifications | N | ? | ? | ? | ? | ? | Y | Y | Y | ? |
| | **CONFIANCE & GARANTIE** | | | | | | | | | | |
| 43 | Verification identite mecanicien | **Y** (photo+selfie) | Y | Y | Y | Y | ? | Y | Y (25pts) | **Y** (ASE+BG) | Y |
| 44 | Reviews publiques | **Y** | Y | **Y** (Trustpilot) | **Y** (Trustpilot) | P | P | Y | **Y** (Trustpilot) | **Y** | Y |
| 45 | Garantie post-achat | **N** | **Y** (6m) | **Y** (3m+ext) | **Y** (12m) | **Y** (3-60m) | N | N | **Y** (12m) | N | N |
| 46 | Badge/certification vendeur | N | N | N | N | **Y** | N | N | N | N | N |
| 47 | Dispute resolution | **Y** | P | P | P | P | ? | P | P | P | P |
| | **LEGAL & COMPLIANCE** | | | | | | | | | | |
| 48 | GDPR suppression compte | **Y** | Y | Y | Y | Y | Y | Y | Y | N/A | N/A |
| 49 | GDPR export donnees | **Y** | ? | ? | ? | ? | ? | ? | ? | N/A | N/A |
| 50 | GDPR anonymisation messages | **Y** | ? | ? | ? | ? | ? | ? | ? | N/A | N/A |
| 51 | Rate limiting | **Y** | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| 52 | Audit log admin | **Y** | ? | ? | ? | ? | ? | ? | ? | ? | ? |
| | **MECANICIEN** | | | | | | | | | | |
| 53 | Dashboard earnings | **Y** | N/A | N/A | N/A | N/A | N/A | Y | N/A | **Y** | N/A |
| 54 | Gestion disponibilites | **Y** | N/A | N/A | N/A | N/A | N/A | P | N/A | Y | N/A |
| 55 | Referral/parrainage | **Y** | N | N | N | N | N | N | N | N | N |
| 56 | Diplomes/certifications | **Y** | P | P | P | P | ? | P | P | **Y** | P |
| 57 | No-show penalty | **Y** | ? | ? | ? | ? | ? | ? | ? | ? | ? |

**Total features eMecano : 39 Y/P sur 57 = 68%**

---

## 6. ANALYSE DES GAPS

### 6.1 GAPS CRITIQUES (Impact business majeur)

#### GAP-1 : Checklist d'inspection insuffisant (9 items vs 150-200)
- **Gravite** : CRITIQUE
- **Impact** : Credibilite du service, confiance acheteur, valeur percue du rapport
- **Concurrents** : AutoJust (200), Trustoo (200+), MonInspection.fr (200+), YourMechanic (150), ClickMechanic (185)
- **eMecano** : 9 items (brakes, tires, fluids, battery, suspension, body, exhaust, lights, test_drive)
- **Manque** : Moteur, transmission, direction, embrayage, climatisation, electronique, interieur, vitrage, pneumatiques (profondeur), chassis, echappement (details), freins (details ABS/disques/plaquettes), systeme electrique, eclairage (details), carrosserie (details peinture/rouille), documents, equipements securite

#### GAP-2 : Absence d'historique vehicule
- **Gravite** : CRITIQUE
- **Impact** : Information cle pour detecter fraudes (km trafiques, accidents, vols)
- **Concurrents** : AutoJust (complet), Trustoo (complet), MonInspection.fr (oui)
- **Solution** : Integration API HistoVec (gratuit, gouvernement francais) ou Autorigin/Carfax Europe

#### GAP-3 : Pas de garantie post-achat
- **Gravite** : HAUTE
- **Impact** : Differentiation majeure des concurrents, reassurance acheteur, revenu recurrent potentiel
- **Concurrents** : AutoJust (6m), Trustoo (3m + 9.99EUR/mois), MonInspection.fr (12m), Chekoto (3-60m), Fixter (12m)
- **Solution** : Partenariat avec assureur/warranty provider (RPM Warranty, etc.)

#### GAP-4 : Pas de diagnostic OBD/electronique
- **Gravite** : HAUTE
- **Impact** : Manque de profondeur technique, codes defaut invisibles
- **Concurrents** : MonInspection.fr (oui), YourMechanic (oui), ClickMechanic (oui)
- **eMecano** : Champ `obd_requested` existe mais pas d'integration
- **Solution** : Formulaire OBD dans checkout (codes DTC, donnees moteur) ; a terme dongle Bluetooth

### 6.2 GAPS IMPORTANTS (Avantage concurrentiel manque)

#### GAP-5 : Pas d'estimation de valeur marche
- **Gravite** : MOYENNE
- **Concurrents** : AutoJust (aide negociation), Trustoo (aide negociation), YourMechanic (estimation reparations)
- **Solution** : Integration Argus/La Centrale API ou estimation basee sur donnees marche

#### GAP-6 : Rapport digital interactif absent
- **Gravite** : MOYENNE
- **Impact** : PDF statique vs rapport web avec photos zoomables, navigation par section
- **Concurrents** : Trustoo (~50 photos, rapport digital), Chekoto (note /20), MonInspection.fr
- **Solution** : Page web partageable en plus du PDF, avec galerie photos, navigation sections

#### GAP-7 : Pas d'inspection VE (batterie)
- **Gravite** : MOYENNE (croissante)
- **Impact** : Marche VE en forte croissance, SoH batterie = info critique
- **Concurrents** : MonInspection.fr (partenariat EV Market), Lemon Squad (EV specialise)
- **Solution** : Partenariat diagnostic batterie VE, checklist VE specifique

#### GAP-8 : Pas de SMS notifications
- **Gravite** : BASSE
- **Impact** : Canal additionnel de fiabilite pour rappels RDV
- **Concurrents** : ClickMechanic, Fixter, YourMechanic
- **Solution** : Integration Twilio ou Resend SMS

#### GAP-9 : Pas de self-check gratuit (lead generation)
- **Gravite** : MOYENNE
- **Impact** : Funnel acquisition — Chekoto genere du trafic avec son QCM gratuit
- **Solution** : Questionnaire rapide gratuit (10-15 questions) avec note indicative + upsell inspection pro

#### GAP-10 : Absence de score/note globale numerique
- **Gravite** : BASSE
- **Impact** : Note /20 ou /100 plus parlante qu'un BUY/NEGOTIATE/AVOID
- **Solution** : Calculer un score numerique en complement de la recommendation

### 6.3 AVANTAGES eMecano (Features uniques ou superieures)

| Feature Unique | Valeur |
|---------------|--------|
| **GPS tracking mecanicien** | Aucun concurrent ne propose le suivi en temps reel |
| **Check-in code 4 chiffres** | Verification physique unique sur le marche |
| **Chat in-booking avec templates** | Communication structuree + contact masking |
| **App mobile native** | Seul acteur avec app React Native dediee |
| **Politique annulation graduee** | Plus sophistiquee que la moyenne |
| **GDPR complete** (delete + export + anonymisation) | Conformite exemplaire |
| **Referral system mecaniciens** | Croissance organique du reseau |
| **Pre-autorisation Stripe** | Paiement capture uniquement apres validation |
| **Prometheus + Sentry** | Observabilite superieure |

---

## 7. ANALYSE UX/UI

### 7.1 Points Forts UX

| Critere | Score | Detail |
|---------|-------|--------|
| Flow de booking | 8/10 | Selection creneau, confirmation, paiement en ~3 etapes |
| Onboarding | 7/10 | Welcome screen + inscription role-based |
| Navigation | 7/10 | 24 ecrans bien structures par role (buyer/mechanic) |
| Trust signals | 7/10 | Reviews, verification identite, check-in code |
| Etat booking | 9/10 | 9 statuts avec transitions claires et notifications |
| Chat | 7/10 | Templates + custom avec masking = bonne UX |

### 7.2 Axes d'Amelioration UX

| Critere | Score Actuel | Benchmark | Recommandation |
|---------|-------------|-----------|----------------|
| Recherche mecano | 6/10 | 8/10 | Ajouter filtres (prix, rating, OBD, VE), autosuggestion ville |
| Rapport inspection | 5/10 | 8/10 | Rapport web interactif, plus de photos, score numerique |
| Post-booking | 4/10 | 7/10 | Partage rapport, historique inspections, re-booking facile |
| Onboarding mecanicien | 6/10 | 8/10 | Progress bar upload docs, checklist onboarding |
| Checkout inspection | 6/10 | 8/10 | Checklist trop court (9 items), UX formulaire photos a ameliorer |
| Accessibilite | ?/10 | 8/10 | Audit WCAG 2.1 AA necessaire |
| Temps de booking | ~3min | <60s | Optimiser le flow (moins d'ecrans, pre-remplissage) |

### 7.3 Benchmarks UX (Meilleures pratiques 2025)

Selon les standards Baymard Institute et les tendances 2025 :

1. **Booking en < 60 secondes** : eMecano ~3 min (a reduire)
2. **Smart search avec autosuggestion** : eMecano = recherche GPS basique
3. **Pricing transparent** : eMecano = bon (prix calcule en temps reel)
4. **Mobile-first** : eMecano = oui (React Native)
5. **Reviews integrees au flow de decision** : eMecano = partiel (reviews sur detail mecanicien)
6. **AI personalization** : eMecano = absent
7. **Voice UI** : eMecano = absent (tendance emergente)
8. **Accessibility WCAG 2.1** : eMecano = non verifie

---

## 8. RECOMMANDATIONS PRIORISEES (25)

### Priorite P0 — Must-Have (1-2 mois)

| # | Recommandation | Effort | Impact | ROI |
|---|---------------|--------|--------|-----|
| R1 | **Enrichir le checklist d'inspection a 80-100 points** | M | CRITIQUE | Credibilite du service, paraxison avec concurrents |
| R2 | **Integrer l'historique vehicule (HistoVec API)** | M | CRITIQUE | Detection fraudes, valeur ajoutee unique |
| R3 | **Ajouter un formulaire OBD dans le checkout** (codes DTC, donnees moteur) | S | HAUTE | Profondeur technique sans materiel supplementaire |
| R4 | **Enrichir le rapport PDF** : plus de photos (jusqu'a 30), commentaires detailles par composant | M | HAUTE | Valeur percue du rapport |
| R5 | **Creer un rapport digital web** partageable (en plus du PDF) | M | HAUTE | Partage facile, meilleure UX que PDF |

### Priorite P1 — Important (2-3 mois)

| # | Recommandation | Effort | Impact | ROI |
|---|---------------|--------|--------|-----|
| R6 | **Garantie post-achat** via partenariat assureur (3 mois inclus) | L | HAUTE | Differentiation majeure, revenu recurrent |
| R7 | **Score numerique d'inspection** (/100) en complement de BUY/NEGOTIATE/AVOID | S | MOYENNE | Comprehension instantanee par l'acheteur |
| R8 | **Estimation valeur marche** du vehicule (integration Argus ou scraping La Centrale) | M | MOYENNE | Aide a la decision, negociation |
| R9 | **Estimation cout des reparations** necessaires | M | MOYENNE | Valeur ajoutee forte (cf. YourMechanic) |
| R10 | **Filtres de recherche avances** (prix, rating, OBD, VE, disponibilite) | S | MOYENNE | Amelioration UX decouverte |
| R11 | **Self-check gratuit** (questionnaire rapide 10-15 questions, score indicatif) | M | MOYENNE | Lead generation, funnel acquisition |
| R12 | **SMS reminders** (24h et 2h avant RDV) | S | BASSE | Reduction no-shows |

### Priorite P2 — Nice-to-Have (3-5 mois)

| # | Recommandation | Effort | Impact | ROI |
|---|---------------|--------|--------|-----|
| R13 | **Inspection VE** : checklist batterie, SoH, autonomie reelle | M | MOYENNE | Marche croissant, peu de concurrents FR |
| R14 | **Multi-langue** (FR/EN minimum) pour acheteurs internationaux | M | BASSE | Expansion marche, expats |
| R15 | **Partenariat classifieds** (LeBonCoin, La Centrale) — bouton "Faire inspecter" | L | HAUTE | Distribution massive |
| R16 | **Profils mecaniciens enrichis** : video presentation, specialites, certifications detaillees | S | BASSE | Trust building |
| R17 | **Historique inspections** pour acheteur (dashboard mes inspections passees) | S | BASSE | Retention, re-achat |
| R18 | **Webhook events enrichis** pour integration tierce | S | BASSE | Ecosystem/API |
| R19 | **Mode hors-ligne partiel** pour mecanicien (checkout en zone sans reseau) | L | MOYENNE | Fiabilite terrain |

### Priorite P3 — Vision Long Terme (5-6 mois+)

| # | Recommandation | Effort | Impact | ROI |
|---|---------------|--------|--------|-----|
| R20 | **Inspection video live** (acheteur assiste en direct par mecanicien) | XL | HAUTE | Innovation (cf. Lemon Squad LIVE) |
| R21 | **IA analyse photos** automatique (detection defauts carrosserie/pneus) | XL | HAUTE | Scalabilite, qualite (cf. Trustoo Lucius AI) |
| R22 | **Couverture europeenne** (Belgique, Suisse, Luxembourg d'abord) | XL | HAUTE | TAM x3-5 |
| R23 | **B2B : inspection pour garages/concessionnaires** (badge certification VO) | L | MOYENNE | Nouveau segment, revenu recurrent |
| R24 | **Programme certification mecaniciens** (niveaux bronze/silver/gold) | M | MOYENNE | Qualite, gamification, retention mecaniciens |
| R25 | **Marketplace etendue** : entretien, reparation, controle technique (cf. ClickMechanic, Fixter) | XL | HAUTE | Lifetime value, retention |

**Effort** : S = Small (<1 semaine), M = Medium (1-3 semaines), L = Large (3-6 semaines), XL = Extra-Large (6+ semaines)

---

## 9. FEATURES A AMELIORER (12)

### 9.1 Checklist d'inspection (CRITIQUE)

**Actuel** : 9 items generiques (brakes, tires, fluids, battery, suspension, body, exhaust, lights, test_drive)

**Cible** : 80-100 points structures en categories

```
PROPOSE : Structure checklist enrichie
============================================

1. DOCUMENTS & ADMINISTRATIF (8 points)
   - Carte grise conforme
   - Controle technique valide
   - Carnet d'entretien present
   - Factures entretien recentes
   - Nombre de proprietaires
   - Cles (nombre, telecommande)
   - Manuel d'utilisation
   - Plaque d'immatriculation conforme

2. EXTERIEUR (12 points)
   - Carrosserie (bosses, rayures, rouille)
   - Peinture (uniformite, retouches)
   - Pare-brise (impacts, fissures)
   - Vitres laterales et arriere
   - Retroviseurs (etat, reglage electrique)
   - Optiques avant (phares, antibrouillards)
   - Optiques arriere (feux stop, recul, clignotants)
   - Pare-chocs avant et arriere
   - Jantes (voile, choc, corrosion)
   - Pneumatiques (marque, profondeur, usure, DOT)
   - Serrures portes et coffre
   - Antenne / barres de toit

3. INTERIEUR (10 points)
   - Siege conducteur (usure, reglage, chauffant)
   - Sieges passagers (usure, reglage)
   - Tableau de bord (voyants, temoins)
   - Volant (usure, reglage)
   - Pedalier (usure, jeu)
   - Moquette / tapis (etat)
   - Ciel de toit
   - Coffre (etat, roue de secours, cric)
   - Ceintures de securite
   - Vitres electriques (fonctionnement)

4. ECLAIRAGE & SIGNALISATION (8 points)
   - Phares (croisement, plein phare)
   - Feux de position
   - Clignotants (avant, arriere, lateraux)
   - Feux de recul
   - Feux stop
   - Antibrouillards (avant, arriere)
   - Eclairage interieur
   - Eclairage tableau de bord

5. MOTEUR & COMPARTIMENT (10 points)
   - Etat general moteur (fuites, proprete)
   - Niveau huile moteur
   - Niveau liquide refroidissement
   - Niveau liquide frein
   - Niveau liquide direction assistee
   - Niveau lave-glace
   - Courroie distribution (date/km dernier changement)
   - Batterie (tension, age, etat)
   - Filtre a air
   - Bruit moteur au ralenti

6. TRANSMISSION & DIRECTION (8 points)
   - Embrayage (patinage, point)
   - Boite de vitesses (passage, bruit)
   - Cardans / soufflets
   - Direction (jeu, bruit, assistance)
   - Train avant (geometrie apparente)
   - Train arriere
   - Amortisseurs (rebond, fuite)
   - Ressorts / silent blocs

7. FREINAGE (8 points)
   - Disques avant (usure, voile)
   - Disques arriere (usure)
   - Plaquettes avant (epaisseur)
   - Plaquettes arriere (epaisseur)
   - Frein a main (efficacite)
   - ABS (fonctionnement)
   - ESP (temoin)
   - Liquide frein (niveau, couleur)

8. ECHAPPEMENT & EMISSIONS (4 points)
   - Ligne d'echappement (etancheite, corrosion)
   - Catalyseur / FAP
   - Fumee echappement (couleur, odeur)
   - Bruit anormal

9. CLIMATISATION & CONFORT (6 points)
   - Climatisation (froid, chaud)
   - Chauffage
   - Ventilation (toutes vitesses)
   - Autoradio / GPS
   - Prise USB / AUX
   - Toit ouvrant (si equipe)

10. ELECTRONIQUE & SECURITE (8 points)
    - Airbags (temoins)
    - Regulateur / limiteur de vitesse
    - Radar de recul / camera
    - Start & Stop
    - Systeme multimedia
    - Prise diagnostic OBD (accessible)
    - Codes defaut (lecture DTC)
    - Temoin moteur (MIL)

11. ESSAI ROUTIER (8 points)
    - Demarrage a froid
    - Ralenti stable
    - Acceleration (reponse, vibrations)
    - Freinage (efficacite, trajectoire)
    - Direction (precision, bruit)
    - Boite de vitesses en charge
    - Bruits anormaux (roulement, suspension)
    - Comportement general

TOTAL : ~90 points de controle
```

### 9.2 Rapport PDF

**Actuel** : Template HTML basique, 2-12 photos, checklist 9 items, 1 recommendation
**Cible** :
- Jusqu'a 30 photos organisees par categorie
- Commentaire detaille par composant (pas seulement 500 car total)
- Score numerique /100
- Estimation budget reparations
- QR code vers rapport digital
- Page historique vehicule (si integre)

### 9.3 Recherche mecanicien

**Actuel** : Recherche GPS + rayon, tri par distance
**Cible** :
- Filtres : prix, rating minimum, OBD disponible, VE competent, disponibilite (date)
- Autosuggestion ville/code postal
- Carte interactive avec clusters
- Badge "Top mecanicien" (>4.5 stars + >20 missions)

### 9.4 Flow checkout inspection (mecanicien)

**Actuel** : 9 items + photos + remarques en 1 seul formulaire
**Cible** :
- Wizard multi-etapes par categorie (10 categories x ~9 items)
- Photo par defaut identifie (liee au point de controle)
- Sauvegarde brouillon en cours d'inspection
- Mode hors-ligne avec sync

### 9.5 Flow post-booking (buyer)

**Actuel** : Valider ou disputer, c'est tout
**Cible** :
- Partager le rapport (lien web public ou prive)
- Telecharger PDF
- Re-booking facilite (meme mecanicien)
- Historique de toutes les inspections
- Avis Google Maps integre

### 9.6 Onboarding mecanicien

**Actuel** : Upload docs, attente review admin
**Cible** :
- Progress bar (etapes completees)
- Checklist onboarding interactif
- Video tutoriel inspection
- Quiz qualification
- Preview profil public avant activation

### 9.7 Dashboard mecanicien

**Actuel** : Stats basiques (missions, earnings, rating, acceptance rate)
**Cible** :
- Graphiques evolution (semaine, mois)
- Comparaison avec la moyenne reseau
- Tips pour ameliorer le rating
- Calendar view des disponibilites + bookings
- Export CSV des revenus (comptabilite)

### 9.8 Notifications

**Actuel** : Push + email, 10 types
**Cible** :
- SMS pour rappels critiques (2h avant)
- Notification "Nouveau mecanicien pres de chez vous"
- Notification "Votre mecanicien favori a de nouvelles dispos"
- Recap hebdomadaire mecanicien (earnings, missions, next week)

### 9.9 Admin Dashboard

**Actuel** : API endpoints, pas de frontend admin
**Cible** :
- Interface web admin (React ou similaire)
- Grafana dashboard lie a Prometheus
- Alertes automatiques (dispute ouverte, mecanicien suspendu, etc.)
- Moderation messages

### 9.10 Pricing dynamique

**Actuel** : Prix fixe (40 EUR + 25 EUR OBD + 0.30 EUR/km)
**Cible** :
- Prix adapte au type de vehicule (luxe, camping-car = plus cher)
- Prix adapte a la complexite (checklist enrichi = temps supplementaire)
- Promotions (premiere inspection, code promo)
- Bundle : inspection + garantie a prix reduit

### 9.11 Systeme de reviews

**Actuel** : Rating + commentaire, buyer->mechanic public, mechanic->buyer prive
**Cible** :
- Sous-ratings (ponctualite, minutie, communication, rapport qualite)
- Reponse du mecanicien aux reviews
- Reviews verifees (badge "Inspection realisee")
- Integration Google Reviews / Trustpilot

### 9.12 Contact masking

**Actuel** : Masque phone/email/social dans messages custom
**Cible** :
- Detection plus fine (liens WhatsApp, Telegram, etc.)
- Message systeme expliquant pourquoi le contact est masque
- Liberation du contact a un moment precis du flow (pas seulement 2h avant)

---

## 10. FEATURES A SUPPRIMER OU SIMPLIFIER

| Feature | Recommandation | Raison |
|---------|---------------|--------|
| `vehicle_plate` optionnel au booking | Rendre **obligatoire** | Necessaire pour historique vehicule et rapport |
| Check-in code 4 chiffres expiration 15min | Garder mais **allonger a 30min** | 15min trop court si retard traffic |
| Max 100 slots non-reserves | **Augmenter a 200** | Mecaniciens actifs peuvent avoir besoin de plus |
| Refresh token 7 jours | **Considerer 30 jours** | Mobile = sessions longues, concurrents offrent "stay logged in" |
| 500 char max remarques | **Augmenter a 2000** | Trop court pour rapport detaille avec checklist enrichi |
| Referral mechanic-only | **Etendre aux buyers** | Source d'acquisition additionnelle |

> Note : Aucune feature majeure n'est a supprimer. Le code est bien structure et chaque feature a une utilite. Les recommandations ci-dessus sont des ajustements de parametres.

---

## 11. IDEES D'INNOVATION (7)

### Innovation 1 : Inspection Video Live (a la Lemon Squad)
**Concept** : L'acheteur lance une session video avec un mecanicien certifie. Le mecanicien guide l'acheteur (ou le vendeur) a travers les points de controle en direct, via la camera du smartphone.
- **Prix** : 39-59 EUR (moins cher qu'une inspection physique)
- **Cas d'usage** : Achat a distance, premier filtre avant inspection physique
- **Tech** : WebRTC / Twilio Video / Daily.co
- **ROI** : Nouveau segment prix, conversion avant inspection complete

### Innovation 2 : IA Analyse Photo (a la Trustoo Lucius AI)
**Concept** : Le mecanicien prend des photos standardisees (angles definis). L'IA detecte automatiquement les defauts visibles (rayures, bosses, usure pneus, rouille).
- **Tech** : Vision model (GPT-4o, Claude Vision) ou modele custom
- **Valeur** : Standardisation qualite, detection defauts oublies, scoring automatique
- **Phase 1** : Analyse photos carrosserie (avant/arriere/cotes)
- **Phase 2** : Analyse photos pneus (profondeur, usure)
- **Phase 3** : Analyse photos interieur (usure sieges, tableau de bord)

### Innovation 3 : Self-Check Gratuit + Score (a la Chekoto)
**Concept** : Questionnaire interactif gratuit (15-20 questions) que l'acheteur remplit avec le vendeur. Genere un score indicatif /20 avec les points de vigilance.
- **Funnel** : Score < 12/20 → suggestion d'inspection pro
- **Lead gen** : Capture email pour re-marketing
- **Viralite** : Partage du score sur les reseaux sociaux

### Innovation 4 : Passeport Digital Vehicule
**Concept** : Chaque vehicule inspecte recoit un "passeport digital" avec QR code, regroupant tous les rapports d'inspection, l'historique HistoVec, et les photos.
- **Valeur vendeur** : Le vendeur peut partager le passeport pour rassurer les acheteurs
- **Valeur acheteur** : Vue 360° du vehicule
- **Revenu** : Abonnement vendeur pour maintenir le passeport a jour

### Innovation 5 : Marketplace de Garanties
**Concept** : Apres une inspection positive (BUY), proposer un choix de garanties de differents assureurs (comparateur integre).
- **Modele** : Commission sur chaque garantie vendue (10-20%)
- **Partenaires** : RPM Warranty, Opteven, iCare, etc.
- **Revenu additionnel** : Potentiel 30-50 EUR de commission par garantie

### Innovation 6 : Estimation IA du Prix Juste
**Concept** : A partir des donnees d'inspection (km, etat composants, defauts), de l'historique vehicule, et des donnees marche (Argus, La Centrale), calculer un prix juste estime.
- **Affichage** : "Prix affiche : 12 500 EUR | Prix estime eMecano : 10 800 EUR (-14%)"
- **Valeur** : Outil de negociation puissant = USP forte
- **Tech** : ML model entraine sur donnees marche + etat inspection

### Innovation 7 : Booking depuis les Annonces (Plugin/Extension)
**Concept** : Extension navigateur ou partenariat API permettant d'ajouter un bouton "Faire inspecter par eMecano" directement sur LeBonCoin, La Centrale, Autoscout24.
- **Acquisition** : Distribution massive sans cout marketing
- **Friction** : Pre-remplissage automatique des infos vehicule depuis l'annonce
- **Reference** : ClickMechanic x Motors.co.uk (2025)

---

## 12. ROADMAP 3-6 MOIS

### Mois 1-2 : Fondations (P0)

```
Semaine 1-2 : Checklist enrichi (90 points)
  - Schema DB : table inspection_items normalisee
  - Migration : nouvelles categories + items
  - Backend : API checkout avec checklist dynamique
  - Mobile : Wizard multi-etapes par categorie
  - Tests : Coverage complete

Semaine 3 : Historique vehicule
  - Integration API HistoVec (SIV) ou Autorigin
  - Affichage dans rapport : nb proprietaires, sinistres, km
  - Stockage cache en DB pour re-consultation

Semaine 4 : Rapport enrichi
  - Template PDF v2 (90 points, plus de photos, score /100)
  - Page web rapport digital (URL partageable)
  - QR code dans le PDF pointant vers la version web

Semaine 5-6 : Formulaire OBD
  - Champs OBD dans checkout : codes DTC, donnees moteur
  - Section OBD dans le rapport
  - UX : photos ecran diagnostic

Semaine 7-8 : Tests, QA, deploiement
  - Tests E2E nouveau flow checkout
  - Migration donnees (anciens rapports)
  - Deploiement progressif (feature flag)
```

### Mois 3-4 : Differentiation (P1)

```
Semaine 9-10 : Garantie post-achat
  - Partenariat assureur (RPM Warranty ou similaire)
  - API integration devis/souscription
  - UX : proposition apres inspection positive

Semaine 11-12 : Estimation valeur + reparations
  - Integration donnees marche (Argus API ou scraping)
  - Algorithme estimation cout reparations base sur checklist
  - Affichage dans rapport

Semaine 13-14 : Recherche avancee + Self-check
  - Filtres recherche (prix, rating, OBD, VE, dispo)
  - Self-check gratuit (questionnaire + score)
  - Landing page SEO

Semaine 15-16 : SMS + Améliorations UX
  - Integration SMS (Twilio)
  - Score numerique /100
  - Dashboard mecanicien enrichi (graphiques)
```

### Mois 5-6 : Innovation (P2-P3)

```
Semaine 17-18 : Inspection VE
  - Checklist VE specifique (batterie, charge, autonomie)
  - Partenariat diagnostic SoH
  - Marketing VE

Semaine 19-20 : Passeport Digital Vehicule
  - Page publique vehicule avec historique inspections
  - QR code physique
  - API partage

Semaine 21-22 : Video Live (MVP)
  - Integration WebRTC (Daily.co ou Twilio Video)
  - Flow simplifie : 1 acheteur + 1 mecanicien
  - Rapport simplifie post-video

Semaine 23-24 : IA Photo Analysis (MVP)
  - Integration vision model (Claude Vision / GPT-4o)
  - Analyse carrosserie (4 angles standardises)
  - Score carrosserie automatique
```

---

## 13. INSIGHTS BUSINESS

### 13.1 Modele Economique — Comparaison

| Metrique | eMecano | Marche FR | Benchmark |
|----------|---------|-----------|-----------|
| Prix inspection | 40 EUR (+25 OBD + frais) | 199-349 EUR | **eMecano est 3-5x moins cher** |
| Commission | 20% | N/A (employes) | Standard marketplace |
| Payout mecanicien | ~32-52 EUR/mission | ~150-250 EUR/mission | **Payout bas = risque retention** |
| Garantie | Non | 3-12 mois inclus | **Gap critique** |

### 13.2 Analyse Prix

Le prix actuel d'eMecano (40 EUR base) est **significativement inferieur** au marche :
- AutoJust : 249-300 EUR
- Trustoo : 199-349 EUR
- MonInspection.fr : 188-300 EUR
- Chekoto : 249-299 EUR
- ClickMechanic : 79-137 GBP (~95-165 EUR)
- YourMechanic : 150-250 USD (~140-230 EUR)

**Recommandation** : Avec un checklist a 90 points (au lieu de 9), le prix doit etre significativement augmente :
- **Inspection Standard (90 points)** : 89-129 EUR
- **Inspection Premium (90 points + OBD + historique)** : 149-199 EUR
- **Inspection VE** : 179-229 EUR (avec diagnostic batterie)
- **Video Live** : 49-69 EUR (premier filtre)

### 13.3 Taille du Marche (TAM France)

- **5.5 millions** de transactions VO/an en France
- **Taux de penetration inspection** : ~2-5% actuellement
- **Potentiel** : 110 000 - 275 000 inspections/an
- **Panier moyen cible** : 150 EUR
- **TAM France** : 16.5 - 41.2 M EUR/an
- **Avec garantie (30% uptake, 10 EUR/mois, 6 mois moyen)** : +3-7.5 M EUR/an

### 13.4 KPIs a Suivre

| KPI | Metrique | Cible M+3 | Cible M+6 |
|-----|---------|-----------|-----------|
| Inspections/mois | Volume | Baseline +30% | Baseline +100% |
| Panier moyen | EUR/inspection | 65 EUR → 120 EUR | 150 EUR |
| NPS | Score | >40 | >50 |
| Retention mecanicien | % actif M+3 | >70% | >80% |
| Taux conversion | Visit → Booking | 5% | 8% |
| Taux completion | Booking → Completed | 85% | 90% |
| Taux dispute | Disputes/Completed | <5% | <3% |
| Coverage (villes) | Nb villes >3 mecanos | 10 | 30 |

### 13.5 Risques

| Risque | Probabilite | Impact | Mitigation |
|--------|------------|--------|-----------|
| Retention mecaniciens faible (payout bas) | HAUTE | CRITIQUE | Augmenter prix + payout proportionnel |
| Concurrents lancent app mobile | MOYENNE | HAUTE | Accelerer features differenciantes |
| Reglementation inspection VO | BASSE | HAUTE | Veille juridique, adaptation rapide |
| Qualite inspections heterogene | HAUTE | HAUTE | Certification, IA quality check, mystery shopping |
| Scalabilite reseau mecaniciens | MOYENNE | HAUTE | Referral, partenariat ecoles auto, onboarding optimise |

---

## 14. SOURCES

### Concurrents France
- [AutoJust - Site officiel](https://www.autojust.fr/)
- [AutoJust - Tarifs](https://www.autojust.fr/nos-tarifs)
- [AutoJust - Trustpilot](https://www.trustpilot.com/review/autojust.fr)
- [Trustoo - Site officiel](https://trustoo.com/fr)
- [Trustoo - Tarifs](https://trustoo.com/fr/tarifs)
- [Trustoo - Lucius AI](https://journalauto.com/journal-des-flottes/inspection-automatisee-trustoo-entre-dans-la-bataille-avec-lucius-ai/)
- [Trustoo - Trustpilot](https://www.trustpilot.com/review/trustoo.com)
- [MonInspection.fr - Site officiel](https://www.moninspection.fr/)
- [MonInspection.fr - Tarifs](https://www.moninspection.fr/tarifs)
- [MonInspection.fr - Inspection](https://www.moninspection.fr/inspection)
- [Chekoto - Site officiel](https://www.chekoto.com/)
- [Chekoto - Auto Infos](https://www.auto-infos.fr/article/chekoto-fait-evoluer-son-offre-de-verification-de-vo.178419)
- [WheelScanner - Site officiel](https://www.wheelscanner.fr/)

### Concurrents UK
- [ClickMechanic - PPI](https://www.clickmechanic.com/pre-purchase-inspection)
- [ClickMechanic x Motors.co.uk](https://cardealermagazine.co.uk/motors-teams-up-with-clickmechanic-to-offer-pre-purchase-inspections-on-used-cars/311661)
- [Fixter - Site officiel](https://www.fixter.co.uk/)
- [Fixter - Trustpilot](https://www.trustpilot.com/review/fixter.co.uk)

### Concurrents US
- [YourMechanic - PPI](https://www.yourmechanic.com/services/pre-purchase-car-inspection)
- [Lemon Squad - Site officiel](https://lemonsquad.com/)
- [Lemon Squad - LIVE](https://lemonsquad.com/live)
- [Lemon Squad - Compare](https://lemonsquad.com/used-car-inspections/compare)

### UX & Tendances
- [Booking UX Best Practices 2025](https://ralabs.org/blog/booking-ux-best-practices/)
- [Marketplace UX Design: 9 Best Practices](https://excited.agency/blog/marketplace-ux-design)
- [Services Marketplace Features 2026](https://www.rigbyjs.com/blog/services-marketplace-features)
- [Baymard Institute - Marketplace UX Benchmark](https://baymard.com/ux-benchmark/collections/marketplace)

---

**Fin du rapport. Document genere le 2026-02-19.**
