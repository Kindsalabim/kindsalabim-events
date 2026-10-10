"""Anrede in Mails an Kunden (Aykut 10.10.2026).

Ist am Vornamen eindeutig erkennbar, ob Frau oder Herr, heißt es „Hallo Frau Aslan,“
bzw. „Hallo Herr Blade,“, unabhängig von der Herkunft des Namens. Bei Vornamen, die
für beide Geschlechter vorkommen, und bei allen nicht gelisteten Namen bleibt es beim
vollen Namen: „Hallo Kim Weber,“. Geraten wird nie, ein falsches „Herr“ an eine Frau
ist schlimmer als gar keine Anrede.

Die Listen stammen aus dem E-Mail-Assistenten (draft_service.py, Erstkontakt) und sind
hier erweitert. Dienstleister-Mails duzen mit Vornamen und nutzen das hier nicht.
"""

_WEIBLICH = frozenset("""
abigail agnieszka aisha alexandra aleyna alina amanda amandine amelia amelie amina ana
angelika anja anke anna anne annette annika anouk antje antonella asli astrid aurelie
ava aylin ayse aysel ayten barbara beata beate beatriz berivan berna bettina betty
bianca birgit brigitte buesra burcu büsra canan cansu carina carmen carol carolin
caroline catherine celina celine ceren chantal charlotte chiara chloe christel
christiane christina christine claire clara claudia cornelia cristina dagmar damla
daniela deborah denise derya diana dilek dimitra dolores donna doris dorota dorothy
dragana duygu ebru edith elena eleni elif elin elisabeth elke ella emel emilia emily
emine emma erika esma esra eva evelyn ewa fadime fatima fatma femke filiz francesca
francoise franziska frauke freya frida funda gabriele galina gamze georgia gerda gertrud
gisela giulia gizem grace grazyna gudrun guel guelsen gönül gül gülsen hacer halina hana
handan hande hanna hannah hannelore hatice hayriye heather hedwig heidi heike helen
helene helga henriette hevin hiba hilal hilde holly huelya hülya ilse imke ines inge
ingrid insa ipek irem irene irina iris isabel isabell isabella isabelle ivana jacqueline
jana janina janine jasmin jelena jennifer jessica joanna johanna josefine judith jule
julia jutta kader karen karin karina katarzyna kate katerina katharina kathrin katie
katja katrin kerstin khadija kirsten klara kristin kristina kuebra kübra lara larissa
laura lauren layla lea leila lena leonie leyla lily lina linda linnea lisa ljudmila
lotte lucia luisa lydia maaike madison magdalena malgorzata mandy manon manuela maren
margaret margarete maria mariam marianne marie marija marina marion marlene marta martha
martina mary maryam mechthild megan meike melanie melek melike melisa melissa mercedes
merve mia michaela michelle mila milica miriam monika monique nadeschda nadia nadine
nancy narges nasrin natalia natalie natascha nathalie nazli nele nese nicole nihan
nilguen nilgün nina nur nurcan nuria nurten oezge oezlem oksana olga olivia parisa
patricia paula peggy pelin petra pia pilar pinar rabia rachel rania rebecca regina
renate rita rosa rosaria rosemarie rosie roya ruth sabine sabrina salma samantha samira
sandra sanne sara sarah seda selin selina sema sevda sevgi sevim sharon shirin sibel
sigrid silke silvana silvia simone sofia songuel songül sonja sophia sophie soraya
stefanie steffi stephanie susan susanne svenja svetlana sybille sylvie tamara tanja
tatjana teresa theresa tina tuelay tuerkan tugba tülay türkan ulrike ursula ute
valentina valerie vanessa vera verena veronika vesna victoria waltraud wiebke yasemin
yasmin yasmina yeliz yvonne zahra zehra zeynep zoe özge özlem
""".split())

_MAENNLICH = frozenset("""
aaron abdullah adam adem ahmad ahmed ahmet alejandro aleksandar alexander alexej ali
amir anatoli anders andre andreas andrew andrzej andré angelo anthony antonio aykut
baris bastian bekir ben benjamin bernd bernhard bilal bjoern björn bram brandon brian
burak caner carlos carsten cem cengiz charles christian christoph christopher christos
cihan connor daniel david davut dejan dennis detlef diego dieter dimitrios dirk dmitri
dominik donald dragan dylan eberhard eckhard edward elias emin emre enes engin ercan
eren eric erich erik erkan ernst ethan fabian fatih felix ferdinand ferhat fernando finn
florian francesco francois frank friedrich furkan gary georg george gerd gerhard giorgos
giovanni giuseppe goekhan goran gregor gregory guenter gunnar gustav gökhan günter hakan
halil hamid hamza hannes hans harald harry hartmut hasan hassan heiko heinrich heinz
helmut hendrik henning henrik henry herbert hermann holger horst hossein hubert huseyin
hussein hüseyin ibrahim igor ingo ioannis ismail ivan jack jacob jacques jake jakob
james jan jannik jason javier jeffrey jens jeroen jerzy jewgeni joachim joerg joern
johannes john jonas jonathan jorge jose josef joseph joshua juan juergen julian justin
jörg jörn jürgen kaan kadir kai karim karl karsten kemal kenneth kerem kevin khaled
klaus konrad konstantinos kostas krzysztof kurt kyle larry lars laurent lennart leon
levent liam logan lucas luis lukas luke lutz magnus mahmoud mahmut malte manfred manuel
marc marcel marco marek mario mark marko markus martin marvin mason mathias mats matthew
matthias mattis max maximilian mehdi mehmet mert metin michael michel miguel milan
mohammed moritz muhammed murat mustafa nasser nathan nenad nicholas niclas nico nicolas
niklas nikolai nikolaos nikolas nikos nils noah norbert nuri oguz okan olaf ole oliver
olivier omar onur orhan osman otto owen pablo panagiotis paolo pascal patrick paul pawel
pedro peter philipp philippe pierre pieter piotr polat rafael rainer ralf rami ramon
raymond recep reiner reza richard ridvan robert roberto roland rolf ronald rudolf
ruediger ryan ryszard rüdiger salvatore samir samuel savas scott sean sebastian selim
serdar sergej sergio serkan siegfried simon sinan soner stanislaw stefan stefano steffen
stephen steven sven tamer taner tarek tarkan thierry thomas thorsten till tim timo
timothy tobias tolga tom tomasz torben torsten tuncay tyler udo ufuk ulrich uwe vasilis
veli viktor vincent vincenzo vladimir volkan volker waldemar walid walter werner
wilfried wilhelm willi william wojciech wolfgang wouter yannick yasin yavuz yigit yilmaz
youssef yunus yusuf zafer zbigniew zeki zoran
""".split())

# Kommt in mindestens einer Sprache für beide Geschlechter vor: nie raten.
_UNEINDEUTIG = frozenset("""
alex alexis andrea ariel ashley avery bilge billie camille casey charlie chris claude
connie conny deniz dilan dominique eden eike elia evren frankie gabriel gerrit guenay
günay ilkay jamie janis jean jo jordan kay kelly kim lou luca maxi mel micha mika morgan
nicola nikita noa noor nour oezguer pat rene rené riley robin sam sascha sasha sezen
sidney sigi taylor toni uemit ulli umut yesim özgür ümit
""".split())

_PARTIKEL = {"von", "van", "de", "der", "den", "du", "da", "di", "del", "la", "le",
             "zu", "zur", "vom", "ten", "ter", "el", "al", "bin", "ibn"}
_TITEL = {"dr", "dr.", "prof", "prof.", "dipl.-ing.", "dipl.", "ing."}


def _schluessel(vorname: str) -> list:
    """Schreibvarianten eines Vornamens: Ayşe → ayse, Jürgen → jürgen/juergen/jurgen."""
    v = vorname.strip().lower().rstrip(".")
    v = v.split("-")[0]                     # Anna-Lena → anna
    v = (v.replace("ş", "s").replace("ç", "c").replace("ğ", "g").replace("ı", "i")
         .replace("é", "e").replace("è", "e"))
    varianten = [v, v.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue"),
                 v.replace("ä", "a").replace("ö", "o").replace("ü", "u")]
    return list(dict.fromkeys(varianten))


def geschlecht(vorname: str) -> str:
    """„Frau“, „Herr“ oder "" (nicht sicher)."""
    keys = _schluessel(vorname or "")
    if not keys[0] or len(keys[0]) < 2 or any(k in _UNEINDEUTIG for k in keys):
        return ""
    if any(k in _WEIBLICH for k in keys):
        return "Frau"
    if any(k in _MAENNLICH for k in keys):
        return "Herr"
    return ""


def kunden_anrede(name: str, ohne_name: str = "Guten Tag,") -> str:
    """Begrüßungszeile für eine Kundenmail.

    „Sandra Schero“ → „Hallo Frau Schero,“ · „Jake Blade“ → „Hallo Herr Blade,“ ·
    „Kim Weber“ → „Hallo Kim Weber,“ · „Frau Schmidt“ bleibt · „Dr. Anna Meier“ →
    „Hallo Frau Dr. Meier,“ · „Jan van der Berg“ → „Hallo Herr van der Berg,“.
    Mehrere Personen („Anna und Peter Meier“) oder nur ein Wort: Name wie angegeben."""
    wert = " ".join((name or "").split())
    if not wert:
        return ohne_name
    teile = wert.split()
    if teile[0] in ("Frau", "Herr"):
        return f"Hallo {wert},"
    if len(teile) < 2 or any(t.lower() in ("und", "u.", "&", "/", "+") for t in teile)             or "," in wert or "/" in wert:
        return f"Hallo {wert},"
    titel = []
    while teile and teile[0].lower() in _TITEL:
        titel.append(teile.pop(0))
    if len(teile) < 2:
        return f"Hallo {wert},"
    anrede = geschlecht(teile[0])
    if not anrede:
        return f"Hallo {wert},"
    rest = teile[1:]
    # Nachname: ab dem ersten Namenszusatz (van der Berg), sonst das letzte Wort
    # (zweite Vornamen wie in „Anna Maria Meier“ fallen weg).
    for i, t in enumerate(rest):
        if t.lower() in _PARTIKEL and i < len(rest) - 1:
            nachname = " ".join(rest[i:])
            break
    else:
        nachname = rest[-1]
    return f"Hallo {' '.join([anrede] + titel + [nachname])},"
