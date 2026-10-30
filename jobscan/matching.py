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
    # more countries / cities seen in remote and multi-region postings
    "latin america", "south america", "central america", "costa rica", "guatemala", "peru", "lima",
    "bogota", "bogotá", "medellin", "buenos aires", "santiago", "montevideo", "uruguay", "mexico city",
    "guadalajara", "monterrey", "pakistan", "lahore", "karachi", "bangladesh", "dhaka", "sri lanka",
    "nepal", "estonia", "tallinn", "lithuania", "vilnius", "latvia", "riga", "greece", "athens",
    "turkey", "türkiye", "istanbul", "serbia", "belgrade", "croatia", "zagreb", "bulgaria", "sofia",
    "hungary", "budapest", "slovakia", "slovenia", "cyprus", "malta", "luxembourg", "iceland",
    "kyiv", "kiev", "lviv", "hamburg", "frankfurt", "cologne", "stuttgart", "rotterdam", "eindhoven",
    "edinburgh", "glasgow", "manchester", "belfast", "cork", "galway", "bristol", "oxford, uk",
    "thailand", "bangkok", "new zealand", "auckland", "wellington, nz", "jakarta", "kuala lumpur",
    "ho chi minh", "hanoi", "da nang", "taipei", "shenzhen", "hangzhou", "guangzhou", "osaka",
    "british columbia", "quebec", "québec", "alberta", "calgary", "edmonton", "ottawa", "waterloo, on",
    "victoria, bc", "lagos", "cairo", "nairobi", "accra", "morocco", "tunisia", "qatar", "doha",
    "abu dhabi", "riyadh", "bahrain", "oman", "jordan", "amman", "lebanon", "beirut", "armenia",
    "yerevan", "georgia (country)", "münchen", "köln", "düsseldorf", "nürnberg", "hannover",
    "mannheim", "leipzig", "dresden", "deutschland", "österreich", "wien", "schweiz", "zürich", "standort",
    "standorte", "bundesweit", "remote - europe", "eu remote", "tbilisi", "kazakhstan", "almaty", "uzbekistan", "worldwide (non-us)",
]
_STATE_CODE_RE = re.compile(r"(?:,|\s)\s?(" + "|".join(US_STATES) + r")\b")
_US_RE = re.compile(r"\b(united states|u\.s\.a?\.?|usa)\b", re.IGNORECASE)
_US_CODE_RE = re.compile(r"(?<![A-Za-z])(US|USA|U\.S\.)(?![A-Za-z])")  # "US" in caps only, not the word "us"
_GLOBAL_RE = re.compile(r"\b(global|worldwide|international|anywhere in the world|multiple countries)\b", re.IGNORECASE)


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
    if _US_RE.search(loc) or _US_CODE_RE.search(loc):
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
    # "Global Remote", "Worldwide", "International": not US-specific, so don't keep on location alone.
    if _GLOBAL_RE.search(low):
        return False
    # Plain "Remote" / "Anywhere" with no country: keep for now; the job description is
    # checked later with description_location_ok().
    return bool(re.search(r"\b(remote|anywhere|distributed)\b", low))


# Phrases in a job description that say the job is outside the US (for vague "Remote" postings).
_NON_US_JD = [
    r"remote\s*(\(|-|–|,|in|within|from)?\s*(canada|the uk|uk|united kingdom|europe|emea|latam|latin america|india|mexico|brazil|apac|asia|australia|germany|poland|spain|portugal|philippines)",
    r"(based|located|living|reside|residing) in (canada|the uk|united kingdom|europe|the eu|emea|latam|latin america|india|mexico|brazil|the philippines|australia|germany|poland|spain|portugal|singapore|japan|israel|vietnam|malaysia)",
    r"(must|need to|required to) (be|have) (legally )?(eligible|authori[sz]ed) to work in (canada|the uk|united kingdom|the eu|europe|india|mexico|brazil|australia|germany|singapore)",
    r"right to work in (the uk|united kingdom|canada|the eu|australia|ireland)",
    r"(salary|compensation|pay)[^.\n]{0,40}\b(cad|gbp|eur|inr|aud|sgd|mxn|brl|€|£|₹)",
    r"\b(cad|gbp|eur|inr|aud|sgd)\s?\d", r"[€£₹]\s?\d",
    r"fluent in (spanish|german|french|portuguese|mandarin|japanese|korean|italian|dutch|polish)",
    r"(cet|cest|gmt|bst|ist|aest|sgt)\s*(time ?zone|working hours|hours)",
    r"only applicants living in (british columbia|ontario|canada|the uk)",
]
_NON_US_JD_RE = [re.compile(p, re.IGNORECASE) for p in _NON_US_JD]
_US_WORDS_RE = re.compile(r"united states|\bu\.s\.(?:-based)?|\bus[- ]based\b|\busa\b|remote\s*(\(|-|–|,|in|within)?\s*(the )?(us|u\.s\.|united states)\b", re.IGNORECASE)
_USD_RE = re.compile(r"\$\s?\d{2,3}(,\d{3}|k)(?![^.\n]{0,15}\b(cad|aud|nzd|sgd|mxn)\b)", re.IGNORECASE)
_US_JD_RE = re.compile(r"united states|\bu\.s\.(?:-based)?|\bus[- ]based\b|\busa\b|remote\s*(\(|-|–|,|in|within)?\s*(the )?(us|u\.s\.|united states)\b|\$\s?\d{2,3}[,k]", re.IGNORECASE)


def description_location_ok(location: str, description: str) -> bool:
    """For vague locations ("Remote", "Anywhere", blank), read the JD for where the job really is.

    Keeps the job if the JD points to the US (US mention or $ salary) or says nothing either way;
    drops it when the JD says the role is in another country (Canada, UK, EU, India, ...).
    """
    low_loc = (location or "").lower()
    has_specific_us = any(st in low_loc for st in US_STATES.values()) or any(c in low_loc for c in US_CITIES) \
        or bool(_STATE_CODE_RE.search(location or "")) or bool(_US_CODE_RE.search(location or "")) \
        or bool(_US_RE.search(location or ""))
    if has_specific_us:
        return True
    text = description or ""
    strong = any(rx.search(text) for rx in _NON_US_JD_RE[:4] + _NON_US_JD_RE[-1:])
    weak = any(rx.search(text) for rx in _NON_US_JD_RE[4:-1])
    explicit_us = bool(_US_WORDS_RE.search(text))
    dollars = bool(_USD_RE.search(text))
    if strong and not explicit_us:
        return False  # "based in Canada", "only applicants living in BC", "right to work in the UK"
    if weak and not (explicit_us or dollars):
        return False  # CAD/GBP/EUR pay, CET hours, other-language fluency, with nothing pointing to the US
    return True


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
    # wider phrasing: "cannot offer any form of visa sponsorship", "unable to provide employment visa sponsorship"
    ("No sponsorship", r"\b(not|unable to|cannot|can't|won't|will not|does not|do not|isn't|is not)\b[^.\n]{0,45}\b(visa|immigration|employment|work) ?sponsor"),
    ("No sponsorship", r"\b(not|unable to|cannot|can't|won't|will not|does not|do not)\b (offer|provide|support|consider)[^.\n]{0,30}\bsponsorship"),
    ("No sponsorship", r"(visa|immigration) sponsorship[^.\n]{0,30}\b(not|unavailable|n't)\b"),
    ("No sponsorship", r"not eligible for[^.\n]{0,30}sponsorship"),
    ("Permanent work authorization only", r"authori[sz]ed to work in the (united states|u\.?s\.?) on a permanent basis"),
    ("Permanent work authorization only", r"permanent (u\.?s\.? )?work authori[sz]ation"),
    ("Federal agency work (citizenship / background check)", r"\b(dhs|cbp|dod|department of (defense|homeland security)|homeland security|customs and border|federal stakeholders|federal (government )?environment|public trust)\b"),
    ("Export control", r"export[- ]control(s|led)?\b|\bitar\b|\bear(s)? (regulations|controlled)|export licen[cs]e"),
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


_WORD_NUMS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
              "ten": 10, "twelve": 12, "fifteen": 15}
_WORD_YEARS_RE = re.compile(r"\b(" + "|".join(_WORD_NUMS) + r")\s*(\(\d+\)\s*)?(\+|or more|plus)?\s*years",
                            re.IGNORECASE)


def years_required(text: str) -> int | None:
    """Largest minimum-years requirement mentioned (e.g. '5+ years' -> 5, 'Eight or more years' -> 8)."""
    mins: list[int] = []
    for m in _WORD_YEARS_RE.finditer(text or ""):
        mins.append(_WORD_NUMS[m.group(1).lower()])
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
    "rag": r"\brag\b|retrieval[- ]augmented|\bretrieval\b|semantic search",
    "agents": r"\bagent(s|ic)?\b|multi-agent|agent orchestration",
    "langchain": r"langchain",
    "langgraph": r"langgraph",
    "llamaindex": r"llama ?index",
    "prompt engineering": r"prompt (engineering|design)|context engineering|prompts and instructions",
    "tool calling": r"tool[- ]calling|function[- ]calling|tool use",
    "vector db": r"vector (database|db|store|search)|pinecone|faiss|weaviate|qdrant|milvus|pgvector|chroma",
    "embeddings": r"\bembeddings?\b",
    "evals": r"\bevals?\b|evaluations?\b|evaluation (framework|harness|suite)|llm evaluation|model evaluation",
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


# ---------------------------------------------------------------------------
# Intern / student / new-grad roles (titles slip through; the JD gives it away)
# ---------------------------------------------------------------------------
_STUDENT_TITLE_RE = re.compile(
    r"\bintern(ship)?s?\b|\bco-?op\b|\bnew[- ]?grad|\bgraduate\b|\bgrad\b|\b20\d\d\s*(start|graduate|grad)\b|"
    r"\bstudent\b|early[- ]career|entry[- ]level|\bapprentice|\bresiden(t|cy)\b|\bfellow(ship)?\b|\bsummer\b|"
    r"\bcampus\b|\buniversity grad", re.IGNORECASE)
_STUDENT_JD_RE = re.compile(
    r"(currently|actively) (enrolled|pursuing)|must be (a )?(currently )?enrolled|pursuing an? (bachelor|master|ph\.?d|degree)|"
    r"(expected|anticipated) graduation|graduating (in|between|by) (spring|summer|fall|winter|20\d\d)|"
    r"recent(ly)? (graduate|completed)|this internship|the internship|co-?op (program|term|assignment)|"
    r"(0|zero)\s*[-–to]+\s*[12]\s*years|no (prior )?(professional )?experience (is )?required|"
    r"commit to an onboarding date", re.IGNORECASE)


def student_role(title: str, description: str) -> bool:
    """True for internships, co-ops, new-grad / early-career programs."""
    if _STUDENT_TITLE_RE.search(title or ""):
        return True
    return bool(_STUDENT_JD_RE.search(description or ""))


# ---------------------------------------------------------------------------
# Off-target domains: jobs that mention AI but whose core requirements are something
# else (networking, security, frontend, infrastructure, hardware, computer vision, Java).
# A domain counts when the JD names several of its specific skills.
# ---------------------------------------------------------------------------
OFF_DOMAINS: dict[str, tuple[int, list[str]]] = {
    "networking": (2, [r"\bbgp\b", r"\bospf\b", r"\bevpn\b", r"\bvxlan\b", r"spine[- ]leaf", r"\bsonic\b",
                       r"linux network stack", r"\bgnmi\b", r"\bnetconf\b", r"\bsnmp\b", r"\brdma\b", r"\bdpdk\b",
                       r"subnetting", r"\bvlans?\b", r"\bipmi\b", r"\bpxe\b"]),
    "security engineering": (3, [r"\bowasp\b", r"\bsast\b", r"\bdast\b", r"\bsca\b", r"penetration test", r"threat model",
                                 r"\bsiem\b", r"\bcspm\b", r"\bciem\b", r"\bsspm\b", r"vulnerability management",
                                 r"incident response", r"\bsoc ?2\b", r"iso ?27001", r"\bcissp\b", r"\boscp\b", r"malware"]),
    "frontend / full-stack": (3, [r"\breact\b", r"\bangular\b", r"\bvue(\.js)?\b", r"\bsvelte\b", r"next\.js", r"\bremix\b",
                                   r"react native", r"\bhtml5?\b", r"\bcss3?\b", r"wordpress", r"\bshopify\b", r"\bblazor\b",
                                   r"frontend framework", r"front[- ]end (framework|development)",
                                   r"\btypescript\b", r"node\.?js", r"web uis?\b", r"design taste", r"\bhtmx\b",
                                   r"alpine\.js", r"tailwind", r"\bdjango\b"]),
    "infrastructure / DevOps": (3, [r"terraform", r"\bbicep\b", r"arm templates", r"\bansible\b", r"\bchef\b", r"\bpuppet\b",
                                     r"control tower", r"aws organizations", r"service control polic", r"\bguardduty\b",
                                     r"pagerduty", r"systems administration", r"patch management", r"\bfinops\b"]),
    "hardware / model compression": (2, [r"quantization", r"\bpruning\b", r"\bonnx\b", r"\bfpga\b", r"\basic\b", r"\bcuda\b",
                                          r"\btriton\b", r"\bvllm\b", r"analog (computing|hardware)", r"hardware bring-?up"]),
    "computer vision / generative media": (2, [r"computer vision", r"\bdiffusion\b", r"image generation", r"video generation",
                                                r"visual generation", r"\bcvpr\b", r"\biccv\b", r"\beccv\b", r"object detection"]),
    "Java / Spring": (2, [r"\bj2ee\b", r"spring boot", r"\bjunit\b", r"\bspock\b", r"\bmaven\b", r"\bquarkus\b"]),
    "Microsoft low-code / BI": (2, [r"copilot studio", r"power automate", r"power apps", r"power platform", r"dataverse",
                                     r"power bi", r"microsoft fabric", r"\bdax\b", r"azure ai foundry", r"entra id", r"\bpurview\b"]),
    "database administration": (3, [r"sql server", r"stored procedures?", r"powershell", r"backup and (recovery|restore)",
                                     r"\bha/dr\b", r"\bdba\b", r"database administrat", r"sort keys", r"workload management",
                                     r"deadlocks?", r"\bcoldfusion\b", r"index (and statistics )?maintenance"]),
    "data platform architecture": (3, [r"collibra", r"alation", r"\batlan\b", r"unity catalog", r"datahub", r"data[- ]vault",
                                        r"data mesh", r"architecture reviews", r"decision records", r"target[- ]state architecture",
                                        r"architecture roles"]),
    "voice / telephony": (3, [r"\bvapi\b", r"retell", r"\bbland\b", r"synthflow", r"twilio", r"telnyx", r"\bsip\b", r"\bvoip\b",
                              r"\ba2p\b", r"10dlc", r"stir/shaken", r"\bcnam\b", r"\btcpa\b", r"gohighlevel", r"deepgram",
                              r"elevenlabs", r"telephony"]),
    "adversarial AI security": (2, [r"adversarial", r"red team", r"data poisoning", r"model (extraction|inversion)",
                                    r"\bnist\b", r"800-53", r"ai rmf", r"vulnerability assessment", r"\bot&e\b"]),
    "cloud infrastructure": (3, [r"\bvpc\b", r"security groups", r"cloudformation", r"bitbucket pipelines", r"least[- ]privilege",
                                 r"secrets management", r"\bec2\b", r"access reviews", r"infrastructure as code"]),
    "sales / marketing growth": (3, [r"salesforce", r"hubspot", r"\bcrm\b", r"outbound", r"lead scoring", r"deliverability",
                                     r"cost per (lead|acquisition)", r"go-to-market", r"\bgtm\b", r"sequencing tools",
                                     r"product marketing", r"win/loss", r"\bseo\b", r"generative engine optimization",
                                     r"semrush", r"ahrefs", r"brightedge", r"search console", r"share of voice",
                                     r"content strategy", r"digital marketing", r"web analytics"]),
    "multimodal / vision": (2, [r"\bopencv\b", r"multimodal", r"screenshots", r"gameplay video", r"image (recognition|classification)"]),
}
_OFF_RE = {d: (n, [re.compile(p, re.IGNORECASE) for p in pats]) for d, (n, pats) in OFF_DOMAINS.items()}


def off_domains(text: str, profile: "ResumeProfile | None" = None) -> list[str]:
    """Domains this JD leans on heavily that aren't on the resume."""
    hits = []
    for d, (need, pats) in _OFF_RE.items():
        n = sum(1 for rx in pats if rx.search(text or ""))
        if n >= need:
            hits.append(d)
    return hits


# ---------------------------------------------------------------------------
# Duplicates: same role posted in several cities, or by sister companies (TikTok/ByteDance)
# ---------------------------------------------------------------------------
COMPANY_FAMILIES = {"tiktok": "bytedance", "bytedance": "bytedance", "lark": "bytedance",
                    "capcut": "bytedance", "lemon8": "bytedance"}


def dedupe_key(company: str, title: str) -> str:
    c = re.sub(r"[^a-z0-9 ]", " ", (company or "").lower())
    c = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|company|technologies|technology|labs)\b", " ", c).strip()
    c = c.split()[0] if c.split() else c
    c = COMPANY_FAMILIES.get(c, c)
    t = (title or "").lower()
    # drop trailing location / team qualifiers like " - San Jose", " (Remote)", " - USDS"
    parts = re.split(r"\s+[-–|]\s+", t)
    kept = [parts[0]] + [x for x in parts[1:] if not (
        any(re.search(rf"\b{re.escape(cty)}\b", x) for cty in US_CITIES) or
        any(re.search(rf"\b{st}\b", x) for st in US_STATES.values()) or
        re.search(r"\b(remote|hybrid|onsite|on-site|us|usa|united states|usds)\b", x))]
    t = " ".join(kept)
    t = re.sub(r"\((remote|hybrid|on-?site|us|usa)\)", " ", t)
    t = re.sub(r"[^a-z0-9/+ ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return f"{c}|{t}"


# ---------------------------------------------------------------------------
# Language: postings written in another language, or that need one
# ---------------------------------------------------------------------------
_GENDER_TAG_RE = re.compile(r"\((m/w/d|w/m/d|w/m/x|m/w/x|f/m/d|m/f/d|h/f|f/h|m/f/x|w/m/div)\)", re.IGNORECASE)
_FOREIGN_WORDS = {
    "german": r"\b(und|wir|du|dein|deine|ihr|sie|mit|für|bei|als|oder|eine|einer|unsere|unser|erfahrung|kenntnisse|"
              r"aufgaben|bewerbung|standort|jahre|sowie|über|deutsch)\b",
    "french": r"\b(nous|vous|avec|pour|dans|votre|notre|expérience|poste|compétences|une|des|les)\b",
    "spanish": r"\b(nosotros|con|para|experiencia|puesto|requisitos|empresa|una|los|las|del)\b",
    "portuguese": r"\b(você|voce|com|para|experiência|vaga|requisitos|empresa|uma|dos|das)\b",
}
_FOREIGN_RE = {k: re.compile(v, re.IGNORECASE) for k, v in _FOREIGN_WORDS.items()}
_ENGLISH_RE = re.compile(r"\b(the|and|with|you|will|our|for|experience|to|of)\b", re.IGNORECASE)
_NON_LATIN_RE = re.compile(r"[\u0400-\u04FF\u0590-\u05FF\u0600-\u06FF\u3040-\u30FF\u4E00-\u9FFF\uAC00-\uD7AF]")
_LANG_REQ_RE = re.compile(
    r"(german|deutsch|french|spanish|portuguese|russian|ukrainian|polish|italian|dutch|japanese|korean|mandarin|chinese|"
    r"cantonese|arabic|hebrew|turkish|vietnamese)[^.\n]{0,40}\b(c1|c2|b2|fluent|fluency|native|proficien|required|must)"
    r"|\b(c1|c2|b2|fluent|fluency|native|proficien\w*)\b[^.\n]{0,25}\b(german|deutsch|french|spanish|portuguese|russian|"
    r"ukrainian|polish|italian|dutch|japanese|korean|mandarin|chinese|cantonese|arabic|hebrew|turkish|vietnamese)"
    r"|interviews?[^.\n]{0,40}\bin (both )?(german|french|spanish|portuguese|russian|japanese|korean|mandarin|chinese)"
    r"|both in (russian|german|french|spanish|portuguese|japanese|korean|mandarin|chinese)",
    re.IGNORECASE)


def language_problem(title: str, description: str) -> str:
    """Reason string if the posting is not in English or needs a non-English language, else ''."""
    t = f"{title or ''} {description or ''}"
    if _GENDER_TAG_RE.search(t):
        return "German/European posting (m/w/d)"
    if _NON_LATIN_RE.findall(t) and len(_NON_LATIN_RE.findall(t)) > 30:
        return "posting not in English"
    words = max(1, len(re.findall(r"[A-Za-zÀ-ÿ]+", t)))
    english = len(_ENGLISH_RE.findall(t))
    for lang, rx in _FOREIGN_RE.items():
        n = len(rx.findall(t))
        if words >= 40 and n > english and n / words > 0.06:
            return f"posting written in {lang.title()}"
    m = _LANG_REQ_RE.search(t)
    if m:
        return "needs another language (" + m.group(0).strip()[:40] + ")"
    return ""


# ---------------------------------------------------------------------------
# Employment type: freelance, part-time, 1099, outsourcing
# ---------------------------------------------------------------------------
_EMPLOYMENT_RE = re.compile(
    r"\bfreelance\b|independent contractor|\b1099\b|\bpart[- ]time\b|hours (of work )?per month|"
    r"business process outsourcing|\bbpo\b|remote - contracted|contract(ed)? position for international|"
    r"joining the pool doesn.t mean|hear from us when a project fits|this is a general application|"
    r"this (posting|requisition) is (an )?evergreen|not (tied to|for) a specific (open )?(role|position)",
    re.IGNORECASE)


def employment_problem(title: str, description: str) -> str:
    m = _EMPLOYMENT_RE.search(f"{title or ''}\n{description or ''}")
    return f"not a full-time job ({m.group(0).strip()})" if m else ""


# ---------------------------------------------------------------------------
# Seniority hidden in the description (title says "Engineer", JD says lead/architect)
# ---------------------------------------------------------------------------
_SENIOR_JD_RE = re.compile(
    r"(we are|we're) (seeking|looking for|hiring) an? (lead|senior|staff|principal)\b|"
    r"as (a|an|the) (lead|senior|staff|principal)\b|"
    r"significant time in architecture|track record of leading (large|multiple)|"
    r"lead (and|&) mentor (a team|engineers|data engineers)|mentor data engineers and architects",
    re.IGNORECASE)


def senior_problem(description: str) -> str:
    m = _SENIOR_JD_RE.search(description or "")
    return f"senior role ({m.group(0).strip()[:40]})" if m else ""
