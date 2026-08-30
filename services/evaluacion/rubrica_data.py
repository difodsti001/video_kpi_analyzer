# services/rubric/rubrica_data.py
# Rúbrica de evaluación de contenido (Rubrica_propuesta.docx).
# Fuente única de verdad: el prompt y el parser se construyen a partir de esta lista.

RUBRICA = [
    {
        "id": "C1",
        "nombre": "Coherencia con el propósito, temática y producto",
        "que_evalua": "Que la respuesta o producto desarrollado responda al propósito de aprendizaje "
                      "y se encuentre directamente relacionado con la temática y el producto solicitado.",
        "peso": 0.15,
        "niveles": {
            "Inicio": "La respuesta no responde al propósito, se desvía de la temática o no desarrolla "
                      "el producto solicitado.",
            "En desarrollo": "La respuesta guarda relación parcial con el propósito y la temática, pero "
                              "presenta desviaciones, omisiones o desarrolla parcialmente el producto solicitado.",
            "Logrado": "La respuesta responde al propósito, aborda la temática de manera pertinente y "
                       "cumple con las características esenciales del producto solicitado.",
            "Destacado": "La respuesta responde plenamente al propósito, profundiza en la temática y "
                         "desarrolla el producto de manera pertinente, incorporando elementos que "
                         "enriquecen o fortalecen lo solicitado.",
        },
    },
    {
        "id": "C2",
        "nombre": "Comprensión del desafío o situación",
        "que_evalua": "La capacidad para comprender la situación planteada, identificar el problema o "
                      "desafío y reconocer la información relevante para responder.",
        "peso": 0.15,
        "niveles": {
            "Inicio": "No identifica adecuadamente el desafío o presenta una comprensión superficial o "
                      "equivocada de la situación.",
            "En desarrollo": "Identifica parcialmente el desafío y algunos elementos relevantes, pero su "
                              "interpretación presenta vacíos o inconsistencias.",
            "Logrado": "Comprende el desafío, identifica los elementos relevantes y los relaciona "
                       "adecuadamente con la situación planteada.",
            "Destacado": "Comprende integralmente el desafío, identifica elementos explícitos e implícitos "
                         "y reconoce su complejidad, considerando diferentes perspectivas o condiciones.",
        },
    },
    {
        "id": "C3",
        "nombre": "Movilización de conocimientos y recursos",
        "que_evalua": "La capacidad para utilizar conocimientos, estrategias, experiencias o recursos "
                      "pertinentes para responder al desafío y desarrollar el producto.",
        "peso": 0.20,
        "niveles": {
            "Inicio": "Reproduce información o utiliza recursos sin relación clara con el desafío o de "
                      "manera mecánica.",
            "En desarrollo": "Utiliza algunos conocimientos o recursos pertinentes, aunque de manera "
                              "parcial o con dificultades para integrarlos.",
            "Logrado": "Selecciona y utiliza conocimientos y estrategias pertinentes para responder al "
                       "desafío y sustentar el producto desarrollado.",
            "Destacado": "Integra diversos conocimientos, estrategias y recursos de manera pertinente, "
                         "flexible y estratégica, adaptándolos a las características de la situación.",
        },
    },
    {
        "id": "C4",
        "nombre": "Análisis, argumentación y toma de decisiones",
        "que_evalua": "La capacidad para analizar información, establecer relaciones, valorar "
                      "alternativas, argumentar y tomar decisiones fundamentadas.",
        "peso": 0.25,
        "niveles": {
            "Inicio": "Presenta afirmaciones sin análisis suficiente, reproduce información o toma "
                      "decisiones sin sustento.",
            "En desarrollo": "Realiza algún análisis y presenta argumentos, pero estos son parciales, "
                              "poco desarrollados o presentan dificultades de fundamentación.",
            "Logrado": "Analiza información relevante, establece relaciones, argumenta sus ideas y toma "
                       "decisiones pertinentes sustentadas en evidencias o razones.",
            "Destacado": "Contrasta perspectivas o alternativas, analiza consecuencias, identifica "
                         "relaciones complejas y construye argumentos sólidos para sustentar decisiones "
                         "pertinentes.",
        },
    },
    {
        "id": "C5",
        "nombre": "Aplicación y resolución del desafío",
        "que_evalua": "La capacidad para aplicar lo aprendido y construir una respuesta o producto que "
                      "permita abordar el desafío planteado.",
        "peso": 0.15,
        "niveles": {
            "Inicio": "La respuesta o producto no permite abordar adecuadamente el desafío o requiere "
                      "orientación constante.",
            "En desarrollo": "La respuesta aborda parcialmente el desafío, aunque presenta dificultades "
                              "en su aplicación o requiere apoyo para completarla.",
            "Logrado": "Aplica lo aprendido de manera pertinente y autónoma, construyendo una respuesta "
                       "o producto coherente con el desafío.",
            "Destacado": "Aplica lo aprendido de manera autónoma, flexible y estratégica, adaptando su "
                         "respuesta ante situaciones nuevas o condiciones diferentes.",
        },
    },
    {
        "id": "C6",
        "nombre": "Reflexión y transferencia",
        "que_evalua": "La capacidad para evaluar lo realizado, reconocer aprendizajes y dificultades, y "
                      "transferirlos a nuevas situaciones.",
        "peso": 0.10,
        "niveles": {
            "Inicio": "Se limita a describir lo realizado sin identificar aprendizajes, dificultades o "
                      "posibilidades de mejora.",
            "En desarrollo": "Identifica algunos aprendizajes o dificultades, pero tiene dificultades para "
                              "explicar su importancia o aplicarlos a otras situaciones.",
            "Logrado": "Reflexiona sobre lo realizado, identifica aprendizajes y oportunidades de mejora y "
                       "establece relaciones con situaciones similares.",
            "Destacado": "Analiza críticamente su actuación, utiliza evidencias para explicar sus "
                         "aprendizajes y propone cómo transferirlos o adaptarlos a situaciones nuevas y "
                         "complejas.",
        },
    },
]

NIVEL_VALOR = {"inicio": 1, "en desarrollo": 2, "logrado": 3, "destacado": 4}
