"""Render romanised Hinglish consult scripts in mixed script for TTS.

Hindi words go to Devanagari (from a hand-checked dictionary covering the
generator's vocabulary); English and medical words (drug names, "fever",
"BP") stay in Latin script, which is how code-mixed Hinglish is commonly
written and how a Hindi TTS voice pronounces English loanwords naturally.
Unknown words are left unchanged.
"""
from __future__ import annotations

import re

HI = dict(x.split(":") for x in """
aa:आ aaiye:आइए aaj:आज aajkal:आजकल aana:आना aankhon:आँखों aao:आओ aap:आप aapka:आपका aapki:आपकी aaraam:आराम
aaya:आया aaye:आए ab:अब abhi:अभी achha:अच्छा agar:अगर aisa:ऐसा aur:और baad:बाद baar:बार bachpan:बचपन badan:बदन
badhani:बढ़ानी bahut:बहुत baithiye:बैठिए bataiye:बताइए batayiye:बताइए beh:बह beta:बेटा bhaari:भारी bhejiye:भेजिए bhi:भी
bhookh:भूख bhool:भूल bilkul:बिल्कुल bimari:बीमारी bukhaar:बुखार bukhar:बुखार chaar:चार chakkar:चक्कर daane:दाने dama:दमा
dard:दर्द dast:दस्त dawai:दवाई de:दे denge:देंगे deta:देता dhanyavaad:धन्यवाद dikha:दिखा dikhaiye:दिखाइए dikkat:दिक्कत
din:दिन dino:दिनों do:दो dopahar:दोपहर ek:एक gala:गला gale:गले garam:गरम gaye:गए ghabrahat:घबराहट ghol:घोल haan:हाँ
haath:हाथ hafte:हफ्ते hai:है hain:हैं halka:हल्का har:हर hmm:हम्म ho:हो hoon:हूँ hua:हुआ hui:हुई isko:इसको jaana:जाना
jaata:जाता jalan:जलन ji:जी ka:का kaafi:काफी kabhi:कभी kal:कल kam:कम kamzori:कमज़ोरी kapkapi:कपकपी kariye:करिए
karti:करती karwa:करवा karwane:करवाने ke:के khaansi:खांसी khane:खाने khansi:खांसी kharab:खराब khoob:खूब khoon:खून
ki:की kisi:किसी kitne:कितने kiya:किया ko:को koi:कोई kuch:कुछ kya:क्या laal:लाल laaye:लाए lag:लग lagna:लगना
lagta:लगता lagti:लगती le:ले leke:लेके lena:लेना lene:लेने lete:लेते lijiye:लीजिए liye:लिए machlana:मचलाना
mahine:महीने main:मैं marod:मरोड़ mat:मत mein:में mujhe:मुझे na:ना naak:नाक naashte:नाश्ते nahi:नहीं namak:नमक
namaste:नमस्ते nikal:निकल paanch:पांच paani:पानी pade:पड़े padegi:पड़ेगी padenge:पड़ेंगे padta:पड़ता pareshani:परेशानी
pe:पे peeche:पीछे pehle:पहले pehli:पहली peshab:पेशाब pet:पेट phir:फिर phool:फूल phoolna:फूलना pichli:पिछली
pijiye:पीजिए pilaiye:पिलाइए piyiye:पीजिए poora:पूरा poore:पूरे purani:पुरानी pyaas:प्यास raat:रात raha:रहा rahe:रहे
rahi:रही rehta:रहता rehti:रहती roz:रोज़ sa:सा saab:साब saal:साल saans:सांस saat:सात saath:साथ sahab:साहब sakta:सकता
sar:सर se:से seene:सीने shaam:शाम shukriya:शुक्रिया sikha:सिखा sir:सिर sirf:सिर्फ sone:सोने sookhi:सूखी subah:सुबह
taklif:तकलीफ tarika:तरीका teen:तीन tez:तेज़ tha:था thakan:थकान thand:ठंड the:थे theek:ठीक thoda:थोड़ा to:तो toh:तो
toot:टूट ulti:उल्टी wapas:वापस woh:वो ya:या ye:ये zarurat:ज़रूरत zukaam:ज़ुकाम zyada:ज़्यादा
""".split())


def to_mixed_script(text: str) -> str:
    def sub(m: re.Match) -> str:
        w = m.group(0)
        return HI.get(w.lower(), w)
    return re.sub(r"[A-Za-z]+", sub, text)
