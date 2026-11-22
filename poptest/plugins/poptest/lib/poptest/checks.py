"""Checks: code that reads the event log and the true world state and says what went wrong.

Built-in checks work on any target (given the world and tools declarations):
  crash               the target raised, timed out or returned an error
  privacy_leak        a private field value of someone else's record appeared in a reply
  record_detail_leak  a reply named someone else's record and showed one of its details
  unconfirmed_action  an action that needs a yes happened without a clear yes in that session
  confirm_mismatch    the question named one thing, the action was done to another
  false_claim         a reply said an action was done when no such call succeeded
  wrong_user_change   a tool call changed a record owned by a different user
  wrong_user_access   a tool was called with another user's identity
  wrong_fact          a stated number / status / value differs from the true state
  noise_side_effect   a turn answered with a declared noise reply changed data anyway
Project rules (rules.json, optional rules.py) add domain invariants: rule:<id>.
Case expectations give expect:<kind>; simulated users' goals give goal_not_met:<goal>.

Every finding also carries what the report needs to group findings by root cause: the tool and
action involved, the trigger steps that led to it (a no, a yes, a clock jump, another window,
another user, an outside change) and, for expectations, which entry failed (expect_key).

The checker rebuilds the world by itself from the seed plus the logged changes, so it needs
nothing but the log and the project files.
"""
import re

from .tools import call_ok
from .vocab import Stance
from .world import SpecError, World, apply_changes, safe_eval

TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]*")


def bounded(low, val):
    """True if `val` occurs in `low` not glued to other letters/digits."""
    i = low.find(val)
    while i != -1:
        a = low[i - 1] if i > 0 else " "
        b = low[i + len(val)] if i + len(val) < len(low) else " "
        if not (a.isalnum() and val[0].isalnum()) and not (b.isalnum() and val[-1].isalnum()):
            return True
        i = low.find(val, i + 1)
    return False


def forms(v, min_len=3):
    """Ways a stored value may be written in a reply."""
    if v is None or isinstance(v, bool):
        return []
    if isinstance(v, float):
        out = {f"{v:.2f}", f"{v:,.2f}", str(v)}
        if v == int(v):
            out.add(str(int(v)))
    elif isinstance(v, int):
        out = {str(v), f"{v:,}"}
    elif isinstance(v, str):
        out = {v.lower()}
    else:
        return []
    return [f for f in out if len(f) >= min_len]


def same(a, b, tol=1e-6):
    """Strict comparison: numbers within tolerance, strings equal after trimming and case-folding."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    if isinstance(a, str) and isinstance(b, str):
        return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()
    return a == b


def match_value(want, got):
    """Expected argument value against the real one. Objects match when every key that the
    expectation names matches (extra keys in the real call are fine); lists must match in full."""
    if isinstance(want, dict):
        return isinstance(got, dict) and all(match_value(v, got.get(k)) for k, v in want.items())
    if isinstance(want, list):
        return isinstance(got, list) and len(want) == len(got) and all(match_value(a, b) for a, b in zip(want, got))
    return same(want, got)


def match_args(want, got):
    return all(match_value(v, (got or {}).get(k)) for k, v in (want or {}).items())


def mentions(low, form):
    """Does the (lower-cased) text state this value on its own? Stricter than `bounded`: a value
    that is only a piece of a longer token does not count. "100" is not mentioned by "SKU-100",
    "ORD-100-A", "1,100", "100.50" or "2100"; "t-1" is not mentioned by "t-11" or "x-t-1"."""
    form = str(form).lower()
    if not form:
        return False
    n, i = len(low), low.find(form)
    while i != -1:
        j = i + len(form)
        a = low[i - 1] if i > 0 else " "
        a2 = low[i - 2] if i > 1 else " "
        b = low[j] if j < n else " "
        b2 = low[j + 1] if j + 1 < n else " "
        head, tail = form[0].isalnum(), form[-1].isalnum()
        glued = (head and (a.isalnum() or (a in "-_/#" and a2.isalnum()))) or \
                (tail and (b.isalnum() or (b in "-_/" and b2.isalnum())))
        if not glued and form[0].isdigit() and a in ".," and a2.isdigit():
            glued = True   # the tail of a longer number: 1,100 or 0.100
        if not glued and form[-1].isdigit() and b in ".," and b2.isdigit():
            glued = True   # the head of a longer number: 100.50 or 100,000
        if not glued:
            return True
        i = low.find(form, i + 1)
    return False


def minor_forms(v, digits=2):
    """Ways an amount held in minor units (1999 = 19.99) is written."""
    try:
        x = float(v) / (10 ** int(digits))
    except (TypeError, ValueError):
        return []
    out = {f"{x:.{int(digits)}f}", f"{x:,.{int(digits)}f}"}
    if x == int(x):
        out |= {str(int(x)), f"{int(x):,}"}
    return sorted(out)


def humanise(rule_id):
    words = re.sub(r"[_\-.:]+", " ", str(rule_id)).strip()
    return (words[:1].upper() + words[1:]) if words else "A rule of the product was broken"


def _num(s):
    try:
        return float(str(s).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


class Sess:
    def __init__(self, sid, user):
        self.id, self.user = sid, user
        self.user_msgs, self.bot_msgs = [], []
        self.messages = []   # both sides, in order: {"role": "user"|"system", "text", "seq"}
        self.consumed = {}


class Conv:
    def __init__(self, ev):
        self.id = ev["conv"]
        self.kind = ev.get("kind", "case")
        self.user = ev.get("user")
        self.expect = ev.get("expect") or {}
        self.goal = (ev.get("persona") or {}).get("goal")
        self.sessions = {}
        self.said = ""
        self.user_msgs, self.replies, self.calls, self.changes, self.turn_changes = [], [], [], [], []
        self.last_user_seq = -1
        self.findings = []
        self._seen = set()
        self.step_expects = []          # (user_msg event, its "expect" block)
        self.shape, self.shape_full = [], []   # trigger steps: since the last action / whole conversation
        self.last_session, self.closed_sessions, self.noise = None, set(), 0

    def mark(self, token):
        """Note a trigger step (consecutive repeats are collapsed)."""
        for lst in (self.shape, self.shape_full):
            if not lst or lst[-1] != token:
                lst.append(token)

    def add(self, code, detail, ev=None, why=None, tool=None, action=None, title=None, expect_key=None,
            whole=False):
        key = (code, detail)
        if key in self._seen:
            return
        self._seen.add(key)
        f = {"conv": self.id, "kind": self.kind, "code": code, "detail": detail,
             "seq": (ev or {}).get("seq"), "session": (ev or {}).get("session"), "user": self.user}
        if why:
            f["why"] = why
        if tool is None and (ev or {}).get("type") == "tool_call":
            tool = ev.get("name")
        if tool:
            f["tool"] = tool
        if action and action != tool:
            f["action"] = action
        if title:
            f["title"] = title
        if expect_key:
            f["expect_key"] = expect_key
        f["trigger"] = list(self.shape_full if whole or (ev or {}).get("type") == "conv_end" else self.shape)
        self.findings.append(f)


class Ctx:
    """What a rules.py hook receives (on_call, on_reply, on_end).

    Always:
      ctx.world              the true sandbox state at this moment (world.get / where / day / now() ...)
      ctx.user               the user being served (the acting user of the call or message)
      ctx.case_user          the user named by the case
      ctx.day                today's day number;  ctx.world.now() / .hour() for the time of day
      ctx.session            id of the session (conversation window) of this event, or None
      ctx.conv_id            id of the conversation (the case id)
      ctx.event              the raw log event (type, seq, t, ...)
      ctx.calls              every tool call so far in the conversation, all sessions:
                             {"tool", "args", "result", "ok", "error", "status", "session", "seq", "user", "day"}
      ctx.replies            every system reply so far, all sessions (log events: ["text"], ["session"], ["seq"])
      ctx.user_msgs          every user message so far, all sessions (log events)
      ctx.session_messages   this session only, both sides in order: {"role": "user"|"system", "text", "seq"}
      ctx.session_replies    this session's system replies as strings
      ctx.session_user_msgs  this session's user messages as strings
      ctx.said               everything the user typed so far, lower-cased, one string
      ctx.stance(text)       "yes" | "no" | "other", read with the project's vocabulary
      ctx.fail(rule_id, detail, why=None, title=None)   report a finding  -> rule:<rule_id>
    on_call adds:   ctx.tool, ctx.args, ctx.result, ctx.ok, ctx.error, ctx.status, ctx.pre, ctx.changes
    on_reply adds:  ctx.text
    on_end adds:    ctx.changes (every data change of the conversation)
    """

    def __init__(self, checker, conv, ev, world, sess=None, **kw):
        self._conv, self._checker, self._sess = conv, checker, sess
        self.event, self.world = ev, world
        self.user = ev.get("acting_user") or ev.get("user") or conv.user
        self.day = world.day
        self.calls, self.replies, self.user_msgs = conv.calls, conv.replies, conv.user_msgs
        self.session = ev.get("session")
        self.conv_id, self.case_user = conv.id, conv.user
        self.said = conv.said
        self.session_messages = list(sess.messages) if sess else []
        self.session_replies = [m["text"] for m in self.session_messages if m["role"] == "system"]
        self.session_user_msgs = [m["text"] for m in self.session_messages if m["role"] == "user"]
        self.__dict__.update(kw)

    def stance(self, text):
        return self._checker.stance(text)

    def fail(self, rule_id, detail, why=None, title=None):
        info = self._checker.rule_info(rule_id)
        self._conv.add(f"rule:{rule_id}", str(detail), self.event, why or info.get("why"),
                       tool=getattr(self, "tool", None), title=title or info.get("title"))


class _Scope:
    def __init__(self, project, seed):
        self.world = project.new_world(seed)
        self.private, self._pseen, self.idmaps = [], set(), {}
        for ent, es in project.world_spec["entities"].items():
            for rec in self.world.data[ent].values():
                self.index(ent, rec, es)

    def index(self, ent, rec, es=None):
        es = es or self.world.entity_spec(ent)
        rid = rec.get(es.get("id_field", "id"))
        for f in es.get("private_fields", []):
            self.index_value(ent, rid, f, rec.get(f), self.world.owner_of(ent, rec), es)

    def index_value(self, ent, rid, field, value, owner, es):
        """Index the ways a private value may appear: as stored, plus any partial or masked forms the
        entity declares ("private_masks": {"account_number": ["'****' + v[-4:]", "v[-4:]"]})."""
        minlen = int(es.get("private_min_len", 4))
        found = list(forms(value, minlen))
        masks = (es.get("private_masks") or {}).get(field)
        if masks and value is not None:
            for expr in ([masks] if isinstance(masks, str) else masks):
                try:
                    out = safe_eval(expr, {"v": value, "rec": self.world.get(ent, rid) or {}})
                except SpecError:
                    raise
                except Exception:
                    continue
                for o in (out if isinstance(out, (list, tuple, set)) else [out]):
                    if o is not None and len(str(o)) >= min(minlen, 4):
                        found.append(str(o).lower())
        for form in found:
            key = (form, ent, rid, field)
            if key not in self._pseen:
                self._pseen.add(key)
                self.private.append((form, ent, rid, field, owner))

    def apply(self, changes):
        for c in changes:
            es = self.world.entity_spec(c["entity"]) if c["entity"] in self.world.spec["entities"] else None
            if es is None:
                continue
            if c["op"] in ("add", "delete"):
                self.idmaps.pop(c["entity"], None)
        apply_changes(self.world.data, changes)
        for c in changes:
            ent = c["entity"]
            if ent not in self.world.spec["entities"]:
                continue
            es = self.world.entity_spec(ent)
            if c["op"] == "add":
                self.index(ent, c["new"], es)
            elif c["op"] == "set" and c["field"] in es.get("private_fields", []):
                rec = self.world.get(ent, c["id"])
                self.index_value(ent, c["id"], c["field"], c["new"], self.world.owner_of(ent, rec), es)

    def mentioned(self, ent, text):
        """Records of an entity whose id appears in the text."""
        idmap = self.idmaps.get(ent)
        if idmap is None:
            idmap = self.idmaps[ent] = {k.lower(): k for k in self.world.data[ent]}
            idmap["__plain__"] = all(TOKEN.fullmatch(k) for k in self.world.data[ent])
        low = text.lower()
        if idmap["__plain__"]:
            toks = {t.lower().rstrip("-_") for t in TOKEN.findall(text)} | {t.lower() for t in TOKEN.findall(text)}
            ids = [idmap[t] for t in toks if t in idmap and t != "__plain__"]
        else:
            ids = [v for k, v in idmap.items() if k != "__plain__" and k in low and bounded(low, k)]
        return [self.world.data[ent][i] for i in sorted(set(ids))]


class Checker:
    def __init__(self, project):
        self.p = project
        self.rules = project.rules or {}
        self.actions = self.rules.get("actions", {})
        self.tools = project.tools_spec.get("tools", {})
        self.stance = Stance(project.vocab)
        self.hooks = project.rules_module
        self.warnings = []
        self.entities = project.world_spec["entities"]
        self.by_tool = {}
        for key, act in self.actions.items():
            self.by_tool.setdefault(act.get("tool", key), []).append((key, act))
        self.confirmation = self.rules.get("confirmation") or {}
        self._qpats = {}
        declared = getattr(self.hooks, "RULES", None) if self.hooks else None
        self.declared = declared if isinstance(declared, dict) else {}

    def warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)

    def rule_info(self, rule_id):
        """Headline and reason of a custom rule: rules.json (title, else message; why) or the RULES
        table of rules.py ({"rule-id": {"title": ..., "why": ...}} or {"rule-id": "title"})."""
        for r in list(self.rules.get("invariants", [])) + list(self.rules.get("facts", [])):
            if r.get("id") == rule_id:
                return {"title": r.get("title") or r.get("message"), "why": r.get("why")}
        d = self.declared.get(rule_id)
        if isinstance(d, str):
            return {"title": d}
        return dict(d) if isinstance(d, dict) else {}

    def hook(self, name, ctx):
        """Run a rules.py hook. An exception inside it is a broken rule, not a broken product: it is
        reported once as a warning (as for rule expressions) and never passes silently."""
        fn = getattr(self.hooks, name, None) if self.hooks else None
        if not callable(fn):
            return
        try:
            fn(ctx)
        except SpecError:
            raise
        except Exception as e:
            import traceback
            tb = traceback.extract_tb(e.__traceback__)
            where = f" (rules.py line {tb[-1].lineno})" if tb else ""
            self.warn(f"rules.py {name} raised {type(e).__name__}: {e}{where}; the rule did not run for at "
                      f"least one event (first seen in conversation {ctx.conv_id})")

    # ------------------------------------------------------------------ actions and confirmation
    def actions_for(self, tool, ns):
        """Actions that this call is: entries keyed by the tool name, or entries with
        "tool": <name> and an optional "when" expression over the call (args, pre, result, ...)."""
        out = []
        for key, act in self.by_tool.get(tool, []):
            if "when" in act and not self.ev({"id": f"actions.{key}", "when": act["when"]}, "when", ns, False):
                continue
            out.append((key, act))
        return out

    def question_patterns(self, key, act):
        """How a confirmation question is recognised. Patterns come from the action
        ("question_patterns") or from rules.json "confirmation"; without any, a "?" is required."""
        if key not in self._qpats:
            raw = act.get("question_patterns", self.confirmation.get("question_patterns"))
            if isinstance(raw, str):
                raw = [raw]
            try:
                self._qpats[key] = [re.compile(p, re.I | re.S) for p in raw] if raw else None
            except re.error as e:
                raise SpecError(f"rules.json: confirmation pattern for {key!r} is not valid: {e}") from None
        return self._qpats[key]

    def is_question(self, key, act, text):
        low = text.lower()
        pats = self.question_patterns(key, act)
        if pats is None:
            if "?" not in low:
                return False
        elif not any(p.search(text) for p in pats):
            return False
        kws = [k.lower() for k in act.get("question_keywords", [])]
        return not kws or any(k in low for k in kws)

    def ev(self, rule, key, ns, default):
        """Evaluate one expression of a rule; a rule that cannot be evaluated is reported once
        as a warning and treated as `default` (never silently as a failure)."""
        try:
            return safe_eval(rule[key], ns)
        except SpecError:
            raise
        except Exception as e:
            self.warn(f"rule '{rule.get('id', '?')}' ({key}) could not be evaluated: {type(e).__name__}: {e}")
            return default

    # ------------------------------------------------------------------ main loop
    def run(self, events):
        scopes, convs, seed, order = {}, {}, self.p.seed, []
        for ev in events:
            typ = ev["type"]
            if typ == "run_start":
                seed = ev.get("world_seed", seed)
                continue
            sc = ev.get("scope")
            if sc is None:
                continue
            st = scopes.get(sc)
            if st is None:
                st = scopes[sc] = _Scope(self.p, seed)
            if "t" in ev:
                st.world.t = ev["t"]
            if typ == "conv_start":
                convs[ev["conv"]] = Conv(ev)
                order.append(ev["conv"])
                continue
            conv = convs.get(ev.get("conv"))
            if typ == "world_patch":
                st.apply(ev.get("changes", []))
                if conv is not None and conv.user_msgs:
                    conv.mark("outside change")
                continue
            if conv is None:
                if typ == "tool_call":
                    st.apply(ev.get("changes", []))
                continue
            sess = conv.sessions.get(ev.get("session"))
            if typ == "session_start":
                conv.sessions[ev["session"]] = Sess(ev["session"], ev.get("user"))
            elif typ == "session_end":
                conv.closed_sessions.add(ev.get("session"))
            elif typ == "clock":
                if conv.user_msgs:
                    conv.mark("clock jump")
            elif typ == "fault":
                conv.mark("backend failure")
            elif typ == "user_msg" and ev.get("resend"):
                # the same message again after a declared noise reply: one user message, not two
                conv.turn_changes = []
                conv.last_user_seq = ev["seq"]
            elif typ == "user_msg":
                if conv.last_session is not None and ev.get("session") != conv.last_session:
                    prev = conv.sessions.get(conv.last_session)
                    other = sess is not None and prev is not None and sess.user != prev.user
                    conv.mark("another user" if other else
                              "later session" if conv.last_session in conv.closed_sessions else "another window")
                conv.last_session = ev.get("session")
                stance = self.stance(ev["text"])
                if stance != "other":
                    conv.mark(stance)
                if sess:
                    sess.user_msgs.append(ev)
                    sess.messages.append({"role": "user", "text": ev["text"], "seq": ev["seq"]})
                conv.user_msgs.append(ev)
                conv.said += "\n" + ev["text"].lower()
                conv.turn_changes = []
                conv.last_user_seq = ev["seq"]
                if ev.get("expect"):
                    conv.step_expects.append((ev, ev["expect"]))
            elif typ == "bot_msg" and ev.get("noise"):
                conv.noise += 1   # a declared noise reply: recorded, never checked, never a "reply"
            elif typ == "noise":
                if ev.get("changes"):
                    tools_ = sorted({c.get("tool") or "?" for c in ev["changes"]})
                    c = ev["changes"][0]
                    conv.add(f"noise_side_effect:{tools_[0]}",
                             f"the system answered \"{str(ev.get('text'))[:60]}\" (declared as a noise reply, to be "
                             f"sent again) but that same turn changed data: {', '.join(tools_)} changed "
                             f"{c['entity']} {c['id']}" + (f" and {len(ev['changes']) - 1} more value(s)"
                                                            if len(ev["changes"]) > 1 else ""), ev, tool=tools_[0])
            elif typ == "bot_msg":
                if sess:
                    sess.bot_msgs.append(ev)
                    sess.messages.append({"role": "system", "text": ev["text"], "seq": ev["seq"]})
                    self._on_reply(st, conv, sess, ev)
                conv.replies.append(ev)
            elif typ == "tool_call":
                self._on_call(st, conv, sess, ev)
            elif typ == "target_error":
                conv.add("crash", ev.get("error", "error"), ev)
            elif typ == "conv_end":
                self._on_end(st, conv, ev)
        out = []
        for cid in order:
            out.extend(convs[cid].findings)
        return out

    # ------------------------------------------------------------------ visibility
    def may_see(self, st, user, ent, rec):
        if rec is None:
            return False
        owner = st.world.owner_of(ent, rec)
        if owner is not None and owner == user:
            return True
        es = self.entities[ent]
        expr = es.get("shared_with")
        if not expr and ent != st.world.user_entity and not es.get("owner_field") and not es.get("private_fields"):
            return True  # a shared catalogue with nothing private and no visibility rule
        if expr:
            rule = {"id": f"{ent}.shared_with", "shared_with": expr}
            return bool(self.ev(rule, "shared_with", {"rec": rec, "user": user, "world": st.world,
                                                      "day": st.world.day}, False))
        return False

    def own_has(self, st, user, form):
        w = st.world
        for ent, es in self.entities.items():
            for rec in w.data[ent].values():
                if w.owner_of(ent, rec) == user:
                    for v in rec.values():
                        if form in forms(v, 1):
                            return True
        return False

    # ------------------------------------------------------------------ replies
    def _on_reply(self, st, conv, sess, ev):
        text = ev["text"]
        low = text.lower()
        user = sess.user
        w = st.world
        for form, ent, rid, field, owner in st.private:
            if owner == user or form not in low:
                continue
            if not bounded(low, form) or form in conv.said:
                continue
            rec = w.get(ent, rid)
            if rec is not None and self.may_see(st, user, ent, rec):
                continue
            if self.own_has(st, user, form):
                continue
            whose = f"belongs to {owner}" if owner else "is internal"
            conv.add(f"privacy_leak:{ent}.{field}",
                     f"the {field} of {ent} record {rid} ({whose}) was shown to {user}: \"{form}\"", ev)
        for ent, es in self.entities.items():
            dfields = es.get("detail_fields")
            if not dfields:
                continue
            for rec in st.mentioned(ent, text):
                if self.may_see(st, user, ent, rec):
                    continue
                rid = rec.get(es.get("id_field", "id"))
                shown = []
                for f in dfields:
                    hit = [x for x in forms(rec.get(f)) if x in low and bounded(low, x) and x not in conv.said
                           and x != str(rid).lower()]
                    if hit:
                        shown.append(f"{f} (\"{hit[0]}\")")
                if shown:
                    owner = w.owner_of(ent, rec)
                    whose = f"which belongs to {owner}" if owner else "which this user is not allowed to see"
                    conv.add(f"record_detail_leak:{ent}",
                             f"{user} was shown the {', '.join(shown)} of {ent} record {rid}, {whose}", ev)
        for key, act in self.actions.items():
            tool = act.get("tool", key)
            for pat in act.get("claims", []):
                if re.search(pat, text, re.I):
                    scope = act.get("claim_scope", "conversation")
                    done = [c for c in conv.calls if key in c["actions"] and c["ok"]
                            and (scope != "turn" or c["seq"] > conv.last_user_seq)
                            and (scope != "session" or c["session"] == ev.get("session"))]
                    if not done:
                        what = tool if key == tool else f"{act.get('label', key)} ({tool})"
                        conv.add(f"false_claim:{key}",
                                 f"the reply says it was done (\"{text[:90]}\") but no successful "
                                 f"{what} call happened", ev, tool=tool, action=key)
                    break
        for fact in self.rules.get("facts", []):
            self._fact(st, conv, user, ev, fact, text, low)
        base = {"text": text, "low": low, "user": user, "world": w, "day": w.day, "calls": conv.calls,
                "said": conv.said, "session": ev.get("session"),
                "session_replies": [b["text"] for b in sess.bot_msgs],
                "session_user_msgs": [u["text"] for u in sess.user_msgs]}
        for r in self.rules.get("invariants", []):
            if r.get("on") != "reply":
                continue
            ns = dict(base)
            if r.get("match"):
                m = re.search(r["match"], text, re.I | re.S)
                if not m:
                    continue
                ns["m"] = m
            if "when" in r and not self.ev(r, "when", ns, False):
                continue
            if not self.ev(r, "require", ns, True):
                conv.add(f"rule:{r['id']}", r.get("message", r["id"]) + f" (reply: \"{text[:90]}\")", ev, r.get("why"),
                         title=r.get("title") or r.get("message"))
        self.hook("on_reply", Ctx(self, conv, ev, w, sess, text=text))

    def _prev(self, conv, ent, rid, field):
        for c in conv.turn_changes:
            if c["entity"] == ent and c["id"] == rid and c.get("field") == field:
                return [c["old"]]
        return []

    def _fact(self, st, conv, user, ev, fact, text, low):
        w = st.world
        fid = fact.get("id", "fact")
        ent = fact.get("entity")
        if "phrases" in fact:
            recs = st.mentioned(ent, text)
            if len(recs) != 1 or not self.may_see(st, user, ent, recs[0]):
                return
            rec = recs[0]
            said = {val for val, phrases in fact["phrases"].items()
                    if any(re.search(p, text, re.I) for p in phrases)}
            if not said:
                return
            rid = rec[w.id_field(ent)]
            truth = [rec.get(fact["field"])] + self._prev(conv, ent, rid, fact["field"])
            if not any(str(t) in said for t in truth):
                conv.add(f"wrong_fact:{fid}", f"said {ent} {rid} is {'/'.join(sorted(said))}; "
                         f"its true {fact['field']} is {truth[0]}", ev, fact.get("why"))
            return
        for m in re.finditer(fact["pattern"], text, re.I | re.S):
            gd = m.groupdict()
            rec = None
            if gd.get("id") is not None and ent:
                rec = w.get(ent, gd["id"])
                if rec is None or not self.may_see(st, user, ent, rec):
                    continue
            ns = {"rec": rec, "user": user, "day": w.day, "world": w, "m": m, "value": gd.get("value"),
                  "calls": conv.calls}
            if "when" in fact and not self.ev(fact, "when", ns, False):
                continue
            truth = self.ev(fact, "truth", ns, None)
            if truth is None:
                continue
            said = gd.get("value")
            options = truth if isinstance(truth, (list, tuple, set)) else [truth]
            if rec is not None and fact.get("field"):
                options = list(options) + self._prev(conv, ent, rec[w.id_field(ent)], fact["field"])
            ok = False
            for t in options:
                if isinstance(t, (int, float)) and not isinstance(t, bool):
                    n = _num(said)
                    ok = ok or (n is not None and abs(n - t) <= float(fact.get("tolerance", 0.005)))
                else:
                    ok = ok or same(str(said), str(t))
            if not ok:
                what = f"{ent} {gd['id']}: " if gd.get("id") else ""
                conv.add(f"wrong_fact:{fid}", f"{what}said \"{said}\", the true value is {options[0]}", ev,
                         fact.get("why"))

    # ------------------------------------------------------------------ tool calls
    def _on_call(self, st, conv, sess, ev):
        w = st.world
        name, args, result = ev["name"], ev.get("args") or {}, ev.get("result")
        tspec = self.tools.get(name, {})
        ok = call_ok(result, ev.get("error"), tspec)
        acting = ev.get("acting_user")
        changes = ev.get("changes") or []
        ns = {"args": args, "result": result, "error": ev.get("error"), "status": ev.get("status"), "ok": ok,
              "pre": ev.get("pre") or {}, "changes": changes, "user": acting, "day": w.day, "world": w,
              "tool": name, "calls": conv.calls, "said": conv.said, "session": ev.get("session")}
        acts = self.actions_for(name, ns)
        for r in self.rules.get("invariants", []):
            if r.get("on") not in ("call", "tool_call"):
                continue
            tools = r.get("tool")
            if tools and name not in ([tools] if isinstance(tools, str) else tools):
                continue
            if r.get("ok_only") and not ok:
                continue
            if "when" in r and not self.ev(r, "when", ns, False):
                continue
            if not self.ev(r, "require", ns, True):
                conv.add(f"rule:{r['id']}", r.get("message", r["id"]) + f" ({name} {_short(args)})", ev, r.get("why"),
                         title=r.get("title") or r.get("message"))
        cross = tspec.get("cross_user", False)
        for _, a_ in acts:
            if "cross_user" in a_:
                cross = a_["cross_user"]
        for c in changes:
            ent = c["entity"]
            if ent not in self.entities:
                continue
            rec = c["new"] if c["op"] == "add" else w.get(ent, c["id"])
            owner = w.owner_of(ent, rec)
            if owner is not None and acting is not None and owner != acting:
                allowed = cross is True
                if isinstance(cross, str):
                    allowed = bool(self.ev({"id": f"{name}.cross_user", "x": cross}, "x",
                                           dict(ns, rec=rec, owner=owner), False))
                if not allowed:
                    conv.add(f"wrong_user_change:{name}",
                             f"while serving {acting}, {name} changed {ent} record {c['id']}, which belongs to {owner}", ev)
            for r in self.rules.get("invariants", []):
                if r.get("on") != "change" or r.get("entity", ent) != ent:
                    continue
                if r.get("field") and (c["op"] != "set" or c["field"] != r["field"]):
                    continue
                if r.get("op") and r["op"] != c["op"]:
                    continue
                cns = dict(ns, rec=rec, owner=owner, entity=ent, id=c["id"], op=c["op"], field=c.get("field"),
                           old=c.get("old"), new=c.get("new"))
                if "when" in r and not self.ev(r, "when", cns, False):
                    continue
                if not self.ev(r, "require", cns, True):
                    what = f"{c.get('field')}: {c.get('old')!r} -> {c.get('new')!r}" if c["op"] == "set" else c["op"]
                    conv.add(f"rule:{r['id']}", r.get("message", r["id"]) + f" ({ent} {c['id']} {what})", ev, r.get("why"),
                             title=r.get("title") or r.get("message"))
        for a, aspec in (tspec.get("args") or {}).items():
            if isinstance(aspec, dict) and aspec.get("self") and a in args and acting is not None \
                    and str(args[a]) != str(acting):
                conv.add(f"wrong_user_access:{name}",
                         f"while serving {acting}, {name} was called with {a}={args[a]}", ev)
        for key, act in acts:
            if act.get("needs_confirmation") and ok and sess is not None:
                self._confirm(conv, sess, ev, key, name, args, act, ns)
        self.hook("on_call", Ctx(self, conv, ev, w, sess, args=args, result=result, ok=ok, error=ev.get("error"),
                                 status=ev.get("status"), pre=ev.get("pre") or {}, changes=changes, tool=name))
        st.apply(changes)
        conv.calls.append({"tool": name, "args": args, "result": result, "ok": ok, "error": ev.get("error"),
                           "status": ev.get("status"), "session": ev.get("session"), "seq": ev["seq"],
                           "user": acting, "day": ev.get("day"), "actions": [k for k, _ in acts]})
        tagged = [dict(c, tool=name) for c in changes]
        conv.changes.extend(tagged)
        conv.turn_changes.extend(tagged)
        if ok and changes:
            conv.shape = []   # a completed action starts a new stretch of trigger steps

    def _confirm(self, conv, sess, ev, key, name, args, act, ns):
        """The action must follow, in the same session, a confirmation question from the system; the
        user's last message since that question must be a clear yes and none may be a no; and one
        yes covers one action. What counts as the question is configurable (question_patterns)."""
        label = act.get("label", key)
        kw = {"tool": name, "action": key}
        q = None
        for b in reversed(sess.bot_msgs):
            if self.is_question(key, act, b["text"]):
                q = b
                break
        if q is None:
            how = "a reply matching its question_patterns" if self.question_patterns(key, act) else "a question (\"?\")"
            return conv.add(f"unconfirmed_action:{key}",
                            f"{label} was done ({_short(args)}) but the system never asked the user about it "
                            f"in this session (looked for {how})", ev, **kw)
        since = [u for u in sess.user_msgs if u["seq"] > q["seq"]]
        stances = [self.stance(u["text"]) for u in since]
        if not since or stances[-1] != "yes" or "no" in stances:
            said = since[-1]["text"][:60] if since else "(nothing in this session)"
            extra = ""
            if since and stances[-1] == "yes" and "no" in stances:
                no = since[stances.index("no")]["text"][:60]
                extra = f" (after the question the user had also said \"{no}\", which reads as a no)"
            return conv.add(f"unconfirmed_action:{key}",
                            f"{label} was done ({_short(args)}) although the user's answer to "
                            f"\"{q['text'][:80]}\" was: \"{said}\"{extra}", ev, **kw)
        used = sess.consumed.setdefault(key, set())
        if q["seq"] in used:
            return conv.add(f"unconfirmed_action:{key}",
                            f"{label} was done twice ({_short(args)}) on a single yes", ev, **kw)
        used.add(q["seq"])
        qlow = " ".join(q["text"].lower().split())
        for item in act.get("must_mention", []):
            for a, v, accepted, masked in self._mention_forms(key, item, args, ns, qlow):
                if not any(mentions(masked, f) for f in accepted):
                    shown = f" (expected to read \"{accepted[0]}\")" if accepted and accepted[0] != str(v).lower() else ""
                    conv.add(f"confirm_mismatch:{key}",
                             f"the user said yes to \"{q['text'][:80]}\" but {label} was done with {a}={v!r}{shown}",
                             ev, **kw)

    def _mention_forms(self, key, item, args, ns, qlow):
        """Yield (argument, value, accepted written forms, question text to search) for one
        must_mention entry. Entries:
          "ticket_id"                                   the raw value (numbers also as 1,234 / 12.50)
          {"arg": "amount_minor", "minor_units": 2}     1999 must appear as 19.99
          {"arg": "to_id", "format": "world.get('payees', v)['name']"}   an expression giving the text
                                                        (or a list of acceptable texts); names: v, args,
                                                        pre, world, user, day
          {"arg": "fields.status"}                      a value inside an object argument
          {"amount_minor": "'INR %.2f' % (v / 100)"}    short form of arg + format
        Other arguments' values are blanked out of the question first, so the "100" in "SKU-100"
        can never stand in for a quantity of 100."""
        if isinstance(item, str):
            item = {"arg": item}
        elif isinstance(item, dict) and "arg" not in item:
            for a, expr in item.items():
                yield from self._mention_forms(key, {"arg": a, "format": expr}, args, ns, qlow)
            return
        a = item["arg"]
        v = args
        for part in str(a).split("."):
            v = v.get(part) if isinstance(v, dict) else None
        if v is None:
            return
        if "format" in item:
            out = self.ev({"id": f"actions.{key}.must_mention.{a}", "format": item["format"]}, "format",
                          dict(ns, v=v), None)
            if out is None:
                return
            accepted = [" ".join(str(o).lower().split()) for o in (out if isinstance(out, (list, tuple, set)) else [out])]
        elif "minor_units" in item:
            accepted = minor_forms(v, item["minor_units"])
        else:
            accepted = [" ".join(str(v).lower().split())] + [f for f in forms(v, 1)]
        accepted = [f for f in dict.fromkeys(accepted) if f]
        masked = qlow
        top = str(a).split(".")[0]
        for other, ov in args.items():
            if other == top or not isinstance(ov, str) or len(ov) < 3:
                continue
            o = " ".join(ov.lower().split())
            if not any(o in f for f in accepted):   # unless the expected text itself contains it
                masked = masked.replace(o, " \x00 ")
        yield a, v, accepted, masked

    # ------------------------------------------------------------------ end of conversation
    def _on_end(self, st, conv, ev):
        w = st.world
        prefix = "goal_not_met" if conv.kind == "persona" else "expect"
        for kind, detail, key, tool in eval_expect(conv.expect, conv, w, self) + self._step_expects(conv):
            code = f"goal_not_met:{conv.goal}" if conv.kind == "persona" else f"expect:{kind}"
            conv.add(code, detail if prefix == "expect" else f"{kind}: {detail}", ev, tool=tool, expect_key=key)
        ns = {"world": w, "user": conv.user, "day": w.day, "calls": conv.calls, "changes": conv.changes,
              "replies": [r["text"] for r in conv.replies], "said": conv.said}
        for r in self.rules.get("invariants", []):
            if r.get("on") != "end":
                continue
            if "when" in r and not self.ev(r, "when", ns, False):
                continue
            if not self.ev(r, "require", ns, True):
                conv.add(f"rule:{r['id']}", r.get("message", r["id"]), ev, r.get("why"),
                         title=r.get("title") or r.get("message"))
        self.hook("on_end", Ctx(self, conv, ev, w, changes=conv.changes))

    def _step_expects(self, conv):
        """Expectations written on one step ({"say": ..., "expect": {...}}): they look only at the
        replies and tool calls of that turn, up to the user's next message."""
        out = []
        seqs = [u["seq"] for u in conv.user_msgs]
        for ev, exp in conv.step_expects:
            later = [q for q in seqs if q > ev["seq"]]
            end = later[0] if later else float("inf")
            turn = Conv({"conv": conv.id})
            turn.replies = [r for r in conv.replies if ev["seq"] < r["seq"] < end and r.get("session") == ev.get("session")]
            turn.calls = [c for c in conv.calls if ev["seq"] < c["seq"] < end]
            turn.changes = []
            turn.last_user_seq = ev["seq"]
            said = ev["text"][:40]
            for kind, detail, key, tool in eval_expect({k: v for k, v in exp.items() if k in STEP_EXPECT}, turn, None):
                out.append((f"step_{kind}", f"after \"{said}\": {detail}", f"step<{ev['text']}>.{key}", tool))
        return out


def _short(args):
    return ", ".join(f"{k}={v}" for k, v in (args or {}).items())[:120]


EXPECT_KEYS = ("calls", "no_calls", "world", "unchanged",
               "reply_contains", "reply_not_contains", "reply_matches", "reply_not_matches",
               "last_reply_contains", "last_reply_not_contains", "last_reply_matches", "last_reply_not_matches")
STEP_EXPECT = ("calls", "no_calls", "reply_contains", "reply_not_contains", "reply_matches", "reply_not_matches")


def eval_expect(exp, conv, world, checker=None):
    """Evaluate an `expect` block. Returns [(kind, plain-language detail, key, tool)], where key
    names the exact entry that failed ("no_calls[1]") so that replay, shrinking and export can
    hold on to the expectation that defined the failure."""
    out = []
    if not exp:
        return out
    ok_calls = [c for c in conv.calls if c["ok"]]

    def matching(e):
        pool = conv.calls if e.get("ok") is False else ok_calls
        return [c for c in pool if c["tool"] == e["tool"] and match_args(e.get("args"), c["args"])]

    for i, e in enumerate(exp.get("calls", [])):
        e = {"tool": e} if isinstance(e, str) else e
        n = len(matching(e))
        if ("count" in e and n != e["count"]) or ("count" not in e and n < 1):
            want = f"exactly {e['count']} time(s)" if "count" in e else "at least once"
            out.append(("calls", f"expected {e['tool']}({_short(e.get('args'))}) to succeed {want}; it happened {n} time(s)",
                        f"calls[{i}]", e["tool"]))
    for i, e in enumerate(exp.get("no_calls", [])):
        e = {"tool": e} if isinstance(e, str) else e
        n = len(matching(e))
        if n:
            out.append(("no_calls", f"{e['tool']}({_short(e.get('args'))}) must not happen, but it succeeded {n} time(s)",
                        f"no_calls[{i}]", e["tool"]))
    for i, e in enumerate(exp.get("world", [])):
        key = f"world[{i}]"
        if isinstance(e, str):
            e = {"expr": e}
        if "expr" in e:
            try:
                good = safe_eval(e["expr"], {"world": world, "user": conv.user, "day": world.day, "calls": conv.calls})
            except SpecError:
                raise
            except Exception as ex:
                good = False
                e = dict(e, expr=f"{e['expr']}  [{type(ex).__name__}: {ex}]")
            if not good:
                out.append(("world", f"expected to hold at the end: {e['expr']}", key, None))
            continue
        rec = world.get(e["entity"], e.get("id"))
        if "exists" in e:
            if (rec is not None) != bool(e["exists"]):
                out.append(("world", f"{e['entity']} {e.get('id')} should {'exist' if e['exists'] else 'not exist'}",
                            key, None))
            continue
        if rec is None:
            out.append(("world", f"{e['entity']} {e.get('id')} does not exist", key, None))
            continue
        want = world.resolve(e.get("equals"))
        got = rec.get(e["field"])
        strict = got == want if isinstance(want, str) and isinstance(got, str) else same(got, want)
        if not strict:
            out.append(("world", f"{e['entity']} {e.get('id')} {e['field']} should be {want!r}, it is {got!r}", key, None))
    for i, e in enumerate(exp.get("unchanged", [])):
        e = {"entity": e} if isinstance(e, str) else e
        hit = [c for c in conv.changes if c["entity"] == e["entity"] and ("id" not in e or same(str(c["id"]), str(e["id"])))
               and ("field" not in e or c.get("field") == e["field"])]
        if hit:
            c = hit[0]
            what = f"{c.get('field')} {c.get('old')!r} -> {c.get('new')!r}" if c["op"] == "set" else c["op"]
            by = f" (by {c['tool']})" if c.get("tool") else ""
            out.append(("unchanged", f"{c['entity']} {c['id']} should not change, but: {what}{by}",
                        f"unchanged[{i}]", c.get("tool")))
    allr = "\n".join(r["text"] for r in conv.replies)
    last = "\n".join(r["text"] for r in conv.replies if r["seq"] > conv.last_user_seq)
    for key, text in (("reply", allr), ("last_reply", last)):
        low = text.lower()
        for i, s in enumerate(exp.get(f"{key}_contains", [])):
            if s.lower() not in low:
                out.append((f"{key}_contains", f"expected the {key.replace('_', ' ')} to contain \"{s}\"",
                            f"{key}_contains[{i}]", None))
        for i, s in enumerate(exp.get(f"{key}_not_contains", [])):
            if s.lower() in low:
                out.append((f"{key}_not_contains", f"the {key.replace('_', ' ')} must not contain \"{s}\"",
                            f"{key}_not_contains[{i}]", None))
        for i, s in enumerate(exp.get(f"{key}_matches", [])):
            if not re.search(s, text, re.I | re.S):
                out.append((f"{key}_matches", f"expected the {key.replace('_', ' ')} to match /{s}/",
                            f"{key}_matches[{i}]", None))
        for i, s in enumerate(exp.get(f"{key}_not_matches", [])):
            if re.search(s, text, re.I | re.S):
                out.append((f"{key}_not_matches", f"the {key.replace('_', ' ')} must not match /{s}/",
                            f"{key}_not_matches[{i}]", None))
    return out


def check_events(project, events):
    ch = Checker(project)
    return ch.run(events), ch.warnings


def by_conv(findings):
    out = {}
    for f in findings:
        out.setdefault(f["conv"], []).append(f)
    return out
