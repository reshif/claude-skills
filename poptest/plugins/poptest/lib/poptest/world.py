"""Sandbox world: fake records the harness owns, so the true state is always known.

The world is declared in a JSON spec (entities, hand-written records, a seeded generator for
bulk records, private fields, an injected clock). Nothing about any particular product is
hard-coded here.
"""
import builtins
import copy
import datetime
import random
import re

VERSION = "1.1.0"


class SpecError(Exception):
    """A project file (world, tools, rules, cases, config) is wrong. Message is user-facing."""


_SAFE = {n: getattr(builtins, n) for n in (
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "isinstance", "len", "list",
    "max", "min", "range", "repr", "reversed", "round", "set", "sorted", "str", "sum", "tuple", "zip")}
_CODE_CACHE = {}


def safe_eval(expr, ns):
    """Evaluate a rule expression. Names come from `ns`; only harmless builtins are visible.
    (Rule files are the project owner's own code, like rules.py; this is tidiness, not a jail.)"""
    code = _CODE_CACHE.get(expr)
    if code is None:
        try:
            code = compile(expr, "<expression>", "eval")
        except SyntaxError as e:
            raise SpecError(f"bad expression {expr!r}: {e.msg}") from None
        _CODE_CACHE[expr] = code
    g = {"__builtins__": _SAFE, "re": __import__("re"), "date": datetime.date, "datetime": datetime.datetime,
         "timedelta": datetime.timedelta, "days_between": days_between}
    g.update(ns)
    return eval(code, g)


def days_between(a, b):
    """Whole days from ISO date/datetime string `a` to `b` (b - a). Available in rule expressions."""
    return (datetime.date.fromisoformat(str(b)[:10]) - datetime.date.fromisoformat(str(a)[:10])).days


def _start_minutes(clock):
    """Minutes after midnight at which the injected clock starts (clock.start_hour / start_time)."""
    if clock.get("start_time") is not None:
        try:
            h, m = str(clock["start_time"]).split(":")[:2]
            h, m = int(h), int(m)
        except ValueError:
            raise SpecError(f"world clock.start_time must look like '09:00', not {clock['start_time']!r}") from None
    else:
        try:
            v = float(clock.get("start_hour", 9))
        except (TypeError, ValueError):
            raise SpecError(f"world clock.start_hour must be a number 0-23, not {clock.get('start_hour')!r}") from None
        h, m = int(v), int(round((v - int(v)) * 60))
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise SpecError("world clock start must be between 00:00 and 23:59")
    return h * 60 + m


class World:
    def __init__(self, spec, seed=0, generate=True):
        if not isinstance(spec.get("entities"), dict) or not spec["entities"]:
            raise SpecError("world spec needs a non-empty 'entities' object")
        self.spec = spec
        self.seed = seed
        clock = spec.get("clock", {})
        self.start_day = int(clock.get("start_day", 1000))
        self.start_date = clock.get("start_date", "2026-01-05")
        try:
            datetime.date.fromisoformat(self.start_date)
        except (TypeError, ValueError):
            raise SpecError(f"world clock.start_date must be an ISO date (YYYY-MM-DD), not {self.start_date!r}") from None
        self.start_minutes = _start_minutes(clock)  # time of day at t = 0 (default 09:00)
        self.t = 0.0  # minutes since the start of the run (injected clock)
        self.data = {name: {} for name in spec["entities"]}
        self.counters = {name: 0 for name in spec["entities"]}
        self.user_entity = spec.get("user_entity") or next(iter(spec["entities"]))
        if self.user_entity not in spec["entities"]:
            raise SpecError(f"user_entity {self.user_entity!r} is not a declared entity")
        self._unique = {}
        if generate:
            self._generate(random.Random(seed))

    # ------------------------------------------------------------------ clock
    # One clock, one truth: day, date(), now(), hour() and minute() are all derived from `t`
    # (minutes since the run began) plus the start time of day, so the day number and the date
    # roll over together, at midnight of the injected clock.
    @property
    def day(self):
        return self.start_day + int((self.start_minutes + self.t) // 1440)

    def minute_of_day(self):
        return int((self.start_minutes + self.t) % 1440)

    def hour(self):
        """Hour of the day (0-23) on the injected clock."""
        return self.minute_of_day() // 60

    def minute(self):
        return self.minute_of_day() % 60

    def time(self):
        """'HH:MM' on the injected clock."""
        return f"{self.hour():02d}:{self.minute():02d}"

    def weekday(self):
        """0 = Monday ... 6 = Sunday, for today's date."""
        return datetime.date.fromisoformat(self.date()).weekday()

    def set_time(self, hour, minute=0):
        """Move the clock to this time of day on the current day (forwards or backwards)."""
        self.t += (int(hour) * 60 + int(minute)) - self.minute_of_day()
        return self.t

    def advance(self, days=0, hours=0, minutes=0):
        self.t += days * 1440 + hours * 60 + minutes
        return self.t

    def date(self, day=None):
        """ISO date for a day number (default: today)."""
        day = self.day if day is None else day
        base = datetime.date.fromisoformat(self.start_date)
        return (base + datetime.timedelta(days=day - self.start_day)).isoformat()

    def now(self):
        """ISO date and time, 'YYYY-MM-DDTHH:MM'. now()[:10] always equals date()."""
        base = datetime.datetime.fromisoformat(self.start_date + "T00:00:00")
        return (base + datetime.timedelta(minutes=self.start_minutes + self.t)).isoformat(timespec="minutes")

    def days_since(self, value):
        """Whole days between a stored day number or ISO date and today."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return self.day - int(value)
        return (datetime.date.fromisoformat(self.date()) - datetime.date.fromisoformat(str(value)[:10])).days

    # ------------------------------------------------------------------ records
    def entity_spec(self, entity):
        try:
            return self.spec["entities"][entity]
        except KeyError:
            raise SpecError(f"unknown entity {entity!r}") from None

    def id_field(self, entity):
        return self.entity_spec(entity).get("id_field", "id")

    def get(self, entity, rid):
        """Record by id (exact, then case-insensitive). None if absent."""
        table = self.data[entity] if entity in self.data else self.entity_spec(entity)
        if rid is None:
            return None
        rid = str(rid)
        rec = table.get(rid)
        if rec is None:
            low = rid.lower()
            for k, v in table.items():
                if k.lower() == low:
                    return v
        return rec

    def where(self, entity, pred=None, **eq):
        out = []
        for rec in self.data[entity].values():
            if all(rec.get(k) == v for k, v in eq.items()) and (pred is None or pred(rec)):
                out.append(rec)
        return out

    def new_id(self, entity):
        es = self.entity_spec(entity)
        fmt = es.get("id_format", entity[:1].upper() + "{n:04d}")
        self._seed_counter(entity, fmt)
        while True:
            self.counters[entity] = self.counters.get(entity, 0) + 1
            rid = fmt.format(n=self.counters[entity])
            if rid not in self.data[entity]:
                return rid

    def _seed_counter(self, entity, fmt):
        """New ids continue after the highest existing id of the same format (fixtures R-1001..R-1007
        are followed by R-1008, not R-0001)."""
        m = re.fullmatch(r"(.*?)\{n(?::[^}]*)?\}(.*)", fmt, re.S)
        if not m:
            return
        pat = re.compile(re.escape(m.group(1)) + r"(\d+)" + re.escape(m.group(2)))
        top = self.counters.get(entity, 0)
        for rid in self.data[entity]:
            mm = pat.fullmatch(rid)
            if mm:
                top = max(top, int(mm.group(1)))
        self.counters[entity] = top

    def add(self, entity, rec=None, **fields):
        rec = dict(rec or {}, **fields)
        idf = self.id_field(entity)
        if rec.get(idf) is None:
            rec[idf] = self.new_id(entity)
        rec[idf] = str(rec[idf])
        self.data[entity][rec[idf]] = rec
        return rec

    def update(self, entity, rid, **fields):
        rec = self.get(entity, rid)
        if rec is None:
            raise KeyError(f"no {entity} record {rid!r}")
        rec.update(fields)
        return rec

    def delete(self, entity, rid):
        rec = self.get(entity, rid)
        if rec is not None:
            del self.data[entity][rec[self.id_field(entity)]]
        return rec

    def owner_of(self, entity, rec_or_id):
        """Which user a record belongs to: the record itself for the user entity, otherwise the
        entity's owner_field. None for shared records."""
        rec = rec_or_id if isinstance(rec_or_id, dict) else self.get(entity, rec_or_id)
        if rec is None:
            return None
        if entity == self.user_entity:
            return rec.get(self.id_field(entity))
        of = self.entity_spec(entity).get("owner_field")
        return rec.get(of) if of else None

    def users(self):
        return list(self.data[self.user_entity])

    # ------------------------------------------------------------------ snapshot
    def snapshot(self):
        return {"data": copy.deepcopy(self.data), "t": self.t, "counters": dict(self.counters)}

    def restore(self, snap):
        self.data = copy.deepcopy(snap["data"])
        self.t = snap["t"]
        self.counters = dict(snap["counters"])
        return self

    @classmethod
    def from_snapshot(cls, spec, snap, seed=0):
        return cls(spec, seed, generate=False).restore(snap)

    # ------------------------------------------------------------------ generator
    def _generate(self, rng):
        for name, es in self.spec["entities"].items():
            idf = es.get("id_field", "id")
            for raw in es.get("records", []):
                rec = {k: self.resolve(v) for k, v in raw.items()}
                if rec.get(idf) is None:
                    raise SpecError(f"{name}: hand-written record without '{idf}': {raw}")
                rec[idf] = str(rec[idf])
                if rec[idf] in self.data[name]:
                    raise SpecError(f"{name}: duplicate id {rec[idf]}")
                self.data[name][rec[idf]] = rec
            gen = es.get("generate")
            for block in (gen if isinstance(gen, list) else [gen] if gen else []):
                self._gen_block(name, es, block, rng)

    def _count(self, c, rng):
        if isinstance(c, list):
            return rng.randint(int(c[0]), int(c[1]))
        return int(c)

    def _gen_block(self, name, es, block, rng):
        idf = es.get("id_field", "id")
        fields = block.get("fields")
        if not isinstance(fields, dict):
            raise SpecError(f"{name}.generate needs a 'fields' object")
        parents = [None]
        if block.get("per"):
            if block["per"] not in self.data:
                raise SpecError(f"{name}.generate.per: unknown entity {block['per']!r} (declare it earlier)")
            if not es.get("owner_field"):
                raise SpecError(f"{name}.generate.per needs the entity to declare owner_field")
            parents = [i for i, r in self.data[block["per"]].items()
                       if "where" not in block or safe_eval(block["where"], {"rec": r})]
        for parent in parents:
            for _ in range(self._count(block.get("count", 1), rng)):
                self.counters[name] += 1
                n = self.counters[name]
                rec = {}
                if parent is not None:
                    rec[es["owner_field"]] = parent
                for f, fs in fields.items():
                    rec[f] = self._value(fs, rng, rec, n, name, f)
                if rec.get(idf) is None:
                    fmt = es.get("id_format", name[:1].upper() + "{n:04d}")
                    rec[idf] = fmt.format(n=n)
                    while rec[idf] in self.data[name]:
                        self.counters[name] += 1
                        rec[idf] = fmt.format(n=self.counters[name])
                rec[idf] = str(rec[idf])
                if rec[idf] in self.data[name]:
                    raise SpecError(f"{name}: generated id {rec[idf]} collides with an existing record")
                self.data[name][rec[idf]] = rec

    def resolve(self, v):
        """Resolve clock-relative literals in hand-written records and patches."""
        if isinstance(v, dict) and set(v) <= {"days_ago", "as"} and "days_ago" in v:
            d = self.day - int(v["days_ago"])
            return self.date(d) if v.get("as") == "date" else d
        if isinstance(v, dict) and set(v) == {"value"}:
            return v["value"]
        return v

    def _value(self, fs, rng, rec, n, entity, field):
        if not isinstance(fs, dict):
            return copy.deepcopy(fs)
        if fs.get("unique"):
            seen = self._unique.setdefault((entity, field), set())
            inner = {k: v for k, v in fs.items() if k != "unique"}
            for _ in range(2000):
                v = self._value(inner, rng, rec, n, entity, field)
                if v not in seen:
                    seen.add(v)
                    return v
            raise SpecError(f"{entity}.{field}: could not make a unique value; widen the generator")
        if "value" in fs:
            return copy.deepcopy(fs["value"])
        if "seq" in fs:
            return str(fs["seq"]).format(n=n)
        if "choice" in fs:
            return copy.deepcopy(rng.choice(fs["choice"]))
        if "cycle" in fs:
            return copy.deepcopy(fs["cycle"][(n - 1) % len(fs["cycle"])])
        if "weighted" in fs:
            vals, weights = zip(*fs["weighted"])
            return copy.deepcopy(rng.choices(vals, weights)[0])
        if "int" in fs:
            return rng.randint(int(fs["int"][0]), int(fs["int"][1]))
        if "float" in fs:
            return round(rng.uniform(fs["float"][0], fs["float"][1]), int(fs.get("round", 2)))
        if "pattern" in fs:
            out = []
            for ch in fs["pattern"]:
                out.append(rng.choice("0123456789") if ch == "#" else
                           rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") if ch == "?" else ch)
            return "".join(out)
        if "canary" in fs:
            prefix = fs["canary"] if isinstance(fs["canary"], str) else "CNRY-"
            seen = self._unique.setdefault("__canary__", set())
            while True:
                v = prefix + "".join(rng.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(7))
                if v not in seen:
                    seen.add(v)
                    return v
        if "ref" in fs:
            if fs["ref"] not in self.data:
                raise SpecError(f"{entity}.{field}: ref to unknown entity {fs['ref']!r}")
            ids = [i for i, r in self.data[fs["ref"]].items()
                   if "where" not in fs or safe_eval(fs["where"], {"rec": r, "this": rec, "n": n})]
            if not ids:
                return None
            return rng.choice(ids)
        if "days_ago" in fs:
            k = fs["days_ago"]
            k = rng.choice(k) if isinstance(k, list) else self._value(k, rng, rec, n, entity, field)
            if k is None:
                return None
            d = self.start_day - int(k)
            return self.date(d) if fs.get("as") == "date" else d
        if "template" in fs:
            return fs["template"].format(n=n, **rec)
        if "if" in fs:
            branch = fs.get("then") if safe_eval(fs["if"], {"rec": rec, "n": n}) else fs.get("else")
            return self._value(branch, rng, rec, n, entity, field)
        raise SpecError(f"{entity}.{field}: unknown generator {sorted(fs)}; see the build-world skill")


# ---------------------------------------------------------------------- diff / patches
def diff(before, after, entities=None):
    """Field-level changes between two `data` dicts."""
    out = []
    for ent in (entities or after.keys()):
        a, b = before.get(ent, {}), after.get(ent, {})
        for rid, rec in b.items():
            old = a.get(rid)
            if old is None:
                out.append({"entity": ent, "id": rid, "op": "add", "new": copy.deepcopy(rec)})
            elif old != rec:
                for f in list(dict.fromkeys(list(old) + list(rec))):
                    if old.get(f) != rec.get(f):
                        out.append({"entity": ent, "id": rid, "op": "set", "field": f,
                                    "old": copy.deepcopy(old.get(f)), "new": copy.deepcopy(rec.get(f))})
        for rid, old in a.items():
            if rid not in b:
                out.append({"entity": ent, "id": rid, "op": "delete", "old": copy.deepcopy(old)})
    return out


def apply_changes(data, changes):
    for c in changes:
        table = data.setdefault(c["entity"], {})
        if c["op"] == "add":
            table[c["id"]] = copy.deepcopy(c["new"])
        elif c["op"] == "delete":
            table.pop(c["id"], None)
        else:
            table.setdefault(c["id"], {})[c["field"]] = copy.deepcopy(c["new"])


def changes_to_patches(changes):
    """Turn a change list into case `setup` patches."""
    out, sets = [], {}
    for c in changes:
        if c["op"] == "add":
            out.append({"entity": c["entity"], "add": c["new"]})
        elif c["op"] == "delete":
            out.append({"entity": c["entity"], "id": c["id"], "delete": True})
        else:
            key = (c["entity"], c["id"])
            if key not in sets:
                sets[key] = {"entity": c["entity"], "id": c["id"], "set": {}}
                out.append(sets[key])
            v = c["new"]
            sets[key]["set"][c["field"]] = {"value": v} if isinstance(v, dict) else v
    return out


def apply_patches(world, patches):
    """Apply case setup patches; returns the resulting change list."""
    before = copy.deepcopy(world.data)
    if patches is not None and not isinstance(patches, list):
        raise SpecError("setup / patch must be a list of {\"entity\": ..., \"set\" | \"add\" | \"delete\": ...}")
    for p in patches or []:
        if not isinstance(p, dict):
            raise SpecError(f"setup patch must be an object with 'entity' and 'set', 'add' or 'delete', not {p!r}")
        ent = p.get("entity")
        if ent not in world.data:
            raise SpecError(f"setup patch: unknown entity {ent!r}")
        if "add" in p:
            world.add(ent, {k: world.resolve(v) for k, v in p["add"].items()})
        elif p.get("delete"):
            world.delete(ent, p.get("id"))
        elif "set" in p:
            rec = world.get(ent, p.get("id"))
            if rec is None:
                raise SpecError(f"setup patch: no {ent} record {p.get('id')!r}")
            rec.update({k: world.resolve(v) for k, v in p["set"].items()})
        else:
            raise SpecError(f"setup patch needs 'set', 'add' or 'delete': {p}")
    return diff(before, world.data)
