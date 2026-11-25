# Py-Shooter - tire avec ton index

Ta webcam en plein ecran, et par dessus des ennemis ASCII qui apparaissent.
Ton **index** est l'arme : les balles partent du **bout de ton doigt**, dans la **direction ou il pointe**.
Tu **baisses le pouce** pour tirer. Pas de score, pas de vies : juste tirer sur des ennemis.

## Installation

Prerequis : Python 3.10 - 3.12 (teste sur 3.12, Windows 11) et une webcam.

```powershell
cd C:\Users\Mat\Desktop\perso\py-shooter
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

`main.py` detecte le dossier `.venv` et s'y relance tout seul : pas besoin de l'activer.
MediaPipe est fixe a la 0.10.21, derniere version qui embarque le modele de main :
aucun telechargement au premier lancement, ca marche hors-ligne.

## Lancer

```powershell
python main.py
```

| Commande | Effet |
|---|---|
| `python main.py` | Le jeu |
| `python main.py --diag` | Diagnostic : flux webcam + landmarks, direction du tir, etat du pouce, FPS, latence |
| `python main.py --mouse` | A la souris (clic gauche = tir), utile sans webcam |
| `python main.py --help` | Tous les reglages en ligne de commande |

Si la webcam est introuvable, le jeu bascule en mode souris et l'indique.

## Jouer

* **Viser** : pointe l'index vers les ennemis. Un repere `+` marque le bout du doigt, des points montrent la direction du tir.
* **Tirer** : replie le **pouce** contre l'index (comme le chien d'un pistolet). Releve-le pour arreter.
  Le tir ne depend que du pouce, pas du mouvement de l'index.
* Les ennemis sortent de l'ecran et reapparaissent de l'autre cote ; il n'y a rien a perdre.

| Ennemi | Comportement |
|---|---|
| `<=O=>` | patrouille horizontale |
| `(V)` | plongeur vertical |
| `~@~` | erratique, change de cap sans prevenir |
| `/MMM\` | tank lent, 4 points de vie |

## Premiere utilisation (2 minutes)

1. `python main.py --diag` : verifie que ta main est detectee, que le cercle suit le bout de l'index,
   que la ligne indique bien la direction du doigt, et que "TIR !" s'affiche quand tu replies le pouce.
2. Appuie sur **`U`** pouce leve, puis **`D`** pouce baisse : les seuils de tir sont calcules sur **ta** main
   (sauvegardes dans `calibration.json`).
3. `python main.py` et joue.

Conseils : bon eclairage (la webcam monte en FPS avec de la lumiere), main a 30-70 cm de la camera.

### Touches

| Touche | Action |
|---|---|
| `U` / `D` | calibrer le pouce leve / baisse |
| `R` | reinitialiser la calibration |
| `M` | miroir on/off |
| `F11` | plein ecran |
| `Echap` | quitter |

## Architecture

| Fichier | Role |
|---|---|
| `main.py` | lancement, arguments, boucle principale 60 FPS, clavier |
| `hand_tracking.py` | webcam + MediaPipe (2 threads), filtre One-Euro, position/direction de l'index, mesure du pouce, anti-rebond, calibration, repli souris |
| `game.py` | ennemis qui apparaissent, balles, collisions, effets |
| `entities.py` | projectiles, ennemis, particules, explosions, collision segment/rectangle |
| `renderer.py` | webcam "cover" en fond + rendu ASCII par dessus, correspondance webcam -> ecran -> cellules, ecran diagnostic |
| `config.py` | **tous les parametres** |
| `tests/test_logic.py` | tests sans webcam (`python tests/test_logic.py`) |

* **Superposition exacte** : la webcam est dessinee en mode "cover" (elle remplit la fenetre, le surplus est rogne) ;
  la position de l'index est convertie avec la meme geometrie, donc le repere tombe pile sur ton doigt a l'image.
* **Direction du tir** : vecteur base de l'index (MCP) -> bout, calcule en pixels, lisse (One-Euro) puis interpole a 60 FPS.
* **Tir** : `ratio = distance(bout du pouce, base/articulation de l'index) / taille de la main` ; hysteresis + anti-rebond
  (2 images consecutives), geste franc valide immediatement. N'utilise jamais le bout de l'index.
* **Pertes de detection** : etat conserve 0,25 s, puis le tir s'arrete ; le jeu ne plante jamais.
* **Fluidite** : capture et detection dans des threads separes, le jeu lit un instantane ; affichage a 60 FPS meme si la webcam en fait 20.

## Parametres (`config.py`)

| Parametre | Defaut | Effet |
|---|---|---|
| `MIRROR` | True | effet miroir |
| `CAMERA_INDEX`, `CAMERA_WIDTH`, `CAMERA_HEIGHT`, `CAMERA_FPS`, `CAMERA_MJPG` | 0, 640, 480, 30, True | webcam |
| `MODEL_COMPLEXITY` | 0 | 0 rapide, 1 precis (~4x plus lent) |
| `DETECT_WIDTH` | 320 | largeur de l'image envoyee a MediaPipe |
| `CURSOR_MIN_CUTOFF` / `CURSOR_BETA` | 2.0 / 15 | lissage de la position du doigt |
| `DIR_MIN_CUTOFF` / `DIR_BETA` | 1.5 / 3 | lissage de la direction du doigt |
| `CURSOR_FOLLOW_RATE` | 30 | nervosite de l'interpolation cote jeu |
| `THUMB_PRESS` / `THUMB_RELEASE` | 0.42 / 0.55 | seuils du pouce (ecrases par la calibration) |
| `THUMB_PRESS_FRAMES` / `THUMB_RELEASE_FRAMES` | 2 / 2 | anti-rebond |
| `FIRE_RATE` | 10 | tirs par seconde |
| `BULLET_SPEED` | 120 | vitesse des balles |
| `ENEMY_SPEED` | 1.0 | vitesse des ennemis |
| `SPAWN_INTERVAL`, `MAX_ENEMIES` | 1.0 s, 9 | rythme d'apparition, nombre max a l'ecran |
| `CAMERA_DIM` | 0.35 | assombrit la webcam pour mieux voir l'ASCII |
| `WINDOW_SIZE`, `FULLSCREEN`, `GRID_COLS`, `GRID_ROWS` | 1280x720, False, 130x38 | affichage |

Exemple : `python main.py --fire-rate 12 --enemy-speed 1.5 --no-mirror --camera 1 --fullscreen`

## Depannage

* **Webcam introuvable** : ferme les applis qui l'utilisent (Teams, Zoom, navigateur) ou essaie `--camera 1`.
* **Peu de FPS camera (~10-20)** : manque de lumiere (l'exposition automatique ralentit la capture).
* **Le tir part tout seul / ne part pas** : refais la calibration (`U`, `D`) en regardant la jauge dans `--diag`.
* **Les balles ne partent pas pile dans l'axe du doigt** : verifie la ligne de direction dans `--diag`.
  Pointe l'index bien tendu, bout du doigt visible par la camera.
