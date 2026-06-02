"""
vani/reasoning/tools/sex_ed.py
Sex Education tool for Vani — personal use, medically accurate, judgment-free.
Hinglish tone — dost jaisa, comfortable, no awkwardness.

Topics covered:
  - Anatomy (male + female)
  - Puberty & body changes
  - Erections, arousal & wet dreams
  - Menstruation
  - Contraception & safe sex
  - STIs / STDs
  - Consent & healthy relationships
  - Mental health around sexuality
  - Common myths (India-specific)
  - Masturbation (normal, healthy)
  - Pregnancy basics
  - LGBTQ+ basics
  - When to see a doctor

Voice triggers:
  "Vani, sex education ke baare mein batao"
  "Condom kaise use karte hain"
  "Periods kya hote hain"
  "STD kya hota hai"
  "Consent ka matlab kya hai"
  "Random erection kyu hoti hai"
  "Morning wood kya hota hai"
  "Wet dream kya hota hai"
"""

from __future__ import annotations

import re
import logging
from langchain_core.tools import tool

logger = logging.getLogger("vani")

# ─────────────────────────────────────────────────────────────────────────────
# Knowledge base — factual, medically accurate, Hinglish friendly
# ─────────────────────────────────────────────────────────────────────────────

_KNOWLEDGE: dict[str, dict] = {

    "anatomy_male": {
        "keywords": ["penis", "testicle", "testis", "scrotum", "male anatomy", "lund", "anda",
                     "male body", "mard ka sharir", "purush anga"],
        "content": """
Male reproductive anatomy — yeh parts hote hain:

Penis: Urine aur semen bahar aata hai iske through. Erection tab hota hai jab blood flow badh jaata hai.
Testicles (Ande): Scrotum mein hote hain. Sperm aur testosterone produce karte hain. Thoda bahar isliye hote hain kyunki sperm ko body temperature se thoda kam temperature chahiye.
Epididymis: Testicles ke peeche — yahan sperm mature hota hai.
Vas Deferens: Tube jo sperm ko carry karti hai.
Prostate gland: Seminal fluid produce karta hai jo sperm ke saath milke semen banta hai.
Urethra: Common tube for urine aur semen — dono ek saath nahi aate, body khud switch karti hai.

Common myths:
- Penis ka size matter nahi karta jitna log sochte hain — pleasure anatomy pe depend karta hai, size pe nahi.
- Testicles ka ek dusre se thoda alag size hona — completely normal hai.
        """,
    },

    "erections_arousal": {
        "keywords": [
            "erection", "erections", "khada hona", "khada ho jaata", "tight ho jaata",
            "morning wood", "random erection", "automatic erection", "spontaneous erection",
            "subah uthke", "study karte hue", "padhai mein", "important kaam mein",
            "arousal", "aroused", "excited ho jaata", "bina wajah", "achanak",
            "wet dream", "nocturnal emission", "sapne mein", "neend mein",
            "sone ke baad", "uthne ke baad", "blue balls", "precum", "pre-ejaculate",
        ],
        "content": """
Random/automatic erections — yeh normal hai, seriously.

Yeh kab hota hai:
- Subah uthte waqt (morning wood / nocturnal penile tumescence)
- Padhai ya kaam karte hue — completely randomly
- Neend mein (wet dreams)
- Bus baithe baithe — bina kisi sexual thought ke
- Exercise karte waqt
- Stress mein bhi

Kyu hota hai — science:
Erection sirf sexual arousal se nahi hota. Yeh tab hota hai jab nervous system
blood flow increase karta hai penis mein. Yeh automatically hota hai — tumhara
conscious brain ispe control nahi kar sakta fully.

Morning wood specifically: REM sleep (sapne waali neend) ke time body
automatically erections produce karta hai — yeh ek health check hai actually.
Iska matlab yeh nahi ki tumhe kuch sexual sapna aaya.

Padhai mein ya important kaam mein kyu: Brain distracted hota hai, body ke
normal arousal inhibition thoda relax ho jaata hai — result: random erection.
Iska tumhare thoughts se koi connection zaroor nahi.

Kya yeh embarrassing hai:
Physically awkward feel hota hai — especially public mein. But medically yeh
bilkul normal hai. Teenagers mein zyada frequent hota hai (hormones high hote
hain), adults mein kam hota jaata hai.

Kaise manage karo (practical tips):
- Thodi der wait karo — usually 5-10 min mein chala jaata hai
- Kuch aur sochne lagao — literally kuch boring
- Adjust karo silently — koi nahi dekh raha typically
- Sitting mein chhupa rehta hai easily

Wet dreams (nocturnal emission):
- Neend mein ejaculation hona — completely normal
- Adolescence mein zyada common, adults mein bhi hota hai
- Iska matlab koi galat sapna zaroor aaya — yeh zaroor nahi
- Body ka natural way hai jo sperm accumulate hua use release karne ka

Pre-ejaculate (Precum):
- Erection ke time thodi liquid aati hai — yeh lubricant hai
- Isme bhi sperm ho sakta hai — isliye withdrawal method unreliable hai

Kab concern karo:
- Erection 4+ ghante tak bina sexual arousal ke rahe — priapism, medical emergency
- Bahut dard ho erection mein — doctor se milna
- Adolescence ke baad morning wood bilkul band ho jaaye — blood flow ya hormone issue possible
        """,
    },

    "anatomy_female": {
        "keywords": ["vagina", "uterus", "ovary", "clitoris", "female anatomy", "yoni",
                     "female body", "aurat ka sharir", "stri anga", "vulva", "cervix"],
        "content": """
Female reproductive anatomy:

Vulva: Bahar se jo dikhta hai — labia, clitoris, vaginal opening sab iska part hain.
Vagina: Internal canal — periods ka blood, sexual activity, aur childbirth iske through hota hai.
Clitoris: Pleasure ke liye primarily — iska zyaadatar hissa internal hota hai. Bahut sensitive hota hai.
Uterus (Bachhedani): Wahan baby develop hota hai pregnancy mein.
Ovaries: Eggs store karti hain aur hormones produce karti hain (estrogen, progesterone).
Fallopian tubes: Egg ovary se uterus tak jaati hai iske through.
Cervix: Uterus ka lower part — vagina se connect karta hai.
Hymen: Vaginal opening ke paas thin tissue — iska torn hona virginity ka proof nahi hota. Yeh bahut common myth hai.

Common myths:
- Hymen se virginity check nahi hoti — yeh medically false hai.
- Vaginal discharge normal hai — infection ka sign tab hota hai jab smell, color, ya amount abnormal ho.
        """,
    },

    "puberty": {
        "keywords": ["puberty", "growing up", "body changes", "hair", "voice change",
                     "jawani", "umar", "teen", "adolescence", "bada hona"],
        "content": """
Puberty — body ka adult hone ka natural process:

Boys mein (typically 9-14 ke beech shuru):
- Height fast badhti hai
- Voice crack hoti hai, phir deep hoti hai
- Pubic hair, underarm hair, facial hair aate hain
- Testicles aur penis bade hote hain
- Wet dreams (nocturnal emission) — completely normal
- Skin oily hoti hai, acne aa sakta hai
- Sweat zyada aata hai

Girls mein (typically 8-13 ke beech shuru):
- Breasts develop hote hain
- Hips wider hote hain
- Pubic hair aur underarm hair aate hain
- Periods shuru hote hain (menarche)
- Vaginal discharge shuru hoti hai — normal hai
- Height badhti hai (usually periods se pehle peak hoti hai)

Dono mein:
- Mood swings — hormones ki wajah se, normal hai
- Sexual feelings develop hoti hain — normal aur healthy hai
- Body image ke baare mein conscious hona — almost sabko hota hai

Agar puberty bahut jaldi (before 8 in girls, before 9 in boys) ya bahut late aaye — doctor se milna chahiye.
        """,
    },

    "menstruation": {
        "keywords": ["period", "periods", "menstruation", "menstrual", "mc", "monthly",
                     "mahwari", "haiz", "bleeding", "cycle", "cramps", "dysmenorrhea"],
        "content": """
Periods (Menstruation) — monthly cycle:

Kya hota hai: Uterus ki lining jo egg fertilize na hone pe shed hoti hai — yahi period hai.
Cycle length: Average 28 days — but 21-35 din bhi normal hai.
Period duration: 3-7 din.
Flow: Light se heavy — dono normal. Clots bhi normal hain agar bahut bade na hon.

Symptoms jo normal hain:
- Cramps (dysmenorrhea) — lower abdomen, back
- Bloating
- Mood changes
- Breast tenderness
- Fatigue

Doctor ke paas kab jaao:
- Bahut heavy bleeding (1 ghante mein pad bhar jaaye)
- 7 din se zyada
- Severe pain jo daily life affect kare
- Periods completely ruk jaayein (pregnancy ke bina)
- Irregular periods suddenly become very irregular

Hygiene:
- Pad, tampon, menstrual cup — sab safe hain
- Tampon/cup regular change karo (4-8 ghante)
- TSS (Toxic Shock Syndrome) rare hai but real — tampon bahut zyada time tak mat chodo

Common myths India mein:
- Period mein temple/kitchen mein nahi jaana — MYTH, medically koi basis nahi
- Period mein nahana nahi chahiye — MYTH, actually hygiene ke liye zaroori hai
- Period mein khana nahi chahiye — MYTH, nutrition important hoti hai
        """,
    },

    "contraception": {
        "keywords": ["contraception", "contraceptive", "condom", "birth control", "pill",
                     "pregnancy rokna", "safe sex", "protection", "iud", "emergency contraceptive",
                     "morning after", "i pill", "copper t", "family planning"],
        "content": """
Contraception — pregnancy rokne ke tarike:

1. CONDOM (Male) — 98% effective sahi use pe
   - STI se bhi protect karta hai — yahi iska sabse bada advantage
   - Kaise use karein: Expiry check karo. Erection pe lagao, tip pe space chodo (air nikalo).
     Base tak roll karo. After sex, base pakad ke nikalo. Ek baar use karo, dispose karo.
   - Oil-based lubricants mat use karo — condom tod dete hain. Water-based theek hai.

2. FEMALE CONDOM — 95% effective
   - Woman wear karti hai. STI protection bhi deta hai.

3. ORAL CONTRACEPTIVE PILL (OCP)
   - Roz same time pe leni hoti hai
   - 99%+ effective sahi use pe
   - Doctor se prescription lo — kyunki different types hain, sahi choose karna zaroori hai
   - Side effects: Nausea, mood changes initially — usually settle ho jaate hain

4. EMERGENCY CONTRACEPTIVE (I-Pill, unwanted 72)
   - Unprotected sex ke 72 ghante ke andar — jitna jaldi utna better
   - Regular contraceptive ki jagah use mat karo — hormones bahut zyada hote hain
   - 85-95% effective

5. COPPER T (IUD)
   - Doctor insert karti hai — 10 saal tak effective
   - Periods thodi heavy ho sakti hain initially

6. CONDOM + PILL = best protection against both pregnancy AND STIs

Kya kaam nahi karta (myths):
- Withdrawal method (pull out) — unreliable, pre-ejaculate mein bhi sperm hota hai
- Pehli baar sex mein pregnancy nahi hoti — MYTH, hoti hai
- Standing sex mein pregnancy nahi hoti — MYTH
        """,
    },

    "sti_std": {
        "keywords": ["sti", "std", "sexually transmitted", "infection", "hiv", "aids",
                     "chlamydia", "gonorrhea", "syphilis", "herpes", "hpv", "yoni infection",
                     "sex se bimari", "yaunsankraman"],
        "content": """
STIs (Sexually Transmitted Infections) — sex ke through spread hone wali bimariyan:

Common STIs:

HIV/AIDS:
- Blood, semen, vaginal fluids, breast milk se spread hota hai
- Condom use se risk bahut kam hota hai
- PrEP (Pre-Exposure Prophylaxis) — HIV negative log le sakte hain prevention ke liye
- Early treatment se normal life possible hai
- Test zaroori hai — symptoms saalon baad aate hain

Chlamydia:
- Bahut common, often no symptoms
- Antibiotics se theek hota hai
- Untreated raha toh infertility cause kar sakta hai

Gonorrhea:
- Discharge, burning urination
- Antibiotics se theek hota hai (but antibiotic resistance badh raha hai)

Syphilis:
- Stages mein aata hai — painless sore (chancre) pehle
- Antibiotics se theek hota hai
- Untreated raha toh serious damage

Herpes (HSV):
- Blisters/sores genitals ya mouth pe
- Cure nahi hai but manageable — medication se outbreaks kam hote hain
- Bahut common — stigma zyada hai reality se

HPV:
- Sabse common STI
- Most cases khud resolve ho jaate hain
- Kuch strains cervical cancer cause karte hain — isliye HPV vaccine important hai
- Gardasil vaccine available hai India mein

Testing:
- Sexually active ho toh regular STI testing recommended hai — especially new partners ke saath
- Most STIs asymptomatic hote hain initially
- Government hospitals mein free testing available hai

Doctor se milne mein sharm mat karo — yeh medical conditions hain, character nahi.
        """,
    },

    "consent": {
        "keywords": ["consent", "permission", "no means no", "rape", "sexual assault",
                     "harassment", "molestation", "force", "pressure", "anumati",
                     "razi hona", "force karna", "metoo"],
        "content": """
Consent — sabse important concept:

Consent ka matlab:
- FREELY given — pressure, threat, ya manipulation ke bina
- REVERSIBLE — koi bhi apna mind badal sakta hai, kisi bhi time pe
- INFORMED — dono ko pata ho kya ho raha hai
- ENTHUSIASTIC — "theek hai" enough nahi — active "haan" chahiye
- SPECIFIC — ek cheez ke liye haan matlab sab ke liye haan nahi

Consent nahi hota jab:
- Person so raha ho, unconscious ho, ya drunk/high ho
- Age of consent se chhota ho (India mein 18 saal)
- Daraya gaya ho, pressurize kiya gaya ho
- Relationship mein hai — iska matlab automatic consent nahi hota (marital rape real hai)

"No" kaise sunein:
- Agar body language uncomfortable hai — ruko aur poochho
- Ek baar "no" = no. Argue mat karo, convince karne ki koshish mat karo
- "Main ready nahi hoon" bhi no hai

Agar tumhare saath kuch galat hua:
- Tumhari galti nahi thi — koi bhi dress, time, ya situation consent replace nahi karti
- National Sexual Assault Helpline: iCall — 9152987821
- Police complaint karo agar comfortable ho — FIR file kar sakte ho
- Medical help lo — evidence preserve karne ke liye 72 ghante important hain

Healthy relationship mein:
- Dono partners comfortable feel karte hain
- Koi bhi kisi bhi time rok sakta hai
- Pressure ya guilt nahi hota
        """,
    },

    "masturbation": {
        "keywords": ["masturbation", "masturbate", "self pleasure", "hath maarna",
                     "hathkand", "khud se", "solo", "touching yourself", "hastamaithun"],
        "content": """
Masturbation — normal aur healthy hai:

Kya hai: Apne genitals ko pleasure ke liye touch karna — sab log karte hain, boys bhi girls bhi.

Health benefits (scientifically proven):
- Stress relief
- Better sleep
- Apne body ko samajhna — kya achha lagta hai
- Period cramps mein relief (girls ke liye)
- Prostate health (boys ke liye)

Myths jo India mein bahut common hain:
- "Haath pair kamzor ho jaate hain" — MYTH, medically bilkul false
- "Andha ho jaata hai" — MYTH
- "Sperm khatam ho jaata hai" — MYTH, body continuously produce karti hai
- "Marriage mein problem aayegi" — MYTH
- "Pimples aate hain" — MYTH
- "Koi nahi karta" — MYTH, almost everyone does at some point

Kab concern karo:
- Agar roz multiple times karna compulsive feel ho raha ho aur daily life affect kar raha ho
- Agar relationships ya responsibilities neglect ho rahi hain
- Tab therapist se baat karo — yeh sex addiction ho sakta hai (rare)

Normal frequency: Koi "normal" frequency nahi hoti — daily bhi normal hai, kabhi nahi bhi normal hai.
        """,
    },

    "pregnancy": {
        "keywords": ["pregnancy", "pregnant", "garbhavati", "baby", "conception",
                     "fertilization", "trimester", "abortion", "miscarriage", "birth",
                     "delivery", "prasav", "baccha", "maa banana"],
        "content": """
Pregnancy basics:

Kaise hoti hai:
- Sperm egg ko fertilize karta hai (ovulation ke time)
- Fertilized egg uterus mein implant hoti hai
- Pregnancy test urine mein HCG hormone detect karta hai
- Home pregnancy test — period miss hone ke baad most accurate

Symptoms:
- Missed period (sabse common sign)
- Nausea/morning sickness
- Breast tenderness
- Fatigue
- Frequent urination

Trimesters:
- 1st (1-12 weeks): Baby ke major organs develop hote hain. Miscarriage risk highest.
- 2nd (13-26 weeks): Most comfortable phase usually. Baby movement feel hoti hai.
- 3rd (27-40 weeks): Baby ka weight gain. Delivery preparation.

Prenatal care:
- Doctor se regular checkup — pehle trimester mein confirm karo aur schedule banao
- Folic acid important hai — neural tube defects prevent karta hai
- Smoking, alcohol, certain medications avoid karo

Abortion (Medical Termination of Pregnancy — MTP):
- India mein legal hai up to 20 weeks (certain conditions mein 24 weeks)
- Registered doctor se karo — unsafe abortion dangerous hai
- Medical abortion (pills): Up to 9 weeks
- Surgical: Doctor perform karega
- MTP clinics government hospitals mein available hain

Miscarriage:
- Bahut common — especially first trimester mein (~10-20% pregnancies)
- Tumhari galti nahi hoti — mostly chromosomal issues hote hain
- Emotional support zaroori hai — grief real hai

Ectopic pregnancy: Egg fallopian tube mein implant ho jaaye — medical emergency hai.
        """,
    },

    "lgbtq": {
        "keywords": ["lgbtq", "gay", "lesbian", "bisexual", "transgender", "queer",
                     "homosexual", "same sex", "non binary", "gender identity",
                     "sexual orientation", "coming out", "homo", "section 377"],
        "content": """
LGBTQ+ — basic understanding:

Sexual orientation (kiske taraf attract hote ho):
- Heterosexual (Straight): Opposite gender ki taraf
- Homosexual (Gay/Lesbian): Same gender ki taraf
- Bisexual: Dono genders ki taraf
- Pansexual: Gender ke bina, person ki taraf
- Asexual: Sexual attraction bahut kam ya bilkul nahi

Gender identity (tum khud ko kya feel karte ho):
- Cisgender: Birth sex aur gender identity match karti hai
- Transgender: Birth sex aur gender identity alag hai
- Non-binary: Exclusively male ya female nahi feel karte
- Gender fluid: Identity shift karti hai

Kya yeh normal hai:
- Haan — WHO ne 1990 mein homosexuality ko mental illness se remove kiya
- Sexual orientation choice nahi hai — nature + nurture ka combination
- India mein Section 377 partially struck down in 2018 — adult same-sex relations decriminalized

India mein LGBTQ+ resources:
- The Humsafar Trust (Mumbai): humsafar.org
- Naz Foundation: Delhi
- iCall helpline: 9152987821 (also handles LGBTQ+ concerns)

Common myths:
- "Phase hai, change ho jaayega" — MYTH
- "Therapy se straight ho sakte hain" — Conversion therapy harmful aur ineffective hai, WHO condemn karta hai
- "Family ke saath nahi hoga" — Yeh fear real hai but support communities exist karti hain
        """,
    },

    "healthy_relationships": {
        "keywords": ["relationship", "partner", "boyfriend", "girlfriend", "dating",
                     "love", "breakup", "toxic", "healthy relationship", "pyaar",
                     "rishta", "communication", "boundaries"],
        "content": """
Healthy relationships — kya dekhna chahiye:

Signs of a healthy relationship:
- Dono log comfortable feel karte hain apni baat karne mein
- Boundaries respect hoti hain — physical aur emotional dono
- No pressure for anything — sex, time, decisions
- Arguments hote hain but respectfully — insults, threats nahi
- Apni individual identity maintain kar sakte ho
- Dono ki feelings equally matter karti hain

Red flags (toxic relationship signs):
- Jealousy ko love ki tarah present karna
- Friends aur family se isolate karna
- Constantly check karna — phone, location
- Emotional manipulation — guilt trips, gaslighting
- Physical ya verbal abuse — koi excuse acceptable nahi
- "Main tumhare bina jee nahi sakta/sakti" — yeh love nahi, unhealthy dependency hai

Sexual pressure:
- "Agar pyaar karte ho toh karo" — yeh manipulation hai
- Relationship mein hona consent nahi hai
- Kabhi bhi "no" kehna tumhara right hai

Breakups:
- Painful hote hain — feel karna normal hai
- Kisi ko date karte rehne ke liye force karna possessive hai
- iCall: 9152987821 — emotional support ke liye

Communication tips:
- "Mujhe aisa feel hota hai jab..." — accusatory "tum yeh karte ho" se better
- Listen karo — sirf respond karne ke liye nahi
- Disagreement mein bhi respect
        """,
    },

    "myths_india": {
        "keywords": ["myth", "misconception", "galat", "sach", "reality", "fact",
                     "sex myths", "sex ke baare mein galat dharna", "indian myths"],
        "content": """
Common Indian sex myths — aur unki reality:

MYTH: Pehli baar sex mein pregnancy nahi hoti.
FACT: Hoti hai. Ek bhi sperm kaafi hai.

MYTH: Pehli baar sex mein ladki ko bleeding honi chahiye.
FACT: Zaroor nahi. Hymen already torn ho sakti hai exercise, tampon, ya simply genetics se.

MYTH: Masturbation se kamzori aati hai.
FACT: Medically completely false. Zero physical harm hota hai.

MYTH: Condom use karne se pleasure kam hoti hai toh zaroor nahi.
FACT: Condom use karo — yeh STI aur pregnancy dono se bachata hai. Better condoms available hain jo sensation reduce nahi karte.

MYTH: Oral sex safe hai, STI nahi hoti.
FACT: Herpes, gonorrhea, syphilis, HPV — sab oral sex se spread ho sakte hain.

MYTH: Agar ladka zyada partners ke saath soya toh "cool" hai, ladki ne kiya toh "bad character".
FACT: Yeh sexist double standard hai. Character sexual history se nahi naapta.

MYTH: Gay log asli mard nahi hote.
FACT: Sexual orientation aur masculinity mein koi connection nahi hai.

MYTH: Period mein sex nahi ho sakta.
FACT: Can happen — though messy. Pregnancy possible hai (rare but possible — sperm survive kar sakta hai). STI risk same rehta hai.

MYTH: Size matters sabse zyada.
FACT: Pleasure ke liye communication, trust, aur knowing each other's bodies matters more.

MYTH: Virginity ek clear, definable concept hai.
FACT: Medical ya physical sense mein virginity define nahi hoti accurately. Yeh social construct hai.
        """,
    },

    "when_to_see_doctor": {
        "keywords": ["doctor", "help", "problem", "pain", "discharge", "symptoms",
                     "kab doctor", "hospital", "issue", "consult"],
        "content": """
Kab doctor ke paas jaana chahiye — sexual health ke liye:

Immediately:
- Sexual assault ke baad (72 ghante mein — evidence + medical care)
- Severe pelvic/abdominal pain
- Heavy abnormal bleeding
- Genital injuries

Within a few days:
- Unusual discharge — color, smell, amount mein change
- Burning during urination
- Genital sores, blisters, rashes, warts
- New sexual partner — STI test karo
- Missed period + unprotected sex

Routine checkups:
- Sexually active hain toh yearly STI test recommended
- Girls 21+ ke baad — Pap smear (cervical cancer screening) har 3 saal
- HPV vaccine — 9-45 age mein effective, lekin jitna jaldi utna better

Where to go in India:
- Government hospitals — free OPD, confidential
- Family planning clinics — contraception aur STI testing
- ASHA workers — rural areas mein
- Online: practo.com, 1mg.com pe doctor consult kar sakte ho anonymously

Doctor se baat karne mein sharm:
- Doctors professional hote hain — judge nahi karte
- Jo bhi bolo confidential rehta hai
- Apna question clearly explain karo — directly bolna better hai
- Agar ek doctor uncomfortable kare — doosra dhundho, yeh tumhara right hai

Helplines:
- iCall: 9152987821 (mental health + sexual health)
- Vandrevala Foundation: 1860-2662-345 (24/7)
        """,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Topic classifier
# ─────────────────────────────────────────────────────────────────────────────

def _find_topic(query: str) -> str | None:
    q = query.lower()
    best_topic = None
    best_score = 0
    for topic, data in _KNOWLEDGE.items():
        score = sum(1 for kw in data["keywords"] if kw in q)
        if score > best_score:
            best_score = score
            best_topic = topic
    return best_topic if best_score > 0 else None


# ─────────────────────────────────────────────────────────────────────────────
# Main tool
# ─────────────────────────────────────────────────────────────────────────────

@tool
def sex_education(query: str) -> dict:
    """
    Sex education — medically accurate, judgment-free, Hinglish friendly.
    Topics: anatomy, puberty, periods, contraception, STIs, consent,
    masturbation, pregnancy, LGBTQ+, healthy relationships, myths.

    Args:
        query: Jo bhi poochna hai — "condom kaise use karein", "periods kya hote hain", etc.

    Returns:
        {
          "topic": str,
          "content": str,       # full educational content
          "voice_reply": str,   # Vani bolegi (shorter)
        }
    """
    topic = _find_topic(query)

    if topic and topic in _KNOWLEDGE:
        content = _KNOWLEDGE[topic]["content"].strip()
        # Voice reply — first 3 meaningful lines, then invite follow-up
        lines = [l.strip() for l in content.split("\n") if l.strip() and not l.strip().endswith(":")]
        short = " ".join(lines[:4])
        if len(short) > 500:
            short = short[:497] + "..."
        voice_reply = short + " Aur detail chahiye toh pooch, bhai."
    else:
        content = (
            "Yaar, yeh topic mujhe samajh nahi aaya exactly. "
            "Inme se kuch pooch: anatomy, puberty, periods, contraception, "
            "STI/STD, consent, masturbation, pregnancy, LGBTQ+, ya sex myths."
        )
        voice_reply = content
        topic = "unknown"

    return {
        "topic":       topic,
        "content":     content,
        "voice_reply": voice_reply,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Intent classifier — for router.py
# ─────────────────────────────────────────────────────────────────────────────

_SEX_ED_TRIGGERS = re.compile(
    r"\b("
    r"sex|sexual|sexuality|sexed|sex.?education|"
    r"condom|contraception|contraceptive|birth.?control|"
    r"period|periods|menstruation|mahwari|"
    r"puberty|jawani|bada.?hona|"
    r"std|sti|hiv|aids|sexually.?transmitted|"
    r"consent|anumati|"
    r"masturbat|hastamaithun|hath.?maarna|"
    r"pregnancy|pregnant|garbhavati|"
    r"lgbtq|gay|lesbian|bisexual|transgender|"
    r"anatomy|genitals|penis|vagina|uterus|ovary|"
    r"hymen|virginity|virgn|"
    r"sex.?myth|sex.?fact|"
    r"safe.?sex|protection.?sex|unprotected|"
    r"sperm|ovulation|fertiliz|"
    r"erection|morning.?wood|khada.?hona|random.?erect|spontaneous|"
    r"wet.?dream|nocturnal|arousal|aroused|precum|pre.?ejaculat|"
    r"blue.?balls|priapism|excited.?ho.?jaata|bina.?wajah.?tight"
    r")\b",
    re.I,
)


def classify_sex_ed_intent(text: str) -> tuple[str, dict] | tuple[None, None]:
    """
    Returns ("sex_education", {"query": text}) if query is sex ed related.
    Wire this in router.py before Ollama.
    """
    if _SEX_ED_TRIGGERS.search(text):
        return "sex_education", {"query": text}
    return None, None