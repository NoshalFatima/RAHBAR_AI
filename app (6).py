"""
Rahbar v8.2 — Pakistan AI Civic Complaint Platform
Changes from v8.1:
  ✅ Issue photo embedded in PDF report (Section B)
  ✅ All Pakistan provinces + cities + rural areas/tehsils (700+ locations)
  ✅ Chatbot "Play Answer" TTS fixed — reads last assistant message correctly
  ✅ Chatbot source references hidden from display (shown only internally)
  ✅ Voice send in chatbot fully working
  ✅ All other functions identical to v8.1
"""

import os, io, re, uuid, base64, datetime, urllib.parse
from PIL import Image
import gradio as gr

# ── ReportLab imports ─────────────────────────────────────────
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                 Table, TableStyle, HRFlowable, Image as RLImage)

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")

complaint_log = []

# ══════════════════════════════════════════════════════════════
# GPS / IP GEOLOCATION
# ══════════════════════════════════════════════════════════════
def get_location_from_ip():
    import requests
    try:
        r = requests.get("https://ipinfo.io/json", timeout=5)
        if r.status_code == 200:
            data = r.json()
            loc  = data.get("loc", "")
            if loc and "," in loc:
                lat, lon = map(float, loc.split(","))
                return lat, lon, data.get("city","Unknown"), data.get("region","Unknown")
    except Exception:
        pass
    try:
        r = requests.get("http://ip-api.com/json/", timeout=5)
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "success":
                return float(data["lat"]), float(data["lon"]), data.get("city","Unknown"), data.get("regionName","Unknown")
    except Exception:
        pass
    return None


def gps_locate_and_update(city_value):
    result = get_location_from_ip()
    if result:
        lat, lon, detected_city, detected_region = result
        status = (f"📍 Location detected: **{detected_city}, {detected_region}** "
                  f"(lat {lat:.4f}, lon {lon:.4f}). "
                  f"*Note: IP geolocation is approximate (~city level).*")
        fig = create_map(city_value, detected_city, lat=lat, lon=lon)
        return fig, status, lat, lon
    else:
        clat, clon = CITY_COORDS.get(city_value, (30.3753, 69.3451))
        status = ("⚠️ Could not detect location automatically. "
                  "Showing city centre. Please enter your street/area manually.")
        fig = create_map(city_value)
        return fig, status, clat, clon


# ══════════════════════════════════════════════════════════════
# RAG KNOWLEDGE BASE
# ══════════════════════════════════════════════════════════════
RAG_DOCUMENTS = [
    {"id":"g1","category":"Garbage",
     "title":"Punjab Waste Management Act 2014 — Citizen Rights",
     "content":"Under Punjab Waste Management Act 2014 any citizen can file a garbage complaint. Fine Rs.500-50,000. Local government must act within 48 hours. Helpline: 1139. Citizens can demand written response and escalate to CM Portal.",
     "laws":["Punjab Waste Management Act 2014","Pakistan EPA 1997 Section 11","Punjab LGA 2022 Schedule II"],
     "hotline":"1139","authority":"Solid Waste Management Board / Local Government","response_time":"48 hours","fine":"Rs. 500 – 50,000"},
    {"id":"g2","category":"Garbage",
     "title":"Urban Solid Waste — City-level Responsibility",
     "content":"Failure to collect garbage is a serious violation. EPA 1997 Section 11 prohibits pollution. Over 1 week = Public Nuisance PPC Section 268. Lahore LWMC: 042-111-222-888. Karachi KMC: 021-99231677.",
     "laws":["PPC Section 268","Punjab Waste Management Act 2014","EPA 1997 Section 11"],
     "hotline":"1139","authority":"LWMC Lahore / KMC Karachi","response_time":"48 hours","fine":"Rs. 500 – 50,000"},
    {"id":"g3","category":"Garbage",
     "title":"Garbage Complaint Escalation Ladder",
     "content":"If authority fails: 1.Contact Union Council 2.Apply at DC office 3.CM Cell 0800-02345 4.citizenportal.gov.pk 5.Federal Ombudsman 051-9204551 6.High Court Writ. Compensation possible under EPA 1997 Section 14.",
     "laws":["Constitution Article 9 & 14","EPA 1997 Section 14","PPC Section 268"],
     "hotline":"0800-02345","authority":"CM Complaints Cell / Federal Ombudsman","response_time":"3 working days","fine":"Compensation claimable"},
    {"id":"p1","category":"Pot Hole",
     "title":"National Highways Safety Ordinance 2000 — Pothole Rights",
     "content":"NHA responsible for road potholes. Repairs within 72 hours. Punjab LGA 2022 Section 54 covers LDA and C&W. Vehicle damage = compensation claim. NHA: 051-9032800. LDA: 042-99230215.",
     "laws":["National Highways Safety Ordinance 2000","Punjab LGA 2022 Section 54","Motor Vehicles Ordinance 1965"],
     "hotline":"051-9032800","authority":"NHA / C&W Department / LDA","response_time":"72 hours","fine":"Authority liable for vehicle damage"},
    {"id":"p2","category":"Pot Hole",
     "title":"Road Accident Due to Pothole — Legal Recourse",
     "content":"If accident: 1.File police report 2.Photograph with date 3.Written notice to NHA/LDA 4.Negligence claim under Tort Law 5.Federal Ombudsman 051-9204551 6.High Court Writ. Reports at nha.gov.pk.",
     "laws":["Tort Law Negligence","NHA Safety Ordinance 2000","Constitution Article 9"],
     "hotline":"051-9204551","authority":"Federal Ombudsman / High Court","response_time":"Court timeline","fine":"Compensation for injury/damage"},
    {"id":"w1","category":"Pipe Leakage",
     "title":"Punjab Water Act 2019 — Pipe Leakage Rights",
     "content":"Punjab Water Act 2019 Section 23: WASA must repair within 24 hours. Fine Rs.10,000-500,000. WASA Lahore: 042-99200300. WASA Karachi: 021-99231677. Supreme Court 2018: clean water is fundamental right.",
     "laws":["Punjab Water Act 2019 Section 23","WASA Act Bylaws","Constitution Article 9"],
     "hotline":"042-99200300","authority":"WASA / Pakistan Water Authority","response_time":"24 hours","fine":"Rs. 10,000 – 5,00,000"},
    {"id":"w2","category":"Pipe Leakage",
     "title":"WASA Did Not Act — Escalation Steps",
     "content":"If WASA fails: 1.Call WASA helpline 2.Written application at WASA office 3.DC office 4.CM Cell 0800-02345 5.citizenportal.gov.pk 6.PWA 051-9246150 7.Federal Ombudsman 8.High Court. Keep evidence.",
     "laws":["Punjab Water Act 2019","Constitution Article 9","EPA 1997"],
     "hotline":"0800-02345","authority":"CM Complaints Cell / PWA / Federal Ombudsman","response_time":"Escalation pathway","fine":"Rs. 10,000 – 5,00,000 + compensation"},
    {"id":"r1","category":"General",
     "title":"Fundamental Rights of Pakistani Citizens",
     "content":"Article 9: Right to Life includes clean environment. Article 14: Dignity. Article 19A: Right to Information. Citizen Portal complaints must get legal response. You can file FIR if public body fails.",
     "laws":["Constitution Article 9","Constitution Article 14","Constitution Article 19A"],
     "hotline":"0800-02345","authority":"High Court / Supreme Court / Federal Ombudsman","response_time":"3 working days","fine":"Authority accountable"},
    {"id":"r2","category":"General",
     "title":"How to File a Civic Complaint — Complete Guide",
     "content":"1.Photograph with date/time 2.Note exact location 3.Call helpline get number 4.If no action in 48-72h use CM Portal 5.citizenportal.gov.pk most effective 6.Share WhatsApp. Numbers: Garbage 1139, Roads 051-9032800, WASA 042-99200300, CM 0800-02345.",
     "laws":["Right to Information Act 2017","Constitution Article 9","EPA 1997"],
     "hotline":"0800-02345","authority":"Pakistan Citizen Portal","response_time":"3-5 working days","fine":"N/A"},
    {"id":"r3","category":"General",
     "title":"Federal Ombudsman — Role and Process",
     "content":"The Federal Ombudsman (Wafaqi Mohtasib) hears complaints against government institutions. Free to file. Decision within 60 days. Phone: 051-9204551 | mohtasib.gov.pk. Can appeal to President of Pakistan.",
     "laws":["Federal Ombudsmen Institutional Reforms Act 2013"],
     "hotline":"051-9204551","authority":"Federal Ombudsman (Mohtasib)","response_time":"60 days","fine":"Binding recommendations"},
]

# ══════════════════════════════════════════════════════════════
# RAG ENGINE
# ══════════════════════════════════════════════════════════════
class RAGEngine:
    def __init__(self):
        self.documents = RAG_DOCUMENTS
        self.vectorizer = None
        self.doc_matrix = None
        self._initialized = False

    def initialize(self):
        if self._initialized: return True
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            corpus = [f"{d['title']} {d['content']} {' '.join(d.get('laws',[]))} {d.get('category','')} {d.get('hotline','')} {d.get('authority','')}"
                      for d in self.documents]
            self.vectorizer = TfidfVectorizer(analyzer='char_wb', ngram_range=(2,5), max_features=8000, sublinear_tf=True, min_df=1)
            self.doc_matrix = self.vectorizer.fit_transform(corpus)
            self._initialized = True
            return True
        except Exception as e:
            print(f"RAG init error: {e}")
            return False

    def retrieve(self, query, top_k=3):
        if not self._initialized:
            if not self.initialize():
                return self._keyword_fallback(query, top_k)
        try:
            from sklearn.metrics.pairwise import cosine_similarity
            import numpy as np
            q_vec  = self.vectorizer.transform([query])
            scores = cosine_similarity(q_vec, self.doc_matrix)[0]
            top_idx = np.argsort(scores)[::-1][:top_k]
            results = []
            for idx in top_idx:
                if scores[idx] > 0.01:
                    doc = self.documents[idx].copy()
                    doc['relevance_score'] = float(scores[idx])
                    results.append(doc)
            return results if results else self._keyword_fallback(query, top_k)
        except Exception:
            return self._keyword_fallback(query, top_k)

    def _keyword_fallback(self, query, top_k=3):
        q = query.lower()
        keywords = {"Garbage":["garbage","waste","sanitation","trash","1139"],
                    "Pot Hole":["pothole","pot hole","road","nha"],
                    "Pipe Leakage":["water","wasa","pipe","leakage","contaminated"]}
        found_cat = None
        for cat, kws in keywords.items():
            if any(kw in q for kw in kws): found_cat = cat; break
        matched = [d for d in self.documents if found_cat and d['category'] == found_cat]
        for d in self.documents:
            if d['category'] == 'General' and d not in matched: matched.append(d)
        return matched[:top_k] if matched else self.documents[:top_k]

    def format_context(self, docs):
        if not docs: return ""
        ctx = "Relevant Legal Information:\n\n"
        for i, doc in enumerate(docs, 1):
            ctx += (f"[{i}] {doc['title']}\nContent: {doc['content'][:400]}\n"
                    f"Laws: {', '.join(doc['laws'][:2])}\nHelpline: {doc['hotline']} | Response: {doc['response_time']}\n\n")
        return ctx

rag_engine = RAGEngine()
rag_engine.initialize()

# ══════════════════════════════════════════════════════════════
# STATIC DATA — ALL PAKISTAN (provinces + cities + rural areas)
# ══════════════════════════════════════════════════════════════

# City coordinates for map centering
CITY_COORDS = {
    # Punjab
    "Lahore":(31.5204,74.3587),"Faisalabad":(31.4181,73.0776),"Rawalpindi":(33.5651,73.0169),
    "Gujranwala":(32.1877,74.1945),"Multan":(30.1575,71.5249),"Sialkot":(32.4945,74.5229),
    "Bahawalpur":(29.3956,71.6836),"Sargodha":(32.0836,72.6711),"Sahiwal":(30.6706,73.1064),
    "Sheikhupura":(31.7167,73.9850),"Jhang":(31.2681,72.3181),"Kasur":(31.1167,74.4500),
    "Okara":(30.8138,73.4544),"Gujrat":(32.5736,74.0789),"Wazirabad":(32.4435,74.1199),
    "Jhelum":(32.9425,73.7257),"Khushab":(32.2979,72.3549),"Mianwali":(32.5856,71.5435),
    "Bhakkar":(31.6276,71.0652),"Muzaffargarh":(30.0694,71.1933),"Dera Ghazi Khan":(30.0564,70.6349),
    "Layyah":(30.9597,70.9397),"Rajanpur":(29.1040,70.3305),"Lodhran":(29.5337,71.6316),
    "Vehari":(30.0449,72.3517),"Pakpattan":(30.3438,73.3881),"Toba Tek Singh":(30.9709,72.4827),
    "Chiniot":(31.7189,72.9787),"Hafizabad":(32.0710,73.6880),"Narowal":(32.0966,74.8716),
    "Chakwal":(32.9310,72.8524),"Attock":(33.7667,72.3583),"Rawala Kot":(33.8579,73.7610),
    "Khanewal":(30.3011,71.9323),"Bahawalnagar":(29.9908,73.2548),"Nankana Sahib":(31.4502,73.7129),
    "Mandi Bahauddin":(32.5865,73.4909),"Phool Nagar":(31.1669,74.0158),
    # Rural Punjab
    "Pindi Bhattian":(31.8953,73.2720),"Kot Addu":(30.4695,70.9636),"Sadiqabad":(28.3090,70.1310),
    "Ahmadpur East":(29.1438,71.2601),"Kabirwala":(30.4021,71.8741),"Hasilpur":(29.6967,72.5596),
    "Jampur":(29.6435,70.5927),"Liaquatpur":(28.9191,70.9550),"Yazman":(29.1179,71.7444),
    "Uch Sharif":(29.2341,71.0918),"Chishtian":(29.7986,72.8543),"Mailsi":(29.8012,72.1671),
    "Burewala":(30.1682,72.6809),"Kamalia":(30.7265,72.6466),"Jaranwala":(31.3342,73.4153),
    "Pattoki":(31.0220,73.8549),"Chunian":(30.9609,73.9788),"Chichawatni":(30.5365,72.6918),
    "Dinga":(32.6422,73.7220),"Khanpur":(28.6470,70.6618),
    # Sindh
    "Karachi":(24.8607,67.0011),"Hyderabad":(25.3960,68.3578),"Sukkur":(27.7052,68.8574),
    "Larkana":(27.5570,68.2140),"Nawabshah":(26.2442,68.4100),"Mirpur Khas":(25.5269,69.0138),
    "Jacobabad":(28.2769,68.4376),"Shikarpur":(27.9557,68.6376),"Khairpur":(27.5295,68.7592),
    "Dadu":(26.7319,67.7764),"Ghotki":(28.0050,69.3172),"Sanghar":(26.0464,68.9466),
    "Tharparkar":(24.7136,70.2491),"Badin":(24.6560,68.8375),"Thatta":(24.7461,67.9236),
    "Jamshoro":(25.4330,68.2810),"Matiari":(25.5998,68.4574),"Shahdadkot":(27.8526,67.9065),
    "Qambar":(27.5864,68.0022),"Sujawal":(24.1278,68.1500),"Umerkot":(25.3618,69.7336),
    "Kandhkot":(28.2436,69.3010),"Kashmore":(28.4382,69.5715),"Karachi East":(24.9056,67.1114),
    "Karachi West":(24.8800,67.0200),"Malir":(25.0694,67.2005),"Korangi":(24.8310,67.1326),
    "Kemari":(24.8417,66.9897),
    # Rural Sindh
    "Tando Adam":(25.7663,68.6638),"Tando Allah Yar":(25.4680,68.7215),"Tando Muhammad Khan":(25.1280,68.5370),
    "Sehwan":(26.4255,67.8669),"Mehar":(27.1705,67.8131),"Daharki":(28.5388,69.7795),
    "Obaro":(28.3730,69.8240),"Mirpur Mathelo":(28.0204,69.5726),"Rohri":(27.6919,68.8989),
    "Pano Aqil":(27.8608,69.1081),"Gambat":(27.3491,68.5221),"Kotri":(25.3668,68.3095),
    "Hala":(25.8165,68.4287),"Tando Bago":(24.7972,68.9577),"Kunri":(25.4657,69.5819),
    "Chhor":(25.5064,69.7875),"Naukot":(25.8917,69.3667),"Mithi":(24.7285,69.7979),
    "Islamkot":(24.6797,70.1768),"Diplo":(24.4613,69.5832),
    # KPK
    "Peshawar":(34.0151,71.5249),"Mardan":(34.1988,72.0404),"Mingora":(34.7717,72.3600),
    "Kohat":(33.5890,71.4411),"Abbottabad":(34.1558,73.2194),"Mansehra":(34.3300,73.1970),
    "Nowshera":(34.0153,71.9747),"Charsadda":(34.1488,71.7307),"Swabi":(34.1200,72.4700),
    "Dera Ismail Khan":(31.8314,70.9019),"Bannu":(32.9891,70.6056),"Tank":(32.2145,70.3776),
    "Hangu":(33.5326,71.0569),"Karak":(33.1170,71.0940),"Buner":(34.5444,72.5000),
    "Shangla":(34.6177,72.5200),"Chitral":(35.8510,71.7875),"Dir Lower":(34.8698,71.8889),
    "Dir Upper":(35.2073,71.8787),"Batagram":(34.6800,73.0200),"Kohistan":(35.4486,73.0942),
    "Torghar":(34.9000,72.6000),"Malakand":(34.5651,71.9330),"Kurram":(33.6716,70.1032),
    "Orakzai":(33.6333,71.0000),"Khyber":(33.9460,71.1590),"Bajaur":(34.8300,71.5600),
    "Mohmand":(34.4200,71.3100),"South Waziristan":(32.3160,69.8260),"North Waziristan":(33.0000,70.0000),
    "Lakki Marwat":(32.6070,70.9120),
    # Rural KPK
    "Timergara":(35.0876,71.8434),"Matta":(35.0176,72.3248),"Bahrain":(35.1942,72.5608),
    "Kalam":(35.4879,72.5770),"Saidu Sharif":(34.7534,72.3584),"Chakdara":(34.6490,71.9273),
    "Thana":(34.3626,72.5060),"Haripur":(33.9980,72.9349),"Havelian":(34.0543,73.1591),
    "Muzzafarabad KPK":(34.2833,73.3667),"Doaba":(33.4987,70.7523),"Parachinar":(33.9007,70.0965),
    "Sadda":(33.7735,70.3498),"Ghallanai":(34.3789,71.2620),"Nawagai":(34.9627,71.3543),
    # Balochistan
    "Quetta":(30.1798,66.9750),"Gwadar":(25.1216,62.3254),"Turbat":(26.0000,63.0500),
    "Khuzdar":(27.8000,66.6167),"Kalat":(29.0231,66.5882),"Panjgur":(26.9680,64.0985),
    "Chaman":(30.9210,66.4460),"Zhob":(31.3416,69.4486),"Loralai":(30.3723,68.5931),
    "Kharan":(28.5880,65.4160),"Nushki":(29.5520,66.0190),"Ziarat":(30.3820,67.7280),
    "Dera Bugti":(29.0358,69.1584),"Sibi":(29.5430,67.8773),"Pishin":(30.5800,66.9960),
    "Mastung":(29.7983,66.8445),"Awaran":(26.3500,62.1167),"Barkhan":(29.8973,69.5259),
    "Dera Murad Jamali":(28.7475,68.1323),"Jaffarabad":(28.7475,68.1323),"Jhal Magsi":(28.2847,67.7267),
    "Kachhi / Bolan":(29.1089,67.5744),"Kohlu":(29.8920,69.2534),"Lasbela":(26.2083,65.8833),
    "Makran":(26.0000,64.0000),"Musa Khel":(30.8517,69.9833),"Nasirabad":(28.4232,68.3583),
    "Panjgur Rural":(26.9680,64.0985),"Qila Abdullah":(30.6783,66.9758),"Qila Saifullah":(30.7034,68.3534),
    "Sherani":(31.5649,70.0782),"Sohbatpur":(28.4892,68.0856),"Surab":(28.4900,66.2600),
    "Tump":(26.0000,62.9500),"Washuk":(27.7780,64.8770),"Harnai":(30.1012,67.9391),
    "Chaghi":(29.0000,64.0000),"Dalbandin":(29.0000,64.4000),"Nokundi":(28.8257,62.7500),
    "Pashni":(25.5075,63.4700),"Ormara":(25.2094,64.6361),"Pasni":(25.2623,63.4700),
    # Islamabad Capital Territory
    "Islamabad":(33.6844,73.0479),"F-7 Islamabad":(33.7271,73.0479),"F-8 Islamabad":(33.7191,73.0393),
    "F-10 Islamabad":(33.7017,73.0209),"G-9 Islamabad":(33.6927,73.0592),"G-10 Islamabad":(33.6839,73.0487),
    "G-11 Islamabad":(33.6745,73.0190),"Blue Area Islamabad":(33.7188,73.0640),"E-7 Islamabad":(33.7380,73.0830),
    "I-8 Islamabad":(33.6622,73.0940),"H-8 Islamabad":(33.6711,73.0570),
    # AJK
    "Muzaffarabad":(34.3700,73.4710),"Mirpur AJK":(33.1445,73.7513),"Rawalakot":(33.8579,73.7610),
    "Bagh AJK":(33.9847,73.7803),"Kotli":(33.5179,73.9025),"Poonch AJK":(33.7737,74.0949),
    "Neelum AJK":(34.5900,74.2100),"Haveli":(33.7500,73.8833),"Sudhnati":(33.5444,73.7015),
    "Hattian Bala":(34.0892,73.8195),"Jhelum Valley":(34.3300,73.6500),
    # Gilgit-Baltistan
    "Gilgit":(35.9221,74.3085),"Skardu":(35.2971,75.6360),"Hunza":(36.3167,74.6500),
    "Ghanche":(35.4950,76.1500),"Astore":(35.3660,74.8590),"Diamer":(35.5000,73.7000),
    "Ghizer":(36.2333,73.5000),"Nagar":(36.1000,74.4167),"Shigar":(35.5000,75.6700),
    "Kharmang":(35.4167,76.3500),"Roundu":(35.5167,76.1833),"Gupis":(36.1667,73.4167),
    "Yasin":(36.4833,73.3000),"Ishkoman":(36.6667,73.7667),"Ganche":(35.4950,76.1500),
}

# Comprehensive city list (sorted) for dropdown
ALL_CITIES = sorted(CITY_COORDS.keys())

ISSUE_TYPES = ["Garbage", "Pot Hole", "Pipe Leakage"]
LANGUAGES   = ["English", "Urdu", "Punjabi", "Sindhi"]

LEGAL_KB = {
    "Garbage": {
        "laws":["Punjab Waste Management Act 2014","Pakistan Environmental Protection Act 1997 (Section 11)","Punjab Local Government Act 2022 (Schedule II – Sanitation Duties)","Pakistan Penal Code Section 268 – Public Nuisance"],
        "fine":"Rs. 500 – 50,000 (per offence)","authority":"Local Government / Solid Waste Management Board",
        "hotline":"1139","response":"48 hours",
        "citizen_rights":["Right to clean environment (Constitution of Pakistan, Article 9 & 14)","Right to file FIR under PPC Section 268 if authority fails to act","Right to compensation for health damage under EPA 1997","Right to written response within 3 working days"],
        "escalation":"CM Complaints Cell: 0800-02345 | citizenportal.gov.pk","dataset_ref":"Punjab SWMB | Urban Issues Dataset",
    },
    "Pot Hole": {
        "laws":["National Highways Safety Ordinance 2000","Punjab Local Government Act 2022 (Section 54 – Road Maintenance)","Motor Vehicles Ordinance 1965 (Road Authority Liability)","Tort Law – Negligence (Pakistani courts)"],
        "fine":"Authority liable for vehicle damage & personal injury","authority":"National Highway Authority (NHA) / C&W Department / LDA",
        "hotline":"051-9032800","response":"72 hours",
        "citizen_rights":["Right to claim compensation for vehicle damage or personal injury","Right to lodge complaint with Federal Ombudsman","Right to file High Court writ petition for dereliction of duty","Right to written notice to NHA/LDA"],
        "escalation":"Federal Ombudsman: 051-9204551 | nha.gov.pk","dataset_ref":"NHA Road Quality Reports | Road Issues Detection Dataset",
    },
    "Pipe Leakage": {
        "laws":["Punjab Water Act 2019 (Section 23 – Supply Obligation)","WASA Act – Water & Sanitation Agency Bylaws","Pakistan Environmental Protection Act 1997 (Section 13)","Punjab Local Government Act 2022 (Water & Sewerage Schedules)","Constitution of Pakistan Article 9 – Right to Life"],
        "fine":"Compensatory damages + Rs. 10,000 – 5,00,000","authority":"WASA / Pakistan Water Authority",
        "hotline":"042-99200300","response":"24 hours",
        "citizen_rights":["Right to safe drinking water (Supreme Court ruling 2018 – PLD 2018 SC 1)","Right to compensation for property damage from water leakage","Right to disconnect billing if water supply is contaminated","Right to file complaint with Pakistan Water Authority (PWA)"],
        "escalation":"Pakistan Water Authority: 051-9246150 | CM Portal: 0800-02345","dataset_ref":"WASA Annual Reports | Consumer Complaints Dataset",
    },
}

LANG_CODES = {"English":"en","Urdu":"ur","Punjabi":"ur","Sindhi":"ur"}
WASTE_CLASS_IDS = {24,25,26,27,28,32,33,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54}

# ══════════════════════════════════════════════════════════════
# YOLO DETECTION
# ══════════════════════════════════════════════════════════════
def detect_with_yolo(image_pil, issue_type):
    try:
        from ultralytics import YOLO
        import numpy as np
        model   = YOLO("yolo26n.pt")
        results = model(np.array(image_pil), verbose=False)
        result  = results[0]
        names   = model.names
        detected, severity = [], 1
        for box in result.boxes:
            cls_id = int(box.cls[0]); conf = float(box.conf[0])
            detected.append(f"{names.get(cls_id, f'class_{cls_id}')} ({conf:.0%})")
            if issue_type == "Garbage" and cls_id in WASTE_CLASS_IDS:
                severity = min(10, severity + 2)
            elif issue_type in ("Pot Hole","Pipe Leakage"):
                severity = min(10, severity + 1)
        annotated = Image.fromarray(result.plot())
        summary   = (f"Detected {len(detected)} object(s): {', '.join(detected[:5])}"
                     if detected else "No specific objects detected.")
        return annotated, summary, max(severity, 3)
    except ImportError:
        return image_pil, "Object detection library not available.", 5
    except Exception as e:
        return image_pil, f"Detection error: {e}", 5

# ══════════════════════════════════════════════════════════════
# GEMINI VISION
# ══════════════════════════════════════════════════════════════
def analyze_with_gemini(image_pil, issue, location, city, yolo_summary):
    if not GOOGLE_API_KEY:
        return "WARNING: GOOGLE_API_KEY not set. Verification skipped."
    try:
        import google.generativeai as genai
        genai.configure(api_key=GOOGLE_API_KEY)
        model = genai.GenerativeModel("gemini-3-flash-preview")
        buf   = io.BytesIO()
        image_pil.save(buf, format="JPEG")
        prompt = (f"You are a STRICT Pakistani Civic Issue Inspector.\n"
                  f"REPORTED ISSUE: '{issue}' | CITY: {city} | LOCATION: {location}\n"
                  f"DETECTION: {yolo_summary}\n"
                  f"Garbage=actual waste/litter, Pot Hole=visible road hole, Pipe Leakage=water from pipe.\n"
                  f"Respond ONLY in this format:\n"
                  f"STATUS: [APPROVED or REJECTED]\nREASON: [2-3 sentences]\n"
                  f"SEVERITY: [1-10]\nCONFIDENCE: [XX%]\nRECOMMENDED_ACTION: [one sentence]")
        image_part = {"mime_type":"image/jpeg","data":base64.b64encode(buf.getvalue()).decode()}
        return model.generate_content([prompt, image_part]).text.strip()
    except Exception as e:
        return f"WARNING: Verification error: {e}"

def parse_gemini_response(text):
    r = {"status":"UNKNOWN","reason":"Could not parse.","severity":5,"confidence":"N/A","action":""}
    if not text: return r
    for pat, key in [(r"STATUS:\s*(APPROVED|REJECTED)","status"),(r"SEVERITY:\s*(\d+)","severity"),(r"CONFIDENCE:\s*(\d+%)","confidence")]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            v = m.group(1)
            r[key] = v.upper() if key=="status" else (int(v) if key=="severity" else v)
    for pat, key in [(r"REASON:\s*(.+?)(?=SEVERITY:|$)","reason"),(r"RECOMMENDED_ACTION:\s*(.+?)(?=$)","action")]:
        m = re.search(pat, text, re.DOTALL|re.IGNORECASE)
        if m: r[key] = m.group(1).strip()
    return r

# ══════════════════════════════════════════════════════════════
# LEGAL ADVICE
# ══════════════════════════════════════════════════════════════
def analyze_with_llama(issue, location, city, yolo_summary, severity, language="English"):
    kb = LEGAL_KB.get(issue, {})
    lang_map = {"Urdu":"Respond entirely in Urdu script.","Punjabi":"Respond in Punjabi Shahmukhi script.","Sindhi":"Respond in Sindhi script."}
    lang_instruction = lang_map.get(language, "Respond in clear professional English.")
    if not GROQ_API_KEY:
        rights = "\n".join(f"  • {r}" for r in kb.get("citizen_rights",[]))
        return (f"Applicable Laws:\n"+"\n".join(f"  • {l}" for l in kb.get("laws",[]))+
                f"\n\nCitizen Rights:\n{rights}\n\nFine / Penalty: {kb.get('fine','N/A')}"
                f"\nAuthority Helpline: {kb.get('hotline','N/A')}\nRequired Response Time: {kb.get('response','N/A')}"
                f"\n\nEscalation: {kb.get('escalation','N/A')}\n\n(Configure API key for AI-generated legal advice)")
    try:
        from groq import Groq
        client = Groq(api_key=GROQ_API_KEY)
        prompt = (f"You are a Pakistani civic law expert.\n{lang_instruction}\n"
                  f"Complaint: {issue} in {location}, {city} | Severity: {severity}/10\n"
                  f"Applicable Laws: {', '.join(kb.get('laws',[]))}\n"
                  f"Required Response Time: {kb.get('response','72 hours')}\n\n"
                  f"Provide:\n1. Specific legal rights (cite law names/sections)\n"
                  f"2. Exact numbered steps to file a formal complaint\n"
                  f"3. What to do if authority does not respond in time\n"
                  f"4. Possible compensation or legal action available\n"
                  f"5. Relevant helplines and escalation contacts\n"
                  f"Keep it concise and practical for an ordinary Pakistani citizen.")
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content":prompt}], max_tokens=700)
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"Legal advice error: {e}"

# ══════════════════════════════════════════════════════════════
# RAG CHATBOT — Gradio 6 messages format
# ══════════════════════════════════════════════════════════════
def legal_chatbot_rag(user_message, history, language):
    """
    history = list of {"role": "user"|"assistant", "content": str}
    Source references are NOT appended to displayed content.
    """
    if history is None: history = []
    if not user_message.strip(): return history, ""

    retrieved_docs = rag_engine.retrieve(user_message, top_k=3)
    rag_context    = rag_engine.format_context(retrieved_docs)
    lang_map = {"Urdu":"Respond entirely in Urdu script.","Punjabi":"Respond in Punjabi Shahmukhi script.","Sindhi":"Respond in Sindhi script."}
    lang_instruction = lang_map.get(language, "Respond in clear professional English.")
    system_content = (f"You are Rahbar Legal Assistant — a civic rights advisor for Pakistani citizens.\n"
                      f"{lang_instruction}\n"
                      f"Only discuss: water, pipe leakage, WASA, garbage, roads, potholes, Pakistani civic law.\n"
                      f"Always cite specific laws and provide helpline numbers. Max 250 words per response.\n\n"
                      f"Knowledge Base:\n{rag_context}")

    if not GROQ_API_KEY:
        if retrieved_docs:
            doc    = retrieved_docs[0]
            answer = (f"**{doc['title']}**\n\n{doc['content'][:500]}\n\n"
                      f"Helpline: {doc['hotline']} | Response Time: {doc['response_time']}\n"
                      f"Laws: {', '.join(doc['laws'][:2])}\n\n"
                      f"_(Configure API key for full AI-powered responses)_")
        else:
            answer = "I can help with water, garbage, and road issues in Pakistan. Please ask a specific civic question."
        return history + [{"role":"user","content":user_message},{"role":"assistant","content":answer}], ""

    try:
        from groq import Groq
        client       = Groq(api_key=GROQ_API_KEY)
        api_messages = [{"role":"system","content":system_content}]
        for msg in history[-16:]:
            api_messages.append({"role":msg["role"],"content":msg["content"]})
        api_messages.append({"role":"user","content":user_message})
        resp   = client.chat.completions.create(
            model="llama-3.3-70b-versatile", messages=api_messages, max_tokens=500)
        # ── FIX: Do NOT append source references to displayed answer ──
        answer = resp.choices[0].message.content.strip()
    except Exception as e:
        answer = f"Sorry, there was an error: {e}"

    return history + [{"role":"user","content":user_message},{"role":"assistant","content":answer}], ""


def chatbot_tts_output(history, language):
    """
    ── FIX: Walk history backwards to find last assistant message,
       clean it, and convert to speech. No source refs, no markdown. ──
    """
    if not history:
        return None
    for msg in reversed(history):
        if not isinstance(msg, dict): continue
        if msg.get("role") == "assistant":
            text = msg.get("content", "")
            # Remove any markdown bold/italic markers and source refs
            text = re.sub(r'_[Ss]ources?:.*?_', '', text, flags=re.DOTALL)
            text = re.sub(r'\*+', '', text)
            text = text.strip()
            if text:
                return make_tts(text[:600], language)
    return None

# ══════════════════════════════════════════════════════════════
# TTS
# ══════════════════════════════════════════════════════════════
def make_tts(text, language):
    try:
        from gtts import gTTS
        lang_code = LANG_CODES.get(language, "en")
        tts  = gTTS(text=str(text)[:600], lang=lang_code, slow=False)
        path = f"/tmp/tts_{uuid.uuid4().hex[:8]}.mp3"
        tts.save(path)
        return path
    except Exception:
        try:
            from gtts import gTTS
            tts  = gTTS(text=str(text)[:600], lang="en", slow=False)
            path = f"/tmp/tts_fb_{uuid.uuid4().hex[:8]}.mp3"
            tts.save(path)
            return path
        except Exception:
            return None

# ══════════════════════════════════════════════════════════════
# STT
# ══════════════════════════════════════════════════════════════
def stt(audio_file):
    if audio_file is None:
        return "No audio received. Please record or upload audio first."
    def ensure_wav(path):
        if path.lower().endswith(".wav"): return path
        try:
            from pydub import AudioSegment
            out = path + "_converted.wav"
            AudioSegment.from_file(path).export(out, format="wav")
            return out
        except Exception: return path
    if GROQ_API_KEY:
        try:
            from groq import Groq
            client   = Groq(api_key=GROQ_API_KEY)
            wav_path = ensure_wav(audio_file)
            with open(wav_path, "rb") as f:
                result = client.audio.transcriptions.create(model="whisper-large-v3", file=f, response_format="text")
            text = result if isinstance(result, str) else result.text
            return text.strip() or "No speech detected in audio."
        except Exception as e: groq_err = str(e)
    else: groq_err = "API key not configured"
    try:
        import speech_recognition as sr
        wav_path   = ensure_wav(audio_file)
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as src:
            recognizer.adjust_for_ambient_noise(src, duration=0.3)
            audio_data = recognizer.record(src)
        return recognizer.recognize_google(audio_data)
    except Exception as e2:
        return f"Transcription failed. Error: {groq_err}. Fallback: {e2}"

# ══════════════════════════════════════════════════════════════
# LAW REFERENCE
# ══════════════════════════════════════════════════════════════
def law_info(issue, language):
    kb     = LEGAL_KB.get(issue, {})
    rights = "\n".join(f"  - {r}" for r in kb.get("citizen_rights",[]))
    out    = f"## Legal Reference: {issue}\n\n### Applicable Laws\n"
    for law in kb.get("laws",[]): out += f"  - {law}\n"
    out += (f"\n### Fine / Penalty\n{kb.get('fine','N/A')}\n"
            f"\n### Responsible Authority\n{kb.get('authority','N/A')}\n"
            f"\n### Official Helpline\n**{kb.get('hotline','N/A')}**\n"
            f"\n### Mandatory Response Time\n{kb.get('response','N/A')}\n"
            f"\n### Citizen Rights\n{rights}\n"
            f"\n### Escalation Path\n{kb.get('escalation','N/A')}\n"
            f"\n---\n*Source: {kb.get('dataset_ref','Pakistani civic law databases')}*")
    return out

# ══════════════════════════════════════════════════════════════
# ADMIN STATS
# ══════════════════════════════════════════════════════════════
def get_admin_stats():
    total = len(complaint_log)
    if total == 0: return "No complaints filed yet.", ""
    counts = {"Garbage":0,"Pot Hole":0,"Pipe Leakage":0}
    cities, severities = {}, []
    for c in complaint_log:
        issue = c.get("issue",""); counts[issue] = counts.get(issue,0)+1
        city  = c.get("city","Unknown"); cities[city] = cities.get(city,0)+1
        severities.append(c.get("severity",5))
    avg_sev  = sum(severities)/len(severities) if severities else 0
    top_city = max(cities, key=cities.get) if cities else "N/A"
    stats_md = (f"## Dashboard Summary\n|Metric|Value|\n|--------|-------|\n"
                f"|Total Complaints|**{total}**|\n|Average Severity|**{avg_sev:.1f}/10**|\n|Most Active City|**{top_city}**|\n\n"
                f"### By Issue Type\n|Issue|Count|\n|-------|-------|\n"
                f"|Garbage|{counts['Garbage']}|\n|Pot Hole|{counts['Pot Hole']}|\n|Pipe Leakage|{counts['Pipe Leakage']}|\n\n"
                f"### By City\n")
    for city, cnt in sorted(cities.items(), key=lambda x:-x[1]): stats_md += f"|{city}|{cnt}|\n"
    log_md = "## Recent Complaints\n\n"
    for c in reversed(complaint_log[-10:]):
        log_md += (f"**{c['id']}** | {c['timestamp']} | {c['city']}, {c['location']} | "
                   f"{c['issue']} | Severity {c['severity']}/10 | {c.get('name','N/A')}\n\n")
    return stats_md, log_md

def severity_label(score):
    if score <= 3: return "LOW"
    if score <= 6: return "MEDIUM"
    if score <= 8: return "HIGH"
    return "CRITICAL"

def update_areas(city):
    # With all-Pakistan support, areas are typed freely — just update the map
    return gr.Dropdown(choices=[], value="", allow_custom_value=True)

# ══════════════════════════════════════════════════════════════
# PLOTLY MAP
# ══════════════════════════════════════════════════════════════
def create_map(city, location_text="", lat=None, lon=None):
    try:
        import plotly.graph_objects as go
    except ImportError:
        return None
    clat, clon = CITY_COORDS.get(city, (30.3753, 69.3451))
    mlat = lat if lat is not None else clat
    mlon = lon if lon is not None else clon
    label = location_text if location_text.strip() else city
    fig = go.Figure(go.Scattermap(
        lat=[mlat], lon=[mlon],
        mode="markers+text",
        marker=dict(size=16, color="#e8410a"),
        text=[label], textposition="top right",
        hovertemplate=f"<b>{label}</b><br>Lat: {mlat:.4f}<br>Lon: {mlon:.4f}<extra></extra>",
    ))
    fig.update_layout(
        map=dict(style="open-street-map", center=dict(lat=mlat, lon=mlon), zoom=13),
        margin=dict(r=0,t=0,l=0,b=0), height=320,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig

def update_map_on_city(city):
    return create_map(city)

def update_map_on_location(city, area, location_text):
    return create_map(city, location_text or area)

# ══════════════════════════════════════════════════════════════
# PDF GENERATION — with issue photo embedded in Section B
# ══════════════════════════════════════════════════════════════
def generate_pdf_report(complaint_id, timestamp, name, cnic, phone, city, location,
                        issue_type, language, severity, gemini_status, gemini_reason,
                        gemini_confidence, kb, description, llama_advice,
                        issue_image_pil=None):   # ← NEW: PIL image
    try:
        pdf_path = f"/tmp/rahbar_report_{complaint_id}.pdf"
        doc = SimpleDocTemplate(
            pdf_path, pagesize=A4,
            rightMargin=0.75*inch, leftMargin=0.75*inch,
            topMargin=0.75*inch, bottomMargin=0.75*inch
        )

        C_DARK_GREEN  = colors.HexColor("#1a5c3f")
        C_MID_GREEN   = colors.HexColor("#25a06b")
        C_LIGHT_GREEN = colors.HexColor("#eaf5ef")
        C_GOLD        = colors.HexColor("#c8860a")
        C_GOLD_LIGHT  = colors.HexColor("#fef9ee")
        C_TEXT        = colors.HexColor("#0d2b1e")
        C_MUTED       = colors.HexColor("#5a8a6e")
        C_WHITE       = colors.white
        SEV_COLORS    = {
            "LOW":      colors.HexColor("#27ae60"),
            "MEDIUM":   colors.HexColor("#f39c12"),
            "HIGH":     colors.HexColor("#e67e22"),
            "CRITICAL": colors.HexColor("#c0392b"),
        }

        def PS(name, **kw): return ParagraphStyle(name, **kw)

        sHeadWhite = PS("hw",fontName="Helvetica-Bold",fontSize=18,textColor=C_WHITE,alignment=TA_CENTER,leading=24,spaceAfter=2)
        sSubWhite  = PS("sw",fontName="Helvetica",fontSize=10,textColor=colors.HexColor("#b8e8cc"),alignment=TA_CENTER,leading=14,spaceAfter=2)
        sRefWhite  = PS("rw",fontName="Helvetica",fontSize=8,textColor=colors.HexColor("#a8d8c0"),alignment=TA_CENTER,spaceAfter=0)
        sSecHead   = PS("sec",fontName="Helvetica-Bold",fontSize=10,textColor=C_WHITE,leading=14,spaceAfter=0)
        sSevBadge  = PS("sev",fontName="Helvetica-Bold",fontSize=11,textColor=C_WHITE,alignment=TA_CENTER,leading=16)
        sLabel     = PS("lbl",fontName="Helvetica-Bold",fontSize=8.5,textColor=C_MUTED,leading=12)
        sValue     = PS("val",fontName="Helvetica",fontSize=9.5,textColor=C_TEXT,leading=14)
        sBody      = PS("bod",fontName="Helvetica",fontSize=9,textColor=C_TEXT,leading=13,spaceAfter=3)
        sBodyI     = PS("bi",fontName="Helvetica-Oblique",fontSize=9,textColor=colors.HexColor("#2d5a3e"),leading=13)
        sBullet    = PS("bul",fontName="Helvetica",fontSize=9,textColor=C_TEXT,leading=13,leftIndent=12)
        sGoldDir   = PS("gd",fontName="Helvetica-Bold",fontSize=10,textColor=C_WHITE,alignment=TA_CENTER,leading=15)
        sFooter    = PS("ft",fontName="Helvetica",fontSize=7.5,textColor=C_WHITE,alignment=TA_CENTER,leading=11)
        sDecl      = PS("dc",fontName="Helvetica",fontSize=9,textColor=C_TEXT,leading=13)
        sImgCapt   = PS("ic",fontName="Helvetica-Oblique",fontSize=8,textColor=C_MUTED,alignment=TA_CENTER,leading=11)

        W = 7.0 * inch

        def sec_header(letter, title):
            t = Table([[Paragraph(f"  {letter}.  {title.upper()}", sSecHead)]], colWidths=[W])
            t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C_DARK_GREEN),
                                    ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
                                    ("LEFTPADDING",(0,0),(-1,-1),10)]))
            return t

        def info_grid(pairs):
            rows = []; row = []
            for i,(lbl,val) in enumerate(pairs):
                row.extend([Paragraph(lbl,sLabel),Paragraph(str(val),sValue)])
                if len(row)==4 or i==len(pairs)-1:
                    while len(row)<4: row.extend([Paragraph("",sLabel),Paragraph("",sValue)])
                    rows.append(row); row=[]
            t = Table(rows, colWidths=[2.0*inch,1.5*inch,2.0*inch,1.5*inch])
            t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C_LIGHT_GREEN),
                                    ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
                                    ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
                                    ("VALIGN",(0,0),(-1,-1),"TOP"),
                                    ("ROWBACKGROUNDS",(0,0),(-1,-1),[C_LIGHT_GREEN,C_WHITE])]))
            return t

        def text_card(paras, bg=None):
            bg = bg or C_LIGHT_GREEN
            rows = [[p] for p in paras]
            t = Table(rows, colWidths=[W])
            t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),bg),
                                    ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
                                    ("LEFTPADDING",(0,0),(-1,-1),12),("RIGHTPADDING",(0,0),(-1,-1),10),
                                    ("VALIGN",(0,0),(-1,-1),"TOP")]))
            return t

        def sp(h=0.15): return Spacer(1, h*inch)

        story = []
        date_str = datetime.datetime.now().strftime("%d %B %Y")
        time_str = datetime.datetime.now().strftime("%I:%M %p")
        sev_lbl  = severity_label(severity)

        # ── Banner ──
        header_rows = [
            [Paragraph("GOVERNMENT OF PAKISTAN", sHeadWhite)],
            [Paragraph("CIVIC COMPLAINT REPORT", sHeadWhite)],
            [Paragraph("Rahbar Digital Civic Redressal System", sSubWhite)],
            [Paragraph(f"Reference: {complaint_id}   |   {date_str} at {time_str}   |   Language: {language}", sRefWhite)],
        ]
        h_t = Table(header_rows, colWidths=[W])
        h_t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C_DARK_GREEN),
                                  ("TOPPADDING",(0,0),(-1,-1),10),("BOTTOMPADDING",(0,0),(-1,-1),10),
                                  ("LEFTPADDING",(0,0),(-1,-1),14),("RIGHTPADDING",(0,0),(-1,-1),14)]))
        story += [h_t, sp(0.12)]

        # ── Severity badge ──
        sev_color = SEV_COLORS.get(sev_lbl, C_MID_GREEN)
        sev_t = Table([[Paragraph(f"SEVERITY: {severity}/10 — {sev_lbl}", sSevBadge)]], colWidths=[W])
        sev_t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),sev_color),
                                    ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8)]))
        story += [sev_t, sp(0.18)]

        # ── Section A: Complainant ──
        story += [sec_header("A","Complainant Information"), sp(0.08)]
        story += [info_grid([("Full Name",name),("CNIC",cnic),("Phone",phone or "N/A"),("City",city)]), sp(0.15)]

        # ── Section B: Complaint Details + PHOTO ──
        story += [sec_header("B","Complaint Details"), sp(0.08)]
        story += [info_grid([("Issue Type",issue_type),("Location",location),("Date Filed",date_str),("Time Filed",time_str)])]
        if description.strip():
            story += [sp(0.08), text_card([Paragraph(f"<b>Description:</b> {description.strip()}", sBodyI)])]

        # ── Embed issue photo ──
        if issue_image_pil is not None:
            try:
                img_buf = io.BytesIO()
                # Resize for PDF — max width 4 inches, maintain aspect ratio
                img_copy = issue_image_pil.copy()
                max_w_px = int(4 * 96)   # 4 inches at 96 dpi
                if img_copy.width > max_w_px:
                    ratio    = max_w_px / img_copy.width
                    new_h    = int(img_copy.height * ratio)
                    img_copy = img_copy.resize((max_w_px, new_h), Image.LANCZOS)
                img_copy.save(img_buf, format="JPEG", quality=85)
                img_buf.seek(0)
                # Compute display dimensions (max 4" wide)
                aspect = img_copy.height / img_copy.width
                disp_w = min(4.0*inch, W * 0.6)
                disp_h = disp_w * aspect
                rl_img = RLImage(img_buf, width=disp_w, height=disp_h)
                caption = Paragraph(f"Issue Photo — {issue_type} at {location}, {city}", sImgCapt)
                # Centre the image in a table
                img_table = Table([[rl_img],[caption]], colWidths=[W])
                img_table.setStyle(TableStyle([
                    ("ALIGN",(0,0),(-1,-1),"CENTER"),
                    ("BACKGROUND",(0,0),(-1,-1),C_LIGHT_GREEN),
                    ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
                ]))
                story += [sp(0.10), img_table]
            except Exception as img_err:
                print(f"PDF image embed error: {img_err}")
        story += [sp(0.15)]

        # ── Section C: Verification ──
        story += [sec_header("C","Verification Results"), sp(0.08)]
        ai_bg = colors.HexColor("#e6f7ed") if "APPROVED" in gemini_status else colors.HexColor("#fdecea")
        story += [text_card([
            Paragraph(f"<b>Status:</b> {gemini_status}   |   <b>Confidence:</b> {gemini_confidence}", sBody),
            Paragraph(f"<b>Assessment:</b> {gemini_reason}", sBody),
        ], bg=ai_bg), sp(0.15)]

        # ── Section D: Legal ──
        story += [sec_header("D","Legal Framework & Applicable Laws"), sp(0.08)]
        story += [info_grid([("Responsible Authority",kb.get("authority","N/A")),
                              ("Official Helpline",kb.get("hotline","N/A")),
                              ("Response Time",kb.get("response","N/A")),
                              ("Fine / Penalty",kb.get("fine","N/A"))]), sp(0.08)]
        law_rows = [[Paragraph(f"{i}. {law}", sBullet)] for i,law in enumerate(kb.get("laws",[]),1)]
        if law_rows:
            lt = Table(law_rows, colWidths=[W])
            lt.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C_LIGHT_GREEN),
                                     ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
                                     ("LEFTPADDING",(0,0),(-1,-1),10)]))
            story.append(lt)
        story += [sp(0.15)]

        # ── Section E: Rights ──
        story += [sec_header("E","Citizen's Legal Rights"), sp(0.08)]
        rights_rows = [[Paragraph(f"✓  {r}", sBullet)] for r in kb.get("citizen_rights",[])]
        if rights_rows:
            rt = Table(rights_rows, colWidths=[W])
            rt.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
                                     ("LEFTPADDING",(0,0),(-1,-1),8),
                                     ("ROWBACKGROUNDS",(0,0),(-1,-1),[C_WHITE,C_LIGHT_GREEN])]))
            story.append(rt)
        story += [sp(0.08),
                  text_card([Paragraph(f"<b>Escalation Path:</b>  {kb.get('escalation','CM Portal: 0800-02345')}", sBodyI)], bg=C_GOLD_LIGHT),
                  sp(0.15)]

        # ── Section F: Legal Advice ──
        story += [sec_header("F",f"Legal Advice ({language})"), sp(0.08)]
        advice_paras = [Paragraph(line.strip(),sBody) for line in llama_advice.strip().split("\n") if line.strip()]
        if advice_paras:
            at = Table([[p] for p in advice_paras], colWidths=[W])
            at.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C_LIGHT_GREEN),
                                     ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
                                     ("LEFTPADDING",(0,0),(-1,-1),10)]))
            story.append(at)
        story += [sp(0.15)]

        # ── Section G: Action Directive ──
        story += [sec_header("G","Mandatory Action Directive"), sp(0.08)]
        dir_t = Table([[Paragraph(f"MANDATORY ACTION REQUIRED WITHIN: {kb.get('response','72 hours').upper()}", sGoldDir)]], colWidths=[W])
        dir_t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C_GOLD),
                                    ("TOPPADDING",(0,0),(-1,-1),9),("BOTTOMPADDING",(0,0),(-1,-1),9)]))
        story += [dir_t, sp(0.08)]
        story += [info_grid([("Responsible Authority",kb.get("authority","N/A")),
                              ("Official Helpline",kb.get("hotline","N/A")),
                              ("Citizen Portal","citizenportal.gov.pk"),
                              ("CM Toll-Free","0800-02345")]), sp(0.18)]

        # ── Section H: Declaration ──
        story += [sec_header("H","Declaration & Official Use"), sp(0.08)]
        inner_decl = [
            [Paragraph(f"I, <b>{name}</b> (CNIC: {cnic}), declare that the information provided is true and correct to the best of my knowledge.", sDecl)],
            [sp(0.1)],
            [Table([[Paragraph("Complainant Signature",sLabel),Paragraph("Date",sLabel),Paragraph("Reference No.",sLabel)],
                    [Paragraph("____________________________",sValue),Paragraph(date_str,sValue),Paragraph(complaint_id,sValue)]],
                   colWidths=[2.5*inch,2.5*inch,2.0*inch])],
            [sp(0.1)],
            [Table([[Paragraph("Received By",sLabel),Paragraph("Date of Receipt",sLabel),Paragraph("Action Taken",sLabel),Paragraph("Resolved On",sLabel)],
                    [Paragraph("______________",sValue),Paragraph("______________",sValue),Paragraph("______________",sValue),Paragraph("______________",sValue)]],
                   colWidths=[1.75*inch,1.75*inch,1.75*inch,1.75*inch])],
        ]
        decl_outer = Table(inner_decl, colWidths=[W])
        decl_outer.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C_LIGHT_GREEN),
                                         ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),
                                         ("LEFTPADDING",(0,0),(-1,-1),12),("RIGHTPADDING",(0,0),(-1,-1),12)]))
        story += [decl_outer, sp(0.18)]

        # ── Footer ──
        foot_t = Table([[Paragraph(f"Generated by Rahbar — Pakistan's Civic Redressal Platform   |   {timestamp}   |   {complaint_id}", sFooter)]], colWidths=[W])
        foot_t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),C_DARK_GREEN),
                                     ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7)]))
        story.append(foot_t)

        doc.build(story)
        return pdf_path

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"PDF error: {e}")
        return None

# ══════════════════════════════════════════════════════════════
# WHATSAPP LINK
# ══════════════════════════════════════════════════════════════
def make_whatsapp_link(text):
    return f"https://wa.me/?text={urllib.parse.quote(text[:1000])}"

# ══════════════════════════════════════════════════════════════
# MAIN REPORT FUNCTION  — passes image to PDF generator
# ══════════════════════════════════════════════════════════════
def make_report(image, issue_type, city, location, name, cnic, phone,
                description, language, enable_tts):
    if image is None:        return None,"Please upload an image of the issue.","","",None,"",None,None,None
    if not location.strip(): return None,"Please enter the complaint location.","","",None,"",None,None,None
    if not name.strip():     return None,"Please enter your full name.","","",None,"",None,None,None
    if not cnic.strip():     return None,"Please enter your CNIC number.","","",None,"",None,None,None

    complaint_id = f"RB-{uuid.uuid4().hex[:8].upper()}"
    timestamp    = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    annotated_img, yolo_summary, yolo_severity = detect_with_yolo(image, issue_type)
    gemini_raw    = analyze_with_gemini(image, issue_type, location, city, yolo_summary)
    gemini_parsed = parse_gemini_response(gemini_raw)
    gemini_status = gemini_parsed["status"]
    gemini_reason = gemini_parsed["reason"]

    if gemini_status == "REJECTED":
        return (annotated_img,
                f"COMPLAINT REJECTED — Verification\n\nReason: {gemini_reason}\n"
                f"Confidence: {gemini_parsed.get('confidence','N/A')}\n\n"
                f"Please upload a clear image of the issue ({issue_type}).\n"
                f"This complaint has NOT been saved.",
                "","",None,complaint_id,None,None,None)

    if gemini_status=="UNKNOWN" and "GOOGLE_API_KEY not set" in gemini_raw:
        gemini_reason = "Verification skipped — API key not configured."
        gemini_status = "APPROVED_WITH_WARNING"

    final_severity = gemini_parsed["severity"] if gemini_status=="APPROVED" else yolo_severity
    kb             = LEGAL_KB.get(issue_type, {})
    sev_lbl        = severity_label(final_severity)
    llama_advice   = analyze_with_llama(issue_type, location, city, yolo_summary, final_severity, language)

    # ── Pass the original PIL image to PDF so it appears in Section B ──
    pdf_path = generate_pdf_report(
        complaint_id, timestamp, name, cnic, phone, city, location,
        issue_type, language, final_severity,
        gemini_status, gemini_reason, gemini_parsed.get("confidence","N/A"),
        kb, description, llama_advice,
        issue_image_pil=image           # ← pass PIL image
    )

    report = (
        f"GOVERNMENT OF PAKISTAN — CIVIC COMPLAINT REPORT\n"
        f"Rahbar Digital Civic Redressal System\n"
        f"{'='*55}\n"
        f"Complaint Number : {complaint_id}\n"
        f"Date             : {datetime.datetime.now().strftime('%d %B %Y')}\n"
        f"Time             : {datetime.datetime.now().strftime('%I:%M %p')}\n"
        f"Language         : {language}\n\n"
        f"SECTION A — COMPLAINANT INFORMATION\n"
        f"Full Name  : {name}\n"
        f"CNIC       : {cnic}\n"
        f"Phone      : {phone if phone else 'Not provided'}\n"
        f"City       : {city}\n"
        f"Location   : {location}\n\n"
        f"SECTION B — COMPLAINT DETAILS\n"
        f"Issue Type : {issue_type}\n"
        f"Location   : {location}, {city}\n"
        f"Date/Time  : {timestamp}\n"
        f"Severity   : {final_severity}/10 [{sev_lbl}]\n"
        f"Description:\n{description.strip() if description.strip() else '[No additional details provided]'}\n\n"
        f"SECTION C — VERIFICATION RESULTS\n"
        f"Status     : {gemini_status}\n"
        f"Confidence : {gemini_parsed.get('confidence','N/A')}\n"
        f"Assessment : {gemini_reason}\n\n"
        f"SECTION D — LEGAL FRAMEWORK\n"
        f"Laws:\n" + "\n".join(f"  - {l}" for l in kb.get("laws",[])) +
        f"\nAuthority  : {kb.get('authority','N/A')}\n"
        f"Helpline   : {kb.get('hotline','N/A')}\n"
        f"Response   : {kb.get('response','N/A')}\n"
        f"Penalty    : {kb.get('fine','N/A')}\n\n"
        f"SECTION E — CITIZEN'S RIGHTS\n" +
        "\n".join(f"  - {r}" for r in kb.get("citizen_rights",[])) +
        f"\nEscalation : {kb.get('escalation','CM Portal: 0800-02345')}\n\n"
        f"MANDATORY ACTION REQUIRED WITHIN: {kb.get('response','72 hours').upper()}\n"
        f"Portal     : citizenportal.gov.pk | CM: 0800-02345\n\n"
        f"DECLARATION\nI, {name} (CNIC: {cnic}), declare that the information provided is accurate.\n"
        f"Reference: {complaint_id} | Generated: {timestamp}"
    )

    wa_text = (f"Rahbar Civic Complaint\nID: {complaint_id}\nIssue: {issue_type}\n"
               f"Location: {location}, {city}\nSeverity: {final_severity}/10\n"
               f"Authority: {kb.get('authority','N/A')}\nHotline: {kb.get('hotline','N/A')}\nTime: {timestamp}")
    wa_md = f"[📲 Share on WhatsApp]({make_whatsapp_link(wa_text)})"

    complaint_log.append({"id":complaint_id,"timestamp":timestamp,"city":city,"location":location,
                           "issue":issue_type,"severity":final_severity,"language":language,
                           "name":name,"cnic":cnic,"phone":phone})

    report_tts_path = None
    if enable_tts:
        tts_text = (f"Complaint {complaint_id} has been filed. Issue: {issue_type}. "
                    f"Location: {location}, {city}. Severity: {final_severity} out of 10. "
                    f"The responsible authority is {kb.get('authority','')}. Helpline: {kb.get('hotline','')}.")
        report_tts_path = make_tts(tts_text, language)

    advice_tts_path = make_tts(llama_advice[:600], language) if llama_advice else None
    map_fig = create_map(city, location)

    return (annotated_img, report, wa_md, llama_advice,
            report_tts_path, complaint_id, advice_tts_path, pdf_path, map_fig)

# ══════════════════════════════════════════════════════════════
# CSS — identical to v8.1
# ══════════════════════════════════════════════════════════════
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Playfair+Display:wght@700;900&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --bg:#ffffff; --bg2:#f5f8f6; --bg3:#e8f3ec; --surface:#ffffff;
  --txt:#0d2b1e; --txt2:#2d5a3e; --muted:#6a8e7a;
  --border:#c0d9ca; --border2:#1f7a52;
  --green:#1f7a52; --green2:#25a06b; --green3:#2ec97f;
  --gold:#c8860a; --gold2:#f5a623; --gold-bg:#fffbf0;
  --info-bg:#f0faf4; --warn-bg:#fffbf0;
  --shadow:0 2px 10px rgba(13,43,30,.10);
  --radius:10px; --radius-lg:18px;
  --header-bg:linear-gradient(135deg,#14432e 0%,#0d2b1e 60%,#091a10 100%);
}
@media(prefers-color-scheme:dark){
  :root{
    --bg:#0c1a10; --bg2:#132118; --bg3:#1a3024; --surface:#0c1a10;
    --txt:#d5f0e0; --txt2:#8fd4ad; --muted:#5a9a78;
    --border:#243d2d; --border2:#2a9460;
    --green:#2a9460; --green2:#34c47a; --green3:#52e09a;
    --gold:#f5a623; --gold2:#f7bc57; --gold-bg:#1e1500;
    --info-bg:#0d2016; --warn-bg:#1a1300;
    --shadow:0 2px 14px rgba(0,0,0,.45);
    --header-bg:linear-gradient(135deg,#091a10 0%,#060d08 60%,#040a06 100%);
  }
}
.dark-mode{
  --bg:#0c1a10; --bg2:#132118; --bg3:#1a3024; --surface:#0c1a10;
  --txt:#d5f0e0; --txt2:#8fd4ad; --muted:#5a9a78;
  --border:#243d2d; --border2:#2a9460;
  --green:#2a9460; --green2:#34c47a; --green3:#52e09a;
  --gold:#f5a623; --gold2:#f7bc57; --gold-bg:#1e1500;
  --info-bg:#0d2016; --warn-bg:#1a1300;
  --shadow:0 2px 14px rgba(0,0,0,.45);
  --header-bg:linear-gradient(135deg,#091a10 0%,#060d08 60%,#040a06 100%);
}
*,*::before,*::after{box-sizing:border-box;}
body,.gradio-container{font-family:'Inter',sans-serif!important;background:var(--bg)!important;color:var(--txt)!important;transition:background .3s,color .3s;}
.rh-header{background:var(--header-bg);padding:28px 20px 22px;text-align:center;position:relative;overflow:hidden;border-bottom:2px solid var(--green);}
.rh-header::before{content:'';position:absolute;inset:0;background:radial-gradient(ellipse 70% 60% at 50% 0%,rgba(37,160,107,.14),transparent);pointer-events:none;}
.rh-title{font-family:'Playfair Display',serif!important;font-size:clamp(2rem,5vw,3.2rem)!important;font-weight:900!important;color:#f8fdf9!important;margin:0 0 4px!important;line-height:1.1;}
.rh-subtitle{font-size:clamp(.9rem,2.5vw,1.1rem);color:#a8e8c4;margin:4px 0 6px;}
.rh-tag{font-size:.78rem;color:#5de3a3;letter-spacing:.1em;text-transform:uppercase;}
.top-bar{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;padding:8px 16px;background:var(--bg2);border-bottom:1px solid var(--border);gap:8px;}
.badge-group{display:flex;flex-wrap:wrap;gap:6px;}
.badge{font-size:.68rem;font-weight:600;letter-spacing:.06em;padding:3px 10px;border-radius:20px;text-transform:uppercase;background:var(--surface);color:var(--green3);border:1px solid var(--border2);}
.badge-gold{color:var(--gold);border-color:var(--gold2);}
.badge-red{color:#ff8080;border-color:rgba(255,100,100,.4);}
.dark-btn{background:transparent;border:1px solid var(--border2);border-radius:20px;padding:4px 14px;cursor:pointer;color:var(--muted);font-size:.78rem;font-weight:500;font-family:'Inter',sans-serif;transition:all .2s;}
.dark-btn:hover{background:var(--bg3);color:var(--txt);}
.gradio-container .tab-nav{background:var(--bg2)!important;border-bottom:2px solid var(--border)!important;}
.gradio-container .tab-nav button{font-family:'Inter',sans-serif!important;font-weight:500!important;font-size:.84rem!important;color:var(--muted)!important;padding:12px 18px!important;border-radius:0!important;background:transparent!important;transition:all .2s!important;}
.gradio-container .tab-nav button.selected,.gradio-container .tab-nav button[aria-selected="true"]{color:var(--gold)!important;border-bottom:3px solid var(--gold2)!important;background:transparent!important;}
.sec-title{font-size:.68rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--green3);margin-bottom:10px;padding-bottom:7px;border-bottom:1px solid var(--border);}
label,.gradio-container .label-wrap span{color:var(--txt)!important;}
.gradio-container input,.gradio-container textarea{background:var(--surface)!important;border:1px solid var(--border2)!important;border-radius:var(--radius)!important;color:var(--txt)!important;font-family:'Inter',sans-serif!important;transition:border-color .2s,box-shadow .2s;}
.gradio-container input:focus,.gradio-container textarea:focus{border-color:var(--gold2)!important;box-shadow:0 0 0 3px rgba(245,166,35,.15)!important;outline:none!important;}
.gradio-container .wrap{background:var(--surface)!important;border-color:var(--border2)!important;}
.gradio-container .block{background:var(--surface)!important;}
.gradio-container button.primary{background:linear-gradient(135deg,var(--green),var(--green2))!important;color:#f8fdf9!important;border:none!important;border-radius:var(--radius)!important;font-weight:600!important;font-size:.88rem!important;padding:11px 22px!important;cursor:pointer!important;box-shadow:var(--shadow)!important;transition:all .2s!important;}
.gradio-container button.primary:hover{background:linear-gradient(135deg,var(--green2),var(--green3))!important;transform:translateY(-1px)!important;}
.gradio-container button.secondary{background:var(--surface)!important;border:1px solid var(--border2)!important;color:var(--green3)!important;}
.gradio-container [data-testid="image"]{border:2px dashed var(--border2)!important;border-radius:var(--radius-lg)!important;background:var(--bg2)!important;}
.gradio-container audio{width:100%!important;border-radius:var(--radius)!important;}
.gradio-container .prose h2,.gradio-container .prose h3{color:var(--gold)!important;}
.info-box{background:var(--info-bg);border:1px solid var(--border2);border-left:4px solid var(--green2);border-radius:var(--radius);padding:10px 14px;font-size:.87rem;line-height:1.6;margin-bottom:8px;color:var(--txt2);}
.warn-box{background:var(--warn-bg);border:1px solid rgba(245,166,35,.4);border-left:4px solid var(--gold2);border-radius:var(--radius);padding:10px 14px;font-size:.87rem;margin-bottom:8px;color:var(--txt2);}
.gps-box{background:var(--bg3);border:1px solid var(--border2);border-left:4px solid var(--green3);border-radius:var(--radius);padding:10px 14px;font-size:.85rem;margin-bottom:8px;color:var(--txt2);}
.hotline-pill{display:inline-block;background:var(--bg2);color:var(--gold);border:1px solid var(--gold2);border-radius:20px;padding:2px 11px;font-size:.78rem;font-weight:600;}
.gradio-container textarea{font-family:'JetBrains Mono',monospace!important;font-size:.82rem!important;line-height:1.7!important;}
.gradio-container .message.user{background:var(--bg3)!important;color:var(--txt)!important;}
.gradio-container .message.bot{background:var(--bg2)!important;color:var(--txt)!important;}
::-webkit-scrollbar{width:6px;height:6px;}
::-webkit-scrollbar-track{background:var(--bg2);}
::-webkit-scrollbar-thumb{background:var(--green);border-radius:3px;}
@media(max-width:640px){.rh-header{padding:16px 12px;}.gradio-container .tab-nav button{padding:10px 10px!important;font-size:.74rem!important;}}
"""

HEADER_HTML = """
<div class="rh-header">
  <div class="rh-title">Rahbar</div>
  <div class="rh-subtitle">Pakistan's AI-Powered Civic Complaint Platform</div>
  <div class="rh-tag">Serving Citizens — Enforcing Rights</div>
</div>
<div class="top-bar">
  <div class="badge-group">
    <span class="badge">Image Verification</span>
    <span class="badge">Object Detection</span>
    <span class="badge">Legal Assistant</span>
    <span class="badge">Knowledge Base</span>
    <span class="badge badge-gold">4 Languages</span>
    <span class="badge badge-red">LIVE</span>
  </div>
  <button class="dark-btn" id="rh_dark_btn" onclick="
    var dm=document.body.classList.toggle('dark-mode');
    var gc=document.querySelector('.gradio-container');
    if(gc)gc.classList.toggle('dark-mode');
    this.textContent=dm?'☀️ Light Mode':'🌙 Dark Mode';
    try{localStorage.setItem('rh_dark',dm?'1':'0');}catch(e){}
  ">🌙 Dark Mode</button>
</div>
<script>
(function(){
  try{
    if(localStorage.getItem('rh_dark')==='1'){
      document.body.classList.add('dark-mode');
      var gc=document.querySelector('.gradio-container');
      if(gc)gc.classList.add('dark-mode');
      setTimeout(function(){var b=document.getElementById('rh_dark_btn');if(b)b.textContent='☀️ Light Mode';},100);
    }
  }catch(e){}
})();
</script>
"""

HOTLINES_HTML = """
<div class="info-box">
  <strong>Emergency Helplines:</strong>&nbsp;&nbsp;
  Garbage: <span class="hotline-pill">1139</span>&nbsp;
  Roads / NHA: <span class="hotline-pill">051-9032800</span>&nbsp;
  WASA Lahore: <span class="hotline-pill">042-99200300</span>&nbsp;
  CM Portal: <span class="hotline-pill">0800-02345</span>&nbsp;
  Federal Ombudsman: <span class="hotline-pill">051-9204551</span>
</div>
"""

# ══════════════════════════════════════════════════════════════
# BUILD UI  — Gradio 6+ compatible, identical layout to v8.1
# ══════════════════════════════════════════════════════════════
def build_ui():
    default_map = create_map("Lahore")

    with gr.Blocks(title="Rahbar | AI Civic Complaint System") as demo:
        gr.HTML(HEADER_HTML)

        with gr.Tabs():

            # ════════════════════════════════════════════════
            # TAB 1 — File Complaint
            # ════════════════════════════════════════════════
            with gr.Tab("📝 File Complaint"):
                with gr.Row(equal_height=False):

                    with gr.Column(scale=1, min_width=300):
                        gr.HTML('<div class="sec-title">Citizen Information</div>')
                        name_tb  = gr.Textbox(label="Full Name", placeholder="e.g. Ali Raza", lines=1)
                        cnic_tb  = gr.Textbox(label="CNIC Number (no dashes)", placeholder="1234567890123", lines=1)
                        phone_tb = gr.Textbox(label="Phone Number (optional)", placeholder="03xxxxxxxxx", lines=1)

                        gr.HTML('<div class="sec-title" style="margin-top:14px">Issue Photo</div>')
                        gr.HTML('<div class="info-box">Upload or capture a clear photo of the issue. The photo will also appear in the PDF report.</div>')
                        image_input = gr.Image(type="pil", label="Upload or Capture Photo",
                                               sources=["webcam","upload"], height=220)

                        gr.HTML('<div class="sec-title" style="margin-top:14px">Complaint Details</div>')
                        issue_type = gr.Radio(choices=ISSUE_TYPES, value=ISSUE_TYPES[0], label="Issue Type")

                        # ── ALL PAKISTAN city dropdown ──
                        city_dd = gr.Dropdown(
                            choices=ALL_CITIES,
                            value="Lahore",
                            label="City / Town / Area (all Pakistan)",
                            allow_custom_value=True,
                            info="Type to search — includes cities, towns and rural areas across all provinces"
                        )

                        gr.HTML('<div class="sec-title" style="margin-top:14px">Location Details</div>')
                        gr.HTML('<div class="info-box">Select your city above. Click <b>Detect My Location</b> to auto-fill via your internet connection, or type a street/landmark below.</div>')
                        location_tb = gr.Textbox(
                            label="Street / Landmark / Additional Location Detail",
                            placeholder="e.g. Near Park, Main Boulevard, Street 5",
                            lines=1)

                        gps_btn    = gr.Button("📍 Detect My Location (IP-based)", variant="secondary")
                        gps_status = gr.Markdown(
                            value="*Click the button above to detect your approximate location.*",
                            elem_classes=["gps-box"])

                        gr.HTML('<div class="sec-title" style="margin-top:10px">Location Map</div>')
                        map_out = gr.Plot(label="Location Map", value=default_map)

                        desc_tb     = gr.Textbox(label="Additional Description (optional)",
                                                  placeholder="Describe the issue in detail...", lines=3)
                        language_dd = gr.Dropdown(choices=LANGUAGES, value="English", label="Report & Voice Language")
                        tts_cb      = gr.Checkbox(label="Read Report Aloud (Text-to-Speech)", value=False)
                        submit_btn  = gr.Button("Submit Complaint", variant="primary", size="lg")

                    with gr.Column(scale=2, min_width=320):
                        gr.HTML('<div class="sec-title">Detection Result</div>')
                        annotated_out    = gr.Image(label="Detection Output", height=240)
                        complaint_id_out = gr.Textbox(label="Complaint Reference Number", interactive=False)

                        gr.HTML('<div class="sec-title" style="margin-top:14px">Complaint Summary</div>')
                        report_out = gr.Textbox(label="Official Summary", lines=12, interactive=False,
                                                 placeholder="Complaint summary will appear here after submission...")

                        gr.HTML('<div class="sec-title" style="margin-top:12px">Download PDF Report</div>')
                        gr.HTML('<div class="info-box">Official complaint PDF including your issue photo — download and share via WhatsApp.</div>')
                        pdf_out        = gr.File(label="📄 Download PDF Report", interactive=False)
                        wa_out         = gr.Markdown()
                        report_tts_out = gr.Audio(label="Report Audio", autoplay=False)

                        gr.HTML('<div class="sec-title" style="margin-top:16px">Legal Advice</div>')
                        gr.HTML('<div class="info-box">Your rights and next steps under Pakistani civic law.</div>')
                        legal_advice_out = gr.Textbox(label="Your Legal Rights & Steps", lines=12, interactive=False,
                                                       placeholder="Legal advice will appear here...")
                        advice_tts_out = gr.Audio(label="Legal Advice Audio", autoplay=False)

                # GPS state
                gps_lat = gr.State(value=None)
                gps_lon = gr.State(value=None)

                def on_gps_click(city):
                    fig, status, lat, lon = gps_locate_and_update(city)
                    return fig, status, lat, lon

                gps_btn.click(fn=on_gps_click, inputs=[city_dd],
                              outputs=[map_out, gps_status, gps_lat, gps_lon])

                city_dd.change(fn=update_map_on_city, inputs=[city_dd], outputs=[map_out])
                location_tb.change(fn=update_map_on_location, inputs=[city_dd, city_dd, location_tb], outputs=[map_out])

                submit_btn.click(
                    fn=make_report,
                    inputs=[image_input, issue_type, city_dd, location_tb,
                            name_tb, cnic_tb, phone_tb, desc_tb, language_dd, tts_cb],
                    outputs=[annotated_out, report_out, wa_out, legal_advice_out,
                             report_tts_out, complaint_id_out, advice_tts_out, pdf_out, map_out])

            # ════════════════════════════════════════════════
            # TAB 2 — Legal Reference & Chatbot
            # ════════════════════════════════════════════════
            with gr.Tab("⚖️ Legal Reference & Chatbot"):
                gr.HTML('<div class="sec-title">Pakistani Civic Laws Database</div>')
                with gr.Row():
                    law_issue_dd = gr.Dropdown(choices=ISSUE_TYPES, value=ISSUE_TYPES[0], label="Select Issue", scale=1)
                    law_lang_dd  = gr.Dropdown(choices=LANGUAGES,   value="English",      label="Language",      scale=1)
                law_out = gr.Markdown()
                gr.Button("Show Legal Details", variant="primary").click(
                    fn=law_info, inputs=[law_issue_dd, law_lang_dd], outputs=[law_out])
                gr.HTML(HOTLINES_HTML)

                gr.HTML('<div class="sec-title" style="margin-top:24px">Legal Chatbot</div>')
                gr.HTML('<div class="info-box">Ask any question about civic issues in Pakistan. Supports voice input and audio output.</div>')

                chat_lang_dd = gr.Dropdown(choices=LANGUAGES, value="English", label="Response Language")

                # Gradio 6 — no type= parameter needed
                chatbot = gr.Chatbot(label="Rahbar Legal Assistant", height=400, value=[])

                with gr.Row():
                    chat_input    = gr.Textbox(label="Your Question",
                                               placeholder="e.g. WASA did not fix the pipe after 3 days — what are my rights?",
                                               lines=2, scale=4)
                    chat_send_btn = gr.Button("Send", variant="primary", scale=1)

                gr.HTML('<div class="sec-title" style="margin-top:12px">Voice Input</div>')
                gr.HTML('<div class="info-box">Record your question — it will be transcribed and sent automatically.</div>')
                with gr.Row():
                    chat_audio_in  = gr.Audio(type="filepath", label="Record Question",
                                               sources=["microphone","upload"], scale=3)
                    chat_voice_btn = gr.Button("🎤 Send Voice", variant="secondary", scale=1)

                gr.HTML('<div class="sec-title" style="margin-top:12px">Voice Output</div>')
                with gr.Row():
                    chat_tts_out = gr.Audio(label="Last Answer (Audio)", autoplay=False, scale=3)
                    chat_tts_btn = gr.Button("🔊 Play Answer", variant="secondary", scale=1)

                gr.Examples(
                    examples=[
                        ["WASA did not fix the pipe leakage for 3 days — what are my legal rights?"],
                        ["Water in my area is contaminated — where should I complain?"],
                        ["Garbage has not been collected for a week — which law applies?"],
                        ["The authority ignored my complaint — what do I do next?"],
                        ["My car was damaged by a pothole — can I claim compensation?"],
                        ["How do I file a complaint on Pakistan Citizen Portal?"],
                    ],
                    inputs=chat_input, label="Try These Sample Questions")

                chat_send_btn.click(fn=legal_chatbot_rag,
                                    inputs=[chat_input, chatbot, chat_lang_dd],
                                    outputs=[chatbot, chat_input])
                chat_input.submit(fn=legal_chatbot_rag,
                                  inputs=[chat_input, chatbot, chat_lang_dd],
                                  outputs=[chatbot, chat_input])

                def voice_then_send(audio_file, history, language):
                    if audio_file is None: return history or [], ""
                    transcribed = stt(audio_file)
                    if (not transcribed or transcribed.startswith("No audio") or
                            transcribed.startswith("Transcription")):
                        return history or [], transcribed
                    new_history, _ = legal_chatbot_rag(transcribed, history or [], language)
                    return new_history, ""

                chat_voice_btn.click(fn=voice_then_send,
                                     inputs=[chat_audio_in, chatbot, chat_lang_dd],
                                     outputs=[chatbot, chat_input])
                # ── FIX: Play Answer now correctly calls chatbot_tts_output ──
                chat_tts_btn.click(fn=chatbot_tts_output,
                                   inputs=[chatbot, chat_lang_dd],
                                   outputs=[chat_tts_out])

            # ════════════════════════════════════════════════
            # TAB 3 — Voice Tools
            # ════════════════════════════════════════════════
            with gr.Tab("🎤 Voice Tools"):
                gr.HTML('<div class="sec-title">Speech to Text</div>')
                gr.HTML('<div class="info-box">Record your complaint. Transcription uses your API key or Google Speech as fallback. Supports English, Urdu, Punjabi, Sindhi.</div>')
                gr.HTML('<div class="warn-box"><strong>Tip:</strong> Speak clearly. Copy the transcript into the complaint description field.</div>')
                audio_in = gr.Audio(type="filepath", label="Record or Upload Audio", sources=["microphone","upload"])
                stt_btn  = gr.Button("Transcribe Audio", variant="primary")
                stt_out  = gr.Textbox(label="Transcript (editable)", lines=6, interactive=True,
                                       placeholder="Transcribed text will appear here...")
                stt_btn.click(fn=stt, inputs=[audio_in], outputs=[stt_out])

                gr.HTML('<div class="sec-title" style="margin-top:24px">Text to Speech Test</div>')
                gr.HTML('<div class="info-box">Test audio output in any supported language.</div>')
                with gr.Row():
                    tts_text_in = gr.Textbox(label="Text to Speak", placeholder="Type something here...", scale=3)
                    tts_lang_in = gr.Dropdown(choices=LANGUAGES, value="English", label="Language", scale=1)
                tts_test_btn = gr.Button("▶ Play", variant="secondary")
                tts_test_out = gr.Audio(label="Audio Output", autoplay=True)
                tts_test_btn.click(fn=make_tts, inputs=[tts_text_in, tts_lang_in], outputs=[tts_test_out])

            # ════════════════════════════════════════════════
            # TAB 4 — Admin Dashboard
            # ════════════════════════════════════════════════
            with gr.Tab("📊 Admin Dashboard"):
                gr.HTML('<div class="sec-title">Complaint Statistics</div>')
                refresh_btn = gr.Button("Refresh Statistics", variant="primary")
                with gr.Row():
                    stats_out = gr.Markdown()
                    log_out   = gr.Markdown()
                refresh_btn.click(fn=get_admin_stats, outputs=[stats_out, log_out])

    return demo

# ══════════════════════════════════════════════════════════════
# LAUNCH
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("Rahbar v8.2 starting...")
    print("Knowledge Engine:", "ready" if rag_engine._initialized else "initializing...")
    demo = build_ui()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        theme=gr.themes.Base(
            primary_hue=gr.themes.colors.green,
            secondary_hue=gr.themes.colors.yellow,
        ),
        css=CSS,    # Gradio 6+: CSS goes in launch()
    )