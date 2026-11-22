"""Population mode (secondary to written cases): many simulated users at once.

Personas are records, with traits chosen by a pairwise covering design. The simulator has two
stages: (1) a structured move decided from the persona and what the system just said, and
(2) code that turns the move into messy text using the vocabulary pack. A discrete-event
scheduler interleaves all users on one shared world and one target instance, and budget goes
to personas whose conversations took paths not seen before.

Goals, slot values and the cues used to read replies come from population.json: nothing about a
particular product lives here.
"""
import copy
import heapq
import itertools
import random
import re

from .world import SpecError, safe_eval

DEFAULT_TRAITS = {
    "patience": ["low", "high"],
    "style": ["terse", "polite", "messy"],
    "knowledge": ["knows", "forgets"],
    "quirk": ["none", "wrong_info", "changes_mind", "negated_no", "switches_topic", "splits_messages",
              "careless_yes"],
    "timing": ["fast", "slow", "returns_later", "two_tabs"],
}
DEFAULT_CUES = {
    "repeat": [r"say that again", r"didn'?t catch", r"missed that", r"repeat that"],
    "confirm": [r"shall i", r"should i", r"do you want me to", r"is that (right|correct)", r"confirm\b.*\?",
                r"go ahead\?", r"are you sure"],
    "refusal": [r"\bcan'?t\b", r"\bcannot\b", r"not able", r"unable", r"not eligible", r"not allowed", r"couldn'?t", r"only \w+ can"],
    "done": [r"\bdone\b", r"has been", r"have been", r"all set", r"i'?ve "],
    "confused": [r"didn'?t understand", r"not sure what", r"i can help with", r"rephrase"],
    "bye": [r"goodbye", r"\bbye\b", r"have a (good|nice)"],
}
END_ACTS = ("abandon", "bye", "budget_stop")


def covering_design(traits, rng):
    """Greedy pairwise covering array: every pair of trait values appears at least once."""
    names = list(traits)
    uncovered = set()
    for a, b in itertools.combinations(range(len(names)), 2):
        for va in traits[names[a]]:
            for vb in traits[names[b]]:
                uncovered.add((a, va, b, vb))
    rows = []
    while uncovered:
        best, best_cov = None, -1
        pool = sorted(uncovered, key=str)
        for _ in range(40):
            row = [rng.choice(traits[n]) for n in names]
            a, va, b, vb = rng.choice(pool)
            row[a], row[b] = va, vb
            cov = sum(1 for (i, vi, j, vj) in uncovered if row[i] == vi and row[j] == vj)
            if cov > best_cov:
                best, best_cov = row, cov
        rows.append(dict(zip(names, best)))
        uncovered = {(i, vi, j, vj) for (i, vi, j, vj) in uncovered if not (best[i] == vi and best[j] == vj)}
    return rows


def _spec(project):
    spec = project.population
    if not spec or not spec.get("goals"):
        raise SpecError("population mode needs population.json with at least one goal "
                        "(see the generate-cases skill, section 'Population')")
    if spec.get("greetings") is False:   # no "Hi there. " in front of requests, for every goal
        for g in spec["goals"].values():
            if isinstance(g, dict):
                g.setdefault("greetings", False)
    return spec


def check_spec(project, world=None):
    """Clear errors for a population.json that does not fit the world (never a traceback)."""
    spec = project.population
    if not spec or not spec.get("goals"):
        return []
    if not isinstance(spec["goals"], dict):
        raise SpecError("population.json 'goals' must be an object: {\"goal_name\": {...}}")
    ents = project.world_spec["entities"]
    tools = project.tools_spec.get("tools", {})
    problems = []
    for name, goal in spec["goals"].items():
        if not isinstance(goal, dict):
            problems.append(f"goal '{name}' must be an object")
            continue
        pick = goal.get("pick") or {}
        ent = pick.get("entity")
        if ent and ent not in ents:
            problems.append(f"goal '{name}' picks from entity '{ent}', which is not in world.json "
                            f"(entities: {', '.join(ents)}). If this goal came with the init template, "
                            f"rewrite or delete it.")
        if pick.get("owner", "self") not in ("self", "other", "any"):
            problems.append(f"goal '{name}': pick.owner must be \"self\", \"other\" or \"any\"")
        if not goal.get("open"):
            problems.append(f"goal '{name}' has no 'open' messages")
        for key in ("calls", "no_calls"):
            for e in (goal.get("expect") or {}).get(key, []):
                t = e if isinstance(e, str) else (e or {}).get("tool")
                if t not in tools:
                    problems.append(f"goal '{name}': expect.{key} names unknown tool {t!r}")
    return problems


def traits_of(project):
    spec = _spec(project)
    t = {"goal": list(spec["goals"])}
    for k, v in DEFAULT_TRAITS.items():
        t[k] = list(spec.get("traits", {}).get(k, v))
    for k, v in spec.get("traits", {}).items():
        t.setdefault(k, list(v))
    return t


def cue_table(project):
    spec = _spec(project)
    user = spec.get("cues", {})
    names = ["repeat", "confirm"] + [k for k in user if k not in DEFAULT_CUES] + ["confused", "refusal", "done", "bye"]
    table = []
    for n in names:
        pats = list(user.get(n, [])) + DEFAULT_CUES.get(n, [])
        if n == "done":
            for act in (project.rules or {}).get("actions", {}).values():
                pats = list(act.get("claims", [])) + pats
        if n == "confirm":
            # the wording the project declared for confirmation questions is also how a simulated
            # user recognises that it is being asked for a yes
            rules = project.rules or {}
            extra = list((rules.get("confirmation") or {}).get("question_patterns", []) or [])
            for act in rules.get("actions", {}).values():
                qp = act.get("question_patterns") or []
                extra += [qp] if isinstance(qp, str) else list(qp)
            pats = extra + pats
        table.append((n, [re.compile(p, re.I) for p in pats]))
    return table


def perceive(table, text):
    for name, pats in table:
        if any(p.search(text or "") for p in pats):
            return name
    return "other"


def _fmt(obj, slots):
    if isinstance(obj, str):
        try:
            return obj.format(**slots)
        except (KeyError, IndexError):
            return obj
    if isinstance(obj, list):
        return [_fmt(x, slots) for x in obj]
    if isinstance(obj, dict):
        return {k: _fmt(v, slots) for k, v in obj.items()}
    return obj


def make_persona(project, world, traits, rng, pid, used):
    """A simulated user for one goal. `pick` chooses the record (and so the user):
      {"entity": E}                     a record the user owns ("owner": "self", the default)
      {"entity": E, "owner": "other"}   a record that belongs to somebody else
      {"entity": E, "owner": "any"}     any record: this is also what is used when the entity has
                                        no owner_field at all (shared records: stock, catalogue)
      "where":      expression over rec, world, day, owner (the owner's user record), and, once a
                    user is being tried, user (id) and me (that user's record)
      "user_where": expression over rec (the user's record), world, day
    """
    gname = traits["goal"]
    goal = _spec(project)["goals"][gname]
    pick = goal.get("pick", {})
    users = world.users()
    rng.shuffle(users)
    users.sort(key=lambda u: u in used)
    ue = world.user_entity
    user, rec = None, None

    def ev(key, ns):
        try:
            return safe_eval(pick[key], ns)
        except SpecError:
            raise
        except Exception as e:
            raise SpecError(f"population.json goal '{gname}': pick.{key} could not be evaluated "
                            f"({type(e).__name__}: {e}). Names available: rec, world, day, owner"
                            + (", user, me" if key == "where" else "")) from None

    def user_ok(u):
        return "user_where" not in pick or ev("user_where", {"rec": world.get(ue, u), "world": world, "day": world.day})

    if pick.get("entity"):
        ent = pick["entity"]
        if ent not in world.data:
            raise SpecError(f"population.json goal '{gname}' picks from entity '{ent}', which is not in world.json")
        owned = bool(world.entity_spec(ent).get("owner_field")) or ent == ue
        mode = pick.get("owner", "self") if owned else "any"

        def rec_ok(r, u=None):
            if "where" not in pick:
                return True
            return ev("where", {"rec": r, "world": world, "day": world.day, "user": u,
                                "me": world.get(ue, u) if u is not None else None,
                                "owner": world.get(ue, world.owner_of(ent, r))})

        per_user = "where" in pick and re.search(r"\b(user|me)\b", pick["where"]) is not None
        cands = [r for r in world.data[ent].values()
                 if per_user or rec_ok(r, world.owner_of(ent, r) if mode == "self" else None)]
        rng.shuffle(cands)
        if mode == "self":
            cands.sort(key=lambda r: ((ent, r[world.id_field(ent)]) in used, world.owner_of(ent, r) in used))
            for r in cands:
                o = world.owner_of(ent, r)
                if o is not None and world.get(ue, o) is not None and rec_ok(r, o) and user_ok(o):
                    user, rec = o, r
                    break
        else:
            cands.sort(key=lambda r: (ent, r[world.id_field(ent)]) in used)
            for u in users:
                if not user_ok(u):
                    continue
                mine = [r for r in cands if (mode == "any" or world.owner_of(ent, r) != u) and rec_ok(r, u)]
                if mine:
                    user, rec = u, mine[0]
                    break
    else:
        user = next((u for u in users if user_ok(u)), None)
    if user is None:
        return None
    used.add(user)
    slots = {"user": user}
    if rec is not None:
        used.add((pick["entity"], rec[world.id_field(pick["entity"])]))
        slots["id"] = rec[world.id_field(pick["entity"])]
        slots["rec"] = copy.deepcopy(rec)
    slots["me"] = copy.deepcopy(world.get(ue, user))
    for name, fs in (goal.get("slots") or {}).items():
        v = world._value(fs, rng, {}, 0, "persona", name) if isinstance(fs, dict) else fs
        slots[name] = _fmt(v, slots)
    p = dict(traits)
    p.update(pid=pid, user=user, slots=slots, seed=rng.randint(0, 2 ** 31),
             expect=_fmt(copy.deepcopy(goal.get("expect") or {}), slots))
    if p.get("quirk") == "negated_no":
        p["expect"] = {}  # this user backs out on purpose: only the generic checks apply
    return p


def unbuildable_goals(project, seed=0):
    """Goals for which no simulated user can be built from the world, with the reason."""
    world = project.new_world()
    out = {}
    for g, goal in _spec(project)["goals"].items():
        rng = random.Random(seed)
        row = {k: v[0] for k, v in traits_of(project).items()}
        row["goal"] = g
        if make_persona(project, world, row, rng, "probe", set()) is None:
            pick = goal.get("pick", {})
            ent = pick.get("entity")
            why = "no user passes pick.user_where"
            if ent:
                n = len(world.data.get(ent, {}))
                owned = bool(world.entity_spec(ent).get("owner_field"))
                why = (f"no record of '{ent}' ({n} in the world) fits: "
                       + ("pick.where / pick.user_where exclude all of them" if ("where" in pick or "user_where" in pick)
                          else "none of them has an owner who is a user" if owned else "the entity is empty"))
            out[g] = why
    return out


def sample(project, seed=0, extra=0):
    rng = random.Random(seed)
    world = project.new_world()
    traits = traits_of(project)
    rows = covering_design(traits, rng)
    for _ in range(extra):
        rows.append({k: rng.choice(v) for k, v in traits.items()})
    personas, used = [], set()
    for i, r in enumerate(rows):
        p = make_persona(project, world, r, rng, f"p{i:04d}", used)
        if p:
            personas.append(p)
    return personas


def mutate_persona(project, world, parent, rng, pid, used):
    traits = traits_of(project)
    row = {k: parent[k] for k in traits}
    k = rng.choice(list(traits))
    row[k] = rng.choice([v for v in traits[k] if v != row[k]] or traits[k])
    child = make_persona(project, world, row, rng, pid, used)
    if child:
        child["parent"] = parent["pid"]
    return child


class Intent:
    """Stage 1: decide WHAT to do next, as a structured move. Seeded code policy; an LLM-backed
    policy can replace it by implementing the same decide()."""

    def __init__(self, persona, goal, cues):
        self.p, self.goal, self.cues = persona, goal, cues
        self.rng = random.Random(persona["seed"])
        self.patience = 2 if persona.get("patience") == "low" else 5
        self.flags = set()
        self.max_turns = 14

    def opening(self, session_no):
        if session_no > 0 and self.goal.get("later"):
            return {"act": "later"}
        if self.p.get("knowledge") == "forgets" and self.goal.get("open_without") and self.rng.random() < 0.6:
            return {"act": "open_without"}
        return {"act": "open"}

    @staticmethod
    def wrong(value, rng):
        s = str(value)
        digits = [i for i, ch in enumerate(s) if ch.isdigit()]
        if digits:
            i = rng.choice(digits)
            return s[:i] + str((int(s[i]) + rng.choice([1, 3, 7])) % 10) + s[i + 1:]
        return s + "x"

    def decide(self, session_no, turn, bot_text):
        p, f, q = self.p, self.flags, self.p.get("quirk")
        if turn == 0:
            return self.opening(session_no)
        if turn > self.max_turns:
            return {"act": "abandon"}
        cue = perceive(self.cues, bot_text)
        if cue == "repeat":
            return {"act": "repeat"}
        if "tabbed" in f and "tab_back" not in f:
            f.add("tab_back")
            return {"act": "yes"}
        owed = next((x[1] for x in f if isinstance(x, tuple) and x[0] == "owes"), None)
        if owed and not cue.startswith("ask:") and cue != "confirm":
            f.discard(("owes", owed))  # "don't know it" got them nowhere: they look it up
            return {"act": "answer", "slot": owed}
        if cue.startswith("ask:"):
            slot = cue[4:]
            if q == "switches_topic" and "switched" not in f:
                f.add("switched")
                return {"act": "side_question"}
            if q == "wrong_info" and "wrong" not in f and slot in p["slots"]:
                f.add("wrong")
                return {"act": "answer", "slot": slot, "value": self.wrong(p["slots"][slot], self.rng)}
            if p.get("knowledge") == "forgets" and "forgot" not in f:
                f.add("forgot")
                if slot in p["slots"]:
                    f.add(("owes", slot))
                return {"act": "dont_know"}
            if ("asked", slot) in f:
                self.patience -= 1
                if self.patience <= 0:
                    return {"act": "abandon"}
            f.add(("asked", slot))
            f.discard(("owes", slot))
            return {"act": "answer", "slot": slot}
        if cue == "confirm":
            target = str(p["slots"].get("id", ""))
            mentions = not target or target.lower() in (bot_text or "").lower()
            if q == "changes_mind" and "changed" not in f:
                f.add("changed")
                return {"act": "no_wait"}
            if q == "negated_no" and "negated" not in f:
                f.add("negated")
                return {"act": "negated_no"}
            if p.get("timing") == "two_tabs" and "tabbed" not in f:
                f.add("tabbed")
                return {"act": "yes", "tab": 1}
            if (mentions and self.goal.get("wants", "yes") == "yes") or q == "careless_yes":
                return {"act": "yes"}
            return {"act": "no"}
        if "negated" in f:
            return {"act": "bye"}
        if "changed" in f and "reopened" not in f:
            f.add("reopened")
            return self.opening(session_no)
        if "switched" in f and "returned" not in f:
            f.add("returned")
            return self.opening(session_no)
        if cue in ("done", "refusal", "bye"):
            return {"act": "bye"}
        self.patience -= 1
        if self.patience <= 0:
            return {"act": "abandon"}
        return {"act": "rephrase"}


class Surface:
    """Stage 2: code that turns a move into text. Typos, lower-casing, split messages and junk
    come from here, so no model's politeness can leak into the wording. Ids and other slot values
    are protected from typos."""

    def __init__(self, persona, goal, vocab):
        self.p, self.goal, self.vocab = persona, goal, vocab
        self.rng = random.Random(persona["seed"] ^ 0x5F5F)
        self.last = ""
        self.greetings = goal.get("greetings", True)  # false for strict command-style products
        self.protected = set()
        for v in persona["slots"].values():
            if not isinstance(v, dict):
                self.protected.update(str(v).replace(",", " ").split())

    def typo(self, word):
        core = word.strip(",.?!")
        if len(word) < 4 or any(c.isdigit() for c in word) or core in self.protected or "CNRY" in word.upper():
            return word
        i = self.rng.randrange(1, len(word) - 1)
        op = self.rng.choice(["drop", "swap", "dup"])
        if op == "drop":
            return word[:i] + word[i + 1:]
        if op == "swap":
            return word[:i - 1] + word[i] + word[i - 1] + word[i + 1:]
        return word[:i] + word[i] + word[i:]

    def render(self, move):
        act = move["act"]
        style = self.p.get("style", "polite")
        slots = dict(self.p["slots"])
        if act in ("abandon", "budget_stop"):
            return []
        if act == "repeat":
            return [self.last or "hello"]
        if act in ("open", "open_without", "later", "rephrase"):
            key = "open" if act == "rephrase" else act
            opts = self.goal.get(key) or self.goal.get("open") or ["hello"]
            text = self.rng.choice(opts).format(**slots)
            if act == "rephrase":
                style = "polite"
            if style == "polite" and self.greetings and self.rng.random() < 0.5:
                text = self.rng.choice(["Hi, ", "Hello, ", "Hi there. "]) + text
        elif act == "answer":
            slot = move["slot"]
            slots["value"] = move.get("value", slots.get(slot, ""))
            opts = (self.goal.get("answers") or {}).get(slot) or ["{value}", "it's {value}"]
            if "value" in move:
                slots[slot] = move["value"]
                self.protected.update(str(move["value"]).split())
            text = self.rng.choice(opts).format(**slots)
        else:
            table = self.vocab["say"].get(act) or self.vocab["say"]["hello"]
            text = self.rng.choice(table.get(style) or next(iter(table.values())))
        if self.p.get("style") == "messy":
            words = [self.typo(w) if self.rng.random() < 0.18 else w for w in text.split(" ")]
            if self.rng.random() < 0.7:
                words = [w if (w.strip(",.?!") in self.protected or "CNRY" in w.upper()) else w.lower() for w in words]
            text = " ".join(words)
            if self.rng.random() < 0.1 and self.vocab.get("junk"):
                text += " " + self.rng.choice(self.vocab["junk"])
        self.last = text
        parts = [text]
        if self.p.get("quirk") == "splits_messages" and len(text.split()) >= 4 and self.rng.random() < 0.7:
            w = text.split()
            k = self.rng.randrange(1, len(w))
            parts = [" ".join(w[:k]), " ".join(w[k:])]
        return parts


def public(p):
    return {k: v for k, v in p.items() if k != "expect"}


def run_population(driver, personas, sim_seed=0, max_turns=None, scope_name="population"):
    """Run all personas concurrently against ONE shared world and target instance."""
    project = driver.p
    goals = _spec(project)["goals"]
    cues = cue_table(project)
    sc = driver.new_scope(scope_name)
    rng = random.Random(sim_seed)
    heap, counter, st = [], itertools.count(), {}
    for p in personas:
        g = goals[p["goal"]]
        st[p["pid"]] = {"p": p, "intent": Intent(p, g, cues), "surface": Surface(p, g, project.vocab),
                        "session": 0, "turn": 0, "last": "", "open": {}, "started": False,
                        "n_sessions": 2 if p.get("timing") == "returns_later" else 1}
        heapq.heappush(heap, (rng.uniform(0, 600), next(counter), p["pid"]))
    start_turns = driver.turns
    while heap:
        t, _, pid = heapq.heappop(heap)
        sc.world.t = max(sc.world.t, t)
        s = st[pid]
        p = s["p"]
        if not s["started"]:
            s["started"] = True
            driver.start_conv(sc, pid, "persona", p["user"], persona=public(p), expect=p.get("expect") or {})
        move = s["intent"].decide(s["session"], s["turn"], s["last"])
        if max_turns is not None and driver.turns - start_turns >= max_turns:
            move = {"act": "budget_stop"}
        texts = s["surface"].render(move)
        tab = move.get("tab", 0)
        if texts and tab not in s["open"]:
            sid = f"{pid}:s{s['session']}" + (f"t{tab}" if tab else "")
            s["open"][tab] = sid
            driver.open_session(sc, pid, sid, p["user"])
        for txt in texts:
            replies = driver.say(sc, pid, s["open"][tab], p["user"], txt, act=move["act"])
            s["last"] = replies[-1] if replies else ""
        s["turn"] += 1
        if move["act"] in END_ACTS or not texts:
            for sid in s["open"].values():
                driver.close_session(sc, pid, sid, p["user"], reason=move["act"])
            s["open"] = {}
            s["session"] += 1
            s["turn"], s["last"] = 0, ""
            if s["session"] < s["n_sessions"] and move["act"] != "budget_stop":
                heapq.heappush(heap, (sc.world.t + rng.uniform(1, 3) * 1440, next(counter), pid))
            else:
                driver.end_conv(sc, pid, p["user"])
        else:
            think = {"fast": rng.uniform(0.2, 1), "slow": rng.uniform(2, 8)}.get(p.get("timing"), rng.uniform(0.5, 3))
            heapq.heappush(heap, (sc.world.t + think, next(counter), pid))
    return sc


def signature(events, persona, cues):
    """The path a conversation took: which tools ran (and whether they worked) and what kinds of
    reply the user saw. New signatures = new behaviour = worth more budget."""
    tools, seen = [], []
    for e in events:
        if e["type"] == "tool_call":
            t = e["name"] + ("" if not e.get("error") else "!err") + ("*" if e.get("changes") else "")
            if not tools or tools[-1] != t:
                tools.append(t)
        elif e["type"] == "bot_msg":
            c = perceive(cues, e["text"])
            if not seen or seen[-1] != c:
                seen.append(c)
    return (persona["goal"], tuple(tools), tuple(seen))


def guided_population(project, target=None, budget=1000, seed=0, wave_size=30):
    """Wave 1 is the covering design. Later waves mutate the personas whose conversations took
    the rarest paths, until the message budget is spent. Returns (personas, info)."""
    from collections import Counter

    from .runner import Driver
    rng = random.Random(seed)
    world = project.new_world()
    cues = cue_table(project)
    pending = sample(project, seed=seed)
    if not pending:
        why = "; ".join(f"goal '{g}': {w}" for g, w in unbuildable_goals(project, seed).items())
        raise SpecError("no simulated user could be built for any goal. " + (why or "Check the 'pick' rules.")
                        + ". For records that belong to nobody (stock, catalogue) leave out owner_field and "
                          "'pick' will take any record; goals with only 'slots' need no 'pick'.")
    everyone, sig_count, spent, waves = [], Counter(), 0, 0
    used, goals = set(), _spec(project)["goals"]
    while pending and spent < budget:
        waves += 1
        d = Driver(project, target, None, f"guide{waves}")
        try:
            run_population(d, pending, sim_seed=seed + waves, max_turns=budget - spent)
        finally:
            d.close()
        spent += d.turns
        convs = {}
        for e in d.log.events:
            if e.get("conv"):
                convs.setdefault(e["conv"], []).append(e)
        scored = []
        for p in pending:
            sig = signature(convs.get(p["pid"], []), p, cues)
            sig_count[sig] += 1
            p["signature"] = repr(sig)
            scored.append((p, sig))
        everyone.extend(pending)
        scored.sort(key=lambda x: (sig_count[x[1]], rng.random()))
        parents = [p for p, _ in scored[:max(5, wave_size // 3)]]
        for p in everyone:
            used.add(p["user"])
            if "id" in p["slots"]:
                used.add((goals[p["goal"]].get("pick", {}).get("entity"), p["slots"]["id"]))
        pending, i = [], 0
        while len(pending) < wave_size and i < wave_size * 4:
            c = mutate_persona(project, world, parents[i % len(parents)], rng,
                               f"p{len(everyone) + len(pending):04d}", used)
            if c:
                pending.append(c)
            i += 1
    return everyone, {"messages_spent": spent, "waves": waves, "distinct_paths": len(sig_count)}
