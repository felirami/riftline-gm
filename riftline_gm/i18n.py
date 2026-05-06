from __future__ import annotations

LANGUAGE_OPTIONS = {
    "es_latam_keep_terms": {
        "label": "Español LatAm + términos en inglés",
        "prompt": "Responde en español latinoamericano natural. Mantén en inglés los términos propios del perfil de juego.",
        "keep_terms": True,
    },
    "es_es_keep_terms": {
        "label": "Español España + términos en inglés",
        "prompt": "Responde en español de España natural. Mantén en inglés los términos propios del perfil de juego.",
        "keep_terms": True,
    },
    "es_latam_full": {
        "label": "Español LatAm + traducción completa",
        "prompt": "Responde en español latinoamericano natural. Traduce términos cuando suenen claros y no rompan el tono.",
        "keep_terms": False,
    },
    "es_es_full": {
        "label": "Español España + traducción completa",
        "prompt": "Responde en español de España natural. Traduce términos cuando suenen claros y no rompan el tono.",
        "keep_terms": False,
    },
}

CONTENT_PRESETS = {
    "gritty_21_plus": {
        "label": "Crudo 21+",
        "prompt": (
            "El tono por defecto es adulto 21+, crudo y de alto riesgo: lenguaje fuerte, violencia, "
            "drogas, body horror, trauma, explotación, horror social y consecuencias duras. Mantén límites de seguridad: "
            "no erotices menores, no escribas violencia sexual explícita, no des instrucciones reales de daño, "
            "y usa fade-to-black si algo sexual se vuelve explícito."
        ),
    },
    "vanilla": {
        "label": "Cinemático",
        "prompt": "Mantén el tono noir y peligroso, pero baja el gore, el sexo explícito y la crueldad extrema.",
    },
    "pg_13": {
        "label": "PG-13",
        "prompt": "Mantén la acción y el drama, pero evita gore gráfico, sexo explícito y detalles muy perturbadores.",
    },
}

def language_label(language: str) -> str:
    return LANGUAGE_OPTIONS.get(language, LANGUAGE_OPTIONS["es_latam_keep_terms"])["label"]


def content_label(content_preset: str) -> str:
    return CONTENT_PRESETS.get(content_preset, CONTENT_PRESETS["gritty_21_plus"])["label"]
