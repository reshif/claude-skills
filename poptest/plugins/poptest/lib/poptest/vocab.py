"""Vocabulary: how users say yes, no and everything in between.

One pack is shared by the checks (what counts as a clear yes) and by the simulated users
(what they type). Projects extend it in vocab.json; lists are merged, never replaced, unless the
project file says {"replace": true}.
"""
import copy
import re

DEFAULT = {
    "affirm": ["yes", "yeah", "yep", "yup", "yes please", "sure", "ok", "okay", "confirm", "confirmed",
               "correct", "go ahead", "please do", "do it", "that's right", "thats right", "right",
               "absolutely", "definitely", "proceed", "sounds good", "fine", "affirmative", "y"],
    "negate": ["no", "nope", "nah", "don't", "dont", "do not", "stop", "cancel", "wait", "never mind",
               "nevermind", "hold on", "not yet", "not now", "not sure", "wrong", "forget it",
               "changed my mind", "rather not", "instead", "actually", "n", "isn't", "isnt", "not right",
               "not correct", "neither", "none of"],
    "say": {
        "yes": {"terse": ["yes", "y", "ok"], "polite": ["Yes, please.", "Yes, go ahead.", "That's right, please do."],
                "messy": ["yes", "yeah", "yep ok", "yup", "sure"]},
        "no": {"terse": ["no"], "polite": ["No, that's not the right one.", "No, thank you."],
               "messy": ["no thats wrong", "nope", "nah"]},
        "no_wait": {"terse": ["no wait"], "polite": ["No, wait. Let me check first.", "Hold on, not yet."],
                    "messy": ["no wait", "wait wait hold on", "actually no"]},
        "negated_no": {"terse": ["please don't", "do not do that"],
                       "polite": ["No, please don't.", "I'd rather you didn't, thanks.", "Please do not go ahead."],
                       "messy": ["no pls dont", "dont do it", "nah dont", "yeah no dont"]},
        "dont_know": {"terse": ["don't know it"], "polite": ["I don't have that to hand, sorry."],
                      "messy": ["idk", "dunno sorry"]},
        "bye": {"terse": ["thanks"], "polite": ["Thank you, bye!"], "messy": ["thx", "ok thanks"]},
        "human": {"terse": ["human please"], "polite": ["Can I talk to a real person, please?"],
                  "messy": ["get me a human"]},
        "side_question": {"terse": ["what can you do"], "polite": ["Actually, before that: what can you help me with?"],
                          "messy": ["wait actually what else can u do"]},
        "hello": {"terse": ["hi"], "polite": ["Hello!"], "messy": ["hey", "hii"]},
    },
    "junk": ["sent from my phone", "sorry typing on the bus", "..", "?"],
}


def merge(base, extra):
    out = copy.deepcopy(base)
    if not extra:
        return out
    replace = extra.get("replace") is True
    for key in ("affirm", "negate", "junk"):
        if key in extra:
            out[key] = list(extra[key]) if replace else list(dict.fromkeys(out[key] + list(extra[key])))
    for act, styles in (extra.get("say") or {}).items():
        slot = out["say"].setdefault(act, {})
        if isinstance(styles, list):
            styles = {"terse": styles, "polite": styles, "messy": styles}
        for style, lines in styles.items():
            slot[style] = list(lines) if replace else list(dict.fromkeys(slot.get(style, []) + list(lines)))
    return out


def normalise(text):
    t = (text or "").lower().replace("’", "'").replace("‘", "'")
    return " ".join(re.sub(r"[^a-z0-9' ]+", " ", t).split())


class Stance:
    """Reads a user message as a clear yes, a no, or neither. Deliberately strict: a yes that
    also contains a no-word ("yes... actually wait") is not a clear yes."""

    def __init__(self, vocab):
        def alt(words):
            ws = sorted({normalise(w) for w in words if normalise(w)}, key=len, reverse=True)
            return "|".join(re.escape(w) for w in ws)
        self.aff = re.compile(r"^(?:(?:oh|um|uh|well|ok so|hmm|hi|hey)\s+)*(?:%s)(?:\s|$)" % alt(vocab["affirm"]))
        self.neg = re.compile(r"(?:^|\s)(?:%s)(?:\s|$)" % alt(vocab["negate"]))

    def __call__(self, text):
        t = normalise(text)
        if self.neg.search(t):
            return "no"
        if self.aff.search(t):
            return "yes"
        return "other"
