"""Crea o actualiza la rúbrica por defecto de observación de aula MBDD.

La configuración se basa en los cinco desempeños observables del Dominio II
del MBDD. La evaluación pedagógica pesa 90 % y la oratoria 10 %.

Uso: ejecutar con el intérprete del entorno virtual desde la raíz del proyecto.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.database import Base, SessionLocal, engine
from shared.models import RubricaCurso


CRITERIOS = [
    {
        "id": "involucramiento_aprendizaje",
        "nombre": "Involucra activamente a los estudiantes",
        "peso": 0.20,
        "que_evalua": (
            "Promueve interés, participación y comprensión del sentido, importancia "
            "o utilidad de lo aprendido. Evalúa solo la evidencia observable en la sesión."
        ),
        "niveles": {
            "Inicio": "No ofrece oportunidades reales de participación o más de la mitad del grupo se muestra distraído, indiferente o desinteresado sin que el docente ajuste la dinámica.",
            "En desarrollo": "Ofrece algunas oportunidades de participación y logra involucrar al menos a la mitad del grupo, pero la participación es limitada o no se sostiene el interés de la mayoría.",
            "Logrado": "Propone actividades atractivas o desafiantes, ofrece múltiples oportunidades de participación y la gran mayoría del grupo se mantiene atenta, concentrada o comprometida.",
            "Destacado": "Involucra a todos o casi todos; identifica y reincorpora deliberadamente a quienes no participan, y ayuda al grupo a comprender el sentido, importancia o utilidad de lo que aprende.",
        },
    },
    {
        "id": "pensamiento_critico",
        "nombre": "Promueve razonamiento, creatividad y pensamiento crítico",
        "peso": 0.20,
        "que_evalua": (
            "Propone actividades e interacciones que promueven análisis, relaciones conceptuales, "
            "estrategias, ideas propias, creatividad o reflexión; no solo respuestas reproductivas."
        ),
        "niveles": {
            "Inicio": "Las actividades se centran en repetición, copia o respuesta cerrada y no se observa una oportunidad significativa para analizar, crear, relacionar ideas o justificar.",
            "En desarrollo": "Plantea de manera aislada una pregunta o actividad de mayor demanda cognitiva, pero la aborda superficialmente o no aprovecha las respuestas para profundizar.",
            "Logrado": "En al menos una oportunidad relevante, plantea preguntas, problemas o tareas que llevan a los estudiantes a explicar, comparar, justificar, crear o formular estrategias propias.",
            "Destacado": "Sostiene durante la sesión oportunidades de pensamiento de orden superior, profundiza en las ideas de los estudiantes y favorece que elaboren, contrasten o argumenten con autonomía.",
        },
    },
    {
        "id": "evaluacion_retroalimentacion",
        "nombre": "Evalúa el progreso y retroalimenta para aprender",
        "peso": 0.25,
        "que_evalua": (
            "Monitorea avances y dificultades, recoge evidencia de comprensión y brinda retroalimentación "
            "formativa o adapta la enseñanza según las necesidades identificadas."
        ),
        "niveles": {
            "Inicio": "No monitorea o lo hace muy ocasionalmente; no retroalimenta, entrega información incorrecta, sanciona el error o desaprovecha la incomprensión como oportunidad de aprendizaje.",
            "En desarrollo": "Monitorea activamente parte de la sesión, pero la retroalimentación es elemental: solo indica si algo está bien o mal, da la respuesta o repite la explicación sin ajustarla.",
            "Logrado": "Recoge evidencia de comprensión y, al menos una vez, brinda retroalimentación descriptiva sobre cómo mejorar y/o adapta la explicación, ejemplo, actividad o dificultad de la tarea.",
            "Destacado": "Monitorea sistemáticamente y, al menos una vez, guía por preguntas para que los estudiantes descubran cómo mejorar, reflexionen sobre su razonamiento o identifiquen el origen de sus errores.",
        },
    },
    {
        "id": "ambiente_respeto_proximidad",
        "nombre": "Propicia un ambiente de respeto y proximidad",
        "peso": 0.175,
        "que_evalua": (
            "Se comunica con respeto y cordialidad, evita el maltrato y responde con sensibilidad "
            "a necesidades afectivas o físicas observables de los estudiantes."
        ),
        "niveles": {
            "Inicio": "Se observa maltrato verbal o físico, humillación, discriminación, hostilidad o desatención grave a necesidades evidentes de los estudiantes.",
            "En desarrollo": "Predomina el trato respetuoso, pero la cordialidad, escucha o respuesta a necesidades de los estudiantes es limitada, irregular o poco sensible.",
            "Logrado": "Mantiene un trato respetuoso y cordial de manera consistente; escucha y responde adecuadamente a intervenciones, dudas o necesidades que se observan durante la sesión.",
            "Destacado": "Además de un trato consistentemente respetuoso y cálido, anticipa o atiende con empatía necesidades individuales y construye un clima seguro que favorece la participación de todos.",
        },
    },
    {
        "id": "regulacion_positiva",
        "nombre": "Regula positivamente el comportamiento",
        "peso": 0.175,
        "que_evalua": (
            "Establece o recuerda normas, previene y redirige conductas con mecanismos formativos "
            "que favorecen autorregulación y continuidad del aprendizaje."
        ),
        "niveles": {
            "Inicio": "No redirige conductas que interrumpen la sesión, predomina el control punitivo o se observa maltrato; la clase se desarrolla con interrupciones importantes o frecuentes.",
            "En desarrollo": "Usa mecanismos formativos o de control externo sin maltrato, pero son poco eficaces o la sesión mantiene interrupciones que dificultan el aprendizaje.",
            "Logrado": "Regula de manera eficaz con mecanismos formativos, sin maltrato, y la mayor parte de la sesión transcurre de forma continua y con normas comprensibles.",
            "Destacado": "Usa siempre mecanismos formativos que promueven reflexión y autorregulación; las normas se sostienen y toda la sesión avanza sin interrupciones relevantes.",
        },
    },
]


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        rubrica = db.get(RubricaCurso, "default")
        if rubrica is None:
            rubrica = RubricaCurso(curso_id="default")
            db.add(rubrica)

        rubrica.nombre = "Observación de aula MBDD — pedagogía 90 % / oratoria 10 %"
        rubrica.criterios = CRITERIOS
        rubrica.peso_contenido = 0.90
        rubrica.peso_forma = 0.10
        rubrica.activo = True
        db.commit()

        print("Rúbrica 'default' creada/actualizada correctamente.")
        print(f"Criterios: {len(CRITERIOS)} | Pedagogía: {rubrica.peso_contenido:.0%} | Oratoria: {rubrica.peso_forma:.0%}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
