from bl import *
reset(fixture())
with sync_playwright() as pw:
    br = launch(pw); ctx = br.new_context(); page = ctx.new_page(); page.set_viewport_size({"width": 375, "height": 800})
    for r in ("/", "/requests", "/split", "/authorizations"):
        page.goto(BASE + r); page.wait_for_timeout(800)
        print(r, "->", page.url, "| login form:", tid(page, "login-email").count(), "| text:", page.inner_text("main")[:120].replace("\n", " / "))
    shot(page, "signedout_root")
    br.close()
