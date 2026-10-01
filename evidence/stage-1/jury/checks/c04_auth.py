"""J18, J19, J39-J41: signup/login, handle derivation, handle_taken leaves no account, bearer rules, signup races."""
from lib import *

t = setup(fx())
ADA = t["ada"]
cases = [("John.Doe+Test@Example.com", "john_doe_test"), ("UPPER@x.com", "upper"), ("a-b.c@x.com", "a_b_c"), ("x" * 25 + "@x.com", "x" * 20),
         ("é@x.com", "_"), ("éé@x.com", "__"), ("\U0001F600a@x.com", "_a"), ("a" * 19 + "éé@x.com", "a" * 19 + "_"),
         ("12_ab@x.com", "12_ab"), ("Zed_9@x.com", "zed_9")]
toks = {}
for em, h in cases:
    r = call("POST", "/auth/signup", {"email": em, "password": "password1", "display_name": "N"})
    ok("signup %r -> 201 {user_id,display_name,token}" % em, r.s == 201 and set(r.j) >= {"user_id", "display_name", "token"} and r.j["display_name"] == "N", r)
    if r.s != 201:
        continue
    toks[h] = r.j["token"]
    p = call("POST", "/payments", {"to_handle": h, "amount": 7}, token=ADA, key=k())
    ok("derived handle %r for %r resolves; new user id matches" % (h, em), p.s == 201 and p.j["to_handle"] == h and p.j["to_user_id"] == r.j["user_id"], p)
    m = me(r.j["token"])
    ok("  /me handle=%r balance=7 after receive, fields exact" % h, m["handle"] == h and m["balance"] == 7 and set(m) == {"user_id", "display_name", "handle", "balance", "currency", "minor_units"} and m["currency"] == "EUR" and m["minor_units"] == 2, m)

# new user balance 0, can be asked for money immediately
r = call("POST", "/auth/signup", {"email": "newbie@x.com", "password": "password1", "display_name": "Nb"})
nt = r.j["token"]
ok("new user balance 0", bal(nt) == 0)
rq = call("POST", "/requests", {"payer_handle": "newbie", "amount": 500}, token=ADA, key=k())
ok("new user can be asked for money immediately (request pending)", rq.s == 201 and rq.j["payer_handle"] == "newbie" and rq.j["status"] == "pending", rq)
rq2 = call("POST", "/requests", {"payer_handle": "ada", "amount": 500}, token=nt, key=k())
ok("new user can ask", rq2.s == 201)
pr = call("POST", "/requests/%s/pay" % rq.j["request_id"], {}, token=nt, key=k())
ok("new user (balance 0) pay 500 -> 409 insufficient_funds, state unchanged", pr.s == 409 and pr.code == "insufficient_funds" and bal(nt) == 0)

# handle_taken leaves no account
before_users = call("GET", "/me", token=ADA).j
for em in ("ada@other.com", "ADA@other.com", "ada@third.org"):
    r = call("POST", "/auth/signup", {"email": em, "password": "password1", "display_name": "X"})
    ok("signup %s (derived handle 'ada' taken) -> 409 handle_taken" % em, r.s == 409 and r.code == "handle_taken", r)
    l = call("POST", "/auth/login", {"email": em, "password": "password1"})
    ok("  no account created: login %s -> 401" % em, l.s == 401 and l.code == "unauthenticated", l)
r = call("POST", "/auth/signup", {"email": "ada@other.com", "password": "password1", "display_name": "X"})
ok("  retry still handle_taken (not email_taken)", r.s == 409 and r.code == "handle_taken", r)
r = call("POST", "/auth/signup", {"email": "ada_other@other.com", "password": "password1", "display_name": "X"})
ok("  a free derived handle with the same domain succeeds", r.s == 201, r)
# truncation collision
r = call("POST", "/auth/signup", {"email": "x" * 26 + "@y.com", "password": "password1", "display_name": "X"})
ok("truncated-20 handle collision -> 409 handle_taken", r.s == 409 and r.code == "handle_taken", r)
# email_taken
r = call("POST", "/auth/signup", {"email": "John.Doe+Test@Example.com", "password": "password1", "display_name": "X"})
print("OBS re-signup same email (email+handle both taken) ->", r.s, r.code)
ok("re-signup same email -> 409 (email_taken or handle_taken)", r.s == 409 and r.code in ("email_taken", "handle_taken"), r)
r = call("POST", "/auth/signup", {"email": "ada@example.com", "password": "password1", "display_name": "X"})
print("OBS signup seeded email ->", r.s, r.code)
ok("signup seeded email -> 409 email_taken", r.s == 409 and r.code == "email_taken", r)
r = call("POST", "/auth/signup", {"email": "Ada@Example.com", "password": "password1", "display_name": "X"})
print("OBS signup seeded email different case ->", r.s, r.code)

# password / email validation
for pw, want in (("1234567", 422), ("12345678", 201), ("é" * 7, 422), ("é" * 8, 201)):
    r = call("POST", "/auth/signup", {"email": "pw%d_%d_%d@x.com" % (len(pw), want, len(pw.encode())), "password": pw, "display_name": "P"})
    ok("password %d chars (bytes %d) -> %d" % (len(pw), len(pw.encode()), want), r.s == want and (want == 201 or r.code == "validation_failed"), r)
for em in ("noatsign", "@b.com", "a@", "", " "):
    r = call("POST", "/auth/signup", {"email": em, "password": "password1", "display_name": "P"})
    ok("signup invalid email %r -> 422" % em, r.s == 422 and r.code == "validation_failed", r)
r = call("POST", "/auth/signup", {"email": "tl@x.com", "display_name": "P"})
ok("signup password missing -> 422", r.s == 422 and r.code == "validation_failed", r)
r = call("POST", "/auth/signup", {"email": 5, "password": "password1", "display_name": "P"})
ok("signup email number -> 400 malformed_request", r.s == 400 and r.code == "malformed_request", r)
r = call("POST", "/auth/signup", raw="{bad")
ok("signup bad json -> 400", r.s == 400 and r.code == "malformed_request", r)
r = call("POST", "/auth/signup", {"email": "nodn@x.com", "password": "password1"})
print("OBS signup without display_name ->", r.s, r.code)

# login
r = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
ok("login seeded user 200 {user_id,display_name,token}", r.s == 200 and r.j["user_id"] == "u_ada" and r.j["display_name"] == "Ada" and r.j["token"], r)
r2 = call("POST", "/auth/login", {"email": "ada@example.com", "password": "correct horse"})
ok("two logins give two valid concurrent tokens; earlier token & fixture token remain valid", r2.j["token"] != r.j["token"] and all(call("GET", "/me", token=x).s == 200 for x in (ADA, r.j["token"], r2.j["token"])))
for nm, body, st, code in (("wrong pw", {"email": "ada@example.com", "password": "nope nope"}, 401, "unauthenticated"),
                           ("unknown email", {"email": "ghost@example.com", "password": "correct horse"}, 401, "unauthenticated"),
                           ("pw case", {"email": "ada@example.com", "password": "Correct Horse"}, 401, "unauthenticated"),
                           ("wrong type", {"email": 5, "password": "x"}, 400, "malformed_request")):
    r = call("POST", "/auth/login", body)
    ok("login %s -> %d" % (nm, st), r.s == st and r.code == code, r)
r = call("POST", "/auth/login", {"email": "ada@example.com"})
print("OBS login missing password ->", r.s, r.code)
ok("login missing password -> 401 or 422", r.s in (401, 422), r)
r = call("POST", "/auth/login", {"email": "John.Doe+Test@Example.com", "password": "password1"})
ok("signup-created user can log in", r.s == 200 and r.j["token"], r)

# bearer rules
for nm, h in (("no header", None), ("Bearer only", "Bearer"), ("Bearer empty", "Bearer "), ("unknown token", "Bearer nope"),
              ("Basic scheme", "Basic " + ADA), ("token without scheme", ADA), ("token + junk", "Bearer " + ADA + "x")):
    r = call("GET", "/me", hdrs={"Authorization": h} if h else None)
    ok("/me with %s -> 401 unauthenticated" % nm, r.s == 401 and r.code == "unauthenticated", r)
r = call("GET", "/me", hdrs={"Authorization": "bearer " + ADA})
print("OBS lowercase 'bearer' scheme ->", r.s)
need_auth = [("GET", "/me", None), ("GET", "/activity", None), ("GET", "/requests", None), ("POST", "/payments", {}), ("POST", "/requests", {}),
             ("POST", "/splits", {}), ("POST", "/settlements", {}), ("POST", "/requests/x/pay", {}), ("POST", "/requests/x/decline", {}), ("POST", "/requests/x/cancel", {})]
for m, p, b in need_auth:
    r = call(m, p, b, key=k())
    ok("%s %s without token -> 401" % (m, p), r.s == 401 and r.code == "unauthenticated", r)
ok("/health, reset, export need no auth", call("GET", "/health").s == 200 and call("GET", "/_test/export").s == 200)

# races: same email x10, same derived handle x10
res = parallel([lambda: call("POST", "/auth/signup", {"email": "race@x.com", "password": "password1", "display_name": "R"}) for _ in range(10)])
c = sorted(r.s for r in res)
ok("race: same email x10 -> exactly one 201, rest 409", c.count(201) == 1 and c.count(409) == 9, c)
res = parallel([lambda i=i: call("POST", "/auth/signup", {"email": "same@d%d.com" % i, "password": "password1", "display_name": "R"}) for i in range(10)])
c = [r.s for r in res]
ok("race: 10 emails same derived handle 'same' -> exactly one 201, rest 409 handle_taken", c.count(201) == 1 and all(r.s == 201 or (r.s == 409 and r.code == "handle_taken") for r in res), [(r.s, r.code) for r in res])
winner = [i for i, r in enumerate(res) if r.s == 201][0]
logins = [call("POST", "/auth/login", {"email": "same@d%d.com" % i, "password": "password1"}).s for i in range(10)]
ok("race: only the winner's account exists (login 200 for winner, 401 for losers)", logins[winner] == 200 and logins.count(401) == 9, logins)
pay = call("POST", "/payments", {"to_handle": "same", "amount": 1}, token=ADA, key=k())
ok("race: handle 'same' resolves to winner", pay.s == 201 and pay.j["to_user_id"] == res[winner].j["user_id"], pay)
ok("conservation after signups/payments (sum of all seeded + new == 17500)", bal(ADA) + bal(t["bob"]) + bal(t["cy"]) + bal(t["dee"]) + sum(bal(x) for x in toks.values()) + bal(nt) + 1 == 17500, None)

done("c04_auth")
