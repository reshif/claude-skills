"""Test the tester: break a copy of the target on purpose and see whether the tests notice.

Small faults (a flipped comparison, a dropped line, an off-by-one) are planted one at a time in
a Python target. Each faulty copy is run through the same cases / simulated users. The share
caught is the suite's detection power, and the faults nobody caught show where it is blind.

Which targets: any target whose source is a Python file that poptest can copy.
  python adapter   the entry file, or any file it imports (--file); the folder is copied, the
                   faulty file is swapped in and the entry is loaded from the copy.
  http / cli       --file names the Python source of the service or program. The folder that holds
                   it (or poptest.json "mutate": {"root": DIR}) is copied, the faulty file swapped
                   in, and the SAME start command is launched on the copy: the working directory and
                   every command argument or env value that points into that folder are redirected.
Not possible: targets with no Python source to change (compiled or remote services, a URL that is
already running), and faults in prompts or models. The original files are never modified.
"""
import ast
import copy
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

from .compare import apply_rule, run_reps
from .world import SpecError

FLIP = {ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Lt: ast.LtE, ast.LtE: ast.Lt,
        ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.In: ast.NotIn, ast.NotIn: ast.In,
        ast.Is: ast.IsNot, ast.IsNot: ast.Is}
KIND_TEXT = {
    "flip_compare": "a comparison turned around (e.g. > became >=, == became !=)",
    "swap_boolop": "'and' swapped with 'or'",
    "if_true": "a condition forced to always be true",
    "if_false": "a condition forced to always be false",
    "const_off_by_one": "a number changed by one",
    "delete_stmt": "one line of work removed",
    "remove_not": "a 'not' removed",
    "return_none": "a function made to return nothing",
}


class _Sites(ast.NodeVisitor):
    def __init__(self):
        self.sites, self.func = [], None

    def _fn(self, node):
        prev, self.func = self.func, node.name
        self.generic_visit(node)
        self.func = prev

    visit_FunctionDef = visit_AsyncFunctionDef = _fn

    def add(self, kind, node):
        if self.func:
            self.sites.append((kind, node.lineno, node.col_offset))

    def visit_Compare(self, node):
        if type(node.ops[0]) in FLIP:
            self.add("flip_compare", node)
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        self.add("swap_boolop", node)
        self.generic_visit(node)

    def visit_If(self, node):
        self.add("if_true", node)
        self.add("if_false", node)
        self.generic_visit(node)

    def visit_UnaryOp(self, node):
        if isinstance(node.op, ast.Not):
            self.add("remove_not", node)
        self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, int) and not isinstance(node.value, bool) and 0 <= node.value <= 1000:
            self.add("const_off_by_one", node)

    def visit_Return(self, node):
        if node.value is not None and not (isinstance(node.value, ast.Constant) and node.value.value is None):
            self.add("return_none", node)
        self.generic_visit(node)

    def _stmt(self, node):
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):  # skip docstrings
            self.add("delete_stmt", node)
        self.generic_visit(node)

    visit_Expr = visit_Assign = visit_AugAssign = _stmt


class _Apply(ast.NodeTransformer):
    def __init__(self, kind, line, col):
        self.kind, self.line, self.col, self.done = kind, line, col, False

    def _hit(self, node, kind):
        return not self.done and self.kind == kind and node.lineno == self.line and node.col_offset == self.col

    def visit_Compare(self, node):
        if self._hit(node, "flip_compare"):
            node.ops[0] = FLIP[type(node.ops[0])]()
            self.done = True
        return self.generic_visit(node)

    def visit_BoolOp(self, node):
        if self._hit(node, "swap_boolop"):
            node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
            self.done = True
        return self.generic_visit(node)

    def visit_If(self, node):
        for k in ("if_true", "if_false"):
            if self._hit(node, k):
                node.test = ast.copy_location(ast.Constant(value=k == "if_true"), node.test)
                self.done = True
        return self.generic_visit(node)

    def visit_UnaryOp(self, node):
        if self._hit(node, "remove_not"):
            self.done = True
            return node.operand
        return self.generic_visit(node)

    def visit_Constant(self, node):
        if self._hit(node, "const_off_by_one"):
            self.done = True
            return ast.copy_location(ast.Constant(value=node.value + 1), node)
        return node

    def visit_Return(self, node):
        if self._hit(node, "return_none"):
            self.done = True
            return ast.copy_location(ast.Return(value=None), node)
        return self.generic_visit(node)

    def _stmt(self, node):
        if self._hit(node, "delete_stmt"):
            self.done = True
            return ast.copy_location(ast.Pass(), node)
        return self.generic_visit(node)

    visit_Expr = visit_Assign = visit_AugAssign = _stmt


def make_mutants(src_path, out_dir, n=40, seed=0, kinds=None):
    """Write up to n faulty copies of src_path into out_dir, spread evenly over fault kinds."""
    with open(src_path, encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)
    v = _Sites()
    v.visit(tree)
    rng = random.Random(seed)
    by_kind = {}
    for s in v.sites:
        if not kinds or s[0] in kinds:
            by_kind.setdefault(s[0], []).append(s)
    for lst in by_kind.values():
        rng.shuffle(lst)
    order = []
    while any(by_kind.values()):  # round-robin so every fault kind is represented
        for k in sorted(by_kind):
            if by_kind[k]:
                order.append(by_kind[k].pop())
    os.makedirs(out_dir, exist_ok=True)
    lines = src.splitlines()
    made, seen = [], {src}
    for kind, line, col in order:
        if len(made) >= n:
            break
        a = _Apply(kind, line, col)
        t = a.visit(copy.deepcopy(tree))
        if not a.done:
            continue
        ast.fix_missing_locations(t)
        try:
            code = ast.unparse(t)
            compile(code, "mutant", "exec")
        except Exception:
            continue
        if code in seen:
            continue
        seen.add(code)
        path = os.path.join(out_dir, f"m{len(made):03d}_{kind}_L{line}.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        made.append({"id": f"m{len(made):03d}", "path": path, "kind": kind, "line": line,
                     "source": lines[line - 1].strip() if line <= len(lines) else ""})
    return made, len(v.sites)


IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "runs", ".git", "node_modules", ".venv", "venv")


def _inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _copy_with_mutant(root, src_path, mutant_path, workdir):
    """Copy `root` and put the faulty file in the place of src_path. Returns the copy's path."""
    root, src_path = os.path.realpath(root), os.path.realpath(src_path)
    if not _inside(src_path, root):
        raise SpecError(f"the file to plant faults in ({src_path}) is not inside the folder that is copied ({root})")
    if len([x for x in root.split(os.sep) if x]) < 2:
        raise SpecError(f"refusing to copy {root!r} for mutation testing: it is too high up. Put the target's "
                        f"source in its own folder, or set poptest.json \"mutate\": {{\"root\": DIR}}.")
    copy_dir = os.path.join(workdir, "tree")
    if os.path.exists(copy_dir):
        shutil.rmtree(copy_dir)
    shutil.copytree(root, copy_dir, ignore=IGNORE, symlinks=True)
    shutil.copyfile(mutant_path, os.path.join(copy_dir, os.path.relpath(src_path, root)))
    return copy_dir


class _Remap:
    """Redirects paths that point into the original folder to the copy."""

    def __init__(self, root, copy_dir, cwd):
        self.root, self.copy, self.cwd, self.hits = os.path.realpath(root), copy_dir, cwd, 0

    def path(self, p):
        return os.path.normpath(os.path.join(self.copy, os.path.relpath(os.path.realpath(p), self.root)))

    def value(self, v):
        if isinstance(v, list):
            return [self.value(x) for x in v]
        if isinstance(v, dict):
            return {k: self.value(x) for k, x in v.items()}
        if not isinstance(v, str) or not v:
            return v
        for form in {self.root, os.path.abspath(self.root)}:
            if form in v:
                self.hits += 1
                return v.replace(form, self.copy)
        if not v.startswith("-") and "{" not in v and not os.path.isabs(v):
            cand = os.path.join(self.cwd, v)
            if os.path.exists(cand) and _inside(cand, self.root):
                self.hits += 1
                return self.path(cand)
        return v


def target_for(project, mutant_path, src_path, workdir):
    """Target config that runs the mutant instead of src_path, through the same adapter and, for
    http/cli targets, the same start command."""
    base = copy.deepcopy(project.target_config())
    kind = base.get("adapter", "python")
    src_path = os.path.realpath(src_path)
    mroot = (project.config.get("mutate") or {}).get("root")
    if kind == "python":
        entry_file, attr = base["entry"].rsplit(":", 1)
        entry_file = os.path.realpath(project.path(entry_file))
        if entry_file == src_path and not mroot:
            return dict(base, entry=f"{os.path.abspath(mutant_path)}:{attr}",
                        pythonpath=list(base.get("pythonpath", [])) + [os.path.dirname(entry_file)])
        root = project.path(mroot) if mroot else os.path.dirname(entry_file)
        if not _inside(src_path, root) or not _inside(entry_file, root):
            # a wrapper as entry and the product elsewhere: copy the smallest folder that holds both
            root = os.path.commonpath([entry_file, src_path])
            if os.path.isfile(root):
                root = os.path.dirname(root)
        copy_dir = _copy_with_mutant(root, src_path, mutant_path, workdir)
        rm = _Remap(root, copy_dir, project.root)
        pp = [rm.path(project.path(x)) if _inside(project.path(x), root) else project.path(x)
              for x in base.get("pythonpath", [])]
        return dict(base, entry=f"{rm.path(entry_file)}:{attr}", pythonpath=pp)
    if kind == "http" and not (base.get("start") or {}).get("command"):
        raise SpecError("mutation testing has to start the faulty copy itself: this http target has no "
                        "'start' command (an already running service cannot be mutated).")
    root = project.path(mroot) if mroot else os.path.dirname(src_path)
    copy_dir = _copy_with_mutant(root, src_path, mutant_path, workdir)
    cwd = os.path.realpath(project.path(base["cwd"])) if base.get("cwd") else os.path.realpath(project.root)
    rm = _Remap(root, copy_dir, cwd)
    if _inside(cwd, root):
        base["cwd"] = rm.path(cwd)
        rm.hits += 1
    else:
        base["cwd"] = cwd
    if kind == "http":
        base["start"] = dict(base["start"], command=rm.value(base["start"]["command"]),
                             env=rm.value(base["start"].get("env", {})))
    else:
        base["command"] = rm.value(base["command"])
    if base.get("env"):
        base["env"] = rm.value(base["env"])
    if not rm.hits:
        raise SpecError(f"the target's command does not run anything inside {root}, so a faulty copy of "
                        f"{os.path.basename(src_path)} would never be started. Name the folder the command runs "
                        f"from with poptest.json \"mutate\": {{\"root\": DIR}} (it must contain the file), or use a "
                        f"command / cwd / env value that points into it.")
    return base


def _worker():
    """Subprocess entry: evaluate one mutant; print {"conv|code": hits} as JSON."""
    job = json.load(sys.stdin)
    from .project import Project
    project = Project(job["project"])
    cases = project.load_cases(job["case_paths"] or None, job.get("only")) if job["approach"] == "cases" else None
    personas = job.get("personas") if job["approach"] == "population" else None
    with tempfile.TemporaryDirectory() as tmp:
        target = target_for(project, job["mutant"], job["src"], tmp)
        units, _, _ = run_reps(project, target, cases, personas, job["reps"])
    json.dump({f"{c}|{code}": n for (c, code), n in units.items()}, sys.stdout)


def _eval_mutant(job, timeout):
    lib = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cmd = [sys.executable, "-c", f"import sys; sys.path.insert(0, {lib!r}); "
                                 "from poptest.mutate import _worker; _worker()"]
    try:
        r = subprocess.run(cmd, input=json.dumps(job), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "hang"
    if r.returncode != 0:
        return None, "error: " + (r.stderr.strip().splitlines() or ["?"])[-1][:200]
    raw = json.loads(r.stdout or "{}")
    return {tuple(k.split("|", 1)): v for k, v in raw.items()}, None


def mutation_score(project, src_path=None, n=40, seed=0, approaches=("cases",), reps=3, rule=None,
                   case_paths=None, only=None, personas=None, out_dir=None, jobs=4, timeout=300, progress=None):
    """Detection power per approach. A mutant is caught when the pre-declared rule (same one as
    release comparison) sees a problem in the mutant that the unmodified target does not show."""
    base = project.target_config()
    kind = base.get("adapter", "python")
    if src_path is None:
        if kind != "python":
            raise SpecError(f"for an {kind} target, say which Python source file to plant faults in: "
                            f"poptest mutate --file path/to/service.py. The folder holding it is copied and the "
                            f"same start command is run on the copy. (A target with no Python source, or one "
                            f"that poptest does not start itself, cannot be mutated.)")
        src_path = project.path(base["entry"].rsplit(":", 1)[0])
    if not os.path.isfile(src_path):
        raise SpecError(f"mutate: no such file {src_path}")
    if not str(src_path).endswith(".py"):
        raise SpecError(f"mutate: {src_path} is not a Python file; faults can only be planted in Python source")
    if kind != "python":
        # one faulty service at a time unless every port is picked fresh for each of them
        st = base.get("start") or {}
        fixed = base.get("port") or base.get("tools_port") or base.get("port_range") or \
            (kind == "http" and "{port}" not in json.dumps([base.get("url"), st.get("command")]))
        if fixed:
            jobs = 1
    rule = dict({"reps": reps, "min_b": min(2, reps), "max_a": 0}, **(rule or {}))
    rule["reps"] = reps
    rule["min_b"] = min(rule["min_b"], reps)
    out_dir = out_dir or os.path.join(project.root, "runs", "mutants")
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    try:
        mutants, sites = make_mutants(src_path, out_dir, n=n, seed=seed)
    except SyntaxError as e:
        raise SpecError(f"mutate: {src_path} could not be parsed as Python (line {e.lineno}: {e.msg})") from None
    if not mutants:
        raise SpecError(f"no mutants could be made from {src_path}")
    rel = os.path.relpath(src_path, project.root)
    result = {"file": rel, "file_abs": os.path.abspath(src_path) if rel.startswith("..") else None,
              "adapter": kind, "sites": sites, "mutants": mutants, "rule": rule, "approaches": {}}
    with tempfile.TemporaryDirectory() as probe:   # fail early, with a clear message, if the copy cannot be launched
        target_for(project, mutants[0]["path"], src_path, probe)
    for ap in approaches:
        cases = project.load_cases(case_paths, only) if ap == "cases" else None
        pers = personas if ap == "population" else None
        if ap == "population" and not pers:
            raise SpecError("population approach needs personas")
        clean, _, convs = run_reps(project, None, cases, pers, reps)
        jobs_ = [{"project": project.root, "approach": ap, "case_paths": case_paths, "only": only,
                  "personas": pers, "mutant": m["path"], "src": os.path.abspath(src_path), "reps": reps}
                 for m in mutants]
        caught = {}
        with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
            for m, (units, problem) in zip(mutants, ex.map(lambda j: _eval_mutant(j, timeout), jobs_)):
                if problem == "hang":
                    caught[m["id"]] = ["hang (the faulty copy never answered)"]
                elif problem:
                    caught[m["id"]] = [problem]
                else:
                    hits = apply_rule(clean, units, rule)
                    caught[m["id"]] = sorted({h["code"] for h in hits})[:4]
                if progress:
                    progress(ap, m, caught[m["id"]])
        by_kind = {}
        for m in mutants:
            k = by_kind.setdefault(m["kind"], {"caught": 0, "total": 0})
            k["total"] += 1
            k["caught"] += bool(caught[m["id"]])
        n_caught = sum(1 for v in caught.values() if v)
        result["approaches"][ap] = {
            "conversations": len(convs), "caught": n_caught, "total": len(mutants),
            "detection_power": round(n_caught / len(mutants), 3), "by_kind": by_kind, "caught_by": caught,
            "clean_problem_pairs": len(clean),
            "missed": [m for m in mutants if not caught[m["id"]]]}
    all_missed = [m for m in mutants if all(not result["approaches"][a]["caught_by"][m["id"]] for a in approaches)]
    result["missed_by_all"] = all_missed
    return result
