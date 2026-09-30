from __future__ import annotations

import re

from app.core import settings

EMBED_DIM = 768
GEMINI_PROVIDER = "gemini-embedding-2"
GROQ_PROVIDER = "nomic-embed-text-v1.5"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:batchEmbedContents"
GROQ_URL = "https://api.groq.com/openai/v1/embeddings"
BATCH_SIZE = 64
REQUEST_TIMEOUT = 10
BATCH_TIMEOUT = 60
DEFAULT_COOLDOWN = 60

HEADERS = {"User-Agent": "SgStats/0.1", "Accept": "application/json"}
DATAGOV_LIST_URL = "https://api-production.data.gov.sg/v2/public/api/datasets"
DATAGOV_URL = "https://data.gov.sg/api/action/datastore_search"
DATAGOV_META_URL = "https://api-production.data.gov.sg/v2/public/api/datasets/{}/metadata"
SINGSTAT_SEARCH_URL = "https://tablebuilder.singstat.gov.sg/api/table/resourceid"
SINGSTAT_URL = "https://tablebuilder.singstat.gov.sg/api/table/tabledata"
ROW_LIMIT = 10000
INDEX_PATH = settings.DATA_DIR / "datagov_index.json"
VECTOR_PATH = settings.DATA_DIR / "datagov_vectors.npz"
EMBED_MARGIN = 0.08
INDEX_MAX_AGE = 7 * 24 * 3600
MAX_CANDIDATES = 12
SINGSTAT_PHRASES = 3
SINGSTAT_BONUS = 0.6
INTERNAL_MIN_SCORE = 2
DUPLICATE_OVERLAP = 0.9
FREQUENCY_WORDS = {"annual", "half", "yearly", "quarterly", "monthly", "weekly", "daily", "seasonally", "adjusted"}
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "between", "by", "compare", "current", "data", "did", "do",
    "does", "for", "from", "how", "in", "is", "latest", "many", "much", "now", "of", "on", "over",
    "present", "show", "since", "singapore", "sg", "the", "to", "total", "trend", "trends", "was",
    "were", "what", "which", "who", "with", "year", "years", "analyse", "analyze", "tell", "me",
    "give", "change", "changes", "during", "past", "last", "number", "numbers", "stats",
    "statistics", "today", "until", "vs", "versus", "perform", "performance", "say", "about",
    "has", "have", "had", "been", "changed", "changing", "grown", "grow", "looks", "like", "can",
    "could", "would", "should", "please", "overall", "recent", "recently", "compared",
}
SYNONYMS = {
    "ep": ["employment pass", "foreign workforce"],
    "eps": ["employment pass", "foreign workforce"],
    "spass": ["s pass", "foreign workforce"],
    "wp": ["work permit", "foreign workforce"],
    "foreigners": ["foreign workforce", "non-resident population"],
    "cpi": ["consumer price index"],
    "inflation": ["consumer price index"],
    "gdp": ["gross domestic product"],
    "coe": ["certificate of entitlement"],
    "pr": ["permanent resident"],
    "prs": ["permanent resident"],
    "fertility": ["births and fertility"],
    "tfr": ["fertility rate"],
    "jobless": ["unemployment"],
}

SECTORS = {
    "technology": "Information and Communications",
    "tech": "Information and Communications",
    "ict": "Information and Communications",
    "information and communications": "Information and Communications",
    "finance": "Financial and Insurance Services",
    "financial": "Financial and Insurance Services",
    "manufacturing": "Manufacturing",
}
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
OPEN_ENDED = re.compile(r"\b(current|now|present|today|to date|latest|since|onwards?)\b")
TIME_HINTS = ("year", "month", "quarter", "period", "date", "half")
SKIP_NUMERIC = re.compile(r"(^id$|year|date|postal|block|code|lease_commence)")
MISSING_MARKERS = {"", "na", "n.a.", "n/a", "-", "--", "..", "nil", "null", "none", "s", "x"}
PREFERRED_MEASURES = ("value", "count", "number", "total", "index", "rate", "price", "amount", "percent")
GRAIN_LABELS = {"year": "Year", "half": "Half-year", "quarter": "Quarter", "month": "Month"}
MAX_SERIES = 6
MAX_MEASURES = 2
MAX_PERIODS = 40
MAX_SCALE_RATIO = 50
MIN_OUTLIER_POINTS = 5
OUTLIER_Z = 3.5
MAX_OUTLIERS = 5
MIN_CORRELATION_POINTS = 4
MAX_CORRELATIONS = 5
FALLBACK_YEARS = 5

PERIOD_LABELS = re.compile(
    r"\b(?:19|20)\d{2}(?:\s*[-/ ]?\s*(?:Q[1-4]|H[12])|[-/]\d{2})\b|\b[QH][1-4]\b|\b[1-4][QH]\b", re.I
)
NUMBERS = re.compile(r"(?<![\w.])([+\-\u2010\u2011\u2012\u2013\u2212]?)(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)")
DATA_CUES = re.compile(
    r"\b(analys|compar|correlat|statistic|dataset|employment|unemploy|wage|salary|cpi|inflation|"
    r"gdp|hdb|fertility|birth|housing|price|vacanc|workforce|sector|resident|population)\b",
    re.I,
)
EDIT_CUES = re.compile(
    r"\b(only|just|focus|instead|without|exclude|remove|limit|update|change|narrow|filter|show|compare|between)\b",
    re.I,
)

CROSS_CHECK_DEPTH = 6
MAX_PLAN = 3
GOVERNMENT_PROVIDERS = {"datagov", "singstat"}
MAX_ATTEMPTS = 4
PROVIDER_ORDER = ("gemini", "groq")
INTERRUPTED = "The server restarted before this analysis finished. Run it again."

PINNED = [
    {
        "provider": "datagov",
        "id": "d_7fa083fa9b837ef84c83caaba76601fd",
        "title": "Labour Market Statistics, Quarterly",
        "agency": "Singapore Department of Statistics",
        "snapshot": "snapshots/datagov_labour_market.json",
        "retrieved": "2026-09-26",
    },
    {
        "provider": "datagov",
        "id": "d_293a874aff064ea9408f31c4da9dd4bb",
        "title": "Employed Residents by Industry",
        "agency": "Ministry of Manpower",
        "snapshot": "snapshots/datagov_employed_residents.csv",
        "retrieved": "2026-09-26",
    },
    {
        "provider": "singstat",
        "id": "M015721",
        "title": "Gross Domestic Product At Current Prices, By Industry",
        "agency": "Singapore Department of Statistics",
        "snapshot": "snapshots/singstat_gdp_by_industry.json",
        "retrieved": "2026-09-26",
    },
]

INTERNAL = [
    {
        "provider": "internal",
        "id": "int_sector_hiring",
        "title": "Sector Hiring Programme Placements and Vacancies (mock internal database)",
        "agency": "Internal research database (mock)",
        "file": "internal/sector_hiring.xlsx",
        "keywords": "employment jobs hiring vacancies placements workforce technology ict finance manufacturing",
        "coverage_start": 2019,
        "coverage_end": 2025,
    },
]
