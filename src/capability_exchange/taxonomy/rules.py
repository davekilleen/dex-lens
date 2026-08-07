"""Rule data for the G6 classifier: phrase patterns per high-impact category.

These are deterministic keyword/stem/phrase rules — data consumed by
:mod:`capability_exchange.taxonomy.classifier`. No model call is involved
anywhere (pilot posture D8: fully local); results are honestly marked
``inferred`` in the R2 vocabulary.

Design bias (gates.md G6 test strategy a): ZERO FALSE NEGATIVES on the
labeled corpus; false positives are acceptable and are recorded, not gated.
Rules therefore over-match on purpose: short stems, generous token gaps,
euphemistic phrasings, and common non-English phrasings (Spanish, French,
German) all route to high-impact.

Matching semantics (implemented by the classifier):

- text and phrases are both normalized: Unicode-decomposed, accents
  stripped, casefolded, punctuation collapsed to spaces (so ``löschen``
  matches ``loschen``, ``envía`` matches ``envia``, ``e-mail`` → ``e mail``);
- each phrase token matches any word starting with it (stem match:
  ``delet`` matches ``deleted``, ``deleting``);
- up to three words may fall between consecutive phrase tokens
  (``send email`` matches ``send the follow-up email``).

Several phrases quote the gates.md/HANDOFF 5.1 hostile fixtures verbatim
(e.g. "outbound correspondence", "tidy up", "access token"): adversarial
input we must catch, not product vocabulary.
"""

from __future__ import annotations

from capability_exchange.taxonomy.categories import HighImpactCategory

__all__ = ["AMBIGUOUS_SCOPE_PHRASES", "RULE_PHRASES"]

#: Phrase patterns per category. Overlap between categories is fine — a job
#: may touch several; the classifier returns the union.
RULE_PHRASES: dict[HighImpactCategory, tuple[str, ...]] = {
    HighImpactCategory.SENDING_MESSAGES: (
        # plain
        "send",
        "sent",
        "email",
        "reply",
        "respond to",
        "message",
        "sms",
        "whatsapp",
        "telegram",
        "post to",
        "post on",
        "publish",
        "tweet",
        "newsletter",
        "broadcast",
        "notify",
        "forward to",
        "mail out",
        "mailing",
        "announce",
        "rsvp",
        # euphemistic
        "outbound correspondence",
        "correspondence",
        "outreach",
        "reach out",
        "follow up with",
        "get back to",
        "keep in touch",
        "keep contacts warm",
        "drop a line",
        "let them know",
        "let him know",
        "let her know",
        "circulate",
        "ping",
        "nudge",
        "share with the team",
        "share it with",
        # Spanish
        "envi",  # enviar / envía / envío
        "mandar",
        "mensaje",
        "correo",
        "responder",
        # French
        "envoyer",
        "envoi",
        "repondre",
        "courriel",
        # German
        "senden",
        "verschicken",
        "nachricht",
        "antworten",
        "schreiben an",
    ),
    HighImpactCategory.MONEY_PURCHASING: (
        # plain
        "buy",
        "purchas",
        "pay for",
        "pay the",
        "pay my",
        "payment",
        "checkout",
        "place order",
        "place an order",
        "reorder",
        "subscri",  # subscribe / subscription
        "renew",
        "book flight",
        "book a flight",
        "book hotel",
        "book a hotel",
        "booking",
        "shopping",
        "shop for",
        "procure",
        "billing",
        "refund",
        "transfer money",
        "send money",
        "wire",
        "venmo",
        "paypal",
        "credit card",
        "debit",
        "money",
        # euphemistic
        "restock",
        "top up",
        "supplies run",
        "groceries",
        # Spanish
        "compr",  # comprar / compra
        "pagar",
        "pago",
        # French
        "acheter",
        "achat",
        "payer",
        # German
        "kauf",  # kaufen / einkaufen / verkaufen
        "bezahl",
        "bestell",  # bestellen
    ),
    HighImpactCategory.PERMISSIONS: (
        # plain
        "permission",
        "permiss",
        "grant",
        "revoke",
        "chmod",
        "acl",
        "sudo",
        "admin right",
        "admin access",
        "make public",
        "make it public",
        "share access",
        "give access",
        "access for",
        "collaborator",
        "role assign",
        "entitlement",
        "visibility",
        "who can see",
        "who can edit",
        # euphemistic
        "open up",
        "loop in",
        "lock down",
        "let everyone",
        # Spanish
        "permiso",
        "acceso",
        # French
        "autorisation",
        "droits",
        "acces",
        # German
        "berechtigung",
        "zugriff",
        "freigeb",  # freigeben
        "freigabe",
    ),
    HighImpactCategory.DELETION: (
        # plain
        "delet",
        "remov",
        "erase",
        "purge",
        "wipe",
        "prune",
        "trash",
        "truncate",
        "drop table",
        "rm rf",
        "overwrit",
        # euphemistic
        "tidy up",
        "tidy old",
        "clean up",
        "clean out",
        "clear out",
        "clear old",
        "declutter",
        "get rid of",
        "throw away",
        "cull",
        "retire old",
        "empty the",
        "sweep out",
        # Spanish
        "borr",  # borrar / borra
        "elimin",  # eliminar (also English eliminate)
        "limpiar",
        # French
        "supprim",  # supprimer
        "effac",  # effacer
        "nettoyer",
        # German
        "losch",  # löschen (normalized)
        "aufraum",  # aufräumen (normalized)
        "entfern",  # entfernen
    ),
    HighImpactCategory.CREDENTIALS: (
        # plain
        "password",
        "passphrase",
        "credential",
        "token",
        "api key",
        "secret",
        "ssh key",
        "oauth",
        "login",
        "sign in",
        "signin",
        "2fa",
        "mfa",
        "two factor",
        "keychain",
        "access token",
        "rotate key",
        "rotate my key",
        "rotate token",
        "rotate credential",
        # euphemistic
        "sign in stuff",
        "consolidate my logins",
        "access stuff",
        # Spanish
        "contrasena",  # contraseña (normalized)
        "clave",
        # French
        "mot de passe",
        "identifiant",
        # German
        "passwort",
        "kennwort",
        "zugangsdaten",
        "schlussel",  # schlüssel (normalized)
    ),
    HighImpactCategory.HEALTH: (
        # plain
        "health",
        "medic",  # medical / medication / medicine / medico
        "meds",
        "doctor",
        "clinic",
        "prescription",
        "pharmac",
        "symptom",
        "therap",
        "illness",
        "blood pressure",
        "insulin",
        "dosage",
        "vaccin",
        "allerg",
        "fitness",
        "diet",
        # euphemistic
        "wellness",
        "refill",
        "check up",
        "checkup",
        # Spanish
        "salud",
        "enfermedad",
        "receta medica",
        # French
        "sante",  # santé (normalized)
        "medecin",  # médecin (normalized)
        "ordonnance",
        # German
        "gesundheit",
        "arzt",
        "krank",  # krankheit / krankenversicherung
        "rezept",
    ),
    HighImpactCategory.LEGAL: (
        # plain
        "legal",
        "lawyer",
        "attorney",
        "lawsuit",
        "court",
        "contract",
        "nda",
        "compliance",
        "visa",
        "immigration",
        "estate",
        "clause",
        "liabilit",
        "settlement",
        "notary",
        "sue the",
        "suing",
        "dispute",
        # euphemistic
        "agreement",
        "redline",
        "paperwork for my case",
        "terms and conditions",
        # Spanish
        "abogado",
        "juridic",  # jurídico / juridique (also French)
        "demanda",
        # French
        "avocat",
        "proces",  # procès (normalized)
        "contrat",
        # German
        "vertrag",
        "anwalt",
        "rechtlich",
        "klage",
        "gericht",
    ),
    HighImpactCategory.FINANCIAL_DECISIONS: (
        # plain
        "invest",
        "portfolio",
        "stock",
        "retirement",
        "401k",
        "pension",
        "mortgage",
        "loan",
        "refinanc",
        "tax",
        "budget",
        "savings",
        "asset allocation",
        "rebalanc",
        "trade",
        "trading",
        "crypto",
        "bitcoin",
        "etf",
        "interest rate",
        # euphemistic
        "nest egg",
        "money work",
        "grow my money",
        "financ",  # finance / finances / financial
        # Spanish
        "inversion",  # inversión (normalized)
        "invertir",
        "hipoteca",
        "impuesto",
        # French
        "investir",
        "placement",
        "impot",  # impôt (normalized)
        "bourse",
        # German
        "investier",
        "anlage",
        "rente",
        "steuer",
        "borse",  # börse (normalized)
    ),
    HighImpactCategory.THIRD_PARTY_CONFIDENTIAL_DATA: (
        # plain
        "confidential",
        "client data",
        "client list",
        "client file",
        "clients shared",
        "customer data",
        "customer record",
        "customer list",
        "patient",
        "employee",
        "personal data",
        "pii",
        "someone else's data",
        "third party data",
        "hr file",
        "hr record",
        # euphemistic
        "what clients",
        "our customers",
        "people's details",
        "contact details of",
        # Spanish
        "confidencial",
        "datos de client",
        "datos personales",
        # French
        "confidentiel",
        "donnees client",
        "donnees personnelles",
        # German
        "vertraulich",
        "kundendaten",
        "personenbezogen",
    ),
}

#: Wide-open or catch-all scope phrasings. A job worded this way cannot be
#: honestly bounded, so it is ambiguous → high-impact (gates.md G6 fail
#: closed), with no specific category attached.
AMBIGUOUS_SCOPE_PHRASES: tuple[str, ...] = (
    "everything",
    "anything",
    "whatever",
    "all of it",
    "all my stuff",
    "full control",
    "full access",
    "on my behalf",
    "act for me",
    "carte blanche",
    "handle it all",
    "do it all",
)
