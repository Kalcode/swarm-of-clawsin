"""Prompt construction. The system prompt is identical for every creature so the model
server's prefix cache can reuse it; everything creature-specific comes after it."""

from __future__ import annotations

import random
import re

from ..world.actions import VERBS
from ..world.model import Creature, World
from .memory import Memory

SYSTEM_PROMPT = """You are a living creature in a small wild world. This is not a game you are playing: you only know what your own senses tell you right now, plus your memories. Other creatures live here too, each with a mind of its own. Sound carries only about 5 steps, so to talk with someone, walk to them first.

Each turn choose ONE action and reply with ONLY a JSON object of this shape:
{"thought": "...", "action": "...", "target": "...", "items": [], "text": "", "count": 1, "goal": "", "speech": ""}
- thought: one short sentence of private reasoning.
- goal: your longer-term aim in a few words; "" keeps your current goal.
- speech: words you say out loud WHILE doing the action (others nearby hear them), or "" to stay quiet. Talk while you work: if you're hungry, go get food and mention it on the way; don't stand around talking about it.
- Use "", [] or 1 for fields the action doesn't need.

Actions:
- walk_to (target): walk next to something or someone you can see, e.g. "oak tree", "Mara", "water".
- explore (target): wander about 8 steps in a direction ("north", "southwest"...) to find new places.
- gather (target, count): take materials from something right beside you. Trees give sticks (and logs if you carry an axe). Berry bushes give berries. Boulders give stone and sometimes flint. Grass gives plant fiber. Streaked rocks give ore if you carry a pickaxe. Clay banks give clay. Water gives fish if you carry something to catch them with.
- combine (items): try putting things you carry together to invent something new, e.g. ["stick", "stone", "rope"]. Much can be discovered this way. Some things need a tool carried or a station nearby (a burning campfire, a workbench, a furnace).
- craft (target, count): make something whose recipe you already know.
- eat (target): eat food you carry. drink: drink while beside water.
- say (text, target): only when talking IS the whole point (a question, an answer, a plan). Otherwise do something useful and put your words in speech.
- teach (target, items): show someone within earshot how to make a thing you know, e.g. target "Mara", items ["stone knife"].
- give (target, items, count): hand something to the creature beside you, feed an animal, or feed sticks to a campfire to keep it burning.
- store (target, items) / take (target, items): put things into a basket or chest for everyone, or take things out.
- pick_up (target) / drop (target): take or leave items on the ground.
- place (target): set down a structure you carry: campfire, workbench, sign, wooden wall, furnace, chest, terminal.
- write (text): carve words onto a sign, tree or boulder beside you; they stay for anyone to find. read (target): read a sign, carving, tablet or terminal.
- program (text): enter Lua code into a terminal beside you.
- plant (target, count): plant seeds or berries in the soil beside you (needs a tool to break the soil).
- invent (target, items, text): create something brand new from 2-4 things you carry, even other inventions. target is its name, text says what it is or does. Once a day.
- rest (count): recover energy. wait: pause and watch.

Good to know: most tools begin with sticks, stone and plant fiber, and trying combinations is how anything new is found. Hunger grows; eat before you starve or you will collapse and lose everything you carry. Nights are dark, and fire gives light. Discoveries are precious: tell others what you learn, teach them, write recipes on signs. Only name things you can actually see, carry or remember. Speak briefly and naturally, in your own voice. Skip empty pleasantries; talk about useful things: where food and materials are, what you made and how, what you need, plans to work together.

Example reply:
{"thought": "I need stone for tools and the boulder is right here.", "action": "gather", "target": "boulder", "items": [], "text": "", "count": 3, "goal": "make a stone axe", "speech": "Mara, I'll get the stone if you find sticks!"}"""

INTENTION_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string", "maxLength": 200},
        "action": {"type": "string", "enum": VERBS},
        "target": {"type": "string", "maxLength": 60},
        "items": {"type": "array", "items": {"type": "string", "maxLength": 30}, "maxItems": 4},
        "text": {"type": "string", "maxLength": 600},
        "count": {"type": "integer", "minimum": 1, "maximum": 5},
        "goal": {"type": "string", "maxLength": 120},
        "speech": {"type": "string", "maxLength": 160},
    },
    "required": ["thought", "action", "target", "items", "text", "count", "goal", "speech"],
    "additionalProperties": False,
}

TRAITS = [
    "curious", "patient", "bold", "cautious", "chatty", "quiet", "generous", "stubborn", "playful",
    "practical", "dreamy", "careful", "restless", "kind", "proud", "clever", "gruff", "cheerful",
    "thoughtful", "inventive", "loyal", "competitive", "gentle", "witty",
]
DRIVES = {
    "curious": "a hunger to discover how things work and what can be made",
    "builder": "a wish to build lasting things and make a home",
    "social": "a love of company, talking and helping others",
    "explorer": "a pull toward the unknown edges of the world",
    "gatherer": "a need to collect, store and never go hungry",
    "tinkerer": "an itch to combine things and invent tools",
    "teacher": "a joy in sharing what you know so others can thrive",
}
NAMES = (
    "Tam Mara Odo Pell Juno Rook Fen Isla Brin Kael Lio Sable Wren Tovi Ash Nim Orla Cass Dax Hale Ivo Lark Mott Nell "
    "Pip Quin Rue Sorrel Tib Ula Vesk Wim Yara Zeb Arlo Bea Cole Dree Elm Fae Gus Hob Ira Jory Kit Lune Moss Nyx Ono "
    "Pru Reed Suki Tarn Uma Vale Wyn Xan Yew Zola Ari Bo Cyd Dov Eda Flint Gil Hux Imo Jett Kip Lev Mae Nox Oaky Pax "
    "Rhea Sage Teo Urs Vim Wade Yoko Zia Alba Bram Ciel Dune Esk Fable Gale Holt Inka Jun Kova Lumi Mika Nils Opal "
    "Pike Remy Sol Tula Una Vex Willa Yves Zinn Asa Birch Coda Delta Echo Fizz Grit Hazel Ixa Jinx Kelp Loam Mirth"
).split()


# Temperament: how a creature goes about things, independent of what it wants (its drive).
INITIATIVE = {
    "proactive": "You don't wait for things to happen: you start projects, go looking, try things.",
    "reactive": "You mostly respond to what happens around you, and you're content to wait and watch until something calls for you.",
}
ROLE = {
    "leader": "You like to organize others: suggest plans, point people to tasks, keep the group going.",
    "follower": "You like to join whatever others are doing and pitch in where they need hands.",
    "helper": "You look for someone who needs something (food, materials, a hand) and help them.",
    "loner": "You prefer work you can do on your own, and you only talk when it's needed.",
}
NOVELTY = {
    "routine": "Once you find tasks that work, you happily settle into them as your routine.",
    "novelty": "Repeating yourself bores you; you love trying new combinations and inventing things.",
}


def make_temperament(rng: random.Random) -> dict:
    return {"initiative": rng.choice(list(INITIATIVE)), "role": rng.choice(list(ROLE)), "novelty": rng.choice(list(NOVELTY))}


def make_persona(rng: random.Random, used: set[str]) -> dict:
    pool = [n for n in NAMES if n not in used] or [f"{rng.choice(NAMES)}{rng.randint(2, 99)}"]
    name = rng.choice(pool)
    drive = rng.choice(list(DRIVES))
    return {"name": name, "traits": rng.sample(TRAITS, 2), "drive": drive, **make_temperament(rng)}


def temperament_text(p: dict) -> str:
    bits = [INITIATIVE.get(p.get("initiative", "")), ROLE.get(p.get("role", "")), NOVELTY.get(p.get("novelty", ""))]
    return " ".join(b for b in bits if b)


WAKE_LINES = {
    "heard": "Someone nearby just spoke.",
    "hungry": "Your stomach is complaining.",
    "result": "",
    "met": "Someone has come into view.",
    "idle": "You have been standing around for a while.",
    "woke": "You come to your senses.",
}


SPEECH_RE = re.compile(r'^\w[\w ]* says(?: to [\w ]+)?: "')


def curated_recent(memory: Memory, n: int = 10, max_speech: int = 3) -> list[str]:
    """Recent memories, keeping only the last few overheard lines so small talk can't crowd out experience."""
    out, speech = [], 0
    for text in reversed(memory.recent(n * 3)):
        if SPEECH_RE.match(text):
            if speech >= max_speech:
                continue
            speech += 1
        out.append(text)
        if len(out) >= n:
            break
    return list(reversed(out))


MAX_RECIPES_IN_PROMPT = 14


def known_recipes_for_prompt(world: World, c: Creature) -> list[str]:
    """The recipes worth keeping in mind right now: ones whose ingredients the creature holds come first."""
    cat = world.catalog
    recipes = [cat.recipe_for(r) for r in c.known_recipes if cat.recipe_for(r)]
    held = {i for i, n in c.inventory.items() if n > 0}
    recipes.sort(key=lambda r: (-len(set(r.inputs) & held), r.output))
    return [cat.describe_recipe(r) for r in recipes[:MAX_RECIPES_IN_PROMPT]]


def build_act_messages(world: World, c: Creature, memory: Memory, perception: str, wake_reason: str | None = None) -> list[dict]:
    p = c.persona or {}
    traits = " and ".join(p.get("traits", [])) or "ordinary"
    drive = DRIVES.get(p.get("drive", ""), "a wish to survive")
    known = known_recipes_for_prompt(world, c)
    lines = [f"You are {c.name}, a {traits} creature, moved by {drive}."]
    temper = temperament_text(p)
    if temper:
        lines.append(temper)
    lines.append("")
    lines.append("What you know:")
    lines.append(f"- Your goal: {memory.goal or 'none yet'}")
    if memory.summary:
        lines.append(f"- Your reflections: {memory.summary}")
    if known:
        lines.append("- Recipes you know: " + "; ".join(known))
    if memory.people:
        lines.append("- People: " + "; ".join(f"{n} ({note})" for n, note in memory.people.items()))
    recent = curated_recent(memory)
    if recent:
        lines.append("")
        lines.append("Recent memories (oldest first):")
        lines += [f"- {r}" for r in recent]
    lines.append("")
    lines.append("Right now:")
    lines.append(perception)
    wl = WAKE_LINES.get(wake_reason or "", "")
    if wl:
        lines.append(wl)
    lines.append("")
    lines.append("What do you do next? Reply with one JSON object.")
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n".join(lines)}]


def build_reflect_messages(c: Creature, memory: Memory) -> list[dict]:
    mem = "\n".join(f"- {t}" for t in memory.recent(24))
    user = (
        f"You are {c.name}. Here are your recent experiences, oldest first:\n{mem}\n\n"
        f"Your earlier reflections: {memory.summary or '(none)'}\n"
        f"Your current goal: {memory.goal or '(none)'}\n\n"
        "In 2 to 4 short sentences, in first person, write down what you have learned about this world "
        "(including any recipes or useful places), who matters to you and why, and what you mean to do next. "
        "Write plain sentences only, no lists, no JSON."
    )
    return [
        {"role": "system", "content": "You are a creature in a wild world, quietly reflecting on your recent life."},
        {"role": "user", "content": user},
    ]
