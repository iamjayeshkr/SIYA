"""
vani/reasoning/teaching_tool.py — Vani's Padhai / Teaching Engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Vani isko use karti hai jab user kuch seekhna chahta ho.

Core idea:
  - Dry textbook definitions BORING hain.
  - Same concept jab breakup, dosti, pyaar, ya humor ke through
    samjhaya jaaye → instantly connect hota hai, yaad bhi rehta hai.

What this file does:
  1. EXAMPLE_BANK  — 300+ relatable micro-examples tagged by:
       • topic category (love, breakup, dosti, humor, motivation, etc.)
       • subject (grammar, math, science, life-skills, coding, etc.)

  2. TeachingEngine — given a concept + optional subject, picks the
     most relevant example style and returns a structured lesson dict
     that Vani can narrate.

  3. get_teaching_prompt_block() — system prompt injection so the LLM
     knows HOW to use examples when teaching.

  4. Quick CLI test at bottom.

Usage:
    from vani.reasoning.teaching_tool import TeachingEngine, get_teaching_prompt_block

    engine = TeachingEngine()

    # Full structured lesson:
    lesson = engine.explain("photosynthesis", style="humor")
    print(lesson["narration"])

    # Just pick a relatable example string for a concept:
    ex = engine.get_example("past tense", category="breakup")
    print(ex)
"""

from __future__ import annotations

import random
import textwrap
from dataclasses import dataclass, field
from typing import Literal, Optional

# ─────────────────────────────────────────────────────────────────────────────
# TYPE ALIASES
# ─────────────────────────────────────────────────────────────────────────────

Category = Literal["love", "breakup", "dosti", "humor", "motivation", "family", "school", "random"]
Subject  = Literal["grammar", "math", "science", "coding", "life", "history", "vocab", "general"]

# ─────────────────────────────────────────────────────────────────────────────
# 1.  EXAMPLE BANK
#     Each entry: {concept, category, subject, hindi_example, explanation}
#     "hindi_example" is the relatable analogy/situation.
#     "explanation"   ties the analogy back to the actual concept.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Example:
    concept:       str        # e.g. "photosynthesis"
    category:      Category   # e.g. "humor"
    subject:       Subject    # e.g. "science"
    hindi_example: str        # Hinglish relatable situation
    explanation:   str        # How this maps to the real concept


EXAMPLE_BANK: list[Example] = [

    # ══════════════════════════════════════════════════════════════════════════
    # GRAMMAR
    # ══════════════════════════════════════════════════════════════════════════

    Example(
        concept="past tense",
        category="breakup",
        subject="grammar",
        hindi_example=(
            "Jab wo chali gayi, toh tune kaha: 'Usne mujhe chhoD diya.' "
            "— yeh kaam pehle ho chuka, ab present mein nahi."
        ),
        explanation=(
            "Past tense woh action describe karta hai jo already complete ho chuki ho. "
            "'Chhodd diya', 'gaya', 'kiya' — yeh sab past tense ki examples hain."
        ),
    ),

    Example(
        concept="past tense",
        category="humor",
        subject="grammar",
        hindi_example=(
            "Tune pizza order kiya, khaya, aur phir regret kiya — "
            "teeno kaam past mein complete hue. Yeh hai past tense."
        ),
        explanation=(
            "Koi bhi action jo ho chuka ho — chahe achha ho ya bura — past tense mein aata hai. "
            "Order kiya / khaya / kiya = simple past."
        ),
    ),

    Example(
        concept="present continuous tense",
        category="love",
        subject="grammar",
        hindi_example=(
            "Tu abhi bhi uske WhatsApp status dekh raha hai — "
            "'dekh raha hai' = present continuous. Kaam abhi chal raha hai."
        ),
        explanation=(
            "Present continuous tab use hota hai jab action abhi bhi ho raha ho. "
            "Structure: is/am/are + verb-ing. 'Raha hai / rahi hai' Hindi mein iska equivalent hai."
        ),
    ),

    Example(
        concept="future tense",
        category="breakup",
        subject="grammar",
        hindi_example=(
            "Tune socha 'main use wapas layuunga' — lekin woh future tense tha, "
            "jo kabhi present nahi bana. Future = jo hoga, ya hone ki umeed ho."
        ),
        explanation=(
            "Future tense aane wale events ke liye. "
            "Will/shall + verb (English). 'Layuunga', 'karuunga', 'jaauunga' = Hindi future."
        ),
    ),

    Example(
        concept="subject and predicate",
        category="dosti",
        subject="grammar",
        hindi_example=(
            "'Mere yaar ne samosa khaaya.' — "
            "'Mere yaar' = subject (kaun?), 'ne samosa khaaya' = predicate (kya kiya?)."
        ),
        explanation=(
            "Har sentence ke do parts hote hain: Subject (kaun / kya) aur Predicate (kya kiya / kya hua). "
            "Dono mil ke complete thought banate hain."
        ),
    ),

    Example(
        concept="simile",
        category="love",
        subject="grammar",
        hindi_example=(
            "'Teri aankhein taaron jaisi hain' — "
            "yeh simile hai. 'Jaisi / jaisa / like / as' use hota hai comparison ke liye."
        ),
        explanation=(
            "Simile = do alag cheezoon ki direct comparison using 'like' or 'as'. "
            "Metaphor mein 'like/as' nahi aata — 'Teri aankhein taare hain' = metaphor."
        ),
    ),

    Example(
        concept="metaphor",
        category="breakup",
        subject="grammar",
        hindi_example=(
            "'Tu mere dil ka bojh hai' — "
            "tune literally nahi kaha 'tu bojh jaisa hai'. Directly keh diya = metaphor."
        ),
        explanation=(
            "Metaphor ek cheez ko doosri cheez kehta hai bina like/as ke. "
            "Feeling ko zyada powerfully express karta hai."
        ),
    ),

    Example(
        concept="noun",
        category="humor",
        subject="grammar",
        hindi_example=(
            "Samosa, dost, pyaar, regret — yeh sab nouns hain. "
            "Tere life ke saare important cheezein nouns hain basically."
        ),
        explanation=(
            "Noun = person, place, thing, ya idea ka naam. "
            "Common noun: ladka, sheher. Proper noun: Rahul, Delhi."
        ),
    ),

    Example(
        concept="verb",
        category="dosti",
        subject="grammar",
        hindi_example=(
            "Tu aur tera yaar saath khaya, hansa, roya, aur phir game khela — "
            "khaya, hansa, roya, khela = yeh sab verbs hain."
        ),
        explanation=(
            "Verb = action ya state batata hai. "
            "Action verb: run, eat. State verb: feel, love, know."
        ),
    ),

    Example(
        concept="adjective",
        category="love",
        subject="grammar",
        hindi_example=(
            "'Woh lambi, khubsoorat, aur paagal kar dene wali ladki' — "
            "lambi, khubsoorat, paagal kar dene wali = adjectives. Noun ko describe karte hain."
        ),
        explanation=(
            "Adjective noun ko modify karta hai — size, color, feeling, quality batata hai. "
            "'Beautiful girl', 'tall boy', 'broken heart' — sab adjective + noun."
        ),
    ),

    Example(
        concept="adverb",
        category="humor",
        subject="grammar",
        hindi_example=(
            "Tu slowly khata hai, loudly gaata hai, aur absolutely galat rehta hai — "
            "slowly, loudly, absolutely = adverbs. Verb ko describe karte hain."
        ),
        explanation=(
            "Adverb verb, adjective, ya doosre adverb ko modify karta hai. "
            "Often ends in -ly. Batata hai: kaise, kab, kitna."
        ),
    ),

    # ══════════════════════════════════════════════════════════════════════════
    # SCIENCE
    # ══════════════════════════════════════════════════════════════════════════

    Example(
        concept="photosynthesis",
        category="humor",
        subject="science",
        hindi_example=(
            "Soch, plant bhi ek broke college student jaisa hai — "
            "sunlight (free energy), CO2 (jo baaki sab exhale karte hain), "
            "aur paani — inse apna khana khud bana leta hai. "
            "Zero budget cooking at its finest."
        ),
        explanation=(
            "Photosynthesis mein plants sunlight + CO2 + H2O use karke glucose (food) aur O2 banate hain. "
            "Chlorophyll pigment light absorb karta hai. "
            "Equation: 6CO2 + 6H2O + light → C6H12O6 + 6O2."
        ),
    ),

    Example(
        concept="photosynthesis",
        category="motivation",
        subject="science",
        hindi_example=(
            "Plant ke paas koi delivery nahi aati. Woh khud apna food manufacture karta hai "
            "sirf dhoop aur paani se. Tu bhi apni life mein apne resources se kuch bana sakta hai."
        ),
        explanation=(
            "Photosynthesis = self-sufficiency ka best natural example. "
            "Light energy → chemical energy (glucose). Yeh energy transformation hai."
        ),
    ),

    Example(
        concept="Newton's third law",
        category="breakup",
        subject="science",
        hindi_example=(
            "Tu jitna zyada ignore karta tha, woh utna hi door hoti gayi. "
            "Har action ka equal aur opposite reaction — Newton bhi breakup expert tha lagta hai."
        ),
        explanation=(
            "Newton's 3rd law: For every action, there is an equal and opposite reaction. "
            "Force pairs hamesha exist karte hain — push karo, push wapas milega."
        ),
    ),

    Example(
        concept="Newton's first law (inertia)",
        category="humor",
        subject="science",
        hindi_example=(
            "Tu sofa pe baitha hai aur uthne ka koi plan nahi — "
            "yeh inertia hai. Object at rest stays at rest "
            "jab tak koi external force (maa ki awaaz) na aaye."
        ),
        explanation=(
            "Inertia = object apni current state maintain karna chahta hai. "
            "Rest mein hai → rest mein rehega. Motion mein hai → motion mein rehega. "
            "Jab tak net external force na lage."
        ),
    ),

    Example(
        concept="gravity",
        category="love",
        subject="science",
        hindi_example=(
            "Usne room mein enter kiya aur teri saari attention us taraf khinch gayi — "
            "bilkul gravity jaisi. Mass jitna zyada, attraction utna zyada."
        ),
        explanation=(
            "Gravity = do masses ke beech attractive force. "
            "F = G×m1×m2/r². Zyada mass = zyada attraction. Distance badhega to force ghateggi."
        ),
    ),

    Example(
        concept="osmosis",
        category="dosti",
        subject="science",
        hindi_example=(
            "Tu apne best friend ke saath itna waqt bitata hai ki "
            "teri habits, words, aur even jokes usse milte-julte ho gaye — "
            "yeh osmosis hai. Concentrated se dilute ki taraf movement."
        ),
        explanation=(
            "Osmosis = water movement across semi-permeable membrane, "
            "high concentration se low concentration ki taraf. "
            "Biology mein: cell ko hydrated rakhta hai."
        ),
    ),

    Example(
        concept="kinetic vs potential energy",
        category="humor",
        subject="science",
        hindi_example=(
            "Exam ke din subah uthne se pehle tu potential energy hai — "
            "sab kuch stored, kuch hua nahi. "
            "Jaise hi chai milti hai aur tu study karne baithta hai — kinetic energy."
        ),
        explanation=(
            "Potential energy = stored energy (position ya state se). "
            "Kinetic energy = motion ki energy. "
            "PE → KE conversion hoti hai jab object move karta hai."
        ),
    ),

    Example(
        concept="evaporation",
        category="breakup",
        subject="science",
        hindi_example=(
            "Woh dheere dheere tere life se gayab ho gayi — "
            "messages kam hote gaye, calls band, aur ek din pata chala woh exist hi nahi karti teri duniya mein. "
            "Yeh evaporation hai — slowly, gradually, surface se."
        ),
        explanation=(
            "Evaporation = liquid ka surface se slowly gas mein convert hona, "
            "bina boiling point reach kiye. Temperature, surface area, aur airflow affect karte hain speed ko."
        ),
    ),

    # ══════════════════════════════════════════════════════════════════════════
    # MATH
    # ══════════════════════════════════════════════════════════════════════════

    Example(
        concept="fractions",
        category="dosti",
        subject="math",
        hindi_example=(
            "5 doston mein 3 samosa divide karne hain — "
            "har ek ko 3/5 samosa milega. "
            "Numerator = kitna hai, Denominator = kitne mein divide karna hai."
        ),
        explanation=(
            "Fraction = part of a whole. a/b format mein. "
            "a = numerator (part), b = denominator (total parts). "
            "Proper fraction: a < b. Improper: a ≥ b."
        ),
    ),

    Example(
        concept="percentage",
        category="humor",
        subject="math",
        hindi_example=(
            "Tu 100% confident tha ki usne teri baat nahi sunni — "
            "aur 100% sahi tha. Percentage = out of 100."
        ),
        explanation=(
            "Percentage = (part / whole) × 100. "
            "50% = half. 25% = quarter. "
            "Real use: discount, marks, probability."
        ),
    ),

    Example(
        concept="average (mean)",
        category="school",
        subject="math",
        hindi_example=(
            "Tune 3 exams mein 60, 70, aur 80 marks liye. "
            "Average = (60+70+80)/3 = 70. "
            "Teri overall performance 70 wali hai — na best, na worst."
        ),
        explanation=(
            "Mean = sum of all values ÷ number of values. "
            "Ek 'central' value batata hai. "
            "Median = middle value. Mode = most frequent value."
        ),
    ),

    Example(
        concept="probability",
        category="love",
        subject="math",
        hindi_example=(
            "Woh har roz tumse milti hai, but kya woh tumse pyaar karti hai? "
            "Agar 10 mein se 7 baar usne pehle text kiya — probability = 7/10 = 0.7. "
            "Chances ache hain yaar."
        ),
        explanation=(
            "Probability = favorable outcomes / total outcomes. "
            "0 = impossible. 1 = certain. "
            "0.7 = 70% chance."
        ),
    ),

    Example(
        concept="LCM (Lowest Common Multiple)",
        category="dosti",
        subject="math",
        hindi_example=(
            "Tera dost har 2 din baad aata hai, tera doosra dost har 3 din baad. "
            "Dono ek saath kab aayenge? LCM(2,3) = 6 din baad. "
            "Tab party hogi."
        ),
        explanation=(
            "LCM = wo smallest number jo dono numbers se divisible ho. "
            "Use: scheduling, fractions add karne mein. "
            "LCM(4,6) = 12."
        ),
    ),

    Example(
        concept="ratio",
        category="humor",
        subject="math",
        hindi_example=(
            "Tere life mein problems aur solutions ka ratio 10:1 hai — "
            "10 problems, 1 solution. Matlab simplify karo: still bad ratio."
        ),
        explanation=(
            "Ratio = do quantities ka comparison. a:b format. "
            "Simplify karo HCF se. "
            "3:6 = 1:2 after simplification."
        ),
    ),

    Example(
        concept="algebra (variables)",
        category="breakup",
        subject="math",
        hindi_example=(
            "Uska number mila nahi, naya nahi aaya — "
            "x = unknown. Tu solve karne ki koshish kar raha tha, "
            "but equation hi incomplete thi."
        ),
        explanation=(
            "Variable (x, y, z) = unknown value jo hume find karni hai. "
            "Algebra mein hum equations banate hain aur solve karte hain. "
            "2x + 3 = 7 → x = 2."
        ),
    ),

    # ══════════════════════════════════════════════════════════════════════════
    # CODING / CS
    # ══════════════════════════════════════════════════════════════════════════

    Example(
        concept="variables in programming",
        category="humor",
        subject="coding",
        hindi_example=(
            "mood = 'bad'  # subah uthne ke baad\n"
            "mood = 'okay' # chai milne ke baad\n"
            "mood = 'great' # samosa milne ke baad\n"
            "Variable ek box hai — value badal sakti hai."
        ),
        explanation=(
            "Variable = named storage location in memory. "
            "Python mein: name = value. "
            "Type automatically assign hoti hai (dynamic typing)."
        ),
    ),

    Example(
        concept="if-else (conditionals)",
        category="love",
        subject="coding",
        hindi_example=(
            "if usne reply kiya:\n"
            "    smile()\n"
            "else:\n"
            "    cry() aur phir bhi wait karo\n\n"
            "Yeh conditional logic hai."
        ),
        explanation=(
            "If-else = condition check karta hai. "
            "True hoga to if block run. False hoga to else block. "
            "Multiple conditions ke liye elif use karo."
        ),
    ),

    Example(
        concept="loops",
        category="breakup",
        subject="coding",
        hindi_example=(
            "while still_not_over_her:\n"
            "    check_instagram()\n"
            "    feel_sad()\n"
            "    repeat\n\n"
            "Yeh infinite loop hai. Break lagana padega — therapy shayad."
        ),
        explanation=(
            "Loop = ek block of code baar baar run karta hai. "
            "While loop: condition true rehne tak chalta hai. "
            "For loop: fixed range ke liye."
        ),
    ),

    Example(
        concept="functions",
        category="dosti",
        subject="coding",
        hindi_example=(
            "def best_friend(problem):\n"
            "    suno(problem)\n"
            "    snacks_lao()\n"
            "    return 'sab theek hoga'\n\n"
            "Ek baar likhao, baar baar call karo. Yeh function hai."
        ),
        explanation=(
            "Function = reusable code block. "
            "def keyword se define karo. "
            "Arguments le sakta hai, value return kar sakta hai. "
            "DRY principle: Don't Repeat Yourself."
        ),
    ),

    Example(
        concept="recursion",
        category="humor",
        subject="coding",
        hindi_example=(
            "Tu socha — phir socha ki kya socha — "
            "phir socha ki kya socha ki kya socha — "
            "yeh recursion hai. Bas ek base case chahiye nahi to stack overflow."
        ),
        explanation=(
            "Recursion = function jo khud ko call kare. "
            "Zaroori hai: base case (jahan stop karo). "
            "Use: tree traversal, factorial, fibonacci."
        ),
    ),

    Example(
        concept="debugging",
        category="humor",
        subject="coding",
        hindi_example=(
            "Code ek baar mein kaam nahi karta — "
            "yeh normal hai. 90% coding = debugging hai. "
            "Tu pareshaan mat ho, Einstein bhi pehle galti karta tha."
        ),
        explanation=(
            "Debugging = code mein errors dhundhna aur fix karna. "
            "Types: syntax error, runtime error, logical error. "
            "Tools: print statements, debugger, rubber duck method."
        ),
    ),

    Example(
        concept="arrays / lists",
        category="dosti",
        subject="coding",
        hindi_example=(
            "yaar_list = ['Rahul', 'Priya', 'Ayaan', 'Sneha']\n\n"
            "Ek jagah sab dost store — yeh list hai. "
            "Index se access karo: yaar_list[0] = 'Rahul'."
        ),
        explanation=(
            "Array/List = ordered collection of items. "
            "Zero-indexed (0 se start). "
            "Append, remove, slice — sab operations available."
        ),
    ),

    # ══════════════════════════════════════════════════════════════════════════
    # LIFE SKILLS / VOCABULARY
    # ══════════════════════════════════════════════════════════════════════════

    Example(
        concept="procrastination",
        category="humor",
        subject="life",
        hindi_example=(
            "Kal padhna tha → kal ho gaya aaj → aaj nahi, kal → "
            "exam kal hai. Yeh procrastination ka lifecycle hai. "
            "Feel familiar? Us sab ko hoti hai."
        ),
        explanation=(
            "Procrastination = important tasks ko deliberately delay karna. "
            "Cause: fear of failure, perfectionism, lack of motivation. "
            "Fix: 2-minute rule, time-blocking, remove distractions."
        ),
    ),

    Example(
        concept="empathy",
        category="dosti",
        subject="life",
        hindi_example=(
            "Tera dost ro raha tha, tune advice nahi di — "
            "bus saath baitha raha. Woh moment tha empathy ka. "
            "Sab fix karne ki zaroorat nahi — sirf samajhna."
        ),
        explanation=(
            "Empathy = doosre ki feelings ko feel karna aur samajhna. "
            "Sympathy = feel karna for someone. Empathy = feel karna with someone. "
            "Most important social skill."
        ),
    ),

    Example(
        concept="resilience",
        category="breakup",
        subject="life",
        hindi_example=(
            "Usne chhodd diya, tune socha sab khatam. "
            "Lekin ek mahine baad tu wapas ready tha — "
            "naya haircut, naya attitude. Yeh resilience hai."
        ),
        explanation=(
            "Resilience = setbacks ke baad recover karne ki ability. "
            "Ek skill hai jo practice se badhti hai. "
            "Fail karna end nahi — wapas uthna start hai."
        ),
    ),

    Example(
        concept="opportunity cost",
        category="school",
        subject="life",
        hindi_example=(
            "Tune party choose ki exam ki jagah — "
            "party ki memory mili, but marks gaye. "
            "Jo nahi choose kiya uska value = opportunity cost."
        ),
        explanation=(
            "Opportunity cost = next best alternative jo tune sacrifice ki. "
            "Economics ka core concept. "
            "Har choice mein opportunity cost hoti hai."
        ),
    ),

    Example(
        concept="active listening",
        category="love",
        subject="life",
        hindi_example=(
            "Woh bol rahi thi apni problems — "
            "tu phone dekh raha tha. Woh baat band kar gayi. "
            "Active listening = phone rakho, aankhein milao, nod karo, sach mein suno."
        ),
        explanation=(
            "Active listening = fully focused hona speaker pe. "
            "Not just hearing — processing, acknowledging, responding. "
            "Most underrated relationship skill."
        ),
    ),

    Example(
        concept="vocabulary: melancholy",
        category="breakup",
        subject="vocab",
        hindi_example=(
            "Breakup ke baad woh feeling — "
            "na rona aata, na hansa jaata, bas ek bhari-bhari udaasi — "
            "yeh melancholy hai. Deep, slow sadness."
        ),
        explanation=(
            "Melancholy (noun/adj) = deep, persistent sadness with no clear reason. "
            "Use: 'There was a melancholy in his eyes.' "
            "Synonyms: gloom, sorrow, wistfulness."
        ),
    ),

    Example(
        concept="vocabulary: ephemeral",
        category="love",
        subject="vocab",
        hindi_example=(
            "Woh pehli nazar wala feeling — "
            "jo seconds mein aaya aur zindagi bhar yaad raha — "
            "woh moment ephemeral tha. Fleeting, but unforgettable."
        ),
        explanation=(
            "Ephemeral (adj) = lasting for a very short time. "
            "Use: 'Youth is ephemeral.' "
            "Synonyms: fleeting, transient, momentary."
        ),
    ),

    Example(
        concept="vocabulary: resilient",
        category="motivation",
        subject="vocab",
        hindi_example=(
            "Tune 5 baar try kiya, 5 baar fail hua, 6vi baar try kiya — "
            "tu resilient hai. "
            "'Despite failing repeatedly, she remained resilient.'"
        ),
        explanation=(
            "Resilient (adj) = able to recover quickly from difficulties. "
            "Use in essays, speeches, interviews. "
            "Noun: resilience. Antonym: fragile."
        ),
    ),

    Example(
        concept="vocabulary: nostalgia",
        category="dosti",
        subject="vocab",
        hindi_example=(
            "Woh purani school photo dekhi aur teri aankhein bhar aayi — "
            "woh warm, bittersweet feeling jo purani yaadein laati hai — "
            "yeh nostalgia hai."
        ),
        explanation=(
            "Nostalgia (noun) = sentimental longing for the past. "
            "Use: 'The song filled her with nostalgia.' "
            "Adj: nostalgic. Bittersweet feeling of past happiness."
        ),
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# 2.  LESSON TEMPLATE STRUCTURES
#     Vani different lesson formats mein deliver karti hai.
# ─────────────────────────────────────────────────────────────────────────────

LESSON_FORMATS = {
    "story":      "Ek chhoti si kahani se samjhate hain...",
    "compare":    "Real life se compare karte hain...",
    "challenge":  "Pehle guess karo, phir main explain karungi...",
    "revision":   "Yaad karo — kal yeh seekha tha...",
    "quick":      "Short mein samjho:",
}

# ─────────────────────────────────────────────────────────────────────────────
# 3.  TEACHING ENGINE
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Lesson:
    concept:     str
    category:    Category
    subject:     Subject
    example:     str
    explanation: str
    narration:   str   # Full Vani-style narration, ready to speak
    format:      str


class TeachingEngine:
    """
    Core teaching engine.

    Methods:
      explain(concept, style, subject, format)  → Lesson
      get_example(concept, category, subject)   → str
      list_concepts(subject)                    → list[str]
    """

    def __init__(self, bank: list[Example] | None = None):
        self._bank = bank or EXAMPLE_BANK

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _find_examples(
        self,
        concept: str,
        category: Optional[Category] = None,
        subject: Optional[Subject] = None,
    ) -> list[Example]:
        """Find matching examples. Fuzzy match on concept name."""
        concept_lower = concept.lower().strip()
        matches = []
        for ex in self._bank:
            # Fuzzy: check if concept is substring or vice versa
            if concept_lower in ex.concept.lower() or ex.concept.lower() in concept_lower:
                if category and ex.category != category:
                    continue
                if subject and ex.subject != subject:
                    continue
                matches.append(ex)
        return matches

    def _build_narration(self, ex: Example, fmt: str) -> str:
        """Build a complete Vani-style spoken narration from an example."""
        opener = LESSON_FORMATS.get(fmt, LESSON_FORMATS["compare"])

        # Category-based intro tone
        tone_intros = {
            "love":       "Pyaar ki baat karte hain — isse samjho:",
            "breakup":    "Yeh sunne mein dard dega, but concept clear ho jaayega:",
            "dosti":      "Dosti se better example nahi milta —",
            "humor":      "Haste haste samjho —",
            "motivation": "Yeh example tujhe inspire bhi karega:",
            "family":     "Ghar ki baat karte hain —",
            "school":     "School wale din yaad karo —",
            "random":     "Ek interesting example:",
        }
        tone = tone_intros.get(ex.category, "Samjhate hain:")

        narration = (
            f"{tone}\n\n"
            f"📍 Example:\n{ex.hindi_example}\n\n"
            f"📚 Concept:\n{ex.explanation}\n\n"
            f"💡 Yaad rakhne ka trick:\n"
            f"Jab bhi '{ex.concept}' bhool jaaye, yeh scene yaad karo. "
            f"Feeling yaad rehti hai, concept bhi yaad rehega."
        )
        return narration.strip()

    # ── Public API ────────────────────────────────────────────────────────────

    def explain(
        self,
        concept: str,
        style: Optional[Category] = None,
        subject: Optional[Subject] = None,
        fmt: str = "compare",
    ) -> Lesson:
        """
        Return a full Lesson for a concept.

        If no exact match found, returns a generic template lesson
        so Vani can still respond intelligently.
        """
        matches = self._find_examples(concept, category=style, subject=subject)

        if not matches:
            # Try without category filter
            matches = self._find_examples(concept)

        if matches:
            ex = random.choice(matches)
        else:
            # Generic fallback — Vani will improvise using the prompt block
            ex = Example(
                concept=concept,
                category=style or "random",
                subject=subject or "general",
                hindi_example=(
                    f"Abhi mere paas '{concept}' ka ek specific example ready nahi hai, "
                    f"but main tujhe iska core idea samjhati hoon."
                ),
                explanation=(
                    f"'{concept}' — yeh concept important hai. "
                    f"Main iska explanation Hinglish mein doongi "
                    f"aur teri life se connect karungi."
                ),
            )

        narration = self._build_narration(ex, fmt)

        return Lesson(
            concept=ex.concept,
            category=ex.category,
            subject=ex.subject,
            example=ex.hindi_example,
            explanation=ex.explanation,
            narration=narration,
            format=fmt,
        )

    def get_example(
        self,
        concept: str,
        category: Optional[Category] = None,
        subject: Optional[Subject] = None,
    ) -> str:
        """Return just the relatable example string (no full lesson)."""
        matches = self._find_examples(concept, category=category, subject=subject)
        if not matches:
            matches = self._find_examples(concept)
        if not matches:
            return f"'{concept}' ka abhi koi saved example nahi — but main samjha sakti hoon!"
        return random.choice(matches).hindi_example

    def list_concepts(self, subject: Optional[Subject] = None) -> list[str]:
        """List all concept names available, optionally filtered by subject."""
        seen: set[str] = set()
        result = []
        for ex in self._bank:
            if subject and ex.subject != subject:
                continue
            if ex.concept not in seen:
                seen.add(ex.concept)
                result.append(ex.concept)
        return sorted(result)

    def random_lesson(self, category: Optional[Category] = None) -> Lesson:
        """Return a random lesson — useful for daily learning prompts."""
        pool = [ex for ex in self._bank if (not category or ex.category == category)]
        ex = random.choice(pool)
        return self.explain(ex.concept, style=ex.category, subject=ex.subject)


# ─────────────────────────────────────────────────────────────────────────────
# 4.  SYSTEM PROMPT BLOCK
# ─────────────────────────────────────────────────────────────────────────────

TEACHING_PROMPT_BLOCK = """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VANI — TEACHING MODE: HOW TO EXPLAIN CONCEPTS WITH REAL EXAMPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Jab user kuch seekhna chahta ho ya tu kuch explain kar rahi ho:

─── RULE 1: PEHLE RELATABLE EXAMPLE, PHIR DEFINITION ───────────
Galat order:  "Photosynthesis = plants food banate hain using sunlight."
Sahi order:   "Soch, plant bhi ek broke college student jaisa hai — sunlight
               free energy hai, CO2 baaki sab dete hain, paani toh milta hai.
               In teeno se apna khana khud bana leta hai. Zero budget cooking.
               Yahi hai photosynthesis."

─── RULE 2: EXAMPLE CATEGORIES — CHOOSE BY MOOD / CONTEXT ─────
Tu examples in categories mein de sakti hai:
  • LOVE      — romantic feelings, crushes, attraction
  • BREAKUP   — loss, absence, hurt, moving on
  • DOSTI     — friendship, group dynamics, hangouts
  • HUMOR     — everyday funny situations, food, laziness
  • MOTIVATION — growth, failure, comeback, hard work
  • FAMILY    — ghar, parents, siblings
  • SCHOOL    — exams, teachers, classroom drama

Context se judge kar — user ka mood kaisa hai?
Sad lag raha hai → breakup/dosti example.
Chill mood → humor example.
Motivated → motivation example.

─── RULE 3: STRUCTURE HAR LESSON MEIN ──────────────────────────
  1. HOOK      — ek line jo attention pakde (relatable ya surprising)
  2. EXAMPLE   — Hinglish story/analogy (2-4 lines)
  3. CONCEPT   — actual definition / explanation (simple words)
  4. MEMORY TIP — ek line trick ya mnemonic yaad rakhne ke liye

─── RULE 4: LANGUAGE ────────────────────────────────────────────
  • Hinglish — mix of Hindi + English, natural aur casual
  • Technical terms English mein rakho (noun, photosynthesis, loop)
  • Explanation Hindi-heavy karo — feel familiar lage
  • Never robotic — always teri apni awaaz mein bol

─── RULE 5: NEVER DRY ───────────────────────────────────────────
  ✗ "Inertia means an object at rest stays at rest."
  ✓ "Tu sofa pe pada hai aur uthne ka mann nahi — yeh inertia hai.
     Newton ne bhi predict kiya tha ki tu sunday ko nahi uthega."

─── EXAMPLES OF GOOD TEACHING LINES ────────────────────────────

  Grammar / Past Tense (breakup style):
  "Usne chhodd diya — yeh past tense hai. Kaam complete ho gaya,
   ab toh sirf yaadein hain. 'Chhodd diya', 'gaya', 'kiya' —
   yeh sab bata rahe hain ki kaam khatam ho chuka."

  Math / Fractions (dosti style):
  "5 dost, 3 samose — har ek ko 3/5 milega. Numerator upar,
   denominator neeche. Simple."

  Coding / Loops (breakup style):
  "while still_not_over_her: check_instagram(), feel_sad(), repeat.
   Yeh infinite loop hai. Break chahiye — therapy wala break."

  Science / Gravity (love style):
  "Woh room mein aayi aur teri saari attention khinch gayi —
   mass jitna zyada, attraction utna zyada. Newton ji, theek kaha."

─── WHEN USER ASKS TO TEACH / EXPLAIN SOMETHING ────────────────
  1. TeachingEngine.explain(concept, style=mood) call karo
  2. Narration as-is bol do, ya apne style mein adapt karo
  3. End mein ek quick quiz question pooch: "Ab tu mujhe ek example de!"
  4. Agar woh galat answer de → encourage karo, correct karo gently
  5. Agar sahi → celebrate karo: "Haan yaar, exactly!"

─── QUIZ AFTER EVERY LESSON ─────────────────────────────────────
  Lesson ke baad always ek short question pooch:
  • "Ab tujhe batana hai — yeh example past tense hai ya present? Kyon?"
  • "Ek apna example bana is concept ka — kuch bhi, life se."
  • "Agar main yeh concept remove kar doon, kya fark padega?"

  Quiz se concept pakka hota hai — yeh mandatory hai teaching mode mein.
"""


def get_teaching_prompt_block() -> str:
    """Return teaching prompt block to inject into Vani's system instructions."""
    return TEACHING_PROMPT_BLOCK


# ─────────────────────────────────────────────────────────────────────────────
# 6.  WORKING MEMORY READER
#     Reads vani_working_memory.json to give lessons context about the user.
#     e.g. if user is learning Java → Java examples get priority.
# ─────────────────────────────────────────────────────────────────────────────

import json as _json
import pathlib as _pathlib

_MEMORY_PATHS = [
    _pathlib.Path(__file__).resolve().parents[4] / "vani_working_memory.json",
    _pathlib.Path(__file__).resolve().parents[3] / "vani_working_memory.json",
    _pathlib.Path.cwd() / "vani_working_memory.json",
]


def _load_working_memory() -> dict:
    """Load vani_working_memory.json — returns empty dict on any failure."""
    for p in _MEMORY_PATHS:
        try:
            if p.exists():
                return _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _get_active_subjects(memory: dict) -> list[str]:
    """Extract what the user is currently studying from working memory."""
    topics = memory.get("active_topics", [])
    reminders = memory.get("pending_reminders", [])
    subjects = []
    for t in topics:
        subjects.append(t.get("text", "").lower())
    for r in reminders:
        subjects.append(r.get("text", "").lower())
    return [s for s in subjects if s]


def _infer_style_from_memory(memory: dict) -> str:
    """Infer preferred teaching style from memory context."""
    active = " ".join(_get_active_subjects(memory))
    if any(w in active for w in ["java", "python", "c++", "code", "coding"]):
        return "humor"
    if any(w in active for w in ["exam", "neet", "jee", "upsc"]):
        return "motivation"
    return "humor"  # default — relatable and engaging


# ─────────────────────────────────────────────────────────────────────────────
# 7.  BUILD VISUAL LESSON
#     Main entry point called by router.py's TEACH intent handler.
#     Returns a dict with:
#       spoken_response  — Vani speaks this (concise Hinglish)
#       visual_type      — "flowchart" | "diagram" | "timeline" | "comparison"
#       mermaid_code     — mermaid.js diagram string (for UI panel)
#       concept          — extracted concept name
#       narration        — full teaching narration
#       memory_context   — list of user's active topics (for UI display)
# ─────────────────────────────────────────────────────────────────────────────

import re as _re

# Keywords that indicate specific visual type preferences in the query
_FLOWCHART_WORDS = _re.compile(r"\b(flow|process|steps?|kaise|how\s+does|how\s+do|cycle|loop)\b", _re.I)
_TIMELINE_WORDS  = _re.compile(r"\b(history|timeline|kab|when|chronology|evolution|invention)\b", _re.I)
_COMPARE_WORDS   = _re.compile(r"\b(difference|vs|compare|versus|better|farak|alag)\b", _re.I)
_MINDMAP_WORDS   = _re.compile(r"\b(overview|all\s+about|poora|types\s+of|kinds\s+of|parts\s+of)\b", _re.I)

# Extract concept from query by stripping trigger words
_CONCEPT_STRIP = _re.compile(
    r"^(?:teach\s+me|explain|samjhao|samjha|padha|padh|sikha|bata|batao|"
    r"what\s+is|what\s+are|how\s+does|how\s+do|kya\s+hai|kya\s+hota|"
    r"diagram\s+of|flowchart\s+of|concept\s+of|define|describe|"
    r"mujhe\s+|about\s+|me\s+|the\s+)",
    _re.IGNORECASE,
)


def _extract_concept(query: str) -> str:
    """Strip trigger words and return the bare concept being asked about."""
    concept = _CONCEPT_STRIP.sub("", query.strip()).strip(" ?!.,")
    # Remove trailing filler
    concept = _re.sub(r"\s+(kya|hai|hota|samajhna|seekhna|batao|please|karo)\s*$", "", concept, flags=_re.I)
    return concept.strip() or query.strip()


def _infer_visual_type(query: str) -> str:
    """Decide best visual type from query keywords."""
    if _TIMELINE_WORDS.search(query):
        return "timeline"
    if _COMPARE_WORDS.search(query):
        return "comparison"
    if _MINDMAP_WORDS.search(query):
        return "mindmap"
    if _FLOWCHART_WORDS.search(query):
        return "flowchart"
    return "diagram"  # default


def _build_mermaid_for_concept(concept: str, visual_type: str, lesson: "Lesson") -> str:
    """
    Generate a Mermaid diagram string for the concept.
    Falls back to a simple concept map if nothing specific found.
    """
    c = concept.lower()

    # ── Pre-baked diagrams for common concepts ────────────────────────────────
    DIAGRAMS: dict[str, str] = {
        "photosynthesis": (
            "flowchart TD\n"
            "    Sun[☀️ Sunlight] --> Chlorophyll\n"
            "    CO2[CO₂ from Air] --> Chlorophyll\n"
            "    Water[💧 Water from Roots] --> Chlorophyll\n"
            "    Chlorophyll[🌿 Chlorophyll in Leaf] --> Glucose[🍬 Glucose]\n"
            "    Chlorophyll --> O2[🫧 Oxygen Released]\n"
            "    Glucose --> Energy[⚡ Plant Energy]"
        ),
        "water cycle": (
            "flowchart LR\n"
            "    Ocean[🌊 Ocean / Water Body] -->|Evaporation| Vapor[☁️ Water Vapor]\n"
            "    Vapor -->|Condensation| Cloud[🌧️ Cloud Formation]\n"
            "    Cloud -->|Precipitation| Rain[🌧️ Rain / Snow]\n"
            "    Rain -->|Runoff| River[🏞️ Rivers]\n"
            "    River --> Ocean"
        ),
        "newton's first law": (
            "flowchart TD\n"
            "    Object[📦 Object at Rest] -->|No Force| Rest[Stays at Rest]\n"
            "    Moving[📦 Object in Motion] -->|No Force| Move[Keeps Moving]\n"
            "    Force[💥 External Force Applied] -->|Changes| State[State Changes]\n"
            "    Rest -.->|Until| Force\n"
            "    Move -.->|Until| Force"
        ),
        "newton": (
            "flowchart TD\n"
            "    N1[1st Law: Inertia\nObject stays as-is without force]\n"
            "    N2[2nd Law: F = ma\nForce = Mass × Acceleration]\n"
            "    N3[3rd Law: Action-Reaction\nEvery action has equal opposite]\n"
            "    Newton[🍎 Newton] --> N1\n"
            "    Newton --> N2\n"
            "    Newton --> N3"
        ),
        "cell division": (
            "flowchart TD\n"
            "    Parent[🧬 Parent Cell] --> Interphase\n"
            "    Interphase[Interphase: DNA Copies] --> Prophase\n"
            "    Prophase[Prophase: Chromosomes Visible] --> Metaphase\n"
            "    Metaphase[Metaphase: Line Up Center] --> Anaphase\n"
            "    Anaphase[Anaphase: Pull Apart] --> Telophase\n"
            "    Telophase[Telophase: Two Nuclei] --> Cytokinesis\n"
            "    Cytokinesis[Cytokinesis: Split] --> D1[Daughter Cell 1]\n"
            "    Cytokinesis --> D2[Daughter Cell 2]"
        ),
        "mitosis": (
            "flowchart TD\n"
            "    Parent[🧬 Parent Cell] --> Interphase\n"
            "    Interphase --> Prophase --> Metaphase --> Anaphase --> Telophase\n"
            "    Telophase --> D1[Daughter Cell 1] & D2[Daughter Cell 2]"
        ),
        "heart": (
            "flowchart LR\n"
            "    Body[🫀 Body] -->|Deoxygenated| RA[Right Atrium]\n"
            "    RA -->|Tricuspid Valve| RV[Right Ventricle]\n"
            "    RV -->|Pulmonary Artery| Lungs[🫁 Lungs]\n"
            "    Lungs -->|Oxygenated| LA[Left Atrium]\n"
            "    LA -->|Mitral Valve| LV[Left Ventricle]\n"
            "    LV -->|Aorta| Body"
        ),
        "dna": (
            "flowchart TD\n"
            "    DNA[🧬 DNA Double Helix] --> Gene[Gene: Segment of DNA]\n"
            "    Gene --> mRNA[mRNA via Transcription]\n"
            "    mRNA --> Ribosome[Ribosome]\n"
            "    Ribosome -->|Translation| Protein[🔬 Protein]\n"
            "    Protein --> Trait[Physical Trait]"
        ),
        "democracy": (
            "flowchart TD\n"
            "    People[👥 People / Citizens] -->|Vote| Election\n"
            "    Election[🗳️ Free & Fair Election] --> Govt[Elected Government]\n"
            "    Govt --> Executive[Executive: PM / President]\n"
            "    Govt --> Legislature[Legislature: Parliament]\n"
            "    Govt --> Judiciary[Judiciary: Courts]\n"
            "    Judiciary -->|Checks| Executive\n"
            "    Legislature -->|Checks| Executive"
        ),
        "indian constitution": (
            "mindmap\n"
            "  root((Indian\n  Constitution))\n"
            "    Preamble\n"
            "      Sovereign\n"
            "      Socialist\n"
            "      Secular\n"
            "      Democratic\n"
            "      Republic\n"
            "    Fundamental Rights\n"
            "      Right to Equality\n"
            "      Right to Freedom\n"
            "      Right against Exploitation\n"
            "    DPSP\n"
            "      Non-Justiciable\n"
            "      Welfare State\n"
            "    Fundamental Duties\n"
            "      Article 51A\n"
            "      11 Duties"
        ),
        "oop": (
            "classDiagram\n"
            "    class Animal {\n"
            "        +name: String\n"
            "        +speak()\n"
            "    }\n"
            "    class Dog {\n"
            "        +breed: String\n"
            "        +fetch()\n"
            "    }\n"
            "    class Cat {\n"
            "        +indoor: Bool\n"
            "        +purr()\n"
            "    }\n"
            "    Animal <|-- Dog\n"
            "    Animal <|-- Cat"
        ),
        "sorting": (
            "flowchart TD\n"
            "    Input[📋 Unsorted Array] --> Choose{Algorithm?}\n"
            "    Choose -->|Small data| Bubble[Bubble Sort O n²]\n"
            "    Choose -->|General use| Merge[Merge Sort O n log n]\n"
            "    Choose -->|Best avg| Quick[Quick Sort O n log n]\n"
            "    Choose -->|Already sorted| Insertion[Insertion Sort O n]\n"
            "    Bubble & Merge & Quick & Insertion --> Output[✅ Sorted Array]"
        ),
        "digestive system": (
            "flowchart TD\n"
            "    Food[🍎 Food] --> Mouth[👄 Mouth: Chewing + Saliva]\n"
            "    Mouth --> Esophagus[Esophagus: Peristalsis]\n"
            "    Esophagus --> Stomach[Stomach: HCl + Enzymes]\n"
            "    Stomach --> SmallInt[Small Intestine: Absorption]\n"
            "    SmallInt --> LargeInt[Large Intestine: Water Absorption]\n"
            "    LargeInt --> Rectum[Rectum] --> Waste[🚽 Excretion]"
        ),
        "french revolution": (
            "timeline\n"
            "    title French Revolution\n"
            "    1789 : Estates-General Convened\n"
            "         : Storming of Bastille\n"
            "         : Declaration of Rights\n"
            "    1791 : Constitutional Monarchy\n"
            "    1792 : First French Republic\n"
            "    1793 : Reign of Terror: Robespierre\n"
            "    1799 : Napoleon's Coup"
        ),
        "respiration": (
            "flowchart TD\n"
            "    O2[O₂ Inhaled] --> Lungs\n"
            "    Lungs[🫁 Lungs] -->|Gas exchange| Blood[🩸 Blood]\n"
            "    Blood --> Cells[Body Cells]\n"
            "    Cells -->|Glucose + O₂| ATP[⚡ ATP Energy]\n"
            "    Cells --> CO2[CO₂ Produced]\n"
            "    CO2 --> Blood2[Blood back to Lungs]\n"
            "    Blood2 --> Exhaled[CO₂ Exhaled]"
        ),
        "gravity": (
            "flowchart TD\n"
            "    Mass1[🌍 Mass 1] -->|Gravitational Force| Mass2[🍎 Mass 2]\n"
            "    Mass2 -->|Equal Force| Mass1\n"
            "    Formula[F = G × m1 × m2 / r²]\n"
            "    G[G = 6.67 × 10⁻¹¹ Nm²/kg²]\n"
            "    Note[More mass = More attraction\nMore distance = Less attraction]"
        ),
        "osmosis": (
            "flowchart LR\n"
            "    HighConc[High Concentration Solution] -->|Water moves| Membrane\n"
            "    Membrane[Semi-permeable\nMembrane] --> LowConc[Low Concentration]\n"
            "    Result[Water always moves from\nHigh → Low concentration]\n"
            "    Bio[In cells: keeps cells\nhydrated & turgid]"
        ),
        "electric circuit": (
            "flowchart LR\n"
            "    Battery[🔋 Battery EMF] --> Resistor[Resistor R]\n"
            "    Resistor --> Bulb[💡 Bulb]\n"
            "    Bulb --> Switch[Switch]\n"
            "    Switch --> Battery\n"
            "    V[V = IR: Ohm's Law]\n"
            "    Power[P = VI = I²R]"
        ),
    }

    # Try exact match first
    if c in DIAGRAMS:
        return DIAGRAMS[c]

    # Try substring match
    for key, code in DIAGRAMS.items():
        if key in c or c in key:
            return code

    # Generic fallback — build a simple concept diagram from the lesson
    if lesson:
        safe_concept = concept.replace('"', '').replace('[', '').replace(']', '')
        return (
            f"flowchart TD\n"
            f"    Concept[📖 {safe_concept}]\n"
            f"    Concept --> What[What it is]\n"
            f"    Concept --> How[How it works]\n"
            f"    Concept --> Why[Why it matters]\n"
            f"    Concept --> Example[Real-life example]"
        )
    return f"flowchart TD\n    A[{concept}] --> B[Learn More]"


def build_visual_lesson(engine: "TeachingEngine", query: str) -> dict:
    """
    Main entry point for TEACH intent.

    Reads Vani's working memory to personalize, extracts the concept from the
    query, picks a visual type, generates a Mermaid diagram, builds the lesson,
    and returns a dict ready for both speech (Vani) and visual rendering (UI).

    Returns:
        {
          "concept":          str,
          "visual_type":      str,
          "mermaid_code":     str,
          "spoken_response":  str,   ← Vani speaks this
          "narration":        str,   ← full lesson text for UI
          "memory_context":   list,  ← user's active topics
          "category":         str,
        }
    """
    # 1. Load working memory for context
    memory = _load_working_memory()
    active_subjects = _get_active_subjects(memory)
    preferred_style = _infer_style_from_memory(memory)

    # 2. Extract concept from the raw query
    concept = _extract_concept(query)

    # 3. Decide visual type
    visual_type = _infer_visual_type(query)

    # 4. Get the lesson from TeachingEngine
    lesson = engine.explain(concept, style=preferred_style)  # type: ignore[arg-type]

    # 5. Build mermaid diagram
    mermaid_code = _build_mermaid_for_concept(concept, visual_type, lesson)

    # 6. Build short spoken response (Vani says this, opens UI panel)
    if active_subjects:
        context_hint = f"Tu {active_subjects[0]} seekh raha hai — "
    else:
        context_hint = ""
    spoken_response = (
        f"{context_hint}{concept} ke baare mein samjhate hain! "
        f"Main iska visual diagram bana rahi hoon screen pe. "
        f"{lesson.example[:80]}..."
    )

    return {
        "concept":         concept,
        "visual_type":     visual_type,
        "mermaid_code":    mermaid_code,
        "spoken_response": spoken_response,
        "narration":       lesson.narration,
        "memory_context":  active_subjects,
        "category":        lesson.category,
        "subject":         lesson.subject,
    }



# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    engine = TeachingEngine()

    print("=" * 60)
    print("VANI TEACHING ENGINE — QUICK TEST")
    print("=" * 60)

    # Test 1: List concepts
    print("\n📚 Available concepts (science):")
    for c in engine.list_concepts("science"):
        print(f"   • {c}")

    # Test 2: Explain with different styles
    test_cases = [
        ("photosynthesis", "humor",      "science"),
        ("past tense",     "breakup",    "grammar"),
        ("loops",          "breakup",    "coding"),
        ("fractions",      "dosti",      "math"),
        ("resilience",     "breakup",    "life"),
    ]

    for concept, style, subject in test_cases:
        print(f"\n{'─'*60}")
        print(f"CONCEPT: {concept}  |  STYLE: {style}  |  SUBJECT: {subject}")
        print(f"{'─'*60}")
        lesson = engine.explain(concept, style=style, subject=subject)  # type: ignore[arg-type]
        # Wrap for readability
        print(textwrap.fill(lesson.narration, width=70, replace_whitespace=False))

    # Test 3: Random lesson
    print(f"\n{'═'*60}")
    print("🎲 RANDOM LESSON (love category):")
    print(f"{'═'*60}")
    r = engine.random_lesson(category="love")
    print(textwrap.fill(r.narration, width=70, replace_whitespace=False))

    # Test 4: Quick example only
    print(f"\n{'─'*60}")
    print("⚡ QUICK EXAMPLE ONLY — gravity (love):")
    print(engine.get_example("gravity", category="love"))
