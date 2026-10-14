"""Function words shared by the detectors and the engine: name particles, articles, stop words."""

from __future__ import annotations

NAME_PARTICLES = frozenset({"de", "di", "da", "del", "della", "dei", "degli", "dello", "lo", "la", "van", "von"})
ARTICLES = frozenset({"il", "lo", "la", "le", "gli", "i", "un", "una", "uno"})
ARTICULATED_PREPOSITIONS = frozenset({
    "del", "della", "dei", "degli", "delle", "dello", "dal", "dalla", "nel", "nella", "sul", "sulla",
    "al", "alla", "allo", "ai", "agli",
})  # fmt: skip
PREPOSITIONS = frozenset({"a", "da", "di", "in", "con", "per", "tra", "fra", "su"})
CONJUNCTIONS = frozenset({"e", "ed", "o", "&", "and"})
COMPANY_ABBREVIATIONS = frozenset({"srl", "spa", "snc", "sas", "s.r.l.", "s.p.a."})

# Trimmed from the edges of what is left of a span that lost an overlap.
EDGE_WORDS = NAME_PARTICLES | (CONJUNCTIONS - {"o"}) | {"il", "con", "per", "tra", "fra", "a", "al", "alla"}

# Words that cannot be (part of) the surname after a first name.
NOT_SURNAMES = (
    ARTICLES
    | COMPANY_ABBREVIATIONS
    | {"con", "per", "tra", "fra", "che", "del", "della", "dei", "delle", "ha", "è"}
)

# A name chain stops before these ("Avv. Marco Verdi Via Roma").
NAME_TRAILING_STOP = frozenset({
    "via", "viale", "piazza", "corso", "largo", "strada", "tel", "email", "cod", "cf", "piva",
    "spett", "nato", "nata", "residente", "domiciliato", "domiciliata",
})  # fmt: skip

# Capitalised words that are not a surname written before a first name ("Ciao Marco", "Oggi Anna").
NOT_LEADING_SURNAMES = frozenset({
    "ciao", "caro", "cara", "cari", "care", "gentile", "gentili", "gentilissimo", "gentilissima", "egregio",
    "egregia", "gent", "buongiorno", "buonasera", "salve", "grazie", "saluti", "cordiali", "distinti",
    "dear", "hi", "hello", "thanks", "spett", "firmato", "signed", "oggi", "ieri", "domani", "anche",
    "quindi", "poi", "allora", "ma", "però", "se", "quando", "dove", "come", "mentre", "dopo", "prima",
    "ecco", "inoltre", "infatti", "comunque", "sono", "ho", "ha", "hanno", "per", "con", "tra", "fra",
    "and", "with", "from", "to", "for", "by", "san", "santa", "santo", "sant", "villa", "porta",
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
    "ottobre", "novembre", "dicembre", "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato",
    "domenica", "january", "february", "march", "april", "june", "july", "august", "september",
    "october", "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday", "presenti", "assenti", "partecipanti", "relatore", "relatrice", "referente",
    "responsabile", "direttore", "direttrice", "presidente", "consulente", "avvocato", "dottore", "dottoressa",
    "ingegnere", "geometra", "architetto", "cliente", "fornitore", "titolare", "socio", "socia",
    "amministratore", "amministratrice", "collega", "contatto", "nota", "oggetto", "attenzione", "progetto",
    "project", "hotel", "teatro", "cinema", "ristorante", "cantina", "ospedale", "clinica", "chiesa",
    "basilica", "scuola", "liceo", "istituto", "università", "banca", "fondazione", "associazione",
    "premio", "festival", "operazione", "missione", "piano", "programma", "prodotto", "linea", "modello",
    "collezione", "team", "ufficio", "reparto", "settore", "studio", "gruppo", "evento", "corso", "sala",
    "aula", "palazzo", "torre", "ponte", "parco", "giardino", "stazione", "aeroporto", "station", "street",
})  # fmt: skip

# Dropped from the front of a company match ("con Acme S.r.l." -> "Acme S.r.l.").
COMPANY_LEADING_STOP = (
    ARTICLES
    | ARTICULATED_PREPOSITIONS
    | PREPOSITIONS
    | CONJUNCTIONS
    | {
        "de", "presso", "spett.le", "spett.", "egr.", "egregio", "gentile", "ditta", "società", "azienda",
        "cliente", "fornitore", "sede", "contratto", "fattura", "ordine",
    }
)  # fmt: skip

# Parts of mailboxes and URLs that are not names ("info@", "/in/", "github").
HANDLE_STOP_WORDS = frozenset({
    "info", "ufficio", "amministrazione", "acquisti", "segreteria", "contatti", "contact", "mail", "email",
    "pec", "admin", "support", "supporto", "sales", "vendite", "office", "noreply", "posta", "hello",
    "ciao", "commerciale", "fatture", "fatturazione", "ordini", "assistenza", "direzione", "personale",
    "linkedin", "github", "gitlab", "twitter", "facebook", "instagram", "youtube", "profile", "profilo",
    "company", "www", "http", "https", "gmail", "hotmail", "outlook", "yahoo", "libero", "example",
})  # fmt: skip


def alternation(words: frozenset[str]) -> str:
    """Regex alternation of `words`, longest first so "del" is tried before "de"."""
    return "|".join(sorted(words, key=lambda word: (-len(word), word)))
