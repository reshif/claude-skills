"""Test target for the 1.1 features: a small shop/helpdesk assistant with switchable faults.

  close T-1 / reopen T-1      one shared backend tool (update_ticket); only closing needs a yes
  pay 1999 SKU-100            confirms as "Pay INR 19.99 for SKU-100."
  reserve 8 SKU-100           confirms as "Reserve 8 x SKU-100."
  stock SKU-100 / show T-1 / time / hello / say:<text> / verify <code> / who <user>
Confirmation wording has no question mark: "... Reply yes to confirm or no to cancel."
NOISE_EVERY = n makes every n-th message (per instance) answer "Sorry, could you repeat that?"
without doing anything, as a spec'd random non-answer would.
"""
import os

NOISE = "Sorry, could you repeat that?"
ASK = " Reply yes to confirm or no to cancel."


class Shop:
    NOISE_EVERY = 0
    NO_CANCELS = True          # False: "no" leaves the pending action in place (bug)
    NOISE_ACTS = False         # True: the noise turn still executes a pending yes (bug)
    RESERVE_QTY = None         # a number: reserve this quantity whatever was confirmed (bug)
    PAY_FACTOR = 1             # 10: charges ten times the confirmed amount (bug)
    STALE_CLOCK = False        # True: reads the clock once and caches it (bug)
    FORGETS = False            # True: any other message drops the pending action (bug)
    DEAF = False               # True: a yes is never understood (bug)

    def __init__(self, tools):
        self.tools = tools
        self.pending = {}
        self.n = 0
        self.clock = None

    def now(self):
        if self.STALE_CLOCK:
            self.clock = self.clock or self.tools.now()
            return self.clock
        return self.tools.now()

    def do(self, user, action):
        kind, a, b = action
        if kind == "close":
            self.tools.update_ticket(ticket_id=a, fields={"status": "closed", "closed_date": self.now()["date"]})
            return f"{a} has been closed."
        if kind == "pay":
            self.tools.pay(user_id=user, amount_minor=a * self.PAY_FACTOR, sku=b)
            return "Paid."
        if kind == "reserve":
            self.tools.reserve(sku=b, qty=self.RESERVE_QTY or a)
            return "Reserved."

    def handle(self, user, session, text):
        self.n += 1
        t = text.strip()
        low = t.lower()
        if self.NOISE_EVERY and self.n % self.NOISE_EVERY == 0:
            if self.NOISE_ACTS and low == "yes" and session in self.pending:
                self.do(user, self.pending[session])
            return NOISE
        if low in ("yes", "yes please", "y") and not self.DEAF:
            if session not in self.pending:
                return "There is nothing to confirm."
            return self.do(user, self.pending.pop(session))
        if low in ("no", "cancel", "stop"):
            if self.NO_CANCELS:
                self.pending.pop(session, None)
            return "Cancelled."
        if self.FORGETS:
            self.pending.pop(session, None)
        w = t.split()
        if low == "leak":
            return "U2's account is 5500998877662222"
        if low == "leakmask":
            return "The other account ends ****2222"
        if low.startswith("close "):
            self.pending[session] = ("close", w[1], None)
            return f"Close {w[1]}." + ASK
        if low.startswith("reopen "):
            self.tools.update_ticket(ticket_id=w[1], fields={"status": "open"})
            return f"Reopened {w[1]}."
        if low.startswith("pay "):
            self.pending[session] = ("pay", int(w[1]), w[2])
            return f"Pay INR {int(w[1]) / 100:.2f} for {w[2]}." + ASK
        if low.startswith("reserve "):
            if self.now()["hour"] >= 18:
                return "We are closed after 18:00."
            self.pending[session] = ("reserve", int(w[1]), w[2])
            return f"Reserve {w[1]} x {w[2]}." + ASK
        if low.startswith("stock "):
            return f"{w[1]}: {self.tools.get_stock(sku=w[1])['qty']} in stock."
        if low.startswith("show "):
            tk = self.tools.get_ticket(ticket_id=w[1])
            return f"{w[1]}: {tk['title']} ({tk['status']})"
        if low.startswith("verify "):
            return "Verified." if self.tools.verify(code=w[1])["ok"] else "Wrong code."
        if low.startswith("who "):
            try:
                return self.tools.get_user(user_id=w[1])["name"]
            except Exception as e:
                return f"error {getattr(e, 'status', '?')}: {e}"
        if low == "time":
            n = self.now()
            return f"It is {n['now']} (day {n['day']}, hour {n['hour']})."
        if low == "hello":
            return "Hello."
        if low.startswith("say:"):
            return t[4:]
        if low == "flake":
            marker = os.environ.get("SHOP_FLAKE_FILE")
            if marker and not os.path.exists(marker):
                open(marker, "w").close()
                return "U2's account is 5500998877662222"
            return "Nothing to see."
        return "I can close, reopen, pay, reserve, stock, show, time."


class Noisy(Shop):
    NOISE_EVERY = 3


class NoisyActs(Shop):
    NOISE_EVERY = 2
    NOISE_ACTS = True


class AlwaysNoise(Shop):
    NOISE_EVERY = 1


class NoCancel(Shop):
    NO_CANCELS = False


class WrongQty(Shop):
    RESERVE_QTY = 100


class Overcharge(Shop):
    PAY_FACTOR = 10


class StaleClock(Shop):
    STALE_CLOCK = True


class NoisyNoCancel(Shop):
    NOISE_EVERY = 7
    NO_CANCELS = False


class Forgets(Shop):
    FORGETS = True


class Deaf(Shop):
    DEAF = True


class Buggy(Shop):
    NO_CANCELS = False
    RESERVE_QTY = 100
