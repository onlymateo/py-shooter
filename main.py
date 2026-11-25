"""Py-Shooter : tire sur des ennemis ASCII avec ton index (webcam plein ecran).

    python main.py              # jouer
    python main.py --diag       # diagnostic : voir les landmarks et le geste de tir
    python main.py --mouse      # jouer a la souris (test sans webcam)
    python main.py --help       # tous les reglages
"""
import os
import subprocess
import sys
from pathlib import Path


def _use_project_venv() -> None:
    """Si un .venv existe a cote de main.py, on s'y relance automatiquement :
    `python main.py` marche donc meme sans activer l'environnement virtuel."""
    here = Path(__file__).resolve().parent
    for rel in ("Scripts/python.exe", "bin/python"):
        venv_python = here / ".venv" / rel
        if venv_python.exists():
            if Path(sys.prefix).resolve() != (here / ".venv").resolve() \
                    and not os.environ.get("PYSHOOTER_NO_VENV"):
                try:
                    sys.exit(subprocess.call([str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]]))
                except KeyboardInterrupt:
                    sys.exit(130)
            return


if __name__ == "__main__":
    _use_project_venv()

import argparse
import time

try:
    import pygame
except ImportError:
    sys.exit("Dependances manquantes. Installe-les avec :\n    pip install -r requirements.txt")

import config
import game as G
from hand_tracking import CameraError, HandTracker, MouseHand
from renderer import Renderer, UiInfo


def parse_args(argv):
    p = argparse.ArgumentParser(description="Py-Shooter : tir ASCII pilote par la main (webcam)")
    p.add_argument("--diag", action="store_true", help="mode diagnostic (landmarks, geste de tir, FPS)")
    p.add_argument("--mouse", action="store_true", help="souris + clic a la place de la webcam")
    p.add_argument("--camera", type=int, help="index de la webcam (defaut %d)" % config.CAMERA_INDEX)
    p.add_argument("--width", type=int, help="largeur webcam (defaut %d)" % config.CAMERA_WIDTH)
    p.add_argument("--height", type=int, help="hauteur webcam (defaut %d)" % config.CAMERA_HEIGHT)
    p.add_argument("--mirror", dest="mirror", action="store_true", default=None, help="effet miroir (defaut)")
    p.add_argument("--no-mirror", dest="mirror", action="store_false", help="desactive l'effet miroir")
    p.add_argument("--enemy-speed", type=float, help="multiplicateur de vitesse des ennemis")
    p.add_argument("--fire-rate", type=float, help="tirs par seconde (defaut %.0f)" % config.FIRE_RATE)
    p.add_argument("--fullscreen", action="store_true", help="plein ecran")
    p.add_argument("--model", type=int, choices=(0, 1), help="MediaPipe : 0 rapide, 1 precis")
    return p.parse_args(argv)


def apply_overrides(a) -> None:
    for attr, name in (("camera", "CAMERA_INDEX"), ("width", "CAMERA_WIDTH"), ("height", "CAMERA_HEIGHT"),
                       ("mirror", "MIRROR"), ("enemy_speed", "ENEMY_SPEED"),
                       ("fire_rate", "FIRE_RATE"), ("model", "MODEL_COMPLEXITY")):
        v = getattr(a, attr)
        if v is not None:
            setattr(config, name, v)
    if a.fullscreen:
        config.FULLSCREEN = True


def make_source(args):
    """Webcam si possible, sinon souris (avec un message clair)."""
    if args.mouse:
        return MouseHand(), ""
    tracker = HandTracker()
    try:
        tracker.start()
        return tracker, ""
    except CameraError as exc:
        print(f"[!] {exc}\n    -> bascule en mode souris (relance avec --camera N pour une autre camera).")
        return MouseHand(), "Webcam indisponible : mode souris"


def run(args) -> int:
    apply_overrides(args)
    source, notice = make_source(args)
    is_mouse = isinstance(source, MouseHand)
    if args.diag and is_mouse:
        print("Le diagnostic necessite une webcam.")
        return 1

    renderer = Renderer(config.GRID_COLS, config.GRID_ROWS, config.WINDOW_SIZE, config.FULLSCREEN,
                        "Py-Shooter - diagnostic" if args.diag else "Py-Shooter")
    game = G.Game(config.GRID_COLS, config.GRID_ROWS, aspect=renderer.cell_aspect)
    ui = UiInfo()
    clock = pygame.time.Clock()
    fps_smooth = 60.0
    running = True
    t_start = time.perf_counter()

    try:
        while running:
            dt = clock.tick(config.FPS_LIMIT) / 1000.0
            if dt > 0:
                fps_smooth += (1.0 / dt - fps_smooth) * 0.1
            ui.fps = fps_smooth

            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    running = False
                elif ev.type == pygame.VIDEORESIZE:
                    renderer.on_resize()
                    game.aspect = renderer.cell_aspect
                elif ev.type == pygame.KEYDOWN:
                    k = ev.key
                    if k == pygame.K_ESCAPE:
                        running = False
                    elif k == pygame.K_F11:
                        renderer.toggle_fullscreen()
                        game.aspect = renderer.cell_aspect
                    elif k == pygame.K_m:
                        source.mirror = not source.mirror
                    elif k == pygame.K_u:
                        source.calibrate("up")
                    elif k == pygame.K_d:
                        source.calibrate("down")
                    elif k == pygame.K_r:
                        source.reset_calibration()

            if is_mouse:
                source.set_input(renderer.window_to_norm(pygame.mouse.get_pos()),
                                 bool(pygame.mouse.get_pressed()[0]))
            hand = source.get_state()
            ui.tracker_error = source.error or ""
            elapsed = time.perf_counter() - t_start
            if notice and elapsed < 6.0:
                ui.message = notice
            elif not is_mouse and not hand.calibrated and elapsed < 10.0:
                ui.message = "U = pouce leve, D = pouce baisse : calibre le tir (une seule fois)"
            else:
                ui.message = ""

            if args.diag:
                renderer.render_diagnostic(hand, ui)
            else:
                game.update(dt, G.Controls(renderer.hand_to_cells(hand), hand.direction,
                                           hand.firing, hand.present))
                renderer.render_game(game, hand, ui)
    except KeyboardInterrupt:
        pass
    finally:
        source.stop()
        pygame.quit()
    return 0


def main() -> int:
    return run(parse_args(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
