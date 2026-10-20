"""Tracking anónimo de personas y extracción de eventos temporales."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import cv2

from app.events import (
    PoseSample,
    TrackSample,
    detect_hand_raised_events,
    detect_movement_events,
    fuse_visual_observations,
    select_presenter,
)


PERSON_CLASS_ID = 0  # Clase person del conjunto COCO.


def _collect_pose_samples(result, timestamp: float, pose_tracks: dict[int, list[PoseSample]]) -> None:
    """Convierte la pose COCO en una señal anónima de mano sobre hombro."""
    if result.boxes is None or result.boxes.id is None or result.keypoints is None:
        return
    points = result.keypoints.xy.tolist()
    confidences = result.keypoints.conf.tolist() if result.keypoints.conf is not None else []

    # Índices COCO: hombros 5/6, muñecas 9/10.
    for track_id, keypoints, confidence in zip(result.boxes.id.int().tolist(), points, confidences):
        required = (5, 6, 9, 10)
        if len(keypoints) <= max(required) or len(confidence) <= max(required):
            continue
        if any(confidence[index] < 0.4 for index in required):
            continue
        left_hand_up = keypoints[9][1] < keypoints[5][1]
        right_hand_up = keypoints[10][1] < keypoints[6][1]
        pose_tracks[int(track_id)].append(PoseSample(
            second=round(timestamp, 3),
            hand_up=bool(left_hand_up or right_hand_up),
        ))


def _encode_visual_frame(frame) -> bytes:
    """Reduce la imagen antes de enviarla a la IA; no escribe frames en disco."""
    height, width = frame.shape[:2]
    if width > 768:
        scale = 768 / width
        frame = cv2.resize(frame, (768, max(1, round(height * scale))))
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise RuntimeError("No se pudo codificar un frame para la IA de visión")
    return encoded.tobytes()


def _analyze_presenter_with_mediapipe(video_path: str, fps: float, samples: list[TrackSample]) -> list[dict]:
    """Mide pose del presentador heurístico en sus recortes, sin guardarlos.

    Esta es una segunda señal independiente de YOLO Pose. Se usa para
    comparación y no para identificar ni confirmar la identidad de una persona.
    """
    by_frame = {
        round(sample.second * fps): sample for sample in samples
        if None not in (sample.left, sample.top, sample.right, sample.bottom)
    }
    if not by_frame:
        return []

    import mediapipe as mp

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir el video para MediaPipe: {video_path}")
    pose = mp.solutions.pose
    output: list[dict] = []
    frame_index = 0
    try:
        with pose.Pose(
            static_image_mode=False,
            model_complexity=1,
            enable_segmentation=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        ) as estimator:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                frame_index += 1
                sample = by_frame.get(frame_index)
                if sample is None:
                    continue
                height, width = frame.shape[:2]
                x1, x2 = int(sample.left * width), int(sample.right * width)
                y1, y2 = int(sample.top * height), int(sample.bottom * height)
                crop = frame[max(0, y1):min(height, y2), max(0, x1):min(width, x2)]
                if crop.size == 0:
                    continue
                result = estimator.process(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
                if not result.pose_landmarks:
                    continue
                landmarks = result.pose_landmarks.landmark
                left_shoulder, right_shoulder = landmarks[11], landmarks[12]
                left_wrist, right_wrist = landmarks[15], landmarks[16]
                required = (left_shoulder, right_shoulder, left_wrist, right_wrist)
                if any(point.visibility < 0.5 for point in required):
                    continue
                hand_up = left_wrist.y < left_shoulder.y or right_wrist.y < right_shoulder.y
                output.append({
                    "second": round(sample.second, 3),
                    "hand_up": bool(hand_up),
                    "shoulder_tilt": round(abs(left_shoulder.y - right_shoulder.y), 4),
                    "source": "mediapipe_presenter_crop",
                })
    finally:
        cap.release()
    return output


def analyze_video(video_path: str, model_path: str, sample_fps: float = 2.0,
                  pose_model_path: str | None = None, vision_provider: str | None = None,
                  vision_model: str | None = None, vision_window_seconds: float = 15.0,
                  mediapipe_presenter: bool = False, appearance_reid: bool = False) -> dict:
    """Analiza un video sin almacenar rostros ni identificar personas."""
    if sample_fps <= 0:
        raise ValueError("sample_fps debe ser mayor que cero")
    if vision_provider and vision_window_seconds <= 0:
        raise ValueError("vision_window_seconds debe ser mayor que cero")
    if not Path(video_path).is_file():
        raise FileNotFoundError(video_path)

    from ultralytics import YOLO

    model = YOLO(model_path, task="detect")
    pose_model = YOLO(pose_model_path, task="pose") if pose_model_path else None
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir el video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_skip = max(1, round(fps / sample_fps))
    width = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1.0
    height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1.0
    frame_area = width * height
    tracks: dict[int, list[TrackSample]] = defaultdict(list)
    reidentifier = None
    if appearance_reid:
        from app.reid import AppearanceReidentifier
        reidentifier = AppearanceReidentifier()
    pose_tracks: dict[int, list[PoseSample]] = defaultdict(list)
    frame_index = 0
    sampled_frames = 0
    vision_frames: dict[int, list[bytes]] = defaultdict(list)
    next_vision_capture = 0.0
    visual_frame_spacing = vision_window_seconds / 3 if vision_provider else 0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame_index += 1
            if frame_index % frame_skip:
                continue

            sampled_frames += 1
            result = model.track(frame, persist=True, classes=[PERSON_CLASS_ID], tracker="bytetrack.yaml", verbose=False)[0]
            boxes = result.boxes
            if boxes is None or boxes.id is None:
                continue

            timestamp = frame_index / fps
            if vision_provider and timestamp >= next_vision_capture:
                window_index = int(timestamp // vision_window_seconds)
                vision_frames[window_index].append(_encode_visual_frame(frame))
                next_vision_capture += visual_frame_spacing
            box_entries = list(zip(boxes.xyxy.tolist(), boxes.id.int().tolist()))
            active_track_ids = {int(track_id) for _, track_id in box_entries}
            for box, track_id in box_entries:
                x1, y1, x2, y2 = box
                center_x = round(((x1 + x2) / 2) / width, 4)
                center_y = round(((y1 + y2) / 2) / height, 4)
                person_id = None
                reid_confidence = None
                visible_descriptor = None
                if reidentifier:
                    crop = frame[max(0, int(y1)):min(int(height), int(y2)), max(0, int(x1)):min(int(width), int(x2))]
                    person_id, reid_confidence, visible_descriptor = reidentifier.assign(
                        int(track_id), crop, timestamp, (center_x, center_y), active_track_ids
                    )
                tracks[int(track_id)].append(TrackSample(
                    second=round(timestamp, 3),
                    center_x=center_x,
                    center_y=center_y,
                    area_ratio=round(max(0, (x2 - x1) * (y2 - y1)) / frame_area, 6),
                    left=round(max(0, x1) / width, 4),
                    top=round(max(0, y1) / height, 4),
                    right=round(min(width, x2) / width, 4),
                    bottom=round(min(height, y2) / height, 4),
                    person_id=person_id,
                    reid_confidence=reid_confidence,
                    visible_descriptor=visible_descriptor,
                ))
            if pose_model:
                pose_result = pose_model.track(
                    frame, persist=True, classes=[PERSON_CLASS_ID], tracker="bytetrack.yaml", verbose=False
                )[0]
                _collect_pose_samples(pose_result, timestamp, pose_tracks)
    finally:
        cap.release()

    person_tracks: dict[str, list[TrackSample]] = defaultdict(list)
    if appearance_reid:
        for track_samples in tracks.values():
            for sample in track_samples:
                if sample.person_id:
                    person_tracks[sample.person_id].append(sample)
        for samples in person_tracks.values():
            samples.sort(key=lambda sample: sample.second)
    presenter_id = select_presenter(person_tracks if appearance_reid else tracks)
    presenter_samples = (person_tracks if appearance_reid else tracks).get(presenter_id, []) if presenter_id is not None else []
    events = detect_movement_events(presenter_samples, presenter_id) if presenter_id is not None else []
    for pose_track_id, samples in pose_tracks.items():
        events.extend(detect_hand_raised_events(samples, pose_track_id))
    events.sort(key=lambda event: event["start_seconds"])
    mediapipe_presenter_pose: list[dict] = []
    if mediapipe_presenter and presenter_id is not None:
        mediapipe_presenter_pose = _analyze_presenter_with_mediapipe(
            video_path, fps, presenter_samples
        )
    visual_descriptions: list[dict] = []
    hybrid_observations: list[dict] = []
    if vision_provider:
        from app.vision import VisionDescriber
        describer = VisionDescriber(vision_provider, vision_model)
        visual_descriptions = [
            describer.describe_window(images, index * vision_window_seconds, (index + 1) * vision_window_seconds)
            for index, images in sorted(vision_frames.items())
        ]
        hybrid_observations = fuse_visual_observations(visual_descriptions, events)
    return {
        "video": Path(video_path).name,
        "sample_fps": sample_fps,
        "sampled_frames": sampled_frames,
        "presenter_track_id": presenter_id if not appearance_reid else None,
        "presenter_person_id": presenter_id if appearance_reid else None,
        "appearance_reidentification": appearance_reid,
        "tracks": {
            str(track_id): [sample.__dict__ for sample in samples]
            for track_id, samples in tracks.items()
        },
        "pose_tracks": {
            str(track_id): [sample.__dict__ for sample in samples]
            for track_id, samples in pose_tracks.items()
        },
        "people": {
            person_id: {
                "track_ids": sorted({track_id for track_id, values in tracks.items() if any(sample.person_id == person_id for sample in values)}),
                "visible_descriptor": next((sample.visible_descriptor for sample in samples if sample.visible_descriptor), "prenda no determinada"),
                "first_seen_seconds": round(samples[0].second, 2),
                "last_seen_seconds": round(samples[-1].second, 2),
                "sample_count": len(samples),
            }
            for person_id, samples in person_tracks.items()
        },
        "mediapipe_presenter_pose": mediapipe_presenter_pose,
        "events": events,
        "visual_descriptions": visual_descriptions,
        "hybrid_observations": hybrid_observations,
    }
