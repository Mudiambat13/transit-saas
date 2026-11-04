# Architecture — Transit SaaS (MVP)

## Stack
Django 5 + Django REST Framework (API `/api/v1/`), PostgreSQL (SQLite en dev/tests), JWT (simplejwt), React 18 + TypeScript + Material UI (Vite), QR via `qrcode` / scan via `@zxing/browser`, PDF via ReportLab (aucune dépendance système), Docker Compose + Nginx.

## Stratégie multi-tenant (décision documentée)
**Base PostgreSQL partagée + `tenant_id` obligatoire** sur toute entité métier (`TenantOwnedModel`, FK non nulle). Choix MVP : simple à exploiter, suffisant avec des contrôles systématiques et testés. `django-tenants` (schémas) reste possible plus tard.

Règles appliquées :
1. Le tenant est résolu **uniquement** depuis l'adhésion active de l'utilisateur authentifié (`Membership`), jamais depuis un paramètre client.
2. `TenantModelViewSet.get_queryset()` filtre toujours sur ce tenant ; deviner un identifiant d'une autre compagnie renvoie **404**.
3. Les clés étrangères en écriture passent par `TenantPrimaryKeyRelatedField` (queryset filtré sur le tenant) : référencer l'agence/le bus d'une autre compagnie donne « n'existe pas ».
4. Les services métier (billets, scans, voyages) re-vérifient le tenant dans leurs requêtes.
5. Unicités composées incluant le tenant (immatriculation, référence de voyage, numéro de manifeste…).
6. Le Super Admin (`is_platform_admin`) n'a **aucune** route d'accès aux données métier des compagnies ; il gère tenants, offres, abonnements et journal.
7. Une compagnie suspendue est bloquée à la connexion **et** à chaque requête (`HasTenantPermission`).
8. Tests automatiques d'accès croisé entre deux compagnies (`backend/tests/test_isolation.py`).
9. Piste suivante recommandée : PostgreSQL Row-Level Security en défense supplémentaire (non faite dans le MVP).

## Autorisations
Matrice rôle → permissions granulaires (`apps/accounts/permissions.py`), ajustable par utilisateur (`extra_permissions` / `revoked_permissions` dans `Membership`). Chaque vue déclare `required_perms`. Le périmètre d'agence (responsable/agents rattachés à une agence) restreint voyages, billets et manifestes. Le frontend ne fait que masquer des éléments.

## Concurrence et intégrité
- **Vente** : transaction atomique, `select_for_update` sur le voyage (sérialise les ventes concurrentes → capacité jamais dépassée), contrainte unique partielle `uniq_active_seat_per_trip` (un siège = un billet actif par voyage) comme garantie ultime en base.
- **Scan** : verrou de ligne sur le billet + contrainte unique partielle `uniq_validated_boarding_per_ticket` ; en cas de course perdue, l'`IntegrityError` est converti en « déjà embarqué ». Clé d'idempotence côté client pour les rejeux réseau.
- **Clôture** : voyage verrouillé, scans bloqués, manifeste définitif créé dans la même transaction.

## QR Code
Contenu : `<jeton aléatoire 144 bits>.<signature HMAC-SHA256 tronquée>`. Aucune donnée personnelle, aucun identifiant séquentiel. La signature (clé `QR_SIGNING_KEY`, distincte de `SECRET_KEY`) rejette un QR altéré sans requête ; l'autorité reste la base (le billet est retrouvé par son jeton, dans le tenant).

## Manifestes
Le manifeste est un **instantané JSON** (`Manifest.snapshot`) ; le PDF est rendu *uniquement* depuis ce JSON. Le définitif (statut `ARCHIVED`) ne change donc jamais quand un billet ou un passager est modifié ensuite. Réouverture exceptionnelle (permission `trip.reopen` + motif + audit) → nouvelle clôture = nouvelle version, l'ancienne passe en `SUPERSEDED` (jamais modifiée ni supprimée).

## Hors connexion (décision MVP)
Scan **connecté uniquement**. Le scanner détecte la perte de réseau, n'affiche **jamais** « validé » sans confirmation du serveur, et propose la saisie manuelle de la référence. Un mode hors ligne n'est pas implémenté : il ne pourrait garantir l'unicité entre plusieurs appareils sans coordination. S'il est ajouté : validation « provisoire », file locale, synchronisation avec `idempotency_key` (déjà supportée par l'API) et règle de conflit explicite (premier horodatage serveur gagne, doublons signalés).

## Compromis connus
- Un utilisateur = une compagnie active (contrainte en base).
- Révocation de refresh token : à la déconnexion le client supprime ses jetons ; pas de liste noire côté serveur (à ajouter avec `token_blacklist`).
- Tâches asynchrones (Celery/Redis) non introduites : inutiles au MVP.
- Chaque requête recharge l'adhésion ; un cache par requête évite les doublons de requêtes.
