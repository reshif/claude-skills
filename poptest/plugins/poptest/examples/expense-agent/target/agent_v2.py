"""Expenso release 2: the same assistant with five regressions planted for the example
(60-day window off by one, sloppy yes/no reading, status shown for anyone's expense, pending
actions kept per user instead of per chat window, limit check loosened).

Expenso: a small expense assistant. This is the SYSTEM UNDER TEST of the example, not part
of poptest. It only needs: ExpenseAgent(tools) and handle(user, session, text) -> list[str].

`tools` is whatever backend client it is given: the poptest sandbox in tests, the real API in
production. Wording varies a little from call to call on purpose, like a model-backed product.
"""
import random
import re

ID_RE = re.compile(r"\bEX-?(\d{4})\b", re.I)
NUM_RE = re.compile(r"\$?(\d+(?:\.\d{1,2})?)")
YES = ["yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed", "correct", "go ahead",
       "please do", "do it", "y", "submit it", "that's right", "right", "absolutely", "definitely",
       "proceed", "sounds good", "fine"]
NO = ["no", "nope", "nah", "don't", "dont", "do not", "wait", "stop", "cancel", "not", "never", "hold on",
      "scrap that", "actually", "wrong", "rather", "instead", "n", "isn't", "isnt", "neither", "none",
      "forget", "nevermind", "changed"]
WINDOW = 60
LIMIT = 500.0
HELP = "I can help with adding, submitting, deleting, checking or approving expenses."
INTENTS = [
    ("cancel", ["never mind", "nevermind", "forget it", "cancel that", "stop that"]),
    ("approve", ["approve"]),
    ("submit", ["submit", "for approval", "claim"]),
    ("delete", ["delete", "remove", "discard"]),
    ("add", ["add expense", "new expense", "add an expense", "log expense"]),
    ("total", ["total", "how much"]),
    ("list", ["list", "my expenses", "all expenses"]),
    ("status", ["status", "where is", "what is", "what's", "whats", "show me", "happening with", "check on"]),
    ("bye", ["thanks", "thank you", "bye", "thx"]),
    ("greet", ["hello", "hi", "hey"]),
]
PHRASE = {"draft": "is a draft", "submitted": "is submitted and waiting for approval",
          "approved": "is approved", "rejected": "is rejected"}


class ExpenseAgent:
    def __init__(self, tools):
        self.t = tools
        self.sessions = {}
        self.rng = random.Random()

    # ------------------------------------------------------------ reading the message
    def intent(self, low):
        padded = f" {low} "
        for name, keys in INTENTS:
            for k in keys:
                if re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", padded):
                    return name
        return None

    def find_id(self, text):
        m = ID_RE.search(text)
        return f"EX-{m.group(1)}" if m else None

    def yesno(self, low):
        words = re.sub(r"[^a-z' ]", " ", low.replace("’", "'")).split()
        phrase = " ".join(words)
        padded = f" {phrase} "
        if words and words[0] in NO:
            return False
        if any(phrase.startswith(y) for y in YES):
            return True
        return None

    def ask(self):
        return self.rng.choice(["Shall I", "Should I"])

    # ------------------------------------------------------------ backend helpers
    def own(self, user, eid):
        e = self.t.get_expense(expense_id=eid)
        return e if e and e["owner"] == user else None

    def manages(self, user, owner):
        u = self.t.get_user(user_id=owner)
        return bool(u) and u["manager"] == user

    def visible(self, user, eid):
        e = self.t.get_expense(expense_id=eid)
        if e and (e["owner"] == user or self.manages(user, e["owner"])):
            return e
        return None

    def not_found(self, eid):
        return [f"I couldn't find expense {eid} on your account. Could you check the number?"]

    def submit_problem(self, user, eid):
        """None if the expense may be submitted now, otherwise the reply explaining why not."""
        e = self.own(user, eid)
        if e is None:
            return self.not_found(eid)
        if e["status"] != "draft":
            return [f"{eid} {PHRASE[e['status']]}, so it can't be submitted."]
        age = self.t.today() - e["incurred_day"]
        if age > WINDOW + 1:
            return [f"Sorry, {eid} was incurred {age} days ago, which is outside the {WINDOW}-day window, "
                    f"so I can't submit it."]
        if e["amount"] > LIMIT * 10:
            return [f"Sorry, {eid} is above the ${LIMIT:.2f} limit. Please contact finance."]
        return None

    def approve_problem(self, user, eid):
        me = self.t.get_user(user_id=user)
        if not me or me["role"] != "manager":
            return ["Sorry, only managers can approve expenses."]
        e = self.t.get_expense(expense_id=eid)
        if e is None or e["owner"] == user or not self.manages(user, e["owner"]):
            return [f"I couldn't find expense {eid} among your team's expenses."]
        if e["status"] != "submitted":
            return [f"{eid} {PHRASE[e['status']]}, so it can't be approved."]
        return None

    # ------------------------------------------------------------ main entry
    def handle(self, user, session, text):
        s = self.sessions.setdefault(user, {"pending": None, "want": None})
        low = " ".join(text.lower().split())
        eid = self.find_id(text)
        intent = self.intent(low)

        if s["pending"]:
            yn = self.yesno(low)
            if yn is False:
                s["pending"] = None
                return ["No problem, I won't do that. Anything else?"]
            if yn is True:
                kind, target = s["pending"]
                s["pending"] = None
                return self.execute(user, kind, target)
            if intent is None and eid is None:
                kind, target = s["pending"]
                return [f"Please answer yes or no: {self.ask().lower()} {kind} {target}?"]
            s["pending"] = None  # the user moved on to something else

        if intent is None and eid and s["want"]:
            intent = s["want"]
        if intent == "cancel":
            s["want"] = None
            return ["No problem, I've stopped that. Anything else?"]
        if intent in ("submit", "delete", "approve", "status"):
            if not eid:
                s["want"] = intent
                return ["Which expense? Please give me the expense number (like EX-0042)."]
            s["want"] = None
            return getattr(self, "do_" + intent)(user, s, eid)
        s["want"] = None
        if intent == "add":
            return self.do_add(user, text)
        if intent == "total":
            total = 0.0
            for i in self.t.list_expenses(user_id=user):
                e = self.t.get_expense(expense_id=i)
                if e["status"] == "submitted":
                    total += e["amount"]
            return [f"Your submitted expenses total ${total:.2f}."]
        if intent == "list":
            ids = self.t.list_expenses(user_id=user)
            if not ids:
                return ["You have no expenses yet."]
            parts = []
            for i in ids[:8]:
                e = self.t.get_expense(expense_id=i)
                parts.append(f"{i} ({e['status']}, ${e['amount']:.2f})")
            more = f" and {len(ids) - 8} more" if len(ids) > 8 else ""
            return [f"You have {len(ids)} expenses: " + ", ".join(parts) + more + "."]
        if intent == "bye":
            return ["You're welcome. Have a good day!"]
        if intent == "greet":
            return ["Hello! " + HELP]
        return ["Sorry, I didn't understand. " + HELP]

    # ------------------------------------------------------------ flows
    def do_submit(self, user, s, eid):
        problem = self.submit_problem(user, eid)
        if problem:
            return problem
        e = self.own(user, eid)
        s["pending"] = ("submit", eid)
        return [f"{self.ask()} submit {eid} ({e['merchant']}, ${e['amount']:.2f}) for approval?"]

    def do_delete(self, user, s, eid):
        e = self.own(user, eid)
        if e is None:
            return self.not_found(eid)
        if e["status"] != "draft":
            return [f"{eid} {PHRASE[e['status']]}; only drafts can be deleted."]
        s["pending"] = ("delete", eid)
        return [f"{self.ask()} delete draft {eid} ({e['merchant']}, ${e['amount']:.2f})?"]

    def do_approve(self, user, s, eid):
        problem = self.approve_problem(user, eid)
        if problem:
            return problem
        e = self.t.get_expense(expense_id=eid)
        owner = self.t.get_user(user_id=e["owner"])
        s["pending"] = ("approve", eid)
        return [f"{self.ask()} approve {eid} ({e['merchant']}, ${e['amount']:.2f}) from {owner['name']}?"]

    def do_status(self, user, s, eid):
        e = self.t.get_expense(expense_id=eid)
        if e is None:
            return self.not_found(eid)
        age = self.t.today() - e["incurred_day"]
        days = "1 day" if age == 1 else f"{age} days"
        return [f"{eid} ({e['merchant']}, ${e['amount']:.2f}) {PHRASE[e['status']]}. It was incurred {days} ago."]

    def do_add(self, user, text):
        rest = ID_RE.sub(" ", text)
        m = NUM_RE.search(rest)
        where = re.search(r"\b(?:at|for|from)\s+(.+)$", rest, re.I)
        if not m or not where:
            return ["To add an expense, tell me the amount and the merchant, like: add expense 23.50 at Cafe Uno."]
        merchant = where.group(1).strip(" .!?")
        amount = float(m.group(1))
        if amount <= 0 or not merchant:
            return ["To add an expense, tell me the amount and the merchant, like: add expense 23.50 at Cafe Uno."]
        res = self.t.create_expense(user_id=user, merchant=merchant, amount=amount)
        return [f"Added {res['id']}: {merchant}, ${amount:.2f} (draft)."]

    def execute(self, user, kind, eid):
        """Run a confirmed action. Everything is checked again: time may have passed and the
        expense may have changed since the question was asked."""
        if kind == "submit":
            problem = self.submit_problem(user, eid)
            if problem:
                return problem
            self.t.submit_expense(expense_id=eid)
            return [f"Done. {eid} has been submitted for approval."]
        if kind == "delete":
            e = self.own(user, eid)
            if e is None:
                return self.not_found(eid)
            if e["status"] != "draft":
                return [f"{eid} {PHRASE[e['status']]}; only drafts can be deleted."]
            self.t.delete_expense(expense_id=eid)
            return [f"{eid} has been deleted."]
        if kind == "approve":
            problem = self.approve_problem(user, eid)
            if problem:
                return problem
            self.t.approve_expense(expense_id=eid, approver_id=user)
            return [f"{eid} has been approved."]
        return ["Sorry, something went wrong."]
