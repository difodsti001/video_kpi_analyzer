from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.analyzer import analyze_video


DEFAULT_MODEL = Path(__file__).resolve().parents[2] / "yolo26n.pt"


def main() -> None:
    parser = argparse.ArgumentParser(description="Análisis temporal anónimo de eventos de aula")
    parser.add_argument("video", help="Ruta al video de aula")
    parser.add_argument("--model", default=str(DEFAULT_MODEL), help="Modelo YOLO con clase persona")
    parser.add_argument("--sample-fps", type=float, default=2.0)
    parser.add_argument(
        "--pose-model",
        help="Modelo YOLO pose multipersona; habilita el evento mano_levantada",
    )
    parser.add_argument(
        "--vision-provider", choices=("azure", "openai"),
        help="Activa descripciones objetivas por IA de visión; usa las credenciales de .env",
    )
    parser.add_argument("--vision-model", help="Deployment Azure o modelo OpenAI para visión")
    parser.add_argument("--vision-window-seconds", type=float, default=15.0,
                        help="Segundos cubiertos por cada descripción de IA (predeterminado: 15)")
    parser.add_argument(
        "--mediapipe-presenter", action="store_true",
        help="Añade una medición MediaPipe sobre el presentador heurístico, sin almacenar recortes",
    )
    parser.add_argument(
        "--appearance-reid", action="store_true",
        help="Une tracklets por apariencia corporal sin rostro, solo durante este video",
    )
    parser.add_argument("--output", default="eventos.json")
    args = parser.parse_args()

    result = analyze_video(
        args.video, args.model, args.sample_fps, args.pose_model,
        args.vision_provider, args.vision_model, args.vision_window_seconds,
        args.mediapipe_presenter, args.appearance_reid,
    )
    output = Path(args.output)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Eventos: {len(result['events'])} | observaciones IA: {len(result['hybrid_observations'])} "
        f"| muestras MediaPipe: {len(result['mediapipe_presenter_pose'])} | salida: {output}"
    )


if __name__ == "__main__":
    main()
