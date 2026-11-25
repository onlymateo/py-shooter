"""Webcam + detection de la main (MediaPipe Hands).

Architecture (2 threads, pour ne jamais bloquer le jeu a 60 FPS) :

    [thread capture]  lit la webcam en continu et ne garde que la DERNIERE image
          |             (pas de file d'attente => pas de latence accumulee)
    [thread detection] MediaPipe -> landmarks -> filtre One-Euro -> geste du pouce
          |
    HandTracker.get_state()  <- le jeu lit un instantane immuable (HandState)

Ce module contient aussi les briques testables sans camera : filtre One-Euro,
mesure du pouce, anti-rebond, conversion coordonnees webcam -> jeu.
"""
from __future__ import annotations

import json
import math
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import config

# Indices des landmarks MediaPipe
WRIST = 0
THUMB_TIP = 4
INDEX_MCP, INDEX_PIP, INDEX_TIP = 5, 6, 8
MIDDLE_MCP = 9
PINKY_MCP = 17


# ==========================================================================
# Briques pures (testables sans webcam)
# ==========================================================================
def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


class OneEuro:
    """Filtre One-Euro : lisse le tremblement quand la main est lente,
    reste reactif quand elle bouge vite."""

    def __init__(self, min_cutoff: float, beta: float, dcutoff: float = 1.0):
        self.min_cutoff, self.beta, self.dcutoff = min_cutoff, beta, dcutoff
        self.reset()

    def reset(self) -> None:
        self._x: Optional[float] = None
        self._dx = 0.0
        self._t = 0.0

    @staticmethod
    def _alpha(dt: float, cutoff: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x: float, t: float) -> float:
        if self._x is None:
            self._x, self._t = x, t
            return x
        dt = max(t - self._t, 1e-3)
        dx = (x - self._x) / dt
        a_d = self._alpha(dt, self.dcutoff)
        self._dx = a_d * dx + (1 - a_d) * self._dx
        cutoff = self.min_cutoff + self.beta * abs(self._dx)
        a = self._alpha(dt, cutoff)
        self._x = a * x + (1 - a) * self._x
        self._t = t
        return self._x


def finger_direction(lm: List[Tuple[float, float]], width: int, height: int
                     ) -> Optional[Tuple[float, float]]:
    """Direction dans laquelle pointe l'index : vecteur unitaire base (MCP) -> bout,
    calcule en pixels (donc sans deformation due au format de l'image)."""
    dx = (lm[INDEX_TIP][0] - lm[INDEX_MCP][0]) * width
    dy = (lm[INDEX_TIP][1] - lm[INDEX_MCP][1]) * height
    n = math.hypot(dx, dy)
    if n < 1e-6:
        return None
    return dx / n, dy / n


def thumb_ratio(lm: List[Tuple[float, float]], width: int, height: int) -> float:
    """Ratio 'pouce baisse' : plus il est PETIT, plus le pouce est replie.

    = distance(bout du pouce, articulation de l'index la plus proche) / taille
    de la main. On ne regarde que des points du pouce et de la base de l'index,
    jamais le bout de l'index (qui sert a viser) => le tir est independant du
    mouvement de l'index.
    """
    def px(i):
        return lm[i][0] * width, lm[i][1] * height

    def dist(a, b):
        (ax, ay), (bx, by) = px(a), px(b)
        return math.hypot(ax - bx, ay - by)

    hand_size = max(dist(WRIST, MIDDLE_MCP), 1.25 * dist(INDEX_MCP, PINKY_MCP), 1e-6)
    d = min(dist(THUMB_TIP, INDEX_MCP), dist(THUMB_TIP, INDEX_PIP))
    return d / hand_size


class TriggerFilter:
    """Hysteresis + anti-rebond du geste de tir.

    * hysteresis : on tire sous `press`, on arrete au-dessus de `release`
      (press < release) => pas de scintillement autour d'un seuil unique ;
    * anti-rebond : il faut `press_frames` / `release_frames` images
      consecutives qui s'accordent pour changer d'etat ;
    * geste net : si le ratio est tres loin du seuil, on valide tout de suite
      (aucune latence ajoutee pour un vrai geste franc).
    """

    def __init__(self, press: float, release: float, press_frames: int,
                 release_frames: int, clear_margin: float):
        self.press, self.release = press, release
        self.press_frames, self.release_frames = press_frames, release_frames
        self.clear_margin = clear_margin
        self.firing = False
        self._count = 0

    def reset(self) -> None:
        self.firing = False
        self._count = 0

    def update(self, ratio: float) -> bool:
        if not self.firing:
            wants = ratio < self.press
            clear = ratio < self.press * self.clear_margin
            need = self.press_frames
        else:
            wants = ratio > self.release
            clear = ratio > self.release / self.clear_margin
            need = self.release_frames
        if not wants:
            self._count = 0
            return self.firing
        self._count += 1
        if clear or self._count >= need:
            self.firing = not self.firing
            self._count = 0
        return self.firing


# ==========================================================================
# Etat partage avec le jeu
# ==========================================================================
@dataclass(frozen=True)
class HandState:
    """Instantane immuable de ce que voit la webcam."""
    present: bool = False           # main utilisable (detectee, ou perdue depuis < GRACE)
    detected: bool = False          # detectee sur la toute derniere image
    tip: Tuple[float, float] = (0.5, 0.5)        # bout de l'index filtre, 0..1 dans l'image webcam
    direction: Tuple[float, float] = (0.0, -1.0)  # sens ou pointe l'index (vecteur unitaire, pixels)
    screen_space: bool = False      # True : tip est deja en coordonnees d'ecran (mode souris)
    firing: bool = False            # pouce baisse (apres anti-rebond)
    ratio: float = 1.0              # mesure brute du pouce
    press_th: float = config.THUMB_PRESS
    release_th: float = config.THUMB_RELEASE
    landmarks: Optional[Tuple[Tuple[float, float], ...]] = None  # 21 points 0..1
    preview: Optional[object] = None  # image RGB (numpy) pleine resolution, deja en miroir si besoin
    cam_fps: float = 0.0
    det_fps: float = 0.0
    latency_ms: float = 0.0         # capture -> etat publie
    seq: int = 0
    lost_for: float = 0.0           # secondes depuis la derniere detection
    status: str = ""                # message (erreur camera, calibration...)
    mirror: bool = True
    source: str = "webcam"
    calibrated: bool = True         # seuils du pouce calibres par l'utilisateur ?


class CameraError(RuntimeError):
    pass


# ==========================================================================
# Tracker (webcam)
# ==========================================================================
class HandTracker:
    def __init__(self):
        self.mirror = config.MIRROR
        self.want_preview = True      # le jeu affiche la webcam en fond
        self.trigger = TriggerFilter(config.THUMB_PRESS, config.THUMB_RELEASE,
                                     config.THUMB_PRESS_FRAMES, config.THUMB_RELEASE_FRAMES,
                                     config.THUMB_CLEAR_MARGIN)
        self._cal = {"up": None, "down": None}
        self._cal_req: Optional[Tuple[str, float, list]] = None
        self._load_calibration()

        self._state = HandState(mirror=self.mirror,
                                press_th=self.trigger.press, release_th=self.trigger.release)
        self._running = False
        self._cap = None
        self._threads: List[threading.Thread] = []
        self._frame_lock = threading.Condition()
        self._frame = None
        self._frame_t = 0.0
        self._frame_seq = 0
        self._cam_fps = 0.0
        self.error: Optional[str] = None
        self.camera_info = ""
        self._status_msg = ("", 0.0)

    # ------------------------------------------------------------------ API
    def start(self) -> None:
        import cv2
        self._cv2 = cv2
        self._cap = self._open_camera(cv2)
        self._running = True
        for target, name in ((self._capture_loop, "capture"), (self._detect_loop, "detect")):
            th = threading.Thread(target=target, name=f"hand-{name}", daemon=True)
            th.start()
            self._threads.append(th)

    def stop(self) -> None:
        self._running = False
        with self._frame_lock:
            self._frame_lock.notify_all()
        for th in self._threads:
            th.join(timeout=1.5)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def get_state(self) -> HandState:
        return self._state

    def calibrate(self, kind: str) -> None:
        """kind = 'up' (pouce leve) ou 'down' (pouce baisse) : moyenne sur 0.8 s."""
        self._cal_req = (kind, time.perf_counter(), [])
        self._set_status(f"Calibration pouce {'LEVE' if kind == 'up' else 'BAISSE'}... garde la pose")

    def reset_calibration(self) -> None:
        self._cal = {"up": None, "down": None}
        self.trigger.press, self.trigger.release = config.THUMB_PRESS, config.THUMB_RELEASE
        try:
            config.CALIBRATION_FILE.unlink()
        except OSError:
            pass
        self._set_status("Calibration reinitialisee")

    # ------------------------------------------------------------ calibration
    def _load_calibration(self) -> None:
        try:
            data = json.loads(config.CALIBRATION_FILE.read_text())
            self._cal = {"up": data.get("up"), "down": data.get("down")}
            self._apply_calibration()
        except (OSError, ValueError):
            pass

    def _apply_calibration(self) -> None:
        up, down = self._cal["up"], self._cal["down"]
        if up is None or down is None or up - down < 0.12:
            return
        self.trigger.press = down + (up - down) * 0.40
        self.trigger.release = down + (up - down) * 0.62

    def _save_calibration(self) -> None:
        try:
            config.CALIBRATION_FILE.write_text(json.dumps(self._cal))
        except OSError:
            pass

    def _set_status(self, msg: str, ttl: float = 3.0) -> None:
        self._status_msg = (msg, time.perf_counter() + ttl)

    def _status(self) -> str:
        msg, until = self._status_msg
        if self.error:
            return self.error
        return msg if time.perf_counter() < until else ""

    # ----------------------------------------------------------------- camera
    def _open_camera(self, cv2):
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY] if sys.platform == "win32" else [cv2.CAP_ANY]
        last = "aucune camera"
        for backend in backends:
            cap = cv2.VideoCapture(config.CAMERA_INDEX, backend)
            if not cap.isOpened():
                cap.release()
                continue
            if config.CAMERA_MJPG:
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
            cap.set(cv2.CAP_PROP_FPS, config.CAMERA_FPS)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            ok, frame = cap.read()
            if ok and frame is not None:
                h, w = frame.shape[:2]
                self.camera_info = f"camera {config.CAMERA_INDEX} {w}x{h}"
                return cap
            cap.release()
            last = f"la camera {config.CAMERA_INDEX} s'ouvre mais ne renvoie pas d'image"
        raise CameraError(f"Impossible d'ouvrir la webcam ({last}). "
                          f"Verifie qu'aucune autre app ne l'utilise, ou change CAMERA_INDEX.")

    def _capture_loop(self) -> None:
        fails = 0
        n, t0 = 0, time.perf_counter()
        while self._running:
            ok, frame = self._cap.read()
            now = time.perf_counter()
            if not ok or frame is None:
                fails += 1
                if fails > 60:
                    self.error = "Webcam deconnectee"
                time.sleep(0.02)
                continue
            fails = 0
            if self.error == "Webcam deconnectee":
                self.error = None
            n += 1
            if now - t0 >= 1.0:
                self._cam_fps = n / (now - t0)
                n, t0 = 0, now
            with self._frame_lock:
                self._frame, self._frame_t = frame, now
                self._frame_seq += 1
                self._frame_lock.notify_all()

    # -------------------------------------------------------------- detection
    def _detect_loop(self) -> None:
        import mediapipe as mp
        cv2 = self._cv2
        hands = mp.solutions.hands.Hands(
            static_image_mode=False, max_num_hands=1,
            model_complexity=config.MODEL_COMPLEXITY,
            min_detection_confidence=config.DETECTION_CONFIDENCE,
            min_tracking_confidence=config.TRACKING_CONFIDENCE)
        fx = OneEuro(config.CURSOR_MIN_CUTOFF, config.CURSOR_BETA)
        fy = OneEuro(config.CURSOR_MIN_CUTOFF, config.CURSOR_BETA)
        fdx = OneEuro(config.DIR_MIN_CUTOFF, config.DIR_BETA)
        fdy = OneEuro(config.DIR_MIN_CUTOFF, config.DIR_BETA)
        last_seq = 0
        last_seen = -1e9
        tip = (0.5, 0.5)
        direction = (0.0, -1.0)
        ratio = 1.0
        lms: Optional[tuple] = None
        n_det, t_fps, det_fps = 0, time.perf_counter(), 0.0

        while self._running:
            with self._frame_lock:
                while self._running and self._frame_seq == last_seq:
                    self._frame_lock.wait(timeout=0.2)
                if not self._running:
                    break
                frame, t_frame, last_seq = self._frame, self._frame_t, self._frame_seq

            if self.mirror:
                frame = cv2.flip(frame, 1)
            h, w = frame.shape[:2]
            preview = None
            if self.want_preview:        # image pleine resolution affichee en fond du jeu
                preview = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                preview.flags.writeable = False   # partage sans copie avec le thread d'affichage
            if config.DETECT_WIDTH and w > config.DETECT_WIDTH:   # detection sur image reduite : plus rapide
                w, h = config.DETECT_WIDTH, int(config.DETECT_WIDTH * h / w)
                frame = cv2.resize(frame, (w, h), interpolation=cv2.INTER_AREA)
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            try:
                result = hands.process(rgb)
            except Exception as exc:  # une erreur ponctuelle ne doit jamais tuer le thread
                self._set_status(f"Erreur detection: {exc}")
                continue
            now = time.perf_counter()

            detected = bool(result.multi_hand_landmarks)
            if detected:
                pts = result.multi_hand_landmarks[0].landmark
                lm = [(p.x, p.y) for p in pts]
                lms = tuple(lm)
                last_seen = now
                ix, iy = lm[INDEX_TIP]
                tip = (fx(ix, now), fy(iy, now))
                d = finger_direction(lm, w, h)
                if d is not None:
                    sx, sy = fdx(d[0], now), fdy(d[1], now)
                    n = math.hypot(sx, sy)
                    if n > 1e-6:
                        direction = (sx / n, sy / n)
                ratio = thumb_ratio(lm, w, h)
                self._calibration_step(ratio, now)
                self.trigger.update(ratio)
            lost_for = now - last_seen
            present = lost_for <= config.HAND_LOST_GRACE
            if not present:  # perte prolongee : on relache tout, on repart propre a la reapparition
                if self.trigger.firing or fx._x is not None:
                    self.trigger.reset()
                    for f in (fx, fy, fdx, fdy):
                        f.reset()
                lms = None

            n_det += 1
            if now - t_fps >= 1.0:
                det_fps = n_det / (now - t_fps)
                n_det, t_fps = 0, now

            self._state = HandState(
                present=present, detected=detected, tip=tip, direction=direction,
                firing=self.trigger.firing and present, ratio=ratio,
                press_th=self.trigger.press, release_th=self.trigger.release,
                landmarks=lms, preview=preview, cam_fps=self._cam_fps, det_fps=det_fps,
                latency_ms=(time.perf_counter() - t_frame) * 1000.0,
                seq=last_seq, lost_for=min(lost_for, 999.0), status=self._status(),
                mirror=self.mirror, source="webcam", calibrated=self._is_calibrated())
        hands.close()

    def _is_calibrated(self) -> bool:
        up, down = self._cal["up"], self._cal["down"]
        return up is not None and down is not None and up - down >= 0.12

    def _calibration_step(self, ratio: float, now: float) -> None:
        req = self._cal_req
        if req is None:
            return
        kind, t0, samples = req
        samples.append(ratio)
        if now - t0 < 0.8:
            return
        self._cal_req = None
        samples.sort()
        value = samples[len(samples) // 2]  # mediane : insensible aux aberrations
        self._cal[kind] = value
        self._save_calibration()
        self._apply_calibration()
        up, down = self._cal["up"], self._cal["down"]
        if up is not None and down is not None and up - down < 0.12:
            self._set_status("Ecart trop faible entre pouce leve et baisse : recommence")
        elif up is None or down is None:
            self._set_status(f"Pouce {'leve' if kind == 'up' else 'baisse'} = {value:.2f}. Fais l'autre pose (U/D)")
        else:
            self._set_status(f"Calibre ! tir < {self.trigger.press:.2f}, relache > {self.trigger.release:.2f}")


# ==========================================================================
# Source de secours : souris (test sans webcam)
# ==========================================================================
class MouseHand:
    """Meme interface que HandTracker, pilotee par la souris (clic gauche / espace = tir)."""

    def __init__(self):
        self.mirror = config.MIRROR
        self.want_preview = False
        self.error: Optional[str] = None
        self.camera_info = "souris"
        self._tip = (0.5, 0.5)
        self._down = False
        self._seq = 0

    def set_input(self, tip: Tuple[float, float], down: bool) -> None:
        self._tip, self._down = tip, down
        self._seq += 1

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def calibrate(self, kind: str) -> None: ...
    def reset_calibration(self) -> None: ...

    def get_state(self) -> HandState:
        # "doigt" fictif : tire depuis la souris, dans la direction qui s'eloigne du bas-centre de l'ecran
        dx, dy = (self._tip[0] - 0.5) * 16.0, (self._tip[1] - 1.0) * 9.0
        n = math.hypot(dx, dy) or 1.0
        return HandState(present=True, detected=True, tip=self._tip, direction=(dx / n, dy / n),
                         screen_space=True, firing=self._down, ratio=0.2 if self._down else 0.8,
                         seq=self._seq, status=self.error or "", mirror=self.mirror, source="souris")
