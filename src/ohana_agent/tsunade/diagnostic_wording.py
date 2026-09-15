"""Decision wording that does not promote optional AI output to observations."""


def ai_conclusion(verdict: str) -> str | None:
    if verdict == "KO":
        return (
            "Des pistes de diagnostic nécessitent une vérification. "
            "L’analyse IA seule ne confirme ni une panne actuelle ni sa cause."
        )
    if verdict == "OK":
        return (
            "L’analyse IA ne propose pas d’investigation supplémentaire. "
            "Le retour à un état sain reste à confirmer par les observations."
        )
    return None
