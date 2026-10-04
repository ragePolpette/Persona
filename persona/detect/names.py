"""Common Italian first names, used to recognise "Mario Rossi" without a title or a glossary.

Matching is accent/case-insensitive on the first word only, and a name needs at least one more
capitalised word after it, so a lone "Rosa" or "Aurora" in running text is not enough.
"""

from __future__ import annotations

from persona.textnorm import fold

_MALE = """
alessandro andrea antonio marco francesco luca giuseppe giovanni matteo lorenzo davide simone
federico stefano roberto paolo daniele riccardo michele mario luigi fabio giorgio claudio massimo
gianluca gianmarco gianmaria gianni gian pietro vincenzo salvatore angelo nicola emanuele giacomo
enrico alberto sergio carlo franco bruno giulio cristian christian mattia edoardo tommaso leonardo
filippo samuele gabriele diego alex manuel domenico maurizio marcello valerio vittorio umberto ugo
renato rino raffaele rocco pasquale piero pierluigi pierpaolo gaetano fabrizio ettore elia dario
cesare aldo adriano achille alessio alfredo amedeo antonino armando arturo augusto beniamino
bernardo carmine corrado damiano dino donato eugenio ezio fausto felice fernando flavio gerardo
gianfranco gianpaolo gino graziano guido ivan jacopo lino livio loris mauro mirko moreno nando
nello nunzio orlando oscar osvaldo otello paride rodolfo romeo ruggero saverio sebastiano silvano
silvio tiziano tullio walter giancarlo gianpiero luciano lucio martino nazario orazio oreste elio
ermanno ivano remo sandro sante
""".split()

_FEMALE = """
maria anna giulia francesca sara chiara laura martina valentina elena alessandra silvia federica
elisa paola roberta daniela claudia simona monica barbara cristina stefania michela giorgia alice
elisabetta sofia aurora ilaria serena veronica eleonora marta angela antonella lucia rossella
emanuela teresa rosa patrizia manuela lorena loredana nicoletta raffaella katia giovanna carla
carmela caterina cinzia debora deborah donatella enrica erika eva fabiola fiorella gabriella gaia
giada gloria ida irene jessica lara letizia liliana lisa luisa margherita marina mariangela
marianna marilena marisa matilde mirella nadia natalia noemi nunzia orietta ornella pamela
rachele renata rita samantha sabrina selena sonia tiziana valeria vanessa vera viviana wanda ada
adele agnese alberta amalia ambra arianna beatrice bianca camilla carolina costanza diana emma
fabiana flavia gemma ginevra greta lidia livia lorella mara miriam nora olga piera rebecca
vittoria ludovica maddalena mariella marzia milena morena
""".split()

# Common names from the languages business documents mix in. Ambiguous English words that are also
# names (Mark, Will, Bill, Grace, Hope, Frank, Rose, May, Pat, Don, Art) are left out on purpose.
_INTERNATIONAL = """
john james robert michael william david richard joseph thomas charles daniel matthew anthony paul
steven andrew kevin brian george edward peter jason jeffrey ryan jacob gary nicholas eric stephen
larry justin scott brandon benjamin samuel gregory raymond patrick alexander jack dennis jerry
tyler aaron henry adam douglas nathan zachary kyle walter harold jeremy ethan carl keith roger
gerald terry sean arthur austin noah lawrence jesse joe bryan billy jordan albert dylan bruce
gabriel alan juan logan wayne ralph roy eugene randy vincent russell louis philip bobby johnny
bradley mary patricia jennifer linda elizabeth susan sarah karen nancy betty sandra ashley kimberly
emily donna michelle carol amanda dorothy melissa stephanie rebecca sharon cynthia kathleen amy
shirley brenda nicole helen samantha katherine christine debra rachel carolyn janet catherine
heather diane olivia julie joyce victoria ruth virginia lauren kelly christina joan evelyn judith
megan cheryl hannah jacqueline martha ann madison frances kathryn janice jean abigail julia judy
sophia denise amber doris marilyn danielle beverly isabella theresa natalie brittany charlotte
marie kayla alexis lori hans klaus wolfgang juergen jurgen stefan andreas markus martin joerg uwe
bernd dieter heike petra sabine monika ursula birgit susanne jose carlos miguel javier francisco
jesus luis pedro pablo jorge rafael carmen pilar dolores lucia isabel paula raquel pierre michel
philippe alain jacques bernard nicolas francois nathalie isabelle sylvie sophie camille
"""

FIRST_NAMES = frozenset(fold(name) for name in (*_MALE, *_FEMALE, *_INTERNATIONAL.split()))


def is_first_name(word: str) -> bool:
    return fold(word.strip(".,;:'’")) in FIRST_NAMES
