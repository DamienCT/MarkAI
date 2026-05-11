# Configuration Meta (Facebook + Instagram) pour MARK AI

> Guide complet pour ajouter une nouvelle marque sur Meta et la connecter à MARK AI pour la publication automatique.
>
> Basé sur les leçons apprises lors de la configuration de la marque Healthspan. Suis les phases dans l'ordre — chaque phase dépend de la précédente.

---

## Vue d'ensemble : 6 niveaux à configurer

```
1. Business Portfolio Meta (le conteneur business)
       ↓
2. Page Facebook  ←→  Compte Instagram Business (liés ensemble)
       ↓
3. App Meta (MarkAI) — déjà existante, pas besoin d'en créer une par marque
       ↓
4. System User (TEST) avec accès aux assets de cette marque
       ↓
5. Page Access Token permanent (dérivé via /me/accounts)
       ↓
6. Brand UI dans MARK AI — canaux configurés avec le token + IDs
```

Une fois ces 6 niveaux corrects, la publication automatique fonctionne pour les deux canaux (FB et IG) avec **un seul token permanent**.

---

## Prérequis

- [ ] Accès admin sur le Business Portfolio Meta de Chemtech (`Rakotomamonjy Allan Ranto / Portefeuille business`)
- [ ] Accès admin sur la Page Facebook de la nouvelle marque
- [ ] Le compte Instagram de la marque doit être de type **Business** ou **Creator** (pas Personnel)
- [ ] Accès au panneau d'admin de l'app **MarkAI** (App ID `1274856484361675`)
- [ ] Accès admin sur l'instance MARK AI de production
- [ ] Accès à l'éditeur n8n sur `srv1191974.hstgr.cloud`

---

## Phase 1 — Préparer la Page Facebook et le compte Instagram

### 1.1 Créer ou récupérer la Page Facebook

Si la Page existe déjà sur un compte personnel, tu vas devoir la "claim" dans le Business Portfolio. Si elle n'existe pas, créer-la d'abord sur Facebook (`facebook.com/pages/create`).

Note l'**ID de la Page** (15 chiffres). Tu le trouves :
- Sur Facebook : Page → À propos → en bas, "ID de la Page"
- Ou via : `https://www.facebook.com/{page-username}` → clic droit → afficher la source → chercher `"page_id"`

> Exemple : Healthspan a Page ID `105594072041737`.

### 1.2 Convertir le compte Instagram en Business / Creator

Sur l'app Instagram (téléphone) :
1. Profil → Menu → Paramètres → Compte
2. **Passer à un compte professionnel** (Business ou Creator)
3. Lier au compte Facebook (la Page de l'étape 1.1)

Note l'**Instagram Business Account ID** (17 chiffres). Tu le trouves via Graph API :

```
GET /{page-id}?fields=instagram_business_account
```

Exemple de réponse :
```json
{ "instagram_business_account": { "id": "17841418686571021" } }
```

> Exemple : Healthspan a IG Business Account ID `17841418686571021`.

### 1.3 Vérifier le lien Page ↔ IG

```
GET /{page-id}?fields=instagram_business_account
```

Doit retourner l'ID IG. Si vide ou erreur, le lien n'est pas fait — refaire l'étape 1.2.

---

## Phase 2 — Ajouter les assets dans le Business Portfolio

Aller sur https://business.facebook.com → **Paramètres / Settings**.

### 2.1 Ajouter la Page Facebook

`Comptes → Pages` → **+ Ajouter** :
- **Ajouter une Page** (si elle est admin par toi sur ton compte personnel) → entrer l'URL ou l'ID Page
- **Demander l'accès à une Page** (si la Page est sur un autre compte) → l'admin de la Page doit accepter

Une fois la Page apparaît dans la liste, vérifie qu'elle dit "Appartient à : Portefeuille business [...]".

### 2.2 Ajouter le compte Instagram Business

`Comptes → Comptes Instagram` → **+ Ajouter** → connecter via Facebook Login (Page admin).

Vérifier qu'`@{handle}` apparaît dans la liste.

---

## Phase 3 — App Meta (déjà configurée pour MarkAI)

L'app MarkAI (`1274856484361675`) est déjà configurée. Vérifier juste :

- [ ] L'app est en mode **Live** (pas Development) si tu veux poster sur des Pages que tu ne contrôles pas en tant que developer/admin de l'app. Sinon Development est OK pour les Pages internes.
- [ ] Les permissions suivantes sont déclarées dans App Review (et approved si en Live) :
  - `pages_show_list`
  - `pages_read_engagement`
  - `pages_manage_posts`
  - `instagram_basic`
  - `instagram_content_publish`
  - `instagram_manage_insights`
  - `business_management`

Si l'app est en Dev, tu peux ajouter le compte Facebook admin de la nouvelle marque comme **Tester** dans l'app pour qu'il puisse interagir avec elle.

---

## Phase 4 — System User et permissions sur les assets

### 4.1 Trouver / créer le System User

Aller dans Business Settings → **Utilisateur(ice)s système**.

Le System User existant est **TEST** (ID `61589546066085`). Le réutiliser pour toutes les marques.

> Tu peux créer un System User par marque si tu veux isoler les permissions (recommandé pour multi-tenant), mais pour le moment on utilise un seul.

### 4.2 Assigner la Page Facebook au System User

`Utilisateur(ice)s système → TEST → ...` (menu) → **Ajouter des éléments**

OU passer par la Page directement :

`Comptes → Pages → [nouvelle Page]` → onglet **Personnes** → **Affecter des personnes** → choisir TEST → cocher **Accès total** ou au minimum **Créer du contenu** + **Modérer** → Enregistrer.

Vérifier ensuite que sur la fiche TEST, la Page apparaît avec `Accès total`.

### 4.3 Assigner le compte Instagram au System User

`Comptes → Comptes Instagram → @{handle}` → onglet **Personnes** → **Affecter des personnes** → choisir TEST → cocher **Accès total** → Enregistrer.

⚠️ **Piège commun** : si tu vois `Aucun élément affecté pour le moment` sur la fiche TEST pour ce compte IG, l'assignation n'est PAS effective. Il faut explicitement choisir un niveau de permission, pas juste lier le compte. Refaire avec **Accès total** sélectionné.

### 4.4 Vérifier les éléments affectés

`Utilisateur(ice)s système → TEST → onglet Éléments affectés` doit montrer :

```
Pages Facebook
  [nouvelle Page]              Accès total

Comptes Instagram
  @[handle]                    Accès total

Applications
  MarkAI                       Accès total
```

Si l'un dit `Aucun élément affecté pour le moment`, refaire l'assignation avec un niveau de permission explicite.

---

## Phase 5 — Générer un token permanent

### 5.1 Générer le System User token

`Utilisateur(ice)s système → TEST` → bouton **Générer un token** (haut droite)

Configuration :

| Champ | Valeur |
|---|---|
| Application | **MarkAI** |
| **Expiration** | **Jamais** ← critique pour token permanent |
| Scopes (cocher tous) | `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `instagram_basic`, `instagram_content_publish`, `instagram_manage_insights`, `business_management` |

Cliquer **Générer un token** → **copier le token immédiatement** (Meta ne le ré-affiche pas).

### 5.2 Vérifier la permanence dans le debugger

Coller le token sur https://developers.facebook.com/tools/debug/accesstoken/ → **Debug**.

Vérifier :
- **Type** : `System User` ✓
- **Expiration** : `Jamais` ✓
- **L'accès aux données expire** : `Jamais` ✓
- **Portées** : la liste doit inclure tous les scopes choisis

Si l'un est différent, recommencer l'étape 5.1.

### 5.3 Récupérer le Page Access Token (le token réellement utilisé)

⚠️ **Le System User token ne marche pas pour POST sur `/photos`** (Meta retourne `(#200) publish_actions deprecated`). Il faut dériver le **Page Access Token** depuis le System User token.

Aller sur https://developers.facebook.com/tools/explorer/ → coller le **System User token** dans le champ Access Token (haut). Puis :

```
GET /me/accounts?fields=id,name,access_token,tasks
```

Réponse attendue :

```json
{
  "data": [
    {
      "id": "{page-id}",
      "name": "{page-name}",
      "access_token": "EAA...une-très-longue-chaîne...",
      "tasks": ["ADVERTISE", "ANALYZE", "CREATE_CONTENT", "MESSAGING", "MODERATE", "MANAGE", ...]
    }
  ]
}
```

**Vérifications critiques** :
- L'ID de la Page apparaît dans `data` (sinon l'assignation Phase 4 n'a pas pris — régénérer le token Phase 5.1)
- `tasks` contient `CREATE_CONTENT` (sinon le niveau de permission Phase 4.2 est insuffisant)

**Copier le `data[0].access_token`** — c'est le **Page Access Token**. C'est CE token qu'on utilise dans MARK AI, pas le System User token.

> Permanence : le Page Access Token hérite la permanence du System User parent. Tant que le System User token est "Jamais", le Page Access Token aussi. Aucune rotation à prévoir.

### 5.4 Test direct dans Graph Explorer (avant MarkAI)

Toujours dans Graph Explorer, coller le **Page Access Token** dans le champ Access Token. Puis :

```
POST /{page-id}/photos
url:          https://www.gstatic.com/webp/gallery/1.webp   (n'importe quelle image publique)
caption:      test from explorer
access_token: {Page Access Token}
```

- ✅ Réponse `200 OK` avec `{ id, post_id }` → le token fonctionne. Continuer Phase 6.
- ❌ `403 publish_actions deprecated` → l'asset assignment n'est pas correcte. Retour Phase 4.
- ❌ `400 image url not accessible` → l'image n'est pas joignable depuis Meta — utiliser une URL publique.

Pour Instagram (test similaire) :

```
POST /{ig-business-account-id}/media
image_url:    https://www.gstatic.com/webp/gallery/1.webp
caption:      test ig
access_token: {Page Access Token}
```

Puis prendre le `id` retourné et :

```
POST /{ig-business-account-id}/media_publish
creation_id:  {id retourné ci-dessus}
access_token: {Page Access Token}
```

Si tout retourne `200`, on est bon.

---

## Phase 6 — Configuration dans MARK AI

### 6.1 Créer / ouvrir la marque

MARK AI → **Brands** → ouvrir la marque cible (ou en créer une nouvelle si besoin).

### 6.2 Onglet Channels

Cliquer l'onglet **Channels** → activer **Facebook** et **Instagram** via les switchs → cliquer l'engrenage de chaque canal pour étendre.

### 6.3 Remplir Facebook

| Champ | Valeur |
|---|---|
| **Page ID** | l'ID de la Page (ex: `105594072041737`) |
| **Access Token** | le **Page Access Token** (Phase 5.3), pas le System User token |

### 6.4 Remplir Instagram

| Champ | Valeur |
|---|---|
| **Handle** | `@{handle}` |
| **Business Account ID** | l'IG Business Account ID (ex: `17841418686571021`) |
| **Access Token** | le **même Page Access Token** que Facebook |

> Pourquoi le même token ? Le Page Access Token marche pour les deux canaux car l'IG Business Account est lié à la Page. Un seul token, deux canaux.

### 6.5 Sauvegarder

Cliquer **Save Channel Config** en bas → attendre le toast `Channel configuration saved`.

⚠️ **Comportement attendu après refresh** : le champ **Access Token** apparaît vide après refresh de la page. **C'est normal** — c'est une mesure de sécurité (le backend strip les tokens des réponses GET). La valeur EST bien sauvegardée en DB. Vérifier en regardant si l'icône de check verte apparaît à côté du nom du canal — ça confirme que `configured: true`.

⚠️ **Piège : ne pas re-sauvegarder avec le champ vide** — ça écraserait le token en DB. Si tu dois modifier d'autres champs après refresh, retape le token aussi avant de Save (ou ne pas toucher au formulaire si tu n'as pas le token sous la main).

---

## Phase 7 — Vérifier la configuration n8n

Le workflow n8n `markai-publish` sur https://n8n.srv1191974.hstgr.cloud doit avoir les bons nœuds.

### 7.1 Vérifier l'Extract Fields

Le nœud **Extract Fields** doit avoir ces assignations (parmi d'autres) :

```
meta_access_token       = {{ $json.body.meta_access_token || '' }}
page_id                 = {{ $json.body.page_id || '' }}
instagram_account_id    = {{ $json.body.instagram_account_id || '' }}
linkedin_access_token   = {{ $json.body.linkedin_access_token || '' }}
linkedin_org_id         = {{ $json.body.linkedin_org_id || '' }}
```

Si l'une manque, l'ajouter via le bouton **+ Add Assignment** dans le nœud.

### 7.2 Vérifier l'URL IG · Create Media

Le nœud **IG · Create Media1** doit avoir :

```
URL: https://graph.facebook.com/v20.0/{{ $('Extract Fields').item.json.instagram_account_id }}/media
```

⚠️ Pas `$json.page_id` (variable erronée), pas `$json.instagram_account_id` (mauvais scope). Doit être `$('Extract Fields').item.json.instagram_account_id` exactement.

### 7.3 Vérifier l'URL IG · Publish Media

Le nœud **IG · Publish Media1** doit avoir :

```
URL: https://graph.facebook.com/v20.0/{{ $('Extract Fields').item.json.instagram_account_id }}/media_publish
```

⚠️ Même règle : référencer Extract Fields explicitement (`$('Extract Fields').item.json.instagram_account_id`), pas juste `$json.instagram_account_id`.

### 7.4 Vérifier l'URL FB · Post Photo

Le nœud **Facebook · Post Photo1** doit avoir :

```
URL: https://graph.facebook.com/v20.0/{{ $json.page_id }}/photos
```

⚠️ FB utilise `$json.page_id` (provient correctement d'Extract Fields, pas besoin de scope explicite ici).

### 7.5 Sauvegarder le workflow

Bouton **Save** (haut droite). Activer le workflow si désactivé.

---

## Phase 8 — Test end-to-end

### 8.1 Créer un contenu test dans MARK AI

Brand → **Generate Content** ou créer un calendar item manuellement → laisser le pipeline générer le contenu.

### 8.2 Publier

Calendar item → **Publish Now** (ou attendre le scheduler).

### 8.3 Vérifier dans n8n

`https://n8n.srv1191974.hstgr.cloud/executions` → chercher l'exécution récente du workflow `markai-publish`. Cliquer pour voir le détail.

- ✅ Tous les nœuds verts → publication réussie
- ❌ Nœud rouge → cliquer dessus pour voir l'erreur, comparer avec le tableau Troubleshooting ci-dessous

### 8.4 Vérifier sur Facebook / Instagram

- Aller sur la Page Facebook → la photo doit apparaître dans le feed
- Aller sur Instagram (`instagram.com/{handle}`) → le post doit apparaître

---

## Troubleshooting

### `(#200) publish_actions deprecated` sur FB POST /photos

**Cause** : token utilisé n'est pas le Page Access Token (probablement le System User token directement).

**Fix** : refaire Phase 5.3 et 6.3 — utiliser le `data[0].access_token` retourné par `/me/accounts`, pas le System User token.

### `Object with ID 'media' does not exist` sur IG Create Media

**Cause** : `instagram_account_id` n'est pas passé à n8n. URL collapse à `/v20.0//media`.

**Fix** : refaire Phase 7.1 et 7.2.

### `Object with ID 'media_publish' does not exist` sur IG Publish Media

**Cause** : Phase 7.3 — l'URL IG Publish Media référence `$json.instagram_account_id` au lieu de `$('Extract Fields').item.json.instagram_account_id`. Après le nœud Create Media, `$json` pointe sur la réponse Graph API, qui ne contient pas `instagram_account_id`.

**Fix** : modifier l'URL dans le nœud IG Publish Media pour utiliser `$('Extract Fields').item.json.instagram_account_id`.

### `/me/accounts` retourne `data: []`

**Cause** : token System User n'a aucune Page assignée à son scope au moment de la génération.

**Fix** : vérifier Phase 4 (assignations correctes), puis **régénérer le token** (Phase 5.1). Les tokens System User snapshotent les assets au moment de la création.

### Le champ Access Token apparaît vide après save + refresh

**Cause** : comportement attendu — le backend GET strip les tokens des réponses pour la sécurité.

**Vérification** : si l'icône check verte est présente à côté du canal, le token EST sauvé en DB. Sinon, re-saisir et re-sauver.

### Image POST échoue avec "image not accessible"

**Cause** : Meta tente de fetch l'`image_url` mais ne peut pas (auth requise, ou domaine non joignable depuis les serveurs Meta).

**Fix** : vérifier que l'URL est publiquement accessible. Pour MarkAI, l'URL est `https://api.markai.srv1191974.hstgr.cloud/api/v1/files/...` qui doit être servie sans auth pour les `content-images`.

### IG fonctionne mais FB échoue (ou vice versa)

**Cause** : la Page et le compte IG ne sont pas liés correctement, ou l'un des deux n'est pas assigné au System User.

**Fix** : Phase 1.3 (vérifier le lien Page ↔ IG) et Phase 4.4 (vérifier les éléments affectés).

---

## Récapitulatif checklist

Pour chaque nouvelle marque :

**Phase 1 — Préparation Meta (côté marque)**
- [ ] Page Facebook créée
- [ ] Compte Instagram converti en Business/Creator
- [ ] IG lié à la Page FB
- [ ] Page ID noté
- [ ] IG Business Account ID noté

**Phase 2 — Business Portfolio**
- [ ] Page ajoutée au Business Portfolio
- [ ] Compte IG ajouté au Business Portfolio

**Phase 3 — App Meta**
- [ ] App MarkAI configurée (déjà fait, vérifier juste)

**Phase 4 — System User**
- [ ] Page assignée à TEST avec Accès total
- [ ] IG assigné à TEST avec Accès total
- [ ] Vérification : tab "Éléments affectés" montre les 2 avec Accès total (pas "Aucun élément affecté")

**Phase 5 — Token**
- [ ] System User token généré avec scopes corrects et "Jamais"
- [ ] Vérification dans le debugger : Type=System User, Expiration=Jamais
- [ ] /me/accounts retourne la Page avec CREATE_CONTENT dans tasks
- [ ] Page Access Token extrait depuis data[0].access_token
- [ ] Test POST /photos depuis Graph Explorer : 200 OK
- [ ] Test POST /media puis /media_publish IG depuis Graph Explorer : 200 OK

**Phase 6 — MARK AI UI**
- [ ] Brand → Channels → Facebook activé, Page ID + Page Access Token saisis
- [ ] Brand → Channels → Instagram activé, Handle + Business Account ID + Page Access Token saisis
- [ ] Save Channel Config → toast confirmé
- [ ] Icône check verte sur les 2 canaux

**Phase 7 — n8n workflow**
- [ ] Extract Fields contient `instagram_account_id`, `linkedin_access_token`, `linkedin_org_id`
- [ ] IG · Create Media URL utilise `$('Extract Fields').item.json.instagram_account_id`
- [ ] IG · Publish Media URL utilise `$('Extract Fields').item.json.instagram_account_id`
- [ ] FB · Post Photo URL utilise `$json.page_id`
- [ ] Workflow sauvegardé et activé

**Phase 8 — Test end-to-end**
- [ ] Contenu test généré dans MARK AI
- [ ] Publish déclenché
- [ ] Exécution n8n verte
- [ ] Post visible sur Facebook
- [ ] Post visible sur Instagram

Une fois toutes les cases cochées, la marque publie automatiquement avec un seul Page Access Token permanent.

---

## Annexe — Permissions Meta requises (référence)

### Scopes minimum par fonctionnalité

| Fonction | Scope requis |
|---|---|
| Lister les Pages du System User | `pages_show_list` |
| Lire le contenu et engagement d'une Page | `pages_read_engagement` |
| Poster sur une Page (photos, feed, ...) | `pages_manage_posts` |
| Lire les insights d'une Page | `pages_read_user_content` |
| Lire un compte IG Business | `instagram_basic` |
| Publier sur IG Business | `instagram_content_publish` |
| Lire les insights IG | `instagram_manage_insights` |
| Opérations business niveau System User | `business_management` |

### Permissions Page (tasks) requises

Sur la Page assignée à TEST, vérifier que les `tasks` retournés par `/me/accounts` incluent au minimum :

- `CREATE_CONTENT` — sans ça, POST /photos échoue
- `MANAGE` — pour les opérations admin
- `ANALYZE` — pour les insights

Le niveau **Accès total** dans Business Settings inclut tout. Si tu veux limiter, choisir au minimum **Créer du contenu** + **Modérer**.

---

## Annexe — Pourquoi 2 tokens (System User vs Page)

| Token | Identité | Marche pour |
|---|---|---|
| **System User token** | "Je suis l'utilisateur TEST" | Lecture business, `/me/accounts`, gestion d'assets |
| **Page Access Token** | "Je suis la Page X" | Tout le Page-write (photos, feed), IG content publish |

Les endpoints Page-write FB sont anciens et leur validation interne demande l'identité Page (pas une délégation business). Le System User token retourne `(#200) publish_actions deprecated` sur ces endpoints — message trompeur mais qui signifie "j'attendais une Page Access Token".

Le Page Access Token est dérivé du System User token via `/me/accounts` et hérite la permanence du parent.

---

## Liens utiles

- Business Settings : https://business.facebook.com/settings
- Graph API Explorer : https://developers.facebook.com/tools/explorer/
- Access Token Debugger : https://developers.facebook.com/tools/debug/accesstoken/
- App Dashboard MarkAI : https://developers.facebook.com/apps/1274856484361675/
- n8n MarkAI : https://n8n.srv1191974.hstgr.cloud
- MarkAI prod : https://markai.srv1191974.hstgr.cloud
