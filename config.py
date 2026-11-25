"""Configuration centrale de Py-Shooter.

Toutes les valeurs ci-dessous peuvent etre modifiees directement ici, ou
surchargees en ligne de commande (voir `python main.py --help`).
Certains reglages (miroir, sensibilite, calibration du pouce) se changent
aussi en direct avec le clavier pendant la partie.
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# --------------------------------------------------------------------------
# Webcam
# --------------------------------------------------------------------------
CAMERA_INDEX = 0          # 0 = webcam par defaut, 1 = deuxieme camera, ...
CAMERA_WIDTH = 640        # resolution demandee (640x480 = le meilleur compromis)
CAMERA_HEIGHT = 480
CAMERA_FPS = 30
CAMERA_MJPG = True        # MJPG : beaucoup plus de FPS que le format brut sous Windows
MIRROR = True             # effet miroir : comme un miroir, ta main a droite apparait a droite

# --------------------------------------------------------------------------
# Detection de la main (MediaPipe Hands)
# --------------------------------------------------------------------------
MODEL_COMPLEXITY = 0      # 0 = rapide (recommande), 1 = plus precis mais ~4x plus lent
DETECT_WIDTH = 320        # l'image est reduite a cette largeur avant detection (0 = pas de reduction)
DETECTION_CONFIDENCE = 0.5
TRACKING_CONFIDENCE = 0.5
HAND_LOST_GRACE = 0.25    # s : on garde le dernier etat si la main disparait moins longtemps

# --------------------------------------------------------------------------
# Index : position du bout du doigt et direction de tir
# --------------------------------------------------------------------------
# Filtre One-Euro (anti-tremblement a basse vitesse, faible latence a haute vitesse).
CURSOR_MIN_CUTOFF = 2.0   # position : plus bas = plus stable mais plus de retard quand on est lent
CURSOR_BETA = 15.0        # position : plus haut = moins de retard quand on bouge vite
DIR_MIN_CUTOFF = 1.5      # direction du doigt (plus stable que la position : elle est amplifiee en tir)
DIR_BETA = 3.0
# Interpolation cote jeu (60 FPS) entre deux mesures de la webcam (~20-30 FPS).
CURSOR_FOLLOW_RATE = 30.0  # 1/s : plus haut = plus nerveux

# --------------------------------------------------------------------------
# Geste de tir (pouce)
# --------------------------------------------------------------------------
# Le pouce est mesure par la distance bout du pouce <-> base/articulation de
# l'index, divisee par la taille de la main (donc independante de la distance
# a la camera et du mouvement de l'index). Pouce leve ~0.6-0.9, pouce baisse ~0.1-0.3.
# Calibre-les avec U (pouce leve) puis D (pouce baisse) : c'est sauvegarde.
THUMB_PRESS = 0.42        # ratio en dessous duquel on tire
THUMB_RELEASE = 0.55      # ratio au dessus duquel on arrete (hysteresis)
THUMB_PRESS_FRAMES = 2    # nb d'images consecutives pour valider un tir (anti-rebond)
THUMB_RELEASE_FRAMES = 2  # nb d'images consecutives pour valider l'arret
THUMB_CLEAR_MARGIN = 0.75  # geste "net" (ratio < PRESS*0.75) = validation immediate
CALIBRATION_FILE = BASE_DIR / "calibration.json"

# --------------------------------------------------------------------------
# Jeu
# --------------------------------------------------------------------------
FIRE_RATE = 10.0          # tirs par seconde quand le pouce est baisse
BULLET_SPEED = 120.0      # colonnes/seconde (la largeur de l'ecran en ~1 s)
ENEMY_SPEED = 1.0         # multiplicateur global de la vitesse des ennemis
SPAWN_INTERVAL = 1.0      # secondes (en moyenne) entre deux apparitions d'ennemis
MAX_ENEMIES = 9           # nombre maximum d'ennemis a l'ecran
GRID_COLS = 130           # taille de la grille ASCII
GRID_ROWS = 38
CELL_ASPECT = 1.85        # hauteur / largeur d'un caractere (mesure ensuite par le renderer)

# --------------------------------------------------------------------------
# Affichage
# --------------------------------------------------------------------------
WINDOW_SIZE = (1280, 720)
FULLSCREEN = False
FPS_LIMIT = 60
FONT_NAMES = "consolas,cascadiamono,couriernew,dejavusansmono,menlo,monospace"
CAMERA_DIM = 0.35         # 0 = webcam telle quelle, 1 = noir : assombrit le fond pour mieux voir l'ASCII
