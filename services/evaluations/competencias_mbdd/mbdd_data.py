# services/competencias_mbdd/mbdd_data.py

DOMINIOS = [
    {"id": "D1", "nombre": "Preparación para el aprendizaje de los estudiantes"},
    {"id": "D2", "nombre": "Enseñanza para el aprendizaje de los estudiantes"},
    {"id": "D3", "nombre": "Participación en la gestión de la escuela articulada a la comunidad"},
    {"id": "D4", "nombre": "Desarrollo de la profesionalidad y la identidad docente"},
]

COMPETENCIAS_MBDD = [
    {
        "id": "C1",
        "dominio": "D1",
        "nombre": "Conocimiento de estudiantes, contenidos y enfoques pedagógicos",
        "descripcion": "Conoce y comprende las características de todos sus estudiantes y sus "
                       "contextos, los contenidos disciplinares que enseña, los enfoques y procesos "
                       "pedagógicos, con el propósito de promover capacidades de alto nivel y su "
                       "formación integral.",
    },
    {
        "id": "C2",
        "dominio": "D1",
        "nombre": "Planificación colegiada de la enseñanza",
        "descripcion": "Planifica la enseñanza de forma colegiada garantizando la coherencia entre "
                       "los aprendizajes que quiere lograr en sus estudiantes, el proceso pedagógico, "
                       "el uso de los recursos disponibles y la evaluación, en una programación "
                       "curricular en permanente revisión.",
    },
    {
        "id": "C3",
        "dominio": "D2",
        "nombre": "Clima de aula y convivencia democrática",
        "descripcion": "Crea un clima propicio para el aprendizaje, la convivencia democrática y la "
                       "vivencia de la diversidad en todas sus expresiones, con miras a formar "
                       "ciudadanos críticos e interculturales.",
    },
    {
        "id": "C4",
        "dominio": "D2",
        "nombre": "Conducción del proceso de enseñanza",
        "descripcion": "Conduce el proceso de enseñanza con dominio de los contenidos disciplinares "
                       "y el uso de estrategias y recursos pertinentes, para que todos los estudiantes "
                       "aprendan de manera reflexiva y crítica lo que concierne a la solución de "
                       "problemas relacionados con sus experiencias, intereses y contextos culturales.",
    },
    {
        "id": "C5",
        "dominio": "D2",
        "nombre": "Evaluación permanente del aprendizaje",
        "descripcion": "Evalúa permanentemente el aprendizaje de acuerdo con los objetivos "
                       "institucionales previstos, para tomar decisiones y retroalimentar a sus "
                       "estudiantes y a la comunidad educativa, teniendo en cuenta las diferencias "
                       "individuales y los contextos culturales.",
    },
    {
        "id": "C6",
        "dominio": "D3",
        "nombre": "Gestión escolar participativa",
        "descripcion": "Participa activamente, con actitud democrática, crítica y colaborativa, en la "
                       "gestión de la escuela, contribuyendo a la construcción y mejora continua del "
                       "Proyecto Educativo Institucional y así éste pueda generar aprendizajes de "
                       "calidad.",
    },
    {
        "id": "C7",
        "dominio": "D3",
        "nombre": "Relación con familias y comunidad",
        "descripcion": "Establece relaciones de respeto, colaboración y corresponsabilidad con las "
                       "familias, la comunidad y otras instituciones del Estado y la sociedad civil; "
                       "aprovecha sus saberes y recursos en los procesos educativos y da cuenta de "
                       "los resultados.",
    },
    {
        "id": "C8",
        "dominio": "D4",
        "nombre": "Reflexión sobre la práctica docente",
        "descripcion": "Reflexiona sobre su práctica y experiencia institucional y desarrolla procesos "
                       "de aprendizaje continuo de modo individual y colectivo, para construir y armar "
                       "su identidad y responsabilidad profesional.",
    },
    {
        "id": "C9",
        "dominio": "D4",
        "nombre": "Ética profesional docente",
        "descripcion": "Ejerce su profesión desde una ética de respeto de los derechos fundamentales "
                       "de las personas, demostrando honestidad, justicia, responsabilidad y "
                       "compromiso con su función social.",
    },
]

NIVELES_EVIDENCIA = ["sí", "evidencia parcial", "sin evidencia en esta sesión"]

# Fuerza/densidad de la evidencia encontrada (NO calidad de ejecución): cuánta
# evidencia hay y qué tan explícita/recurrente es. Solo aplica cuando
# evidencia == "sí"; en los demás casos corresponde "no aplica".
NIVELES_FUERZA = ["alto", "medio", "bajo"]
FUERZA_NO_APLICA = "no aplica"
