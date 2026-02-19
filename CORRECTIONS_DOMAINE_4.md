# CORRECTIONS DOMAINE 4 : ORPHANED FILES DETECTION

**Date :** 2026-02-19
**Bug corrige :** AUD5-008
**Tests ajoutes :** 15

---

## IMPLEMENTATION COMPLETE

### Fonctionnalites

**Detection :**
- Liste tous les fichiers R2 via boto3 paginator
- Collecte toutes les URLs en DB (6 tables, 10 colonnes)
- Calcule orphans = R2 keys - DB keys

**Grace Period :**
- 7 jours avant suppression
- Evite suppression uploads en cours
- Log age de chaque fichier

**Scheduler :**
- Cron hebdomadaire dimanche 3h AM (deja configure)
- Distributed lock pour multi-worker safety
- Logs structures (count, deleted, skipped, errors)

**RGPD :**
- Conformite Article 17 (droit a l'oubli)
- PII supprimees automatiquement apres grace period
- Tracabilite complete dans logs

---

## FICHIERS MODIFIES

### backend/app/services/scheduler.py

**Fonctions ajoutees :**
- `_extract_key_from_url(url)` : Parse URL -> S3 key (strip host + query params)
- `_list_r2_keys()` : Liste bucket R2 avec pagination boto3
- `_collect_db_keys(db)` : Collecte URLs depuis 6 tables :
  - MechanicProfile (identity_document_url, selfie_with_id_url, cv_url, photo_url)
  - ValidationProof (photo_plate_url, photo_odometer_url, additional_photo_urls)
  - Diploma (document_url)
  - DisputeCase (photo_urls)
  - Report (pdf_url)

**Fonction remplacee :**
- `detect_orphaned_files()` : Placeholder -> implementation complete
  - Distributed lock
  - Set difference R2 - DB
  - head_object pour age checking
  - delete_object apres 7j grace period
  - Error isolation par fichier

### backend/tests/test_orphaned_files.py (NOUVEAU)

**15 tests :**

```
TestExtractKeyFromUrl::test_simple_url        PASSED
TestExtractKeyFromUrl::test_presigned_url     PASSED
TestExtractKeyFromUrl::test_nested_path       PASSED
TestExtractKeyFromUrl::test_none              PASSED
TestExtractKeyFromUrl::test_empty             PASSED
TestExtractKeyFromUrl::test_root_only         PASSED
test_list_r2_keys_not_configured              PASSED
test_list_r2_keys_paginated                   PASSED
test_list_r2_keys_error                       PASSED
test_detect_no_orphans                        PASSED
test_detect_orphan_within_grace_period        PASSED  (< 7j : NOT deleted)
test_detect_orphan_past_grace_period          PASSED  (> 7j : deleted)
test_detect_mixed_ages                        PASSED  (2 old deleted, 1 recent skipped)
test_detect_lock_not_acquired                 PASSED  (no-op)
test_detect_r2_empty                          PASSED  (no-op)
```

---

## VERIFICATIONS

```
Backend compile        : OK
Tests orphaned files   : 15/15 passed
Tests total            : 335 passed, 3 skipped (320 + 15)
Cron job               : deja configure (dimanche 3h AM)
```

---

## IMPACT

**RGPD :**
- Conformite Article 17 : PII auto-supprimees
- Grace period securitaire (7 jours)
- Tracabilite complete

**Couts :**
- Reduction progressive stockage R2
- Nettoyage automatique sans intervention manuelle

**Maintenance :**
- Cron hebdomadaire automatique
- Distributed lock multi-worker safe
- Logs structures pour monitoring

---

## PROCHAINES ETAPES

**DOMAINE 4 termine**

Options :
- A) Commit et pause
- B) Passer au DOMAINE 3 : Tests coverage (3-4 jours)
- C) Commit et considerer le projet pret

---

*Fin du rapport DOMAINE 4*
