"""Entites du jeu : projectiles, ennemis, particules, effets, boutons.

Coordonnees : cellules de la grille ASCII (x = colonne, y = ligne), flottantes.
Une cellule est ~1.85 fois plus haute que large ; pour que les distances et les
vitesses soient "visuellement" homogenes, la physique convertit y * aspect.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import List, Tuple

Color = Tuple[int, int, int]


# --------------------------------------------------------------------------
# Geometrie
# --------------------------------------------------------------------------
def segment_hits_rect(x0: float, y0: float, x1: float, y1: float,
                      rx0: float, ry0: float, rx1: float, ry1: float) -> bool:
    """Le segment (x0,y0)->(x1,y1) traverse-t-il le rectangle ? (methode des 'slabs').
    Test balaye : un projectile rapide ne peut pas 'sauter' par-dessus un ennemi."""
    dx, dy = x1 - x0, y1 - y0
    tmin, tmax = 0.0, 1.0
    for p, d, lo, hi in ((x0, dx, rx0, rx1), (y0, dy, ry0, ry1)):
        if abs(d) < 1e-9:
            if p < lo or p > hi:
                return False
        else:
            t1, t2 = (lo - p) / d, (hi - p) / d
            if t1 > t2:
                t1, t2 = t2, t1
            tmin, tmax = max(tmin, t1), min(tmax, t2)
            if tmin > tmax:
                return False
    return True


# --------------------------------------------------------------------------
# Projectiles
# --------------------------------------------------------------------------
@dataclass
class Bullet:
    x: float
    y: float
    vx: float            # colonnes / s
    vy: float            # lignes / s
    px: float = 0.0      # position precedente (collision balayee)
    py: float = 0.0
    alive: bool = True
    age: float = 0.0

    def __post_init__(self):
        self.px, self.py = self.x, self.y

    def update(self, dt: float) -> None:
        self.px, self.py = self.x, self.y
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.age += dt

    @property
    def glyph(self) -> str:
        """Caractere oriente selon la direction du tir."""
        ang = math.degrees(math.atan2(-self.vy * 1.85, self.vx)) % 180
        if 67.5 <= ang < 112.5:
            return "|"
        if 22.5 <= ang < 67.5:
            return "/"
        if 112.5 <= ang < 157.5:
            return "\\"
        return "-"


# --------------------------------------------------------------------------
# Ennemis
# --------------------------------------------------------------------------
ENEMY_TYPES = {
    # kind:    sprite (lignes), hp, score, couleur, vitesse de base
    "drifter": dict(sprite=["<=O=>"], hp=1, score=10, color=(80, 220, 255), speed=15.0),
    "diver":   dict(sprite=[r"\|/", r"(V)"], hp=1, score=15, color=(255, 190, 60), speed=5.5),
    "wobbler": dict(sprite=["~@~"], hp=1, score=20, color=(255, 90, 200), speed=13.0),
    "tank":    dict(sprite=["/MMM\\", "|XXX|"], hp=4, score=40, color=(150, 255, 110), speed=5.0),
}


class Enemy:
    def __init__(self, kind: str, x: float, y: float, rng: random.Random, speed_mult: float):
        spec = ENEMY_TYPES[kind]
        self.kind = kind
        self.sprite: List[str] = spec["sprite"]
        self.w = max(len(s) for s in self.sprite)
        self.h = len(self.sprite)
        self.hp = self.max_hp = spec["hp"]
        self.score = spec["score"]
        self.color: Color = spec["color"]
        self.x, self.y = x, y                   # centre
        self.rng = rng
        self.alive = True
        self.age = 0.0
        self.flash = 0.0                        # >0 : affiche en blanc (impact)
        self.dir = rng.choice((-1, 1))
        self.base_x = x
        self.phase = rng.uniform(0, 6.28)
        self.heading = rng.uniform(0, 6.28)
        self.turn_timer = rng.uniform(0.2, 0.8)
        spd = spec["speed"] * speed_mult
        self.speed = spd
        self.vx = self.vy = 0.0
        if kind == "drifter":
            self.vx = self.dir * spd
            self.vy = 0.30 * speed_mult          # descend tres lentement
        elif kind == "diver":
            self.vy = spd                        # lignes/s (tombe vite)
        elif kind == "wobbler":
            self.vy = 0.9 * speed_mult
        elif kind == "tank":
            self.vx = self.dir * spd
            self.vy = 1.5 * speed_mult

    # Rectangle de collision, en unites "visuelles" (y * aspect), avec une marge genereuse.
    def hitbox(self, aspect: float, pad: float = 0.6) -> Tuple[float, float, float, float]:
        hw, hh = self.w / 2 + pad, (self.h / 2) * aspect + pad
        cy = self.y * aspect
        return self.x - hw, cy - hh, self.x + hw, cy + hh

    def update(self, dt: float, cols: int, rows: int, rng: random.Random) -> None:
        self.age += dt
        self.flash = max(0.0, self.flash - dt)
        k = self.kind
        if k == "drifter":
            self.x += self.vx * dt
            self.y += self.vy * dt
            # Sortie de l'ecran -> reapparition de l'autre cote, un cran plus bas
            if self.vx > 0 and self.x - self.w / 2 > cols:
                self.x, self.y = -self.w / 2, self.y + 2
            elif self.vx < 0 and self.x + self.w / 2 < 0:
                self.x, self.y = cols + self.w / 2, self.y + 2
        elif k == "diver":
            self.y += self.vy * dt
            self.x = self.base_x + math.sin(self.age * 2.2 + self.phase) * 2.5
        elif k == "wobbler":
            self.turn_timer -= dt
            if self.turn_timer <= 0:      # changement de cap imprevisible
                self.heading += rng.uniform(-2.4, 2.4)
                self.turn_timer = rng.uniform(0.25, 0.9)
            self.x += math.cos(self.heading) * self.speed * dt
            self.y += (math.sin(self.heading) * self.speed * 0.45 + self.vy) * dt
            if self.x > cols + self.w:
                self.x = -self.w / 2
            elif self.x < -self.w:
                self.x = cols + self.w / 2
            if self.y < -self.h:
                self.y = rows + self.h / 2
        elif k == "tank":
            self.x += self.vx * dt
            self.y += self.vy * dt
            if self.x - self.w / 2 < 0:
                self.x, self.vx = self.w / 2, abs(self.vx)
            elif self.x + self.w / 2 > cols:
                self.x, self.vx = cols - self.w / 2, -abs(self.vx)
        # Sortie par le bas -> reapparition en haut
        if self.y - self.h / 2 > rows:
            self.y = -self.h / 2
            if k == "diver":
                self.base_x = rng.uniform(6, cols - 6)

    @property
    def bottom(self) -> float:
        return self.y + self.h / 2


# --------------------------------------------------------------------------
# Effets
# --------------------------------------------------------------------------
@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    char: str
    color: Color
    max_life: float = 0.0
    gravity: float = 0.0

    def __post_init__(self):
        self.max_life = self.life

    def update(self, dt: float) -> None:
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += self.gravity * dt
        self.vx *= 1.0 - 1.6 * dt
        self.life -= dt


@dataclass
class Explosion:
    """Onde de choc ASCII : un anneau qui grandit puis s'eteint."""
    x: float
    y: float
    duration: float
    max_radius: float
    color: Color
    age: float = 0.0

    def update(self, dt: float) -> None:
        self.age += dt

    @property
    def done(self) -> bool:
        return self.age >= self.duration
