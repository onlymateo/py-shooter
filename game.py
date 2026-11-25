"""Logique du jeu : des ennemis qui apparaissent, des balles qui partent du bout de l'index.

Aucune dependance a la webcam ni a l'affichage. `Game.update(dt, controls)` tourne a la
cadence de l'affichage (60 FPS) ; la position et la direction du doigt sont interpolees
entre deux mesures de la webcam.

Coordonnees : cellules de la grille ASCII (x = colonne, y = ligne). Les directions sont
des vecteurs unitaires en espace "visuel" (pixels), convertis en cellules grace a `aspect`
(hauteur / largeur d'une cellule).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

import config
from entities import Bullet, Enemy, Explosion, Particle, segment_hits_rect


@dataclass
class Controls:
    """Ce que le jeu attend du joueur, quelle que soit la source (main ou souris)."""
    tip: Tuple[float, float] = (65.0, 19.0)     # bout de l'index, en cellules
    direction: Tuple[float, float] = (0.0, -1.0)  # sens du doigt (unitaire, espace visuel)
    fire: bool = False
    present: bool = True


class Game:
    def __init__(self, cols: int = config.GRID_COLS, rows: int = config.GRID_ROWS,
                 seed: Optional[int] = None, aspect: float = config.CELL_ASPECT):
        self.cols, self.rows = cols, rows
        self.aspect = aspect
        self.rng = random.Random(seed)
        self.time = 0.0
        self.tip = [cols / 2.0, rows / 2.0]       # bout de l'index lisse (cellules)
        self.dir = [0.0, -1.0]                    # direction lissee (espace visuel)
        self.firing = False
        self.muzzle = 0.0
        self._fire_cd = 0.0
        self._spawn_timer = 0.3
        self.enemies: List[Enemy] = []
        self.bullets: List[Bullet] = []
        self.particles: List[Particle] = []
        self.explosions: List[Explosion] = []

    # ------------------------------------------------------------------
    def update(self, dt: float, ctl: Controls) -> None:
        dt = max(0.0, min(dt, 0.05))     # un gros hoquet ne doit pas teleporter les entites
        self.time += dt
        self._update_finger(dt, ctl)

        self.firing = bool(ctl.fire and ctl.present)
        self._update_fire(dt)
        self._update_spawning(dt)
        for e in self.enemies:
            e.update(dt, self.cols, self.rows, self.rng)
        for b in self.bullets:
            b.update(dt)
        self._collide()
        self._update_effects(dt)

    # -- doigt ----------------------------------------------------------
    def _update_finger(self, dt: float, ctl: Controls) -> None:
        if not ctl.present:
            return                                   # main perdue : on garde la derniere pose
        a = 1.0 - math.exp(-config.CURSOR_FOLLOW_RATE * dt)   # interpolation independante du FPS
        self.tip[0] += (ctl.tip[0] - self.tip[0]) * a
        self.tip[1] += (ctl.tip[1] - self.tip[1]) * a
        self.dir[0] += (ctl.direction[0] - self.dir[0]) * a
        self.dir[1] += (ctl.direction[1] - self.dir[1]) * a
        n = math.hypot(*self.dir)
        if n < 1e-6:
            self.dir[:] = ctl.direction
        else:
            self.dir[0] /= n
            self.dir[1] /= n

    # -- tir ------------------------------------------------------------
    def _update_fire(self, dt: float) -> None:
        period = 1.0 / max(config.FIRE_RATE, 0.1)
        self._fire_cd -= dt
        if self.firing:
            n = 0
            while self._fire_cd <= 0.0 and n < 3:
                self._shoot()
                self._fire_cd += period
                n += 1
            if self._fire_cd < 0.0:
                self._fire_cd = 0.0
        else:
            self._fire_cd = max(self._fire_cd, 0.0)

    def _shoot(self) -> None:
        dx, dy = self.dir
        reach = 1.5                                   # la balle sort juste devant le bout du doigt
        ox = self.tip[0] + dx * reach
        oy = self.tip[1] + dy * reach / self.aspect
        speed = config.BULLET_SPEED
        self.bullets.append(Bullet(ox, oy, dx * speed, dy * speed / self.aspect))
        self.muzzle = 0.06

    # -- apparition des ennemis ----------------------------------------
    def _update_spawning(self, dt: float) -> None:
        self._spawn_timer -= dt
        if self._spawn_timer > 0 or len(self.enemies) >= config.MAX_ENEMIES:
            return
        self._spawn_timer = config.SPAWN_INTERVAL * self.rng.uniform(0.6, 1.4)
        kind = self.rng.choices(("drifter", "diver", "wobbler", "tank"), (5, 3.5, 3, 1.2))[0]
        m = config.ENEMY_SPEED
        if kind == "drifter":
            side = self.rng.choice((-1, 1))
            x = -3.0 if side > 0 else self.cols + 3.0
            e = Enemy(kind, x, self.rng.uniform(3, self.rows * 0.7), self.rng, m)
            e.vx = side * abs(e.vx)
        else:
            e = Enemy(kind, self.rng.uniform(6, self.cols - 6), -1.0, self.rng, m)
        self.enemies.append(e)

    # -- collisions -----------------------------------------------------
    def _collide(self) -> None:
        asp = self.aspect
        for b in self.bullets:
            if not (-6 <= b.x <= self.cols + 6 and -6 <= b.y <= self.rows + 6):
                b.alive = False
                continue
            best, best_d = None, 1e18
            for e in self.enemies:
                if e.alive and segment_hits_rect(b.px, b.py * asp, b.x, b.y * asp, *e.hitbox(asp)):
                    d = (e.x - b.px) ** 2 + ((e.y - b.py) * asp) ** 2
                    if d < best_d:
                        best, best_d = e, d
            if best is not None:
                b.alive = False
                self._hit_enemy(best, b)
        self.bullets = [b for b in self.bullets if b.alive]
        self.enemies = [e for e in self.enemies if e.alive]

    def _hit_enemy(self, e: Enemy, b: Bullet) -> None:
        e.hp -= 1
        e.flash = 0.09
        self._sparks(b.x, b.y, 5, e.color, 26)
        if e.hp <= 0:
            e.alive = False
            self._explode(e.x, e.y, e.color, big=e.max_hp > 1)

    # -- effets ---------------------------------------------------------
    def _sparks(self, x: float, y: float, n: int, color, speed: float) -> None:
        for _ in range(n):
            a = self.rng.uniform(0, math.tau)
            s = self.rng.uniform(0.3, 1.0) * speed
            self.particles.append(Particle(x, y, math.cos(a) * s, math.sin(a) * s / self.aspect,
                                           self.rng.uniform(0.15, 0.35),
                                           self.rng.choice("*+.'`"), color))

    def _explode(self, x: float, y: float, color, big: bool = False) -> None:
        for _ in range(26 if big else 14):
            a = self.rng.uniform(0, math.tau)
            s = self.rng.uniform(0.2, 1.0) * (40 if big else 28)
            self.particles.append(Particle(x, y, math.cos(a) * s, math.sin(a) * s / self.aspect,
                                           self.rng.uniform(0.3, 0.8),
                                           self.rng.choice("*#%+.:o"), color, gravity=4.0))
        self.explosions.append(Explosion(x, y, 0.45 if big else 0.32, 7.0 if big else 4.5, color))

    def _update_effects(self, dt: float) -> None:
        for lst in (self.particles, self.explosions):
            for o in lst:
                o.update(dt)
        self.particles = [p for p in self.particles if p.life > 0]
        self.explosions = [x for x in self.explosions if not x.done]
        self.muzzle = max(0.0, self.muzzle - dt)
