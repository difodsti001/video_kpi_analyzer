import unittest

from services.pedagogical_analysis.evaluacion.analyzer import (
    construir_evidencia,
    construir_prompt_evaluacion,
    parsear_respuesta,
)


CRITERIO = {
    "id": "c1",
    "nombre": "Involucramiento activo",
    "peso": 1.0,
    "que_evalua": "Cómo se promueve la participación de estudiantes.",
    "niveles": {
        "Inicio": "Sin evidencia suficiente.",
        "En desarrollo": "Participación ocasional.",
        "Logrado": "Participación sostenida.",
        "Destacado": "Participación profunda.",
    },
}


class PedagogicalFeedbackTests(unittest.TestCase):
    def test_evidence_keeps_timestamped_windows_without_media(self):
        evidencia = construir_evidencia(
            "¿Cómo podríamos comprobarlo?",
            {"claridad": {"resumen": "Mensaje comprensible."}},
            {"objetos": []},
            {
                "transcripcion_multimodal": [
                    {
                        "inicio": "00:18:05",
                        "fin": "00:18:29",
                        "audio": "¿Cómo podríamos comprobarlo?",
                        "visual": "Una pose de persona detectada permanece orientada al grupo.",
                    }
                ]
            },
        )

        self.assertEqual(evidencia["evidencias_temporales"][0]["tiempo"], "00:18:05–00:18:29")
        self.assertNotIn("clip", str(evidencia).lower())

    def test_prompt_and_parser_keep_public_feedback_non_scored(self):
        evidencia = construir_evidencia("texto", {}, {"objetos": []})
        prompt = construir_prompt_evaluacion(evidencia, 6.0, [CRITERIO], 0.9, 0.1)
        self.assertIn('"orientacion_por_criterio"', prompt)
        self.assertIn("NO debe incluir puntajes, niveles", prompt)
        self.assertIn("evidencia_ids", prompt)
        self.assertIn("No agregues personas", prompt)

        criterios, narrativa = parsear_respuesta(
            '{"criterios":{"c1":{"nivel":"Logrado","justificacion":"Interno"}},'
            '"retroalimentacion_pedagogica":"En 00:18:05–00:18:29 se formula una pregunta abierta. '
            'Para profundizar, puede dar tiempo de intercambio antes de recoger respuestas."}',
            [CRITERIO],
        )

        self.assertEqual(criterios["c1"]["nivel"], "Logrado")
        self.assertIn("00:18:05", narrativa)

    def test_public_feedback_is_built_from_selected_evidence_ids(self):
        evidencia = construir_evidencia(
            "¿Cómo podríamos comprobarlo?",
            {}, {"objetos": []},
            {"transcripcion_multimodal": [{
                "inicio": "00:18:05", "fin": "00:18:29",
                "audio": "¿Cómo podríamos comprobarlo?",
                "visual": "Una persona permanece junto a una pizarra.",
            }]},
        )
        raw = (
            '{"criterios":{"c1":{"nivel":"Logrado"}},'
            '"orientacion_por_criterio":{"c1":{"evidencia_ids":["E01"],'
            '"lectura_pedagogica":"La pregunta abre una oportunidad para recoger ideas.",'
            '"sugerencia":"espere ocho segundos y pida dos explicaciones antes de responder."}}}'
        )
        _, narrativa = parsear_respuesta(raw, [CRITERIO], evidencia)

        self.assertTrue(narrativa.startswith("Involucramiento activo:"))
        self.assertIn("00:18:05–00:18:29", narrativa)
        self.assertIn("¿Cómo podríamos comprobarlo?", narrativa)


if __name__ == "__main__":
    unittest.main()
