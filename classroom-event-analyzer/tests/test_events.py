from app.events import (
    PoseSample,
    TrackSample,
    detect_hand_raised_events,
    detect_movement_events,
    fuse_visual_observations,
    select_presenter,
)


def test_selects_longest_track_as_presenter():
    tracks = {
        1: [TrackSample(0, 0.3, 0.5, 0.1)],
        2: [TrackSample(0, 0.5, 0.5, 0.2), TrackSample(1, 0.5, 0.5, 0.2)],
    }
    assert select_presenter(tracks) == 2


def test_detects_sustained_horizontal_movement():
    samples = [
        TrackSample(0, 0.2, 0.5, 0.2),
        TrackSample(2, 0.25, 0.5, 0.2),
        TrackSample(4, 0.45, 0.5, 0.2),
    ]
    events = detect_movement_events(samples, track_id=3)
    assert len(events) == 1
    assert events[0]["evidence"]["direction"] == "derecha"


def test_detects_sustained_hand_raised_event():
    samples = [PoseSample(0, True), PoseSample(1, True), PoseSample(2.5, True), PoseSample(4, False)]
    events = detect_hand_raised_events(samples, track_id=8)
    assert len(events) == 1
    assert events[0]["type"] == "mano_levantada"


def test_marks_vision_observation_as_supported_when_time_overlaps_detector_event():
    visual = [{"start_seconds": 10, "end_seconds": 20, "observations": [
        {"text": "Una persona cambia de posición.", "labels": ["person_movement"], "confidence": 0.7}
    ]}]
    detector = [{"type": "presentador_desplazamiento", "start_seconds": 14, "end_seconds": 18}]
    fused = fuse_visual_observations(visual, detector)
    assert fused[0]["verification"] == "corroborada_por_detector"
