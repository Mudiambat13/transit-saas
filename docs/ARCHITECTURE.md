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

### Gestion des comptes (délégation)
- **Administrateur de compagnie** (`user.manage`) : crée, modifie, désactive tous les comptes de sa compagnie, définit le rôle, l'agence et les permissions particulières. Agence obligatoire pour un responsable d'agence et un agent de billetterie.
- **Responsable d'agence** (`user.manage_team`) : gère uniquement les agents de billetterie, d'embarquement et chauffeurs **de son agence** ; l'agence est imposée par le serveur, il ne peut ni créer d'encadrement, ni accorder de permissions, ni voir les autres agences ; sans agence rattachée il ne gère personne.
- Garde-fous : personne ne peut se désactiver, changer son rôle/agence ou ses permissions ; il reste toujours un administrateur actif ; réactiver un compte réactive son adhésion ; créer un compte chauffeur crée sa fiche chauffeur liée (suivi GPS).
- Mot de passe : l'administrateur ou le responsable fixe un mot de passe provisoire ; chacun le change lui-même (page « Mon mot de passe », `POST /auth/change-password/`, mot de passe actuel exigé). Limite connue : pas de changement obligatoire à la première connexion, ni de révocation des sessions ouvertes après changement.

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

## Suivi GPS du bus (v2, étape web)
Le téléphone du chauffeur (ou de son adjoint) envoie la position du bus pendant un voyage.

- **Session de suivi** (`TrackingSession`) : démarrée par un utilisateur autorisé (`tracking.manage`) sur un voyage ouvert / en embarquement / clôturé (en route). Elle génère un **jeton appareil** propre à la session, montré une seule fois et stocké **haché** (SHA-256). Un seul téléphone actif par voyage : en démarrer un second remplace le premier (l'ancien reçoit 410). La session se termine automatiquement quand le voyage est terminé, annulé ou suspendu.
- **Chauffeur** : ne peut suivre que les voyages auxquels il est affecté (fiche chauffeur liée à son compte). Un voyage non affecté est invisible pour lui (404).
- **Ingestion** `POST /api/v1/tracking/ingest/` : authentifiée par le seul jeton (`X-Tracking-Token`), limitée par jeton. Lots de 200 points maximum, **rejouables** (unicité session + heure d'origine : un point déjà reçu est ignoré), heure d'origine conservée pour les envois différés après une zone sans réseau. Coordonnées invalides, (0,0), dates futures ou de plus de 2 jours : rejetées.
- **Anomalies** : un point impliquant plus de 220 km/h depuis le dernier point valide est marqué *suspect*, conservé mais ignoré pour la position et le tracé.
- **Téléphone** : échantillonnage ≤ 1 point / 15 s, file locale persistante (localStorage) vidée par lots, reprise automatique au retour du réseau, verrou d'écran (Wake Lock) pour garder le GPS actif.
- **Lecture** : carte compagnie (`/tracking/live`), état « sans signal » après 5 min. **Page publique passagers** `/suivi/<code>` : code aléatoire par voyage, sans connexion, ne révèle ni plaque, ni chauffeur, ni billets ; position masquée si le dernier signal a plus de 30 min ou si le voyage est terminé ; inaccessible si la compagnie est suspendue.
- **Conservation** : `python manage.py purge_tracking --days 90` (à planifier). Durée à fixer avec la compagnie ; informer les chauffeurs du suivi (vie privée).
- **Limite majeure du MVP web** : un navigateur ne localise plus le téléphone quand l'écran est verrouillé ou la page quittée. Le suivi fiable de bout en bout exige l'**application Android** (service en arrière-plan), qui utilisera la même API d'ingestion sans modification.
- Fond de carte : tuiles OpenStreetMap (usage modéré). Pour un fort trafic, utiliser un fournisseur de tuiles dédié.

## Application Android de suivi (v3)

Dossier `android/` : application native Kotlin, sans dépendance tierce (HttpURLConnection, LocationManager, org.json), minSdk 24.
- `TrackingService` est un service de premier plan (`foregroundServiceType=location`, notification permanente avec bouton Arrêter, wake lock partiel) : la position continue écran verrouillé.
- Le cœur (`core/`, Kotlin pur) reproduit `trackerEngine.ts` : un point toutes les 15 s, précision ≤ 500 m, file persistante sur disque (5 000 points max), envoi par lots de 100, seuls les lots confirmés sont retirés, 400 → lot écarté, 401/410 → arrêt, 5xx/429/réseau → nouvel essai.
- Authentification : login JWT une fois pour démarrer ; ensuite seul le jeton appareil (`X-Tracking-Token`) sert à l'envoi et à `POST /tracking/end/`. Le service redémarre seul (START_STICKY) tant qu'un jeton est stocké.
- HTTPS obligatoire en release (`network_security_config`) ; `http://` seulement en debug.
- Limites : constructeurs agressifs (Tecno/Infinix/Xiaomi…) peuvent tuer le service malgré tout (réglages batterie à faire par l'utilisateur) ; pas de position sans GPS/réseau ; pas de FusedLocation (Google Play Services) pour rester sans dépendance — précision parfois moindre en intérieur.

## Compromis connus
- Un utilisateur = une compagnie active (contrainte en base).
- Révocation de refresh token : à la déconnexion le client supprime ses jetons ; pas de liste noire côté serveur (à ajouter avec `token_blacklist`).
- Tâches asynchrones (Celery/Redis) non introduites : inutiles au MVP.
- Chaque requête recharge l'adhésion ; un cache par requête évite les doublons de requêtes.
