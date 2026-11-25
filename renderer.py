"""Affichage : la webcam en plein ecran, avec le jeu ASCII dessine par dessus.

Le jeu ne dessine rien : le Renderer lit l'etat de `Game` et de `HandState`,
remplit une grille (caractere + couleur par cellule) puis blitte uniquement les
cellules non vides (glyphes mis en cache) au dessus de l'image de la webcam
(recadree en mode "cover", legerement assombrie pour que l'ASCII ressorte).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pygame

import config
import game as G
from hand_tracking import HandState

Color = Tuple[int, int, int]

BG: Color = (7, 9, 16)
GREEN: Color = (90, 255, 140)
DIM: Color = (150, 165, 185)
WHITE: Color = (240, 245, 255)
RED: Color = (255, 80, 70)
YELLOW: Color = (255, 225, 90)
CYAN: Color = (90, 220, 255)

# Connexions du squelette de la main (MediaPipe)
HAND_CONNECTIONS = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
                    (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16),
                    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17)]


def blend(c: Color, target: Color, k: float) -> Color:
    """k=0 -> c ; k=1 -> target (quantifie pour limiter le cache de glyphes)."""
    k = round(max(0.0, min(1.0, k)) * 8) / 8.0
    return (int(c[0] + (target[0] - c[0]) * k),
            int(c[1] + (target[1] - c[1]) * k),
            int(c[2] + (target[2] - c[2]) * k))


@dataclass
class UiInfo:
    fps: float = 0.0
    tracker_error: str = ""
    message: str = ""


class Renderer:
    def __init__(self, cols: int, rows: int, size: Tuple[int, int], fullscreen: bool = False,
                 caption: str = "Py-Shooter"):
        pygame.init()
        pygame.display.set_caption(caption)
        self.cols, self.rows = cols, rows
        self.fullscreen = fullscreen
        flags = pygame.RESIZABLE | (pygame.FULLSCREEN if fullscreen else 0)
        try:
            self.screen = pygame.display.set_mode(size, flags, vsync=1)
        except (pygame.error, TypeError):
            self.screen = pygame.display.set_mode(size, flags)
        self._glyphs: Dict[Tuple[str, Color], pygame.Surface] = {}
        self._ui_font_cache: Dict[int, pygame.font.Font] = {}
        self._fit_font()
        n = cols * rows
        self._blank_ch = [" "] * n
        self._blank_co: List[Optional[Color]] = [None] * n
        self.ch = list(self._blank_ch)
        self.co = list(self._blank_co)
        self._cam_size = (640, 480)
        self._bg_cache: Tuple[object, Optional[pygame.Surface]] = (None, None)
        self._view_cache: Tuple[object, Optional[pygame.Surface]] = (None, None)

    # ------------------------------------------------------------------
    # Police / fenetre
    # ------------------------------------------------------------------
    def _make_font(self, size: int) -> pygame.font.Font:
        return pygame.font.SysFont(config.FONT_NAMES, size)

    def _fit_font(self) -> None:
        """Plus grande police telle que la grille entiere tienne dans la fenetre."""
        W, H = self.screen.get_size()
        best = None
        for size in range(8, 64):
            f = self._make_font(size)
            cw, ch = f.size("M")
            if cw * self.cols > W or ch * self.rows > H:
                break
            best = (size, f, cw, ch)
        if best is None:
            f = self._make_font(8)
            best = (8, f, *f.size("M"))
        self.font_size, self.font, self.cw, self.chh = best
        self._glyphs.clear()
        self.x0 = (W - self.cw * self.cols) // 2
        self.y0 = (H - self.chh * self.rows) // 2
        self._bg_cache = (None, None)

    @property
    def cell_aspect(self) -> float:
        return self.chh / self.cw

    def on_resize(self) -> None:
        self.screen = pygame.display.get_surface()
        self._fit_font()

    def toggle_fullscreen(self) -> None:
        pygame.display.toggle_fullscreen()
        self.fullscreen = not self.fullscreen
        self.on_resize()

    def ui_font(self, size: int) -> pygame.font.Font:
        f = self._ui_font_cache.get(size)
        if f is None:
            f = self._ui_font_cache[size] = pygame.font.SysFont(config.FONT_NAMES, size)
        return f

    # ------------------------------------------------------------------
    # Coordonnees : webcam <-> ecran <-> cellules
    # ------------------------------------------------------------------
    def camera_rect(self) -> Tuple[float, float, float, float]:
        """Rectangle (x, y, largeur, hauteur) ou la webcam est dessinee : mode 'cover'
        (l'image remplit la fenetre, le surplus est rogne)."""
        W, H = self.screen.get_size()
        cw, ch = self._cam_size
        s = max(W / cw, H / ch)
        dw, dh = cw * s, ch * s
        return (W - dw) / 2.0, (H - dh) / 2.0, dw, dh

    def cam_to_pixels(self, nx: float, ny: float) -> Tuple[float, float]:
        ox, oy, dw, dh = self.camera_rect()
        return ox + nx * dw, oy + ny * dh

    def hand_to_cells(self, hand: HandState) -> Tuple[float, float]:
        """Bout de l'index -> coordonnees (flottantes) dans la grille du jeu.
        Le point est exactement celui que l'on voit sur l'image de la webcam."""
        if hand.screen_space:
            return hand.tip[0] * self.cols - 0.5, hand.tip[1] * self.rows - 0.5
        px, py = self.cam_to_pixels(*hand.tip)
        return (px - self.x0) / self.cw - 0.5, (py - self.y0) / self.chh - 0.5

    def window_to_norm(self, pos: Tuple[int, int]) -> Tuple[float, float]:
        """Position souris -> coordonnees normalisees dans la grille (mode souris)."""
        gx = (pos[0] - self.x0) / max(1, self.cw * self.cols)
        gy = (pos[1] - self.y0) / max(1, self.chh * self.rows)
        return max(0.0, min(1.0, gx)), max(0.0, min(1.0, gy))

    # ------------------------------------------------------------------
    # Primitives grille
    # ------------------------------------------------------------------
    def clear(self) -> None:
        self.ch[:] = self._blank_ch
        self.co[:] = self._blank_co

    def put(self, x: float, y: float, c: str, color: Color) -> None:
        if c == " ":
            return
        ix, iy = int(round(x)), int(round(y))
        if 0 <= ix < self.cols and 0 <= iy < self.rows:
            i = iy * self.cols + ix
            self.ch[i] = c
            self.co[i] = color

    def text(self, x: float, y: float, s: str, color: Color) -> None:
        ix = int(round(x))
        for k, c in enumerate(s):
            self.put(ix + k, y, c, color)

    def text_c(self, y: float, s: str, color: Color) -> None:
        self.text(self.cols / 2.0 - len(s) / 2.0, y, s, color)

    def _glyph(self, c: str, color: Color) -> pygame.Surface:
        """Glyphe sur un fond sombre semi-transparent : lisible meme sur une image claire."""
        key = (c, color)
        s = self._glyphs.get(key)
        if s is None:
            s = pygame.Surface((self.cw, self.chh), pygame.SRCALPHA)
            s.fill((0, 0, 0, 120))
            g = self.font.render(c, True, color)
            s.blit(g, ((self.cw - g.get_width()) // 2, (self.chh - g.get_height()) // 2))
            self._glyphs[key] = s
        return s

    # ------------------------------------------------------------------
    # Scene de jeu
    # ------------------------------------------------------------------
    def render_game(self, game: G.Game, hand: HandState, ui: UiInfo) -> None:
        self.clear()
        for e in game.enemies:
            self._draw_enemy(e)
        for b in game.bullets:
            g = b.glyph
            for j, shade in ((2, 0.55), (1, 0.25)):   # trainee lumineuse derriere la balle
                self.put(b.x - b.vx * j / 60.0, b.y - b.vy * j / 60.0, g, blend(YELLOW, BG, shade))
            self.put(b.x, b.y, g, WHITE)
        for ex in game.explosions:
            self._draw_explosion(ex, game)
        for p in game.particles:
            self.put(p.x, p.y, p.char, blend(p.color, BG, 1.0 - p.life / p.max_life))
        self._draw_finger(game)

        msg = ui.message or hand.status or ui.tracker_error
        if msg:
            self.text_c(2, msg[:self.cols - 4], YELLOW)
        if hand.source == "webcam" and not hand.present:
            self.text_c(self.rows - 3, "MONTRE TA MAIN A LA CAMERA", WHITE)
        self._present(hand)

    def _draw_finger(self, game: G.Game) -> None:
        """Repere au bout de l'index + pointilles dans la direction du tir."""
        tx, ty = game.tip
        dx, dy = game.dir
        col = RED if game.firing else GREEN
        for d in (4.0, 7.0, 10.0):
            self.put(tx + dx * d, ty + dy * d / game.aspect, ".", blend(col, BG, 0.15))
        self.put(tx, ty, "o" if game.firing else "+", col)
        if game.muzzle > 0:
            self.put(tx + dx * 2.2, ty + dy * 2.2 / game.aspect, "*", YELLOW)

    def _draw_enemy(self, e) -> None:
        color = WHITE if e.flash > 0 else e.color
        x0 = int(round(e.x - e.w / 2.0 + 0.5))     # entier : sinon l'arrondi des colonnes saute des caracteres
        y0 = int(round(e.y - e.h / 2.0 + 0.5))
        for r, line in enumerate(e.sprite):
            for k, c in enumerate(line):
                self.put(x0 + k, y0 + r, c, color)
        if e.max_hp > 1:   # barre de vie
            n = e.max_hp
            self.text(e.x - n - 0.5, y0 - 1, "[" + "#" * e.hp + "-" * (n - e.hp) + "]", (220, 220, 220))

    def _draw_explosion(self, ex, game: G.Game) -> None:
        k = ex.age / ex.duration
        r = ex.max_radius * (0.25 + 0.75 * k)
        ch = "O" if k < 0.4 else "o" if k < 0.7 else "."
        col = blend(ex.color, BG, k ** 1.5)
        n = max(8, int(r * 6))
        for i in range(n):
            a = i / n * math.tau
            self.put(ex.x + math.cos(a) * r, ex.y + math.sin(a) * r / game.aspect, ch, col)

    # ------------------------------------------------------------------
    # Presentation
    # ------------------------------------------------------------------
    def _blit_grid(self) -> None:
        scr, cols, cw, chh, x0, y0 = self.screen, self.cols, self.cw, self.chh, self.x0, self.y0
        ch, co = self.ch, self.co
        for i, c in enumerate(ch):
            if c != " ":
                scr.blit(self._glyph(c, co[i]), (x0 + (i % cols) * cw, y0 + (i // cols) * chh))

    def _camera_surface(self, hand: HandState) -> Optional[pygame.Surface]:
        """Image webcam 'cover', assombrie ; reconstruite seulement quand une nouvelle image arrive."""
        arr = hand.preview
        if arr is None:
            return None
        key = (hand.seq, self.screen.get_size())
        if self._bg_cache[0] == key:
            return self._bg_cache[1]
        h, w = arr.shape[:2]
        self._cam_size = (w, h)
        _, _, dw, dh = self.camera_rect()
        surf = pygame.image.frombuffer(arr.tobytes(), (w, h), "RGB")
        surf = pygame.transform.smoothscale(surf, (int(dw), int(dh)))
        k = int(255 * (1.0 - config.CAMERA_DIM))
        surf.fill((k, k, k), special_flags=pygame.BLEND_RGB_MULT)
        self._bg_cache = (key, surf)
        return surf

    def _present(self, hand: Optional[HandState]) -> None:
        self.screen.fill(BG)
        bg = self._camera_surface(hand) if hand is not None else None
        if bg is not None:
            ox, oy, _, _ = self.camera_rect()
            self.screen.blit(bg, (int(ox), int(oy)))
        self._blit_grid()
        pygame.display.flip()

    # ------------------------------------------------------------------
    # Mode diagnostic
    # ------------------------------------------------------------------
    def _draw_landmarks(self, surf: pygame.Surface, hand: HandState) -> None:
        W, H = surf.get_size()
        if not hand.landmarks:
            return
        pts = [(int(x * W), int(y * H)) for x, y in hand.landmarks]
        for a, b in HAND_CONNECTIONS:
            pygame.draw.line(surf, (60, 255, 140), pts[a], pts[b], 2)
        for p in pts:
            pygame.draw.circle(surf, (255, 255, 255), p, 3)
        tip = (int(hand.tip[0] * W), int(hand.tip[1] * H))
        col = (255, 60, 60) if hand.firing else (60, 200, 255)
        pygame.draw.circle(surf, col, tip, 8, 3)                                    # bout de l'index
        pygame.draw.line(surf, col, tip, (tip[0] + int(hand.direction[0] * 120),
                                          tip[1] + int(hand.direction[1] * 120)), 3)  # direction de tir
        pygame.draw.circle(surf, (255, 220, 60), pts[4], 7, 3)                      # pouce
        pygame.draw.line(surf, (255, 220, 60), pts[4], pts[5], 1)                   # mesure du pouce

    def _diag_view(self, hand: HandState) -> Optional[pygame.Surface]:
        arr = hand.preview
        if arr is None:
            return None
        if self._view_cache[0] == hand.seq:
            return self._view_cache[1]
        h, w = arr.shape[:2]
        surf = pygame.image.frombuffer(arr.tobytes(), (w, h), "RGB").copy()
        self._draw_landmarks(surf, hand)
        self._view_cache = (hand.seq, surf)
        return surf

    def render_diagnostic(self, hand: HandState, ui: UiInfo) -> None:
        scr = self.screen
        scr.fill((12, 14, 22))
        W, H = scr.get_size()
        f_big, f, f_s = self.ui_font(34), self.ui_font(18), self.ui_font(15)

        def txt(font, s, pos, col=WHITE):
            scr.blit(font.render(s, True, col), pos)

        view = self._diag_view(hand)
        vw = 0
        if view is not None:
            k = min((W * 0.62) / view.get_width(), (H - 20) / view.get_height())
            v = pygame.transform.smoothscale(view, (int(view.get_width() * k), int(view.get_height() * k)))
            scr.blit(v, (10, 10))
            vw = v.get_width()
            col = (255, 70, 70) if hand.firing else (90, 255, 140) if hand.detected else (120, 120, 120)
            pygame.draw.rect(scr, col, (8, 8, v.get_width() + 4, v.get_height() + 4), 3)
        px = vw + 30
        y = 12
        txt(f_big, "TIR !" if hand.firing else "pouce leve", (px, y), RED if hand.firing else GREEN)
        y += 48
        lines = [
            ("Main", "DETECTEE" if hand.detected else f"perdue depuis {hand.lost_for:.1f}s" if hand.lost_for < 999 else "aucune",
             GREEN if hand.detected else RED),
            ("Camera", f"{hand.cam_fps:4.1f} fps", WHITE),
            ("Detection", f"{hand.det_fps:4.1f} fps", WHITE),
            ("Latence", f"{hand.latency_ms:4.0f} ms", WHITE),
            ("Bout de l'index", f"x={hand.tip[0]:.3f}  y={hand.tip[1]:.3f}", CYAN),
            ("Direction du tir", f"dx={hand.direction[0]:+.2f}  dy={hand.direction[1]:+.2f}", CYAN),
            ("Miroir", "OUI" if hand.mirror else "NON", WHITE),
            ("Ratio pouce", f"{hand.ratio:.3f}", YELLOW),
            ("Seuil tir / relache", f"{hand.press_th:.2f} / {hand.release_th:.2f}", WHITE),
        ]
        for k_, v_, c_ in lines:
            txt(f_s, k_, (px, y), (150, 160, 180))
            txt(f, v_, (px + 170, y - 2), c_)
            y += 26
        y += 6
        gw = max(120, W - px - 24)
        pygame.draw.rect(scr, (40, 46, 60), (px, y, gw, 22))
        r = max(0.0, min(1.0, hand.ratio / 1.2))
        pygame.draw.rect(scr, RED if hand.firing else GREEN, (px, y, int(gw * r), 22))
        for th, c in ((hand.press_th, RED), (hand.release_th, YELLOW)):
            tx = px + int(gw * th / 1.2)
            pygame.draw.line(scr, c, (tx, y - 4), (tx, y + 26), 3)
        txt(f_s, "rouge: seuil de tir   jaune: seuil de relache", (px, y + 30), (150, 160, 180))
        y += 70
        for s in ("U : calibrer pouce LEVE    D : calibrer pouce BAISSE", "R : reinitialiser calibration",
                  "M : miroir", "Echap : quitter"):
            txt(f_s, s, (px, y), (150, 160, 180))
            y += 20
        msg = ui.message or hand.status or ui.tracker_error
        if msg:
            txt(f, msg, (10, H - 30), YELLOW)
        if view is None:
            txt(f, "En attente de la webcam...", (20, 20), YELLOW)
        pygame.display.flip()
