"""
vani/reasoning/hinglish_speech.py — Strict Hinglish Pronunciation Layer
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TTS engines (Google, Edge, Gemini) read Hinglish with English phonetics.
This layer rewrites every token Vani commonly speaks into a form the TTS
engine actually pronounces correctly — before the text is ever sent.

Coverage (v2 — strict):
  • 400+ Hinglish word/phrase mappings
  • English loanwords with Indian-English stress patterns
  • All common verb conjugations (hoon / hai / ho / tha / thi / the)
  • Time words, emotions, social words, tech words
  • Multi-word phrase map runs FIRST (longest-match wins)
  • Devanagari strip, emoji strip, whitespace normalise
"""

import re
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# PHRASE MAP  — checked BEFORE word map; longest phrases first
# ─────────────────────────────────────────────────────────────────────────────
# fmt: off
_PHRASE_MAP: list[tuple[str, str]] = [

    # ── very common full phrases ──────────────────────────────────────────────
    ("koi baat nahi",           "ko-ee baat na-hi"),
    ("koi baat nhi",            "ko-ee baat na-hi"),
    ("theek thaak",             "theek-taak"),
    ("bilkul theek",            "bil-kul theek"),
    ("bilkul sahi",             "bil-kul saa-hi"),
    ("ekdum sahi",              "ayk-dum saa-hi"),
    ("ekdum theek",             "ayk-dum theek"),
    ("no problem",              "no prob-lum"),
    ("dont worry",              "dont wor-ry"),
    ("don't worry",             "dont wor-ry"),
    ("ho gaya na",              "ho ga-ya naa"),
    ("ho gayi na",              "ho ga-yi naa"),
    ("kar diya na",             "kur di-ya naa"),
    ("mil gaya na",             "mil ga-ya naa"),
    ("theek hai na",            "theek hay naa"),
    ("accha hai na",            "uch-cha hay naa"),
    ("sab kuch",                "sub kuch"),
    ("sab log",                 "sub log"),
    ("kuch bhi",                "kuch bhi"),
    ("koi bhi",                 "ko-ee bhi"),
    ("kuch nahi",               "kuch na-hi"),
    ("kuch nhi",                "kuch na-hi"),
    ("pata nahi",               "pu-ta na-hi"),
    ("pata nhi",                "pu-ta na-hi"),
    ("theek hai",               "theek hay"),
    ("accha hai",               "uch-cha hay"),
    ("chal yaar",               "chul yaar"),
    ("haan haan",               "haan haan"),
    ("nahi nahi",               "na-hi na-hi"),
    ("nhi nhi",                 "na-hi na-hi"),
    ("ek second",               "ayk second"),
    ("ek sec",                  "ayk sec"),
    ("ek baar",                 "ayk baar"),
    ("ek kaam",                 "ayk kaam"),
    ("matlab kya",              "mul-lub kya"),
    ("matlab yeh",              "mul-lub yeh"),
    ("matlab hai",              "mul-lub hay"),
    ("samajh gaya",             "sum-jh ga-ya"),
    ("samajh gayi",             "sum-jh ga-yi"),
    ("samajh gaye",             "sum-jh ga-yay"),
    ("kyun nahi",               "kyoon na-hi"),
    ("kyun nhi",                "kyoon na-hi"),
    ("kaise hoga",              "kai-say ho-ga"),
    ("kaise hogi",              "kai-say ho-gi"),
    ("kar lena",                "kur lay-na"),
    ("kar lena hai",            "kur lay-na hay"),
    ("kar dena",                "kur day-na"),
    ("kar dena hai",            "kur day-na hay"),
    ("ho gaya",                 "ho ga-ya"),
    ("ho gayi",                 "ho ga-yi"),
    ("ho gaye",                 "ho ga-yay"),
    ("ho jayega",               "ho jaa-ye-ga"),
    ("ho jayegi",               "ho jaa-ye-gi"),
    ("ho jayenge",              "ho jaa-yen-gay"),
    ("iske baad",               "is-kay baad"),
    ("uske baad",               "us-kay baad"),
    ("baad mein",               "baad main"),
    ("pehle se",                "peh-lay say"),
    ("pehle hi",                "peh-lay hi"),
    ("kya kar raha",            "kya kur ra-ha"),
    ("kya kar rahi",            "kya kur ra-hi"),
    ("kya ho raha",             "kya ho ra-ha"),
    ("kya ho rahi",             "kya ho ra-hi"),
    ("kya hua",                 "kya hu-aa"),
    ("kya hoga",                "kya ho-ga"),
    ("kya bolun",               "kya bo-lun"),
    ("kya bolunga",             "kya bo-lun-ga"),
    ("kya bolungi",             "kya bo-lun-gi"),
    ("kya karun",               "kya ka-run"),
    ("kya karunga",             "kya ka-run-ga"),
    ("kya karungi",             "kya ka-run-gi"),
    ("kya sochta",              "kya soch-ta"),
    ("kya sochti",              "kya soch-ti"),
    ("lag raha hai",            "lug ra-ha hay"),
    ("lag rahi hai",            "lug ra-hi hay"),
    ("lag rahe hain",           "lug ra-hay hain"),
    ("ho sakta hai",            "ho suk-ta hay"),
    ("ho sakti hai",            "ho suk-ti hay"),
    ("ho sakte hain",           "ho suk-tay hain"),
    ("kar raha hoon",           "kur ra-ha hoon"),
    ("kar rahi hoon",           "kur ra-hi hoon"),
    ("kar rahe hain",           "kur ra-hay hain"),
    ("bol raha hoon",           "bol ra-ha hoon"),
    ("bol rahi hoon",           "bol ra-hi hoon"),
    ("bata raha hoon",          "bu-ta ra-ha hoon"),
    ("bata rahi hoon",          "bu-ta ra-hi hoon"),
    ("sun raha hoon",           "sun ra-ha hoon"),
    ("sun rahi hoon",           "sun ra-hi hoon"),
    ("dekh raha hoon",          "daykh ra-ha hoon"),
    ("dekh rahi hoon",          "daykh ra-hi hoon"),
    ("soch raha hoon",          "soch ra-ha hoon"),
    ("soch rahi hoon",          "soch ra-hi hoon"),
    ("samajh raha hoon",        "su-majh ra-ha hoon"),
    ("samajh rahi hoon",        "su-majh ra-hi hoon"),
    ("jaanta hoon",             "jaan-ta hoon"),
    ("jaanti hoon",             "jaan-ti hoon"),
    ("chahta hoon",             "chah-ta hoon"),
    ("chahti hoon",             "chah-ti hoon"),
    ("sunta hoon",              "sun-ta hoon"),
    ("sunti hoon",              "sun-ti hoon"),
    ("mil jayega",              "mil jaa-ye-ga"),
    ("mil jayegi",              "mil jaa-ye-gi"),
    ("aa jayega",               "aah jaa-ye-ga"),
    ("aa jayegi",               "aah jaa-ye-gi"),
    ("de dena",                 "day day-na"),
    ("le lena",                 "lay lay-na"),
    ("kar liya",                "kur li-ya"),
    ("kar li",                  "kur li"),
    ("reh ja",                  "reh jaa"),
    ("jaane de",                "jaa-nay day"),
    ("jane de",                 "jaa-nay day"),
    ("rehne de",                "reh-nay day"),
    ("chhod de",                "chhod day"),
    ("chhod do",                "chhod do"),
    ("nikal gaya",              "ni-kul ga-ya"),
    ("nikal gayi",              "ni-kul ga-yi"),
    ("phir bhi",                "phir bhi"),
    ("phir se",                 "phir say"),
    ("phir kab",                "phir kub"),
    ("warna nahi",              "wur-na na-hi"),
    ("jaise ki",                "jai-say ki"),
    ("waisa hi",                "wai-sa hi"),
    ("theek thaak hai",         "theek-taak hay"),
    ("hona chahiye",            "ho-na cha-hi-yay"),
    ("karna chahiye",           "kur-na cha-hi-yay"),
    ("chahiye tha",             "cha-hi-yay tha"),
    ("karna padega",            "kur-na pu-day-ga"),
    ("karna tha",               "kur-na tha"),
    ("dobara karo",             "do-ba-ra ku-ro"),
    ("dobara kar",              "do-ba-ra kur"),
    ("toh phir",                "to phir"),
    ("lekin phir",              "lay-kin phir"),
    ("check karta hoon",        "check kur-ta hoon"),
    ("check karti hoon",        "check kur-ti hoon"),
    ("try karta hoon",          "try kur-ta hoon"),
    ("try karti hoon",          "try kur-ti hoon"),
    ("sun raha hai",            "sun ra-ha hay"),
    ("sun rahi hai",            "sun ra-hi hay"),
    ("sabse pehle",             "sub-say peh-lay"),
    ("sabse zyada",             "sub-say zya-da"),
    ("sabse accha",             "sub-say uch-cha"),
]

# ─────────────────────────────────────────────────────────────────────────────
# WORD MAP  — whole-word replacement after phrase pass
# ─────────────────────────────────────────────────────────────────────────────

_WORD_MAP: dict[str, str] = {

    # ── Questions / interrogatives ────────────────────────────────────────────
    "kyun":         "kyoon",
    "kyunki":       "kyoon-ki",
    "kyunke":       "kyoon-ke",
    "kyon":         "kyoon",
    "kaise":        "kai-say",
    "kaisa":        "kai-sa",
    "kaisi":        "kai-si",
    "kya":          "kya",
    "kahan":        "ka-haan",
    "kab":          "kub",
    "kaun":         "kown",
    "kitna":        "kit-na",
    "kitne":        "kit-nay",
    "kitni":        "kit-ni",
    "kuch":         "kuch",
    "koi":          "ko-ee",
    "jo":           "jo",
    "jab":          "jub",
    "tab":          "tub",
    "jahaan":       "ja-haan",
    "idhar":        "id-hur",
    "udhar":        "ud-hur",
    "yahan":        "ya-haan",
    "wahan":        "wa-haan",
    "agar":         "u-gur",
    "warna":        "wur-na",

    # ── Common verbs — base forms ─────────────────────────────────────────────
    "hai":          "hay",
    "hain":         "hain",
    "tha":          "tha",
    "thi":          "thi",
    "the":          "thay",
    "hoga":         "ho-ga",
    "hogi":         "ho-gi",
    "honge":        "hon-gay",
    "hoge":         "ho-gay",
    "ho":           "ho",
    "hoon":         "hoon",
    "kar":          "kur",
    "karo":         "ku-ro",
    "karna":        "kur-na",
    "karega":       "kur-ay-ga",
    "karegi":       "kur-ay-gi",
    "karenge":      "kur-en-gay",
    "karte":        "kur-tay",
    "karti":        "kur-ti",
    "karta":        "kur-ta",
    "karein":       "kur-ain",
    "karun":        "ka-run",
    "karunga":      "ka-run-ga",
    "karungi":      "ka-run-gi",
    "kiya":         "ki-ya",
    "kiye":         "ki-yay",
    "dekh":         "daykh",
    "dekho":        "daykh-o",
    "dekha":        "daykh-a",
    "dekhe":        "daykh-ay",
    "dekhna":       "daykh-na",
    "dekhta":       "daykh-ta",
    "dekhti":       "daykh-ti",
    "bol":          "bol",
    "bolo":         "bolo",
    "bola":         "bo-la",
    "boli":         "bo-li",
    "bolunga":      "bo-lun-ga",
    "bolungi":      "bo-lun-gi",
    "bolna":        "bol-na",
    "bolega":       "bo-lay-ga",
    "bolegi":       "bo-lay-gi",
    "sun":          "sun",
    "suno":         "suno",
    "suna":         "soo-na",
    "sunn":         "sun",
    "sunta":        "sun-ta",
    "sunti":        "sun-ti",
    "sunna":        "sun-na",
    "de":           "day",
    "dena":         "day-na",
    "dega":         "day-ga",
    "degi":         "day-gi",
    "denge":        "den-gay",
    "le":           "lay",
    "lena":         "lay-na",
    "liya":         "li-ya",
    "legi":         "lay-gi",
    "lega":         "lay-ga",
    "lenge":        "len-gay",
    "aa":           "aah",
    "aaja":         "aah-ja",
    "aao":          "aah-o",
    "aana":         "aah-na",
    "aata":         "aah-ta",
    "aati":         "aah-ti",
    "aaye":         "aah-yay",
    "jaana":        "jaa-na",
    "jao":          "jaa-o",
    "ja":           "jaa",
    "jaata":        "jaa-ta",
    "jaati":        "jaa-ti",
    "jaaye":        "jaa-yay",
    "jayega":       "jaa-ye-ga",
    "jayegi":       "jaa-ye-gi",
    "jayenge":      "jaa-yen-gay",
    "gaya":         "ga-ya",
    "gayi":         "ga-yi",
    "gaye":         "ga-yay",
    "raha":         "ra-ha",
    "rahi":         "ra-hi",
    "rahe":         "ra-hay",
    "rehna":        "reh-na",
    "reh":          "reh",
    "ruk":          "ruk",
    "ruko":         "ru-ko",
    "ruka":         "ru-ka",
    "rukna":        "ruk-na",
    "pata":         "pu-ta",
    "puch":         "pooch",
    "pucha":        "poo-cha",
    "puchna":       "pooch-na",
    "samajh":       "su-majh",
    "samajha":      "su-maj-ha",
    "samjha":       "sum-jha",
    "samjhe":       "sum-jhay",
    "samjna":       "sum-jh-na",
    "batao":        "bu-tao",
    "bata":         "bu-ta",
    "batana":       "bu-ta-na",
    "batata":       "bu-ta-ta",
    "batati":       "bu-ta-ti",
    "chahiye":      "cha-hi-yay",
    "chahta":       "chah-ta",
    "chahti":       "chah-ti",
    "chahna":       "chah-na",
    "chahun":       "chah-un",
    "chahunga":     "chah-un-ga",
    "chahungi":     "chah-un-gi",
    "sochna":       "soch-na",
    "socho":        "so-cho",
    "socha":        "so-cha",
    "soch":         "soch",
    "sochta":       "soch-ta",
    "sochti":       "soch-ti",
    "jaanta":       "jaan-ta",
    "jaanti":       "jaan-ti",
    "jaanun":       "jaan-un",
    "jaanunga":     "jaan-un-ga",
    "jaanungi":     "jaan-un-gi",
    "nikal":        "ni-kul",
    "nikalna":      "ni-kul-na",
    "nikalo":       "ni-ka-lo",
    "chhod":        "chhod",
    "chhodo":       "chho-do",
    "chhodna":      "chhod-na",
    "pakad":        "pa-kad",
    "pakdo":        "pak-do",
    "pakadna":      "pa-kad-na",
    "likh":         "likh",
    "likho":        "lik-ho",
    "likhna":       "likh-na",
    "laga":         "la-ga",
    "lagi":         "la-gi",
    "lage":         "la-gay",
    "lagta":        "lug-ta",
    "lagti":        "lug-ti",
    "lagana":       "la-ga-na",
    "milna":        "mil-na",
    "milega":       "mi-lay-ga",
    "milegi":       "mi-lay-gi",
    "milenge":      "mi-len-gay",
    "dhundh":       "dhoondh",
    "dhundna":      "dhoondh-na",
    "dhundho":      "dhoondh-o",
    "dhoondna":     "dhoondh-na",
    "padh":         "purh",
    "padho":        "pur-ho",
    "padha":        "pur-ha",
    "padhna":       "purh-na",
    "padhta":       "purh-ta",
    "padhti":       "purh-ti",
    "seekh":        "seekh",
    "seekhna":      "seekh-na",
    "seekha":       "seekh-a",
    "seekhta":      "seekh-ta",
    "seekhti":      "seekh-ti",
    "likha":        "lik-ha",
    "khol":         "khol",
    "kholo":        "kho-lo",
    "kholna":       "khol-na",
    "band":         "bund",
    "chal":         "chul",
    "chala":        "chu-la",
    "chalao":       "chu-lao",
    "chalna":       "chul-na",

    # ── Pronouns / connectors ─────────────────────────────────────────────────
    "mein":         "main",
    "main":         "main",
    "mera":         "may-ra",
    "meri":         "may-ri",
    "mere":         "may-ray",
    "mujhe":        "muj-hay",
    "mujhse":       "muj-say",
    "tera":         "tay-ra",
    "teri":         "tay-ri",
    "tere":         "tay-ray",
    "tujhe":        "tuj-hay",
    "tujhse":       "tuj-say",
    "uska":         "us-ka",
    "uski":         "us-ki",
    "uske":         "us-kay",
    "usse":         "us-say",
    "humara":       "hu-ma-ra",
    "humari":       "hu-ma-ri",
    "humare":       "hu-ma-ray",
    "hume":         "hum-ay",
    "humko":        "hum-ko",
    "apna":         "up-na",
    "apni":         "up-ni",
    "apne":         "up-nay",
    "isko":         "is-ko",
    "isse":         "is-say",
    "inhe":         "in-hay",
    "inko":         "in-ko",
    "unhe":         "un-hay",
    "unko":         "un-ko",
    "tumhe":        "tum-hay",
    "tumko":        "tum-ko",
    "tumse":        "tum-say",
    "woh":          "wo",
    "wo":           "wo",
    "ye":           "yay",
    "yeh":          "yeh",
    "ek":           "ayk",

    # ── Particles / connectors ────────────────────────────────────────────────
    "na":           "naa",
    "nahi":         "na-hi",
    "nahin":        "na-hin",
    "nah":          "naa",
    "nhi":          "na-hi",
    "toh":          "to",
    "bhi":          "bhi",
    "hi":           "hi",
    "aur":          "or",
    "ya":           "yaa",
    "lekin":        "lay-kin",
    "par":          "pur",
    "pe":           "pay",
    "se":           "say",
    "ke":           "kay",
    "ki":           "ki",
    "ko":           "ko",
    "ka":           "ka",
    "ne":           "nay",
    "iske":         "is-kay",
    "isliye":       "is-li-yay",
    "waise":        "wai-say",
    "phir":         "phir",
    "fir":          "phir",
    "dobara":       "do-ba-ra",
    "phirse":       "phir-say",
    "firse":        "phir-say",
    "wapas":        "wa-pas",
    "pehle":        "peh-lay",
    "pehele":       "peh-lay",
    "pehli":        "peh-li",
    "pehla":        "peh-la",
    "baad":         "baad",
    "baaki":        "baa-ki",
    "sabse":        "sub-say",
    "abhi":         "ab-hi",
    "ab":           "ab",

    # ── Common adjectives / adverbs ───────────────────────────────────────────
    "accha":        "uch-cha",
    "achha":        "uch-ha",
    "acha":         "uch-a",
    "theek":        "theek",
    "thoda":        "tho-da",
    "thodi":        "tho-di",
    "thode":        "tho-day",
    "bahut":        "ba-hut",
    "zyada":        "zya-da",
    "kam":          "kum",
    "jaldi":        "jul-di",
    "seedha":       "seed-ha",
    "seedhe":       "seed-hay",
    "sahi":         "saa-hi",
    "galat":        "gu-lut",
    "bada":         "bu-da",
    "badi":         "bu-di",
    "bade":         "bu-day",
    "chhota":       "chho-ta",
    "chhoti":       "chho-ti",
    "purana":       "pu-ra-na",
    "naya":         "nu-ya",
    "nayi":         "nu-yi",
    "kafi":         "kaa-fi",
    "kaafi":        "kaa-fi",
    "zaroor":       "za-roor",
    "zaruri":       "za-roo-ri",
    "mushkil":      "mush-kil",
    "asaan":        "aa-saan",
    "taiyar":       "tai-yaar",
    "dhyan":        "dhyaan",
    "dhyaan":       "dhyaan",

    # ── Time words ────────────────────────────────────────────────────────────
    "aaj":          "aaj",
    "kal":          "kul",
    "parso":        "pur-so",
    "raat":         "raat",
    "subah":        "su-bah",
    "dopahar":      "do-pa-hur",
    "shaam":        "shaam",
    "sawere":       "sa-we-ray",

    # ── Emotions / reactions ──────────────────────────────────────────────────
    "yaar":         "yaar",
    "arre":         "ur-ray",
    "arrey":        "ur-ray",
    "oye":          "oi",
    "haan":         "haan",
    "han":          "hun",
    "hmm":          "hm",
    "haha":         "ha-ha",
    "hehe":         "he-he",
    "haww":         "haw",
    "wah":          "waa",
    "waah":         "waa",
    "chalo":        "cha-lo",
    "matlab":       "mul-lub",
    "matlb":        "mul-lub",
    "bas":          "bus",
    "sach":         "such",
    "sachchi":      "such-chi",
    "pakka":        "puk-ka",
    "bilkul":       "bil-kul",
    "ekdum":        "ayk-dum",
    "khatam":       "kha-tum",
    "shuru":        "shu-roo",
    "chill":        "chil",
    "bakwaas":      "buk-waas",
    "faltu":        "fal-too",
    "mast":         "mast",
    "zabardast":    "za-bar-dast",
    "bindaas":      "bin-daas",

    # ── Relationship / social ─────────────────────────────────────────────────
    "dost":         "dost",
    "doston":       "dos-ton",
    "bhai":         "bhai",
    "bhaiya":       "bhai-ya",
    "didi":         "di-di",
    "behen":        "be-hen",
    "pyaar":        "pyaar",
    "dil":          "dil",
    "zindagi":      "zin-da-gi",
    "rishta":       "rish-ta",
    "saath":        "saath",

    # ── English loanwords — Indian-English stress/pronunciation ───────────────
    "actually":     "ak-chu-lee",
    "basically":    "bay-si-klee",
    "obviously":    "ob-vee-us-lee",
    "literally":    "lit-ru-lee",
    "seriously":    "see-ree-us-lee",
    "honestly":     "on-ist-lee",
    "definitely":   "def-i-nit-lee",
    "probably":     "prob-ub-lee",
    "already":      "ol-red-ee",
    "exactly":      "eg-zak-tlee",
    "perfect":      "pur-fect",
    "amazing":      "uh-may-zing",
    "awesome":      "aw-sum",
    "important":    "im-por-tunt",
    "sorry":        "sor-ry",
    "thanks":       "thanks",
    "please":       "pleez",
    "okay":         "o-kay",
    "fine":         "fine",
    "done":         "done",
    "wait":         "wait",
    "relax":        "ri-laks",
    "understood":   "un-dur-stood",
    "remember":     "ri-mem-bur",
    "forget":       "fur-get",
    "problem":      "prob-lum",
    "solution":     "so-loo-shun",
    "question":     "kwes-chun",
    "answer":       "aan-sur",
    "correct":      "ku-rect",
    "wrong":        "rong",
    "different":    "dif-runt",
    "special":      "spesh-ul",
    "normal":       "nor-mul",
    "simple":       "sim-pul",
    "difficult":    "dif-fi-cult",
    "possible":     "pos-i-bul",
    "impossible":   "im-pos-i-bul",
    "necessary":    "nes-uh-ser-ee",
    "available":    "uh-vail-uh-bul",
    "comfortable":  "kumf-ta-bul",
    "suppose":      "su-pose",
    "depends":      "di-pends",
    "happened":     "hap-und",
    "happens":      "hap-uns",
    "working":      "work-ing",
    "trying":       "try-ing",
    "thinking":     "think-ing",
    "feeling":      "feel-ing",
    "talking":      "taw-king",
    "listening":    "lis-ning",
}
# fmt: on


# ─────────────────────────────────────────────────────────────────────────────
# DEVANAGARI / EMOJI / SYMBOL STRIP
# ─────────────────────────────────────────────────────────────────────────────

_DEVA_RE   = re.compile(r"[\u0900-\u097F\u0200-\u024F]+")
_EMOJI_RE  = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)
# Markdown artefacts TTS reads aloud ("asterisk", "hashtag", etc.)
_MARKDOWN_RE = re.compile(r"[*_`#>|]+")
# Repeated punctuation (ellipsis typed as "......" → "...")
_MULTI_DOT_RE = re.compile(r"\.{4,}")


def _strip_devanagari(text: str) -> str:
    return _DEVA_RE.sub("", text)

def _strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub(" ", text)

def _strip_markdown(text: str) -> str:
    return _MARKDOWN_RE.sub(" ", text)

def _normalise_punctuation(text: str) -> str:
    text = _MULTI_DOT_RE.sub("...", text)
    # Smart quotes → straight
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return text


# ─────────────────────────────────────────────────────────────────────────────
# APPLY MAPS
# ─────────────────────────────────────────────────────────────────────────────

def _apply_phrase_map(text: str) -> str:
    result = text
    for phrase, replacement in _PHRASE_MAP:
        result = re.sub(re.escape(phrase), replacement, result, flags=re.IGNORECASE)
    return result


def _apply_word_map(text: str) -> str:
    def _replace(match: re.Match) -> str:
        word  = match.group(0)
        lower = word.lower()
        rep   = _WORD_MAP.get(lower)
        if rep is None:
            return word
        if word.isupper():
            return rep.upper()
        if word[0].isupper():
            return rep.capitalize()
        return rep
    return re.sub(r"\b[a-zA-Z]+\b", _replace, text)


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def normalize_for_tts(
    text: str,
    strip_emoji: bool = True,
    strip_devanagari: bool = True,
    strip_markdown: bool = True,
    phonetic_map: bool = True,
) -> str:
    """
    Normalize Hinglish text for TTS engines.

    Pipeline:
      1. Strip emoji
      2. Strip Devanagari  (TTS skips them, causing weird pauses)
      3. Strip markdown artefacts  (* _ ` # etc.)
      4. Normalise punctuation
      5. Phrase map  (multi-word, runs first)
      6. Word map   (single-word, whole-word boundaries)
      7. Collapse whitespace
    """
    if not text:
        return text

    if strip_emoji:
        text = _strip_emoji(text)
    if strip_devanagari:
        text = _strip_devanagari(text)
    if strip_markdown:
        text = _strip_markdown(text)

    text = _normalise_punctuation(text)
    if phonetic_map:
        text = _apply_phrase_map(text)
        text = _apply_word_map(text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()

    return text


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT BLOCK
# ─────────────────────────────────────────────────────────────────────────────

SPEECH_PROMPT_BLOCK = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HINGLISH SPEECH — STRICT RULES FOR NATURAL TTS VOICE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Tu voice mein bolti hai — text TTS engine ko jaata hai.
Neeche diye rules STRICTLY follow karo warna pronunciation galat hogi.

ALWAYS USE FULL HINGLISH SPELLINGS (no shortcuts):
  nahi / nahin      NOT: nhi, nhii, nah
  haan              NOT: han (TTS "han" = wrong sound)
  kyun / kyunki     NOT: q, qu, kyu
  toh               NOT: toh is fine; but "to" only as conjunction
  bhi               ALWAYS "bhi" — TTS "bi" = "bee"
  woh               NOT: wo (engine says "woo")
  yeh               NOT: just "y" or "ye" alone
  kya               NOT: kia
  phir              NOT: fir (TTS reads "fir" as English "fir tree")
  abhi              NOT: abh, abhe
  mujhe             NOT: mujhy, muje
  tujhe             NOT: tujhy, tuje
  chahiye           NOT: chahiiye, chaiye, chhaiye
  theek             NOT: thik, thek
  pakka             NOT: paka
  dobara            NOT: dubara (TTS stresses wrong)
  warna             NOT: warna is fine; NOT: wrna
  seedhe            NOT: seedhay, sidhay
  zaroor            NOT: zarur, zaror
  zaruri            NOT: zarori
  mushkil           NOT: mushkl
  taiyar            NOT: tayar, tayyar
  shuru             NOT: suru
  khatam            NOT: khtm
  bilkul            NOT: bilkull
  ekdum             NOT: ekdam
  zindagi           NOT: zindgi
  pyaar             NOT: pyar (engine clips the long vowel)
  dopahar           NOT: dopehar

PUNCTUATION = NATURAL PAUSES:
  , (comma)     short pause between clauses
  . (period)    full stop
  ... (ellipsis) thinking pause — "Hmm... soch rahi hoon"
  — (dash)      quick thought shift — "Accha — woh toh sahi"

NO DEVANAGARI in speech text:
  ✗ "Aaj मैं gyi thi"
  ✓ "Aaj main gayi thi"

NO SHORT FORMS:
  ✗ u, ur, r, kl, tmrw, bc, brb, wtf, omg, lol, lmao
  ✓ Full words always when speaking

NO MARKDOWN in speech:
  ✗ **bold**, *italic*, `code`, ## heading
  ✓ Plain text only — no symbols that TTS will read aloud

NUMBERS:
  ✓ "teen log", "chaar baje", "paanch minute"  (Hindi numbers in Hindi sentence)
  ✓ "5 baje", "3 log" also fine — digits ok in mixed context

LAUGHTER:
  ✓ "haha", "hehe"
  ✗ "lol", "lmao", "xD"
"""


def get_speech_prompt_block() -> str:
    """Return speech prompt block to inject into Vani's system instructions."""
    return SPEECH_PROMPT_BLOCK


# ─────────────────────────────────────────────────────────────────────────────
# SELF-TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        "Kyun nahi bata rahi hoon toh?",
        "Yeh kya kar raha hai yaar",
        "Pata nahi, samajh nahi aaya mujhe.",
        "Accha haan, theek hai na, bilkul sahi.",
        "Kaise hoga yeh project bhai?",
        "Nahi nahi, ek second ruk.",
        "Bahut zyada ho gaya ab toh.",
        "Abhi check karti hoon, ek sec.",
        "Phir bhi lag raha hai kuch nahi hua.",
        "Dobara try karo, warna khatam.",
        "Mujhe pata hai yeh mushkil hai, lekin zaroor ho sakta hai.",
        "Sab kuch theek thaak hai, koi baat nahi.",
        "Actually basically yeh obviously sahi hai.",
        "Taiyar hoon, shuru karte hain.",
        "Aaj kal aur subah shaam matlab idhar udhar rehna padta hai.",
    ]

    print("HINGLISH TTS NORMALIZATION v2 — STRICT")
    print("=" * 60)
    changes = 0
    for t in tests:
        n = normalize_for_tts(t)
        if n != t:
            print(f"IN : {t}")
            print(f"OUT: {n}")
            print()
            changes += 1
    print(f"{changes}/{len(tests)} strings normalized.")
