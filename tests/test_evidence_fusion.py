import unittest

from services.extractions.evidence_fusion.analyzer import build_evidence_ficha
from services.extractions.vision_description.analyzer import _remove_role_attribution


class EvidenceFusionTests(unittest.TestCase):
    def test_builds_temporal_audio_and_visual_evidence(self):
        ficha = build_evidence_ficha(
            duration_seconds=65,
            words=[
                {"word": "¿Por", "start": 18.1},
                {"word": "qué", "start": 18.3},
                {"word": "crees", "start": 18.6},
                {"word": "eso?", "start": 19.0},
            ],
            transcription_quality={"confiable": True},
            posture={
                "tracking_timeline": [
                    {"second": 18, "nose_x": 0.20, "nose_y": 0.4},
                    {"second": 25, "nose_x": 0.55, "nose_y": 0.4},
                ]
            },
            objects={
                "personas_por_segundo": [0] * 18 + [3] * 12,
                "objetos": [
                    {
                        "label": "Pizarra / Pantalla",
                        "primera_aparicion": 10,
                        "ultima_aparicion": 28,
                    }
                ],
            },
            vision={
                "descripciones": [
                    {
                        "second": 18,
                        "descripcion": "Se observa una persona de pie frente a varias personas sentadas y una pizarra.",
                        "confianza": "media",
                    }
                ]
            },
            video_info={"resolucion": "1280x720", "fps": 30},
            window_seconds=30,
        )

        self.assertEqual(len(ficha["transcripcion_multimodal"]), 3)
        first = ficha["transcripcion_multimodal"][0]
        self.assertEqual(first["inicio"], "00:00:00")
        self.assertIn("desplazamiento lateral", first["visual"])
        self.assertIn("persona de pie", first["visual"])
        self.assertTrue(any(e["tipo"] == "interrogante_detectada" for e in ficha["evidencias"]))
        self.assertTrue(any(e["tipo"] == "observacion_visual" for e in ficha["evidencias"]))
        self.assertEqual(ficha["politica_retencion"]["clips_y_frames"], "No se conservan clips, audio temporal ni frames temporales.")
        self.assertEqual(ficha["identificacion_docente"]["estado"], "no_identificado")
        self.assertIn("no identifica el rol", " ".join(first["limitaciones"]))

    def test_marks_missing_pose_as_a_limitation_not_an_absence(self):
        ficha = build_evidence_ficha(
            duration_seconds=30,
            words=[],
            transcription_quality={},
            posture={},
            objects={},
            video_info={},
            window_seconds=30,
        )

        window = ficha["transcripcion_multimodal"][0]
        self.assertIn("No se detectó una pose", window["visual"])
        self.assertIn("no prueba ausencia", " ".join(window["limitaciones"]))

    def test_visual_description_does_not_assign_teacher_or_student_roles(self):
        description = _remove_role_attribution(
            "Un docente observa a los estudiantes y varias alumnas escriben."
        )
        self.assertNotIn("docente", description.lower())
        self.assertNotIn("estudiantes", description.lower())
        self.assertNotIn("alumnas", description.lower())


if __name__ == "__main__":
    unittest.main()
