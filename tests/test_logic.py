"""Tests sans webcam ni vraie fenetre : `python tests/test_logic.py` (ou pytest).

Couvre : filtre One-Euro, mesure du pouce et direction du doigt sur des landmarks
synthetiques, anti-rebond, correspondance webcam -> ecran -> cellules, collisions
balayees, balles qui partent du bout de l'index, apparition des ennemis.
"""
import math
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import game as G  # noqa: E402
from entities import Enemy, segment_hits_rect  # noqa: E402
from hand_tracking import (HandState, OneEuro, TriggerFilter, finger_direction,  # noqa: E402
                           thumb_ratio)


# ---------------------------------------------------------------- tracking
def make_hand(thumb_tip, index_tip=(0.46, 0.30)):
    """21 landmarks synthetiques (image 640x480) : poignet en bas, doigts vers le haut."""
    lm = [(0.5, 0.5)] * 21
    lm = list(lm)
    lm[0] = (0.50, 0.80)    # poignet
    lm[5] = (0.46, 0.55)    # base index
    lm[6] = (0.46, 0.46)    # PIP index
    lm[8] = index_tip       # bout index
    lm[9] = (0.50, 0.54)    # base majeur
    lm[17] = (0.60, 0.60)   # base auriculaire
    lm[4] = thumb_tip
    return lm


def test_thumb_ratio_up_vs_down():
    up = thumb_ratio(make_hand((0.30, 0.50)), 640, 480)      # pouce ecarte
    down = thumb_ratio(make_hand((0.47, 0.52)), 640, 480)    # pouce replie sur l'index
    assert up > 0.6, up
    assert down < 0.3, down
    assert down < config.THUMB_PRESS < config.THUMB_RELEASE < up


def test_thumb_ratio_independent_of_index_tip():
    a = make_hand((0.30, 0.50))
    b = make_hand((0.30, 0.50), index_tip=(0.10, 0.05))      # l'index bouge enormement
    assert abs(thumb_ratio(a, 640, 480) - thumb_ratio(b, 640, 480)) < 1e-9


def test_thumb_ratio_scale_invariant():
    near = make_hand((0.47, 0.52))
    far = [(0.5 + (x - 0.5) * 0.5, 0.5 + (y - 0.5) * 0.5) for x, y in near]  # main 2x plus petite
    assert abs(thumb_ratio(near, 640, 480) - thumb_ratio(far, 640, 480)) < 1e-6


def test_finger_direction():
    dx, dy = finger_direction(make_hand((0.3, 0.5)), 640, 480)       # index vertical, vers le haut
    assert abs(math.hypot(dx, dy) - 1) < 1e-9
    assert dy < -0.99 and abs(dx) < 0.1
    dx, dy = finger_direction(make_hand((0.3, 0.5), index_tip=(0.9, 0.55)), 640, 480)  # vers la droite
    assert dx > 0.99
    # calcule en pixels : un doigt a 45 deg en pixels reste a 45 deg meme si l'image n'est pas carree
    lm = make_hand((0.3, 0.5), index_tip=(0.46 + 0.1, 0.55 - 0.1 * 640 / 480))
    dx, dy = finger_direction(lm, 640, 480)
    assert abs(abs(dx) - abs(dy)) < 1e-6


def test_trigger_debounce_and_hysteresis():
    f = TriggerFilter(0.42, 0.55, 2, 2, 0.75)
    assert f.update(0.9) is False
    assert f.update(0.40) is False        # 1 seule image limite : rebond ignore
    assert f.update(0.9) is False
    assert f.update(0.40) is False
    assert f.update(0.40) is True         # 2 images consecutives : tir
    assert f.update(0.50) is True         # entre les deux seuils : hysteresis, reste en tir
    assert f.update(0.60) is True         # 1 image au dessus du relache : pas encore
    assert f.update(0.50) is True
    assert f.update(0.60) is True
    assert f.update(0.60) is False        # 2 images consecutives : arret
    assert f.update(0.10) is True         # geste net (< 0.42*0.75) : immediat


def test_one_euro_smooths_jitter_but_follows_motion():
    f = OneEuro(config.CURSOR_MIN_CUTOFF, config.CURSOR_BETA)
    t, out = 0.0, []
    for i in range(60):               # immobile + bruit +-0.004
        t += 1 / 30
        out.append(f(0.5 + (0.004 if i % 2 else -0.004), t))
    assert max(out[10:]) - min(out[10:]) < 0.004   # bruit divise
    f = OneEuro(config.CURSOR_MIN_CUTOFF, config.CURSOR_BETA)
    t = 0.0
    for i in range(30):               # mouvement rapide 0 -> 1 en 1 s
        t += 1 / 30
        y = f(i / 29, t)
    assert y > 0.9                    # le filtre suit sans gros retard


# ---------------------------------------------------------------- coordonnees
def test_camera_cover_mapping():
    import pygame
    from renderer import Renderer
    r = Renderer(config.GRID_COLS, config.GRID_ROWS, (1280, 720))
    ox, oy, dw, dh = r.camera_rect()
    assert abs(dw - 1280) < 1e-6 and abs(dh - 960) < 1e-6      # 640x480 couvre 1280x720 : rogne en hauteur
    assert abs(oy + 120) < 1e-6
    # centre de l'image -> centre de la fenetre -> centre de la grille
    cx, cy = r.hand_to_cells(HandState(tip=(0.5, 0.5)))
    assert abs(cx - (config.GRID_COLS / 2 - 0.5)) < 1.0 and abs(cy - (config.GRID_ROWS / 2 - 0.5)) < 1.0
    # un point a droite de l'image est a droite dans la grille, un point haut est en haut
    assert r.hand_to_cells(HandState(tip=(0.8, 0.5)))[0] > cx
    assert r.hand_to_cells(HandState(tip=(0.5, 0.3)))[1] < cy
    # le pixel retombe exactement sur le pixel de la camera dessinee
    px, py = r.cam_to_pixels(0.25, 0.75)
    assert abs(px - 320) < 1e-6 and abs(py - (-120 + 0.75 * 960)) < 1e-6
    # mode souris : coordonnees d'ecran normalisees
    mx, my = r.hand_to_cells(HandState(tip=(0.0, 1.0), screen_space=True))
    assert mx < 0 and my > config.GRID_ROWS - 1.5
    pygame.quit()


# ---------------------------------------------------------------- physique
def test_segment_hits_rect():
    assert segment_hits_rect(0, 0, 10, 0, 4, -1, 6, 1)           # traverse
    assert not segment_hits_rect(0, 5, 10, 5, 4, -1, 6, 1)       # passe a cote
    assert segment_hits_rect(0, 0, 100, 0, 40, -1, 42, 1)        # tres rapide : pas de tunneling
    assert not segment_hits_rect(0, 0, 3, 0, 4, -1, 6, 1)        # s'arrete avant


# ---------------------------------------------------------------- jeu
def ctl(tip=(65.0, 30.0), direction=(0.0, -1.0), fire=False, present=True):
    return G.Controls(tip, direction, fire, present)


def run_for(g, seconds, fn, dt=1 / 60):
    for _ in range(int(seconds / dt)):
        g.update(dt, fn(g))


def test_bullets_leave_fingertip_in_finger_direction():
    g = G.Game(seed=1)
    g.enemies.clear()
    config_spawn = config.MAX_ENEMIES
    config.MAX_ENEMIES = 0                      # pas d'ennemis : on observe juste les balles
    try:
        direction = (math.sin(math.radians(30)), -math.cos(math.radians(30)))  # 30 deg a droite de la verticale
        run_for(g, 0.5, lambda _: ctl((40.0, 30.0), direction, fire=False))     # laisse le viseur se caler
        g.update(1 / 60, ctl((40.0, 30.0), direction, fire=True))
        b = g.bullets[0]
        assert abs(b.x - 40.0) < 3 and abs(b.y - 30.0) < 2, (b.x, b.y)          # sort du bout du doigt
        # direction VISUELLE de la balle = direction du doigt (y converti avec l'aspect)
        vis = (b.vx, b.vy * g.aspect)
        n = math.hypot(*vis)
        assert abs(vis[0] / n - direction[0]) < 0.02 and abs(vis[1] / n - direction[1]) < 0.02
        assert abs(n - config.BULLET_SPEED) < 1
    finally:
        config.MAX_ENEMIES = config_spawn


def test_bullet_hits_enemy_in_line_with_finger():
    g = G.Game(seed=2)
    config_max = config.MAX_ENEMIES
    config.MAX_ENEMIES = 0
    try:
        e = Enemy("drifter", 65, 8, g.rng, 0.0)
        e.vx = e.vy = 0
        g.enemies.append(e)
        for _ in range(60):                                                    # droit vers le haut
            g.update(1 / 60, ctl((65.0, 30.0), (0.0, -1.0), fire=True))
            if not e.alive:
                break
        assert not e.alive
        assert g.explosions and g.particles                                    # effet de destruction
    finally:
        config.MAX_ENEMIES = config_max


def test_bullet_misses_when_finger_points_elsewhere():
    g = G.Game(seed=3)
    config_max = config.MAX_ENEMIES
    config.MAX_ENEMIES = 0
    try:
        e = Enemy("drifter", 65, 8, g.rng, 0.0)
        e.vx = e.vy = 0
        g.enemies.append(e)
        run_for(g, 1.0, lambda _: ctl((20.0, 30.0), (0.0, -1.0), fire=True))   # tire a cote
        assert e.alive
    finally:
        config.MAX_ENEMIES = config_max


def test_enemies_spawn_and_respect_max():
    g = G.Game(seed=4)
    run_for(g, 30, lambda _: ctl())
    assert 1 <= len(g.enemies) <= config.MAX_ENEMIES
    assert {e.kind for e in g.enemies} <= {"drifter", "diver", "wobbler", "tank"}


def test_no_game_state_is_needed():
    g = G.Game(seed=5)
    for attr in ("lives", "score", "kills", "level", "state"):
        assert not hasattr(g, attr), attr


def test_short_hand_loss_does_not_fire_nor_crash():
    g = G.Game(seed=6)
    run_for(g, 0.5, lambda _: ctl(fire=True))
    n = len(g.bullets)
    run_for(g, 0.5, lambda _: ctl(fire=True, present=False))
    assert not g.firing
    assert len(g.bullets) <= n                       # plus aucun nouveau tir (les anciennes balles sortent)


def test_fire_rate():
    g = G.Game(seed=7)
    created = 0
    orig = g._shoot

    def counting():
        nonlocal created
        created += 1
        orig()
    g._shoot = counting
    for _ in range(120):                              # 2 s a 60 FPS
        g.update(1 / 60, ctl(fire=True))
    assert abs(created - 2 * config.FIRE_RATE) <= 2, created


def test_enemy_types_move_and_wrap():
    rng = random.Random(0)
    for kind in ("drifter", "diver", "wobbler", "tank"):
        e = Enemy(kind, 20, 5, rng, 1.0)
        x0, y0 = e.x, e.y
        for _ in range(600):
            e.update(1 / 60, 130, 38, rng)
        assert (e.x, e.y) != (x0, y0), kind
    d = Enemy("drifter", 128, 5, rng, 1.0)             # sort a droite -> reapparait a gauche
    d.vx = 15
    for _ in range(60):
        d.update(1 / 60, 130, 38, rng)
    assert d.x < 10
    v = Enemy("diver", 50, 37, rng, 1.0)               # sort en bas -> reapparait en haut
    for _ in range(120):
        v.update(1 / 60, 130, 38, rng)
    assert v.y < 20


def test_renderer_headless_frames():
    import numpy as np
    import pygame
    from renderer import Renderer, UiInfo
    r = Renderer(config.GRID_COLS, config.GRID_ROWS, (1280, 720))
    g = G.Game(seed=8, aspect=r.cell_aspect)
    cam = np.full((480, 640, 3), 90, dtype=np.uint8)
    cam[:, 320:] = (60, 90, 140)
    cam.flags.writeable = False
    hand = HandState(present=True, detected=True, tip=(0.5, 0.65), direction=(0.2, -0.98),
                     firing=True, preview=cam, seq=1)
    for e_kind, x, y in (("drifter", 30, 8), ("diver", 50, 14), ("wobbler", 80, 6), ("tank", 100, 18)):
        g.enemies.append(Enemy(e_kind, x, y, g.rng, 1.0))
    for i in range(45):
        tip = r.hand_to_cells(hand)
        g.update(1 / 60, G.Controls(tip, hand.direction, True, True))
    r.render_game(g, hand, UiInfo())
    out = os.environ.get("PYSHOOTER_SHOTS")
    if out:
        Path(out).mkdir(parents=True, exist_ok=True)
        pygame.image.save(r.screen, str(Path(out) / "overlay.png"))
    pygame.quit()


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except Exception as exc:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                print(f"FAIL {name}: {exc!r}")
                fails += 1
    sys.exit(1 if fails else 0)
