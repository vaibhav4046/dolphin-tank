from bl import *
reset(fixture())
with sync_playwright() as pw:
    br = launch(pw); ctx = br.new_context(); page = ctx.new_page(); page.set_viewport_size({"width": 375, "height": 800})
    ui_login(page, "ada@example.com")
    print("signed in url", page.url, "token stored:", bool(page.evaluate("localStorage.getItem('pocketful.token')")))
    tid(page, "logout-button").click(); page.wait_for_timeout(800)
    print("after logout url", page.url, "token stored:", page.evaluate("localStorage.getItem('pocketful.token')"))
    page.goto(BASE + "/"); page.wait_for_timeout(1500)
    print("goto / ->", page.url, "current-user count", tid(page, "current-user").count(), "login form", tid(page, "login-email").count())
    print(page.inner_text("main")[:200].replace("\n", " / "))
    shot(page, "after_logout_root")
    # fresh signup user then logout then /
    page.goto(BASE + "/signup"); page.wait_for_timeout(300)
    tid(page, "signup-email").fill("neo2@example.com"); tid(page, "signup-password").fill("long enough pw"); tid(page, "signup-display-name").fill("Neo"); tid(page, "signup-submit").click()
    page.wait_for_selector('[data-testid="current-user"]'); 
    print("signup url", page.url)
    tid(page, "logout-button").click(); page.wait_for_timeout(800)
    print("after logout url", page.url, "token:", page.evaluate("localStorage.getItem('pocketful.token')"))
    page.goto(BASE + "/"); page.wait_for_timeout(1500)
    print("goto / ->", page.url, "current-user", tid(page, "current-user").count(), "login form", tid(page, "login-email").count())
    br.close()
