import os
import subprocess
import cv2
import mediapipe as mp
import numpy as np
from dotenv import load_dotenv

load_dotenv()

FFMPEG_PATH = os.getenv("FFMPEG_PATH", "ffmpeg")
mp_pose     = mp.solutions.pose


def extract_frames(video_path: str, output_folder: str, fps: int = 1) -> list[str]:
    """Extrae 1 frame por segundo como JPG usando ffmpeg."""
    os.makedirs(output_folder, exist_ok=True)
    pattern = os.path.join(output_folder, "frame_%04d.jpg")
    subprocess.run([
        FFMPEG_PATH, "-y", "-i", video_path,
        "-vf", f"fps={fps}", pattern
    ], check=True, capture_output=True)
    return sorted([
        os.path.join(output_folder, f)
        for f in os.listdir(output_folder)
        if f.endswith(".jpg")
    ])


def analyze_frame(pose, image_path: str) -> dict | None:
    """
    Analiza postura y gestos en un frame individual.
    Devuelve métricas o None si no detecta persona.
    """
    img = cv2.imread(image_path)
    if img is None:
        return None

    rgb     = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    results = pose.process(rgb)

    if not results.pose_landmarks:
        return None

    lm = results.pose_landmarks.landmark

    # ── Keypoints principales ─────────────────────────────────────
    nose       = lm[mp_pose.PoseLandmark.NOSE]
    l_shoulder = lm[mp_pose.PoseLandmark.LEFT_SHOULDER]
    r_shoulder = lm[mp_pose.PoseLandmark.RIGHT_SHOULDER]
    l_ear      = lm[mp_pose.PoseLandmark.LEFT_EAR]
    r_ear      = lm[mp_pose.PoseLandmark.RIGHT_EAR]
    l_hip      = lm[mp_pose.PoseLandmark.LEFT_HIP]
    r_hip      = lm[mp_pose.PoseLandmark.RIGHT_HIP]
    l_elbow    = lm[mp_pose.PoseLandmark.LEFT_ELBOW]
    r_elbow    = lm[mp_pose.PoseLandmark.RIGHT_ELBOW]
    l_wrist    = lm[mp_pose.PoseLandmark.LEFT_WRIST]
    r_wrist    = lm[mp_pose.PoseLandmark.RIGHT_WRIST]

    # Centro de hombros y caderas
    shoulder_cx = (l_shoulder.x + r_shoulder.x) / 2
    shoulder_cy = (l_shoulder.y + r_shoulder.y) / 2
    hip_cy      = (l_hip.y + r_hip.y) / 2

    # ── Métricas de postura ───────────────────────────────────────

    # Inclinación de hombros: diferencia vertical entre hombro izq y der
    # (en coordenadas normalizadas: 0 = arriba, 1 = abajo)
    shoulder_tilt = abs(l_shoulder.y - r_shoulder.y)

    # Inclinación de cabeza: diferencia vertical entre orejas
    head_tilt = abs(l_ear.y - r_ear.y)

    # Offset de cabeza: nariz vs centro horizontal de hombros
    # Indica si la cabeza está desplazada lateralmente
    head_offset = abs(nose.x - shoulder_cx)

    # Ancho de hombros: distancia horizontal entre hombros
    shoulder_width = abs(l_shoulder.x - r_shoulder.x)

    # ── Métricas de gestos ────────────────────────────────────────

    # Mano levantada: muñeca por encima del hombro ipsilateral
    # En MediaPipe, coordenada Y menor = más arriba en la imagen
    l_hand_up = l_wrist.y < l_shoulder.y
    r_hand_up = r_wrist.y < r_shoulder.y

    # Mano al centro: muñeca cerca del eje central del cuerpo
    l_hand_center = abs(l_wrist.x - 0.5) < 0.2
    r_hand_center = abs(r_wrist.x - 0.5) < 0.2

    # Mano baja: muñeca debajo de la cadera
    l_hand_low = l_wrist.y > hip_cy
    r_hand_low = r_wrist.y > hip_cy

    # Brazos abiertos: codo fuera del ancho de hombros
    shoulder_half_w = shoulder_width / 2
    l_arm_open = abs(l_elbow.x - shoulder_cx) > shoulder_half_w + 0.05
    r_arm_open = abs(r_elbow.x - shoulder_cx) > shoulder_half_w + 0.05

    return {
        # postura
        "shoulder_tilt":   round(float(shoulder_tilt), 4),
        "head_tilt":       round(float(head_tilt), 4),
        "head_offset":     round(float(head_offset), 4),
        "shoulder_width":  round(float(shoulder_width), 4),
        "nose_x":          round(float(nose.x), 4),
        "nose_y":          round(float(nose.y), 4),
        # gestos
        "hand_up":         bool(l_hand_up or r_hand_up),
        "hand_center":     bool(l_hand_center or r_hand_center),
        "hand_low":        bool(l_hand_low or r_hand_low),
        "arms_open":       bool(l_arm_open or r_arm_open),
        "both_hands_up":   bool(l_hand_up and r_hand_up),
    }


def analyze_posture(video_path: str, frames_folder: str) -> dict:
    """
    Pipeline completo de análisis de postura y gestos.

    Extrae frames a 1 FPS, detecta 33 keypoints corporales con MediaPipe Pose
    y calcula scores de postura, estabilidad, centrado y distribución de gestos.

    Args:
        video_path:     Ruta al archivo de video original.
        frames_folder:  Carpeta temporal donde se guardan los JPG (se limpian al final).

    Returns:
        dict con scores, métricas agregadas, gestos y timeline.
    """
    frames = extract_frames(video_path, frames_folder, fps=1)
    if not frames:
        return {"error": "No se pudieron extraer frames del video"}

    results = []

    with mp_pose.Pose(
        static_image_mode=True,
        model_complexity=1,
        min_detection_confidence=0.5
    ) as pose:
        for i, frame_path in enumerate(frames):
            data = analyze_frame(pose, frame_path)
            if data:
                data["second"] = i
                results.append(data)

    # limpiar frames temporales
    for f in frames:
        try:
            os.remove(f)
        except OSError:
            pass
    try:
        os.rmdir(frames_folder)
    except OSError:
        pass

    if not results:
        return {"error": "No se detectó persona en el video"}

    total = len(results)

    shoulder_tilts = [r["shoulder_tilt"] for r in results]
    nose_xs        = [r["nose_x"]        for r in results]
    head_offsets   = [r["head_offset"]   for r in results]

    # ── Scores de postura ─────────────────────────────────────────

    # postura_score: penaliza inclinación de hombros
    # umbral: tilt > 0.08 empieza a penalizar
    postura_score = round(max(0.0, 1.0 - float(np.mean(shoulder_tilts)) / 0.08), 3)

    # estabilidad_score: usa rango intercuartílico (Q75 - Q25) de la posición X de nariz
    # más robusto que std para videos con movimientos ocasionales legítimos
    mov_range = float(np.percentile(nose_xs, 75)) - float(np.percentile(nose_xs, 25))
    estabilidad_score = round(max(0.0, 1.0 - mov_range / 0.15), 3)

    # centrado_score: qué tan cerca del centro horizontal (0.5) está el orador en promedio
    centrado_score = round(max(0.0, 1.0 - abs(float(np.mean(nose_xs)) - 0.5) / 0.3), 3)

    # movimiento_excesivo: True si el rango intercuartílico supera 0.12
    movimiento_excesivo = bool(mov_range > 0.12)

    # ── Distribución de gestos ────────────────────────────────────
    hands_up_ratio     = round(sum(1 for r in results if r["hand_up"])     / total, 3)
    hands_center_ratio = round(sum(1 for r in results if r["hand_center"]) / total, 3)
    hands_low_ratio    = round(sum(1 for r in results if r["hand_low"])    / total, 3)
    arms_open_ratio    = round(sum(1 for r in results if r["arms_open"])   / total, 3)

    # gesto predominante: el de mayor proporción
    gesto_predominante = max(
        [
            ("manos al centro", hands_center_ratio),
            ("manos arriba",    hands_up_ratio),
            ("manos bajas",     hands_low_ratio),
            ("brazos abiertos", arms_open_ratio),
        ],
        key=lambda x: x[1]
    )[0]

    # ── Timeline (cada 5 frames para no saturar el JSON) ─────────
    timeline = [
        {
            "second":        r["second"],
            "shoulder_tilt": r["shoulder_tilt"],
            "head_offset":   r["head_offset"],
            "hand_up":       r["hand_up"],
            "arms_open":     r["arms_open"],
        }
        for r in results[::5]
    ]

    return {
        "frames_analizados":   total,
        "postura_score":       postura_score,
        "estabilidad_score":   estabilidad_score,
        "centrado_score":      centrado_score,
        "shoulder_tilt_avg":   round(float(np.mean(shoulder_tilts)), 4),
        "head_offset_avg":     round(float(np.mean(head_offsets)), 4),
        "movimiento_excesivo": movimiento_excesivo,
        "gestos": {
            "manos_arriba_ratio":    hands_up_ratio,
            "manos_centro_ratio":    hands_center_ratio,
            "manos_bajas_ratio":     hands_low_ratio,
            "brazos_abiertos_ratio": arms_open_ratio,
            "gesto_predominante":    gesto_predominante,
        },
        "timeline": timeline,
    }
