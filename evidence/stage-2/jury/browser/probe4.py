from bl import *
reset(fixture(requests=[{"id": "rq_in1", "requester_id": "u_bob", "payer_id": "u_ada", "amount": 1200, "note": "taxi", "status": "pending"}]))
T = tok("ada@example.com")
with sync_playwright() as pw:
    br = launch(pw); ctx = br.new_context(); seeded_page(ctx, T); page = ctx.new_page(); page.set_viewport_size({"width": 375, "height": 900})
    page.goto(BASE + "/requests"); page.wait_for_selector('[data-testid="incoming-list"]'); page.wait_for_timeout(500)
    for t in ("incoming-list", "outgoing-list", "empty-requests", "request-error"):
        print(t, tid(page, t).count())
    print(page.eval_on_selector_all("[data-testid]", "els => els.map(e => e.getAttribute('data-testid'))")[:30])
    br.close()
