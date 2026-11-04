# Transit SaaS — billetterie et gestion de voyages interurbains

SaaS B2B multi-tenant : agences, bus, voyages, vente de billets au guichet (PDF + QR), embarquement par scan QR, manifestes prévisionnel et définitif figé. Interface en français.

Voir `docs/ARCHITECTURE.md` (décisions, sécurité, concurrence) et `docs/DATA_MODEL.md` (ERD).

## Démarrage rapide (développement, sans Docker)
```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements/dev.txt
export DJANGO_DEBUG=1 DJANGO_SECRET_KEY=dev-key-at-least-32-characters-long-xx
python manage.py migrate
python manage.py seed_demo          # données de démonstration (DEBUG uniquement)
python manage.py runserver          # http://localhost:8000

# Frontend (autre terminal)
cd frontend
npm install
npm run dev                         # http://localhost:5173 (proxy /api → :8000)
```
Comptes de démo (mot de passe `Demo12345!`) : `superadmin@transit.local` (Super Admin), `admin@trans-katanga.local`, `guichet@trans-katanga.local`, `embarquement@trans-katanga.local`.

La caméra du scanner exige **HTTPS ou localhost** (règle des navigateurs). Pour tester sur téléphone, servez l'app en HTTPS.

## Production (Docker Compose)
```bash
cp .env.example .env     # puis remplacer TOUS les secrets (DJANGO_SECRET_KEY, QR_SIGNING_KEY, POSTGRES_PASSWORD)
docker compose up -d --build
docker compose exec backend python manage.py createsuperuser   # puis cocher is_platform_admin dans /admin/
```
Application sur `http://localhost:8080`. En production : placer un reverse proxy HTTPS devant (ou activer `SECURE_SSL_REDIRECT=1` derrière un proxy qui envoie `X-Forwarded-Proto`), renseigner `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`.
Le premier Super Admin peut aussi se créer ainsi : `python manage.py shell -c "from apps.accounts.models import User; User.objects.create_user('vous@exemple.com','MotDePasseSolide!',is_platform_admin=True,is_staff=True,is_superuser=True)"`.

## Variables d'environnement
Voir `.env.example` (toutes commentées). `DJANGO_SECRET_KEY` est obligatoire hors mode debug.

## Tests
```bash
cd backend && pytest                       # 54 tests (SQLite) : isolation, billetterie, concurrence, scan, manifestes, permissions
cd backend && TEST_DB=postgres POSTGRES_HOST=localhost POSTGRES_PASSWORD=... pytest   # mêmes tests sur PostgreSQL (compte avec droit CREATEDB)
cd frontend && npm test     # fuseaux horaires, connexion
cd frontend && npm run build
```

## Sauvegarde PostgreSQL
```bash
docker compose exec db pg_dump -U transit transit | gzip > sauvegarde_$(date +%F).sql.gz
# Restauration
gunzip -c sauvegarde_XXXX.sql.gz | docker compose exec -T db psql -U transit transit
```
Planifier la sauvegarde (cron) et tester la restauration régulièrement.

## Parcours type
1. Super Admin : crée la compagnie + son administrateur initial, choisit l'offre.
2. Admin compagnie : agences, utilisateurs/rôles, bus (sièges générés), chauffeurs.
3. Voyage : création (brouillon) → *Ouvrir à la vente* → ventes au guichet (PDF/QR).
4. *Démarrer l'embarquement* → scanner (téléphone) → *Clôturer* : le manifeste définitif est figé et archivé.

## Limites connues du MVP
- Scan connecté uniquement (voir ARCHITECTURE.md) ; pas de paiement en ligne ni de vente publique.
- Rendu PDF vérifié ; le scanner doit être testé sur vos téléphones Android/navigateurs cibles (caméra, HTTPS).
- Suite complète (dont concurrence : ventes d'un même siège, capacité, scans simultanés) validée sur SQLite **et** PostgreSQL 16. Rejouez-la sur la version de PostgreSQL de votre hébergeur.
- Pas d'export CSV, pas de RLS PostgreSQL, pas de liste noire de refresh tokens (cf. compromis).
- Politique de conservation des données personnelles à définir avec la compagnie pilote.
