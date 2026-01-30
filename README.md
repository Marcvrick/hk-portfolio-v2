# Portfolio HK Tracker v2 - Firebase

Version avec backend **Firebase Firestore** pour une synchronisation fiable multi-appareils.

## Pourquoi v2 ?

La v1 (hk-portfolio-cron) utilise localStorage + GitHub sync manuel, ce qui cause :
- Conflits de données entre appareils
- Positions "disparues" après sync
- Snapshots non mis à jour

## Différences v1 vs v2

| | v1 (localStorage + GitHub) | v2 (Firebase) |
|---|---|---|
| Stockage | localStorage + data.json | Firebase Firestore |
| Sync | Manuel (Push/Pull) | **Automatique temps réel** |
| Conflits | Fréquents | Aucun |
| Multi-device | Fragile | Natif |
| Cron | Écrit dans data.json | Écrit dans Firestore |
| Offline | Oui | Oui (avec sync auto) |

---

## Setup Firebase

### 1. Créer projet Firebase
1. Aller sur https://console.firebase.google.com
2. Créer un nouveau projet "hk-portfolio-tracker"
3. Activer **Firestore Database** (mode production, région asia-east1)
4. Aller dans Project Settings > Your apps > Web app
5. Copier la config Firebase

### 2. Structure Firestore

```
portfolios/
  └── main/
      ├── positions: []
      ├── closedTrades: []
      ├── transactions: []
      ├── snapshots: []
      ├── settings: {}
      └── priceCache: {}
```

### 3. Règles de sécurité Firestore (dev)

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /portfolios/{portfolioId} {
      allow read, write: if true;
    }
  }
}
```

> Note: À sécuriser avec authentification pour production

### 4. Config pour le cron (update.py)

Créer un Service Account:
1. Firebase Console > Project Settings > Service Accounts
2. Generate new private key
3. Sauvegarder comme `firebase-credentials.json`
4. Ajouter en secret GitHub Actions

---

## Migration Plan

### Phase 1: Setup
- [ ] Créer projet Firebase
- [ ] Configurer Firestore
- [ ] Ajouter Firebase SDK à index.html

### Phase 2: Frontend
- [ ] Remplacer localStorage par Firestore
- [ ] Implémenter listeners temps réel
- [ ] Supprimer logique GitHub sync (Push/Pull buttons)
- [ ] Garder export JSON pour backup

### Phase 3: Cron
- [ ] Installer firebase-admin pour Python
- [ ] Modifier update.py pour écrire dans Firestore
- [ ] Configurer GitHub Actions avec credentials

### Phase 4: Deploy
- [ ] Créer nouveau repo GitHub
- [ ] Configurer GitHub Pages
- [ ] Tester sync multi-appareils
- [ ] Importer données existantes

---

## Fichiers

- `index.html` — App React (à modifier pour Firebase)
- `update.py` — Cron Yahoo Finance (à modifier pour Firebase)
- `data.json` — Données v1 (pour import initial)
- `.github/workflows/daily-update.yml` — GitHub Actions cron

---

## Tech Stack

**Frontend:**
- React 18 (CDN)
- Firebase JS SDK 10.x
- Recharts
- Tailwind CSS

**Backend:**
- Firebase Firestore (database)
- GitHub Actions (cron)
- Python + firebase-admin

---

## Commandes utiles

```bash
# Installer firebase-admin pour Python
pip install firebase-admin

# Tester le cron localement
GOOGLE_APPLICATION_CREDENTIALS=firebase-credentials.json python update.py
```

---

## Coûts Firebase (Spark plan - gratuit)

- 50K lectures/jour
- 20K écritures/jour
- 1GB stockage
- 10GB transfert/mois

Largement suffisant pour un portfolio personnel.
