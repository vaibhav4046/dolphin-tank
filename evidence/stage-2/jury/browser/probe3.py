from bl import *
reset(fixture())
bad = 0
with sync_playwright() as pw:
    br = launch(pw)
    for i in range(20):
        ctx = br.new_context(); page = ctx.new_page(); page.set_viewport_size({"width": 375, "height": 800})
        page.goto(BASE + "/signup")
        tid(page, "signup-email").fill("neo%d@example.com" % i); tid(page, "signup-password").fill("long enough pw"); tid(page, "signup-display-name").fill("Neo"); tid(page, "signup-submit").click()
        page.wait_for_selector('[data-testid="current-user"]')
        tid(page, "logout-button").click(); page.wait_for_timeout(100 + 40 * i)
        t0 = time.time(); page.goto(BASE + "/")
        try:
            page.wait_for_url("**/login", timeout=8000); dt = time.time() - t0
        except Exception:
            dt = None; bad += 1; shot(page, "stuck_%d" % i); print("STUCK", i, page.url, page.evaluate("localStorage.getItem('pocketful.token')"), page.inner_text("main")[:100])
        print(i, "redirect in", dt and round(dt, 2))
        ctx.close()
    br.close()
print("stuck:", bad)
