"""Filtering and resume-matching logic. Pure functions, no network."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(value: str | None) -> str:
    """HTML (possibly double-escaped, as Greenhouse sends it) -> plain text."""
    if not value:
        return ""
    text = html.unescape(html.unescape(value))
    text = re.sub(r"(?i)<\s*(br|/p|/li|/div|/h\d)\s*/?>", "\n", text)
    text = _TAG_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


# ---------------------------------------------------------------------------
# Title filters
# ---------------------------------------------------------------------------
def compile_patterns(patterns: list[str]) -> list[re.Pattern]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def title_ok(title: str, include: list[re.Pattern], exclude: list[re.Pattern]) -> bool:
    if not title:
        return False
    if not any(p.search(title) for p in include):
        return False
    return not any(p.search(title) for p in exclude)


def company_excluded(company: str, excluded: list[str]) -> bool:
    c = (company or "").lower()
    return any(re.search(rf"\b{re.escape(e.lower())}\b", c) for e in excluded)


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------
US_STATES = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california",
    "CO": "colorado", "CT": "connecticut", "DE": "delaware", "FL": "florida", "GA": "georgia",
    "HI": "hawaii", "ID": "idaho", "IL": "illinois", "IN": "indiana", "IA": "iowa",
    "KS": "kansas", "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland",
    "MA": "massachusetts", "MI": "michigan", "MN": "minnesota", "MS": "mississippi",
    "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada", "NH": "new hampshire",
    "NJ": "new jersey", "NM": "new mexico", "NY": "new york", "NC": "north carolina",
    "ND": "north dakota", "OH": "ohio", "OK": "oklahoma", "OR": "oregon", "PA": "pennsylvania",
    "RI": "rhode island", "SC": "south carolina", "SD": "south dakota", "TN": "tennessee",
    "TX": "texas", "UT": "utah", "VT": "vermont", "VA": "virginia", "WA": "washington",
    "WV": "west virginia", "WI": "wisconsin", "WY": "wyoming", "DC": "district of columbia",
}
US_CITIES = [
    "new york", "nyc", "san francisco", "bay area", "seattle", "boston", "chicago", "austin",
    "los angeles", "denver", "atlanta", "dallas", "houston", "san jose", "palo alto",
    "mountain view", "sunnyvale", "menlo park", "redwood city", "san mateo", "san diego",
    "washington, d.c", "washington dc", "philadelphia", "pittsburgh", "miami", "raleigh",
    "charlotte", "phoenix", "salt lake", "minneapolis", "detroit", "nashville", "portland",
    "brooklyn", "manhattan", "cambridge, ma", "plano", "irving", "frisco", "mclean", "reston",
    "arlington, va", "bellevue", "kirkland", "santa clara", "oakland", "berkeley", "columbus",
    "st. louis", "kansas city", "baltimore", "richmond", "tampa", "orlando", "jersey city",
]
NON_US = [
    "india", "bangalore", "bengaluru", "hyderabad", "pune", "chennai", "mumbai", "gurgaon",
    "gurugram", "noida", "delhi", "canada", "toronto", "vancouver", "montreal", "ontario",
    "united kingdom", "london", "england", "uk", "ireland", "dublin", "germany", "berlin",
    "munich", "france", "paris", "spain", "madrid", "barcelona", "portugal", "lisbon",
    "netherlands", "amsterdam", "poland", "warsaw", "krakow", "romania", "ukraine", "israel",
    "tel aviv", "singapore", "australia", "sydney", "melbourne", "japan", "tokyo", "china",
    "beijing", "shanghai", "hong kong", "taiwan", "korea", "seoul", "brazil", "são paulo",
    "sao paulo", "mexico", "argentina", "colombia", "chile", "philippines", "vietnam",
    "indonesia", "malaysia", "south africa", "nigeria", "kenya", "egypt", "uae", "dubai",
    "saudi", "switzerland", "zurich", "sweden", "stockholm", "denmark", "copenhagen", "norway",
    "finland", "italy", "milan", "belgium", "austria", "vienna", "czech", "prague", "emea",
    "apac", "latam", "europe",
]
_STATE_CODE_RE = re.compile(r"(?:,|\s)\s?(" + "|".join(US_STATES) + r")\b")
_US_RE = re.compile(r"\b(united states|u\.s\.a?\.?|usa|us)\b", re.IGNORECASE)


def is_us_location(location: str, country: str | None = None, extra_places: list[str] | None = None) -> bool:
    """Best-effort: True if the posting looks US-based or US-remote."""
    if country:
        c = country.strip().lower()
        if c in {"us", "usa", "united states", "united states of america"}:
            return True
        if len(c) == 2 or c in NON_US:
            return False
    loc = (location or "").strip()
    if not loc:
        return False
    low = loc.lower()
    if _US_RE.search(loc):
        return True
    for st in US_STATES.values():
        # "Washington" alone is ambiguous (state vs D.C.); both are US, so either is fine.
        if re.search(rf"\b{st}\b", low):
            return True
    places = US_CITIES + [p.lower() for p in (extra_places or [])]
    if any(re.search(rf"\b{re.escape(p)}\b", low) for p in places):
        return True
    # Check foreign places before 2-letter state codes ("Berlin, DE" is not Delaware).
    if any(re.search(rf"\b{re.escape(n)}\b", low) for n in NON_US):
        return False
    if _STATE_CODE_RE.search(loc):
        return True
    # Plain "Remote" / "Anywhere" with no country: keep (description check is next).
    return bool(re.search(r"\b(remote|anywhere|distributed)\b", low))


# ---------------------------------------------------------------------------
# Disqualifiers (citizenship / clearance / no sponsorship)
# ---------------------------------------------------------------------------
_DISQUALIFIERS = [
    ("US citizens only", r"\bu\.?s\.? citizens?(hip)?\s+(is\s+)?(required|only)\b"),
    ("US citizens only", r"must be (a )?u\.?s\.? citizen"),
    ("US citizens only", r"requires? u\.?s\.? citizenship"),
    ("US citizens only", r"(only|solely) (open|available) to u\.?s\.? citizens"),
    ("Green card / citizens only", r"(u\.?s\.? citizens?|citizenship) or (lawful )?(permanent residents?|green card)"),
    ("Green card / citizens only", r"green card holders? (only|required)"),
    ("US person (export control)", r"\bu\.?s\.? persons?\b"),
    ("Security clearance", r"(security|secret|top secret|ts/sci|public trust) clearance"),
    ("Security clearance", r"\bts/sci\b|\bpolygraph\b|active clearance|clearance (is )?required|obtain (and maintain )?a (u\.?s\.? )?(government )?(security )?clearance"),
    ("No sponsorship", r"(not|unable to|cannot|can't|won't|will not|does not|do not) (provide |offer |pursue |be able to )?(visa |immigration |employment )?sponsor"),
    ("No sponsorship", r"no (visa |immigration |employment )?sponsorship"),
    ("No sponsorship", r"without (the need for |requiring )?(current or future |now or in the future )?(visa |employment |immigration )?sponsorship"),
    ("No sponsorship", r"not eligible for (current or future |any )?(visa |immigration |employment )?sponsorship"),
    ("No sponsorship", r"sponsorship (is |will )?(not|n't) (be )?(available|offered|provided|considered)"),
    ("No sponsorship", r"not (in a position|able) to sponsor"),
    ("No sponsorship", r"(do not|don't|will not|won't) (anticipate|expect) (providing |offering )?(visa )?sponsorship"),
]
_DISQ_RE = [(label, re.compile(p, re.IGNORECASE)) for label, p in _DISQUALIFIERS]


def disqualifiers(text: str) -> list[str]:
    """Return human-readable reasons this posting excludes you (empty = fine)."""
    found: list[str] = []
    for label, rx in _DISQ_RE:
        m = rx.search(text or "")
        if not m:
            continue
        # Skip EEO boilerplate like "...without regard to ... citizenship status".
        window = text[max(0, m.start() - 120): m.end() + 40].lower()
        if "without regard to" in window or "regardless of" in window or "equal opportunity" in window:
            continue
        if label not in found:
            found.append(label)
    return found


# ---------------------------------------------------------------------------
# Years of experience
# ---------------------------------------------------------------------------
_YEARS_RE = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:-|–|to)?\s*(\d{1,2})?\s*\+?\s*(?:years?|yrs?)\b(?:\s+of)?"
    r"(?=[^.;\n]{0,60}\b(experience|professional|industry|hands-on|engineering|software|"
    r"development|building|working|relevant|production|ml|ai|machine learning)\b)",
    re.IGNORECASE,
)


def years_required(text: str) -> int | None:
    """Largest minimum-years requirement mentioned (e.g. '5+ years' -> 5)."""
    mins: list[int] = []
    for m in _YEARS_RE.finditer(text or ""):
        lo = int(m.group(1))
        ctx = text[max(0, m.start() - 40): m.start()].lower()
        if "founded" in ctx or "history" in ctx or "over" in ctx and "company" in ctx:
            continue
        if 0 < lo <= 20:
            mins.append(lo)
    return max(mins) if mins else None


# ---------------------------------------------------------------------------
# Keyword resume match
# ---------------------------------------------------------------------------
# Each concept -> regex. A JD "asks for" a concept if the regex hits the JD;
# you "have" it if it hits your resume (or your confirmed extra skills).
SKILLS: dict[str, str] = {
    "python": r"\bpython\b",
    "sql": r"\bsql\b",
    "llm": r"\bllms?\b|large language model",
    "genai": r"generative ai|\bgenai\b|gen ai",
    "rag": r"\brag\b|retrieval[- ]augmented",
    "agents": r"\bagent(s|ic)?\b|multi-agent",
    "langchain": r"langchain",
    "langgraph": r"langgraph",
    "llamaindex": r"llama ?index",
    "prompt engineering": r"prompt (engineering|design)",
    "tool calling": r"tool[- ]calling|function[- ]calling|tool use",
    "vector db": r"vector (database|db|store|search)|pinecone|faiss|weaviate|qdrant|milvus|pgvector|chroma",
    "embeddings": r"\bembeddings?\b",
    "evals": r"\bevals?\b|evaluation (framework|harness|suite)|llm evaluation|model evaluation",
    "guardrails": r"guardrails?",
    "hitl": r"human[- ]in[- ]the[- ]loop",
    "fine-tuning": r"fine[- ]?tun(e|ing)|\blora\b|\bpeft\b|\brlhf\b",
    "pytorch": r"pytorch",
    "tensorflow": r"tensorflow|keras",
    "scikit-learn": r"scikit|sklearn",
    "xgboost": r"xgboost|lightgbm|gradient boost",
    "nlp": r"\bnlp\b|natural language processing",
    "feature engineering": r"feature engineering",
    "mlops": r"\bmlops\b|\bllmops\b",
    "mlflow": r"mlflow",
    "monitoring": r"\bmonitoring\b|observability",
    "drift": r"\bdrift\b",
    "spark": r"\bspark\b|pyspark",
    "kafka": r"\bkafka\b",
    "airflow": r"\bairflow\b",
    "databricks": r"databricks",
    "snowflake": r"snowflake",
    "redshift": r"redshift",
    "etl": r"\betl\b|\belt\b|data pipelines?",
    "pandas": r"\bpandas\b",
    "fastapi": r"fastapi",
    "flask": r"\bflask\b",
    "rest api": r"\brest(ful)?\b|\bapis?\b",
    "microservices": r"microservices?",
    "docker": r"\bdocker\b|container",
    "kubernetes": r"kubernetes|\bk8s\b|\beks\b|\baks\b|\bgke\b",
    "ci/cd": r"ci/cd|\bcicd\b|continuous (integration|delivery|deployment)|github actions|jenkins",
    "git": r"\bgit\b|github|gitlab",
    "aws": r"\baws\b|amazon web services",
    "bedrock": r"bedrock",
    "azure": r"\bazure\b",
    "gcp": r"\bgcp\b|google cloud|vertex",
    "openai": r"openai|gpt-?\d",
    "anthropic": r"anthropic|claude",
    "hugging face": r"hugging ?face|transformers library",
    "postgres": r"postgres",
    "nosql": r"nosql|mongodb|dynamodb|cassandra",
    "typescript": r"typescript|\bnode(\.js)?\b",
    "javascript": r"javascript",
    "react": r"\breact\b|next\.js",
    "java": r"\bjava\b",
    "go": r"\bgolang\b|\bgo\b(?=,| and| or)",
    "c++": r"c\+\+",
    "scala": r"\bscala\b",
    "computer vision": r"computer vision|opencv|object detection",
    "terraform": r"terraform|infrastructure as code",
    "mcp": r"\bmcp\b|model context protocol",
    "fraud/risk": r"\bfraud\b|risk model|credit risk|anomaly detection",
    "recommendation": r"recommendation|recommender|personaliz",
    "search": r"semantic search|hybrid search|information retrieval|ranking",
    "agile": r"\bagile\b|scrum",
    "healthcare": r"healthcare|clinical|patient",
    "fintech": r"financial services|fintech|banking",
}
_SKILL_RE = {k: re.compile(v, re.IGNORECASE) for k, v in SKILLS.items()}

# Concepts that matter more when an AI-engineering JD asks for them.
CORE = {"python", "llm", "genai", "rag", "agents", "langchain", "langgraph", "vector db",
        "evals", "aws", "sql", "pytorch", "mlops", "fastapi", "docker", "ci/cd"}


@dataclass
class ResumeProfile:
    have: set[str] = field(default_factory=set)

    @classmethod
    def from_text(cls, resume_text: str, extra_skills: list[str] | None = None) -> "ResumeProfile":
        have = {k for k, rx in _SKILL_RE.items() if rx.search(resume_text)}
        for s in extra_skills or []:
            s = s.lower().strip()
            for k, rx in _SKILL_RE.items():
                if rx.search(s) or k == s:
                    have.add(k)
        return cls(have=have)


def keyword_match(jd_text: str, profile: ResumeProfile) -> tuple[int, list[str], list[str]]:
    """Return (score 0-100, matched concepts, missing concepts)."""
    asked = [k for k, rx in _SKILL_RE.items() if rx.search(jd_text or "")]
    if not asked:
        return 0, [], []
    weight = lambda k: 2.0 if k in CORE else 1.0  # noqa: E731
    total = sum(weight(k) for k in asked)
    got = [k for k in asked if k in profile.have]
    miss = [k for k in asked if k not in profile.have]
    raw = sum(weight(k) for k in got) / total
    # JDs that mention very few concepts give noisy scores; pull them toward 50.
    confidence = min(1.0, len(asked) / 10)
    score = round(100 * (raw * confidence + 0.5 * (1 - confidence)))
    # Keyword overlap can't see seniority or depth, so cap below a perfect score.
    return max(0, min(95, score)), got, miss


# ---------------------------------------------------------------------------
# AI intensity: lets generic titles ("Software Engineer", "Data Engineer") through
# when the job description is clearly AI/ML work.
# ---------------------------------------------------------------------------
AI_CONCEPTS = ["llm", "genai", "rag", "agents", "langchain", "langgraph", "llamaindex", "vector db",
               "embeddings", "evals", "fine-tuning", "pytorch", "tensorflow", "mlops", "mlflow",
               "prompt engineering", "tool calling", "nlp", "hugging face", "openai", "anthropic", "bedrock"]
_ML_RE = re.compile(r"machine learning|\bml\b|artificial intelligence|\bai\b", re.IGNORECASE)


def ai_intensity(text: str) -> int:
    """How many distinct AI/ML concepts the JD mentions (0 = none)."""
    n = sum(1 for k in AI_CONCEPTS if _SKILL_RE[k].search(text or ""))
    if len(_ML_RE.findall(text or "")) >= 4:
        n += 1
    return n
