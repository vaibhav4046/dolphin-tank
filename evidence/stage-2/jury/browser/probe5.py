from bl import *
def run(label, requests):
    reset(fixture(requests=requests)); T = tok("ada@example.com")
    with sync_playwright() as pw:
        br = launch(pw); ctx = br.new_context(); seeded_page(ctx, T); page = ctx.new_page(); page.set_viewport_size({"width": 1280, "height": 900})
        page.goto(BASE + "/requests"); page.wait_for_selector('[data-testid="incoming-list"]'); page.wait_for_timeout(500)
        e = tid(page, "empty-requests")
        print(label, "| empty-requests count", e.count(), "visible", e.is_visible() if e.count() else None, "text:", (e.inner_text() if e.count() else "")[:80].replace("\n", " "), "| parent:", e.evaluate("e => e.parentElement.outerHTML.slice(0,160)") if e.count() else "")
        shot(page, "requests_partial_" + label)
        br.close()
inc = {"id": "rq_in1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}
out = {"id": "rq_out1", "requester_id": "u_ada", "payer_id": "u_cy", "amount": 450, "note": "snacks", "status": "pending"}
run("only_incoming", [inc]); run("only_outgoing", [out]); run("both", [inc, out]); run("none", [])
