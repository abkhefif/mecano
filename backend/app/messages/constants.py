"""Message template constants for the eMecano messaging system.

These predefined templates allow buyers and mechanics to communicate
quickly during a booking without exposing personal contact information.
"""

BUYER_TEMPLATES = [
    {
        "category": "Retard",
        "messages": [
            "Je serai en retard de 10 minutes",
            "Je serai en retard de 15 minutes",
            "Je serai en retard de 30 minutes",
        ],
    },
    {
        "category": "Localisation",
        "messages": [
            "Je ne trouve pas l'adresse",
            "Je suis sur place",
            "Je suis en route",
        ],
    },
    {
        "category": "Véhicule",
        "messages": [
            "Le véhicule est prêt",
            "Le véhicule n'est pas disponible pour le moment",
            "J'ai une question sur l'inspection",
        ],
    },
    {
        "category": "Autre",
        "messages": [
            "Je souhaite reporter le rendez-vous",
            "Je confirme ma présence",
            "Merci beaucoup !",
        ],
    },
]

MECHANIC_TEMPLATES = [
    {
        "category": "Retard",
        "messages": [
            "Je serai en retard de 10 minutes",
            "Je serai en retard de 15 minutes",
            "Je serai en retard de 30 minutes",
        ],
    },
    {
        "category": "Localisation",
        "messages": [
            "Je ne trouve pas l'adresse",
            "Je suis en route vers vous",
            "Je suis arrivé",
        ],
    },
    {
        "category": "Véhicule",
        "messages": [
            "Merci de préparer le véhicule SVP",
            "Avez-vous le carnet d'entretien ?",
            "Quel est le kilométrage actuel ?",
        ],
    },
    {
        "category": "Autre",
        "messages": [
            "Je souhaite reporter le rendez-vous",
            "L'inspection est terminée",
            "Je vous envoie le rapport",
        ],
    },
]

# Combined list for backward compatibility
ALL_TEMPLATES = BUYER_TEMPLATES + MECHANIC_TEMPLATES

# Keep backward-compatible default
TEMPLATES = BUYER_TEMPLATES

# Rebuild ALL_TEMPLATE_MESSAGES to include BOTH sets (used for validation in routes.py)
ALL_TEMPLATE_MESSAGES = {
    msg for cat in ALL_TEMPLATES for msg in cat["messages"]
}
