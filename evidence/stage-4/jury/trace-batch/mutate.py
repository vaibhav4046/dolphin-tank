"""jury mutation control: does MY check set fail when the batch code is broken? Copies stage-4 to a scratch dir, applies one
source mutation, builds, runs the part(s) that should notice. CAUGHT = a part exited non-zero; SURVIVED = all passed.

usage: python mutate.py <stage-4 dir> <scratch dir> <go build output dir>
"""
import os
import shutil
import subprocess
import sys

SRC, SCR, BIN = sys.argv[1], sys.argv[2], sys.argv[3]
HERE = os.path.dirname(os.path.abspath(__file__))

MUTS = [
    ("M1 affordability ignores held funds (uses total balance)", "correct_batch.go",
     "st.Available(st.usersByID[id], stamp)+n < 0", "st.usersByID[id].Balance+n < 0", ["jury_batch_2.py"]),
    ("M2 affordability per item instead of net effect", "correct_batch.go",
     """	for _, s := range steps {
		net[s.p.FromUserID] -= s.delta()
		net[s.p.ToUserID] += s.delta()
	}
	for id, n := range net {""",
     """	for _, s := range steps {
		net = map[string]int64{s.p.FromUserID: -s.delta(), s.p.ToUserID: s.delta()}
		for id, n := range net {
			if n < 0 && st.Available(st.usersByID[id], stamp)+n < 0 {
				return NewErr(409, "insufficient_funds", "x")
			}
		}
	}
	net = map[string]int64{}
	for id, n := range net {""", ["jury_batch_2.py"]),
    ("M3 historical overdraft does not roll the revisions back", "correct_batch.go",
     """		for i := len(steps) - 1; i >= 0; i-- {
			st.dropLastRevision(steps[i].p.PaymentID)
			st.moveBatchDelta(steps[i], -steps[i].delta())
		}
""", "", ["jury_batch_1.py"]),
    ("M4 settlement members' instants not compared", "correct_batch.go",
     "if !inBatch[pid].Equal(first) {", "if false && !inBatch[pid].Equal(first) {", ["jury_batch_1.py"]),
    ("M5 incomplete settlement allowed", "correct_batch.go",
     "return NewErr(422, \"incomplete_settlement\", \"every member of a settlement must be corrected together\")", "continue", ["jury_batch_1.py"]),
    ("M6 batch recorded_at is not raised above a member's later recorded_at", "correct_batch.go",
     "rec.Before(floor) {", "false && rec.Before(floor) {", ["jury_batch_5.py"]),
    ("M7 current-funds check removed (historical check only)", "correct_batch.go",
     """	if e := st.checkBatchAffordable(steps, stamp); e != nil {
		return nil, e
	}
	return st.applyBatch(steps, stamp)""",
     """	out, he := st.applyBatch(steps, stamp)
	if he != nil {
		return nil, he
	}
	if e := st.checkBatchAffordable(steps, stamp); e != nil {
		return out, nil
	}
	return out, nil""", ["jury_batch_1.py"]),
    ("M8 stale revision not enforced for batch items", "correct_batch.go",
     "if it.In.ExpectedRevision != latest.Revision {", "if false && it.In.ExpectedRevision != latest.Revision {", ["jury_batch_3.py"]),
    ("M9 refunded amount floor not enforced", "correct_batch.go",
     "if it.In.Amount < st.refundedAmount(it.PaymentID) {", "if false && it.In.Amount < st.refundedAmount(it.PaymentID) {", ["jury_batch_2.py"]),
    ("M10 refund payments not immutable in a batch", "correct_batch.go",
     "if p.AuthorizationID != nil || p.isRefund() {", "if p.AuthorizationID != nil {", ["jury_batch_1.py"]),
    ("M11 imported batch ids not reserved", "store.go",
     "ids[*r.CorrectionBatchID] = struct{}{}", "_ = r", ["jury_batch_4.py"]),
]

only = sys.argv[4:] or None
results = []
for name, fname, old, new, parts in MUTS:
    if only and not any(name.startswith(o) for o in only):
        continue
    if os.path.exists(SCR):
        shutil.rmtree(SCR)
    shutil.copytree(SRC, SCR, ignore=shutil.ignore_patterns("*.exe"))
    path = os.path.join(SCR, fname)
    text = open(path, encoding="utf-8").read()
    if old not in text:
        print("SKIP %s: pattern not found" % name)
        continue
    open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))
    exe = os.path.join(BIN, "mut.exe")
    b = subprocess.run(["go", "build", "-o", exe, "."], cwd=SCR, capture_output=True, text=True)
    if b.returncode != 0:
        print("BUILD-FAIL %s: %s" % (name, b.stderr[:300]))
        results.append((name, "build failed"))
        continue
    caught = []
    for part in parts:
        args = [sys.executable, os.path.join(HERE, part), exe]
        if part == "jury_batch_4.py":
            args += [os.path.join(BIN, "s1.exe"), os.path.join(BIN, "s2.exe"), os.path.join(BIN, "s3.exe")]
        if part == "jury_batch_5.py":
            args += [os.path.join(BIN, "s3.exe")]
        r = subprocess.run(args, cwd=HERE, capture_output=True, text=True)
        fails = [l[5:120] for l in r.stdout.splitlines() if l.startswith("FAIL ")]
        if r.returncode != 0:
            caught.append((part, fails[:3] or [(r.stderr or "")[-200:]]))
    status = "CAUGHT" if caught else "SURVIVED"
    print("%s  %s" % (status, name))
    for part, f in caught:
        print("     by %s: %s" % (part, " | ".join(f)))
    results.append((name, status))
print("summary: %d caught, %d survived" % (sum(1 for _, s in results if s == "CAUGHT"), sum(1 for _, s in results if s == "SURVIVED")))
