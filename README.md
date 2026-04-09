# Qarta — Backend API

API REST du système de fidélité Qarta. Permet aux commerçants de gérer leurs programmes de fidélité et aux clients de collecter des tampons via QR codes.

## Stack

- **FastAPI** (Python) — framework async
- **Supabase** — base de données PostgreSQL + storage avatars
- **Firebase Admin** — push notifications FCM
- **APScheduler** — notifications planifiées (job toutes les minutes)
- **Railway** — hébergement production

## Installation

```bash
# Cloner et installer les dépendances
pip install -r requirements.txt

# Configurer les variables d'environnement
cp .env.example .env
# Remplir .env avec vos clés

# Lancer en local
uvicorn app.main:app --reload
```

## Variables d'environnement

Voir `.env.example` pour la liste complète. Variables requises :

| Variable | Description |
|---|---|
| `SUPABASE_URL` | URL du projet Supabase |
| `SUPABASE_SERVICE_KEY` | Clé service_role Supabase |
| `SECRET_KEY` | Clé secrète JWT |
| `GOOGLE_CLIENT_ID` | Client ID Google OAuth |
| `FIREBASE_SERVICE_ACCOUNT` | JSON service account Firebase (sur une ligne) |

## Endpoints principaux

| Préfixe | Description |
|---|---|
| `/auth` | Login, register, Google OAuth, codes marchands |
| `/merchants` | Profil commerçant, QR statique, récompenses |
| `/cards` | Cartes fidélité, QR dynamique, stats, export CSV |
| `/scan` | Validation QR et incrémentation tampons |
| `/notifications` | Broadcast, push ciblé, planification |
| `/users` | Profil, photo, changement mot de passe |

Documentation interactive disponible sur `/docs` (Swagger) en local.

## Structure

```
app/
├── main.py          # Point d'entrée FastAPI + scheduler + middleware
├── database.py      # Connexion Supabase
├── dependencies.py  # Authentification JWT
├── logger.py        # Logging structuré
└── routers/
    ├── auth.py
    ├── cards.py
    ├── merchants.py
    ├── notifications.py
    ├── scan.py
    └── users.py
```

## Déploiement

Hébergé sur Railway via `Procfile` :
```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```
