"""Create scratch copies of stage-4 with one deliberate UI/CSS fault each (never touches the worktree). usage: python ui_mutants.py <stage-4 dir> <out dir>"""
import os, shutil, sys

SRC, OUT = sys.argv[1], sys.argv[2]
MUT = {
    "m1_radius": ("web/css/tokens.css", "--radius-control: 5px;", "--radius-control: 6px;"),
    "m2_dropshadow": ("web/css/components.css", ".card {\n  background: var(--color-surface); border: 1px solid var(--color-line); border-radius: var(--radius-card);\n  box-shadow: var(--rim-light);", ".card {\n  background: var(--color-surface); border: 1px solid var(--color-line); border-radius: var(--radius-card);\n  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.5);"),
    "m3_weight600": ("web/css/tokens.css", "--weight-medium: 500;", "--weight-medium: 600;"),
    "m4_green_success": ("web/css/components.css", '.notice[data-kind="success"] { border-color: var(--color-line); color: var(--color-text-2); }', '.notice[data-kind="success"] { border-color: #2ecc71; color: #2ecc71; }'),
    "m5_refund_on_refund": ("web/js/refund-math.js", "p.to_user_id === me.user_id && !p.refund_of", "p.to_user_id === me.user_id"),
    "m6_no_busy_guard": ("web/js/writes.js", 'if (button.getAttribute("aria-busy") === "true") return undefined;', ""),
    "m7_new_key_each_retry": ("web/js/writes.js", "const key = scope ? tracker.attemptFor(scope, JSON.stringify(fingerprint)).key : undefined;", "const key = scope ? globalThis.crypto.randomUUID() : undefined;"),
    "m8_hidden_label": ("web/js/refund.js", 'h("label", { for: id("amount"), text: "Refund amount" })', 'h("label", { for: id("amount"), class: "vh", text: "Refund amount" })'),
    "m9_uncertain_as_error": ("web/js/outcome.js", "if (networkError) return 'uncertain';", "if (networkError) return 'refused';"),
    "m10_canvas_color": ("web/css/tokens.css", "--color-canvas: #030014;", "--color-canvas: #0a0a0a;"),
    "m11_stale_default": ("web/js/refund-math.js", "return Math.max(0, (current ?? original) - refunded);", "return Math.max(0, original - refunded);"),
}
os.makedirs(OUT, exist_ok=True)
for name, (rel, old, new) in MUT.items():
    dst = os.path.join(OUT, name)
    if os.path.exists(dst): shutil.rmtree(dst)
    shutil.copytree(SRC, dst)
    p = os.path.join(dst, rel)
    s = open(p, encoding="utf-8", newline="").read()
    if old not in s:
        s_n = s.replace("\r\n", "\n"); assert old in s_n, (name, "pattern not found")
        s = s_n
    open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new, 1))
    print("made", name)
