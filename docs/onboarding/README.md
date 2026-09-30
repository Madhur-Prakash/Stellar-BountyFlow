<div align="center">

# User onboarding

**The form that collects participant details, and the workbook the responses land in.**

[Readme](../../README.md) · [Documentation](../README.md) · [Product roadmap](../product-roadmap.md) · [Compliance](../compliance.md)

</div>

---

## What this covers

Two separate streams of evidence, deliberately kept apart because they are not the same thing:

| Stream | Where it comes from | Who it represents |
|---|---|---|
| **Google Form responses** | People who filled in the onboarding form | Anyone invited to try the platform, whether or not they created an account |
| **In-product feedback** | The feedback button inside the app, stored in the `feedback` table | People already using the platform, on the screen they were looking at |

Both end up in `bountyflow-onboarding.xlsx`, on their own sheets. Neither is ever merged into the other,
and neither is ever filled with invented rows.

---

## Building the form

The form has to be created under the maintainer's own Google account — it cannot be provisioned from the
repository. Create it at [forms.new](https://forms.new), title it **BountyFlow — user onboarding**, and add
these questions in order.

| # | Question | Type | Required | Validation |
|---|---|---|---|---|
| 1 | Your name | Short answer | Yes | — |
| 2 | Email | Short answer | Yes | Response validation → Text → Email address |
| 3 | Stellar wallet address | Short answer | Yes | Regex `^G[A-Z2-7]{55}$`, error text "A Stellar public key starts with G and is 56 characters." |
| 4 | How would you rate BountyFlow? | Linear scale 1–5 | Yes | Label 1 "Would not use", label 5 "Would use again" |
| 5 | What worked well? | Paragraph | No | — |
| 6 | What got in your way? | Paragraph | No | — |
| 7 | What should we build next? | Paragraph | No | — |

**Settings worth changing from the defaults**

| Setting | Value | Why |
|---|---|---|
| Collect email addresses | Off | Question 2 already asks, and the Google account address is often not the one they use here |
| Limit to 1 response | Off | It would force a Google sign-in, which excludes people who do not have one |
| Response receipts | Off | Nothing is promised in return |

Question 3 asks for a **public** key only. Nobody should ever be asked for a secret key or a seed phrase,
and the form must never include a field that invites one.

---

## Exporting the responses

In the form's **Responses** tab, use *Download responses (.csv)*, then build the workbook:

```bash
cd backend
uv run python -m app.scripts.export_onboarding --form-csv ~/Downloads/responses.csv
```

Without `--form-csv` the script still runs and writes everything it can read from the database; the form
sheet is then written with its headers and a note saying no export was supplied. That is deliberate — an
empty sheet is the honest state until real responses exist.

---

## What the workbook contains

| Sheet | Rows | Notes |
|---|---|---|
| **Summary** | One per measure | Account totals, wallet-verified count, feedback split by kind and handled state, and the export timestamp |
| **Participants** | One per active account | Name, username, email, role, verified Stellar address, whether they post or contribute, and when they joined |
| **In-product feedback** | One per note | Type, status, the message, who sent it, the page it came from, the viewport, and how it was resolved |
| **Form responses** | One per response | Exactly the columns the form exported, untouched |

---

## Handling it

The workbook contains personal data — names, email addresses and wallet addresses — so it carries the same
obligations as the database it came from. Keep it out of public places, and regenerate it rather than
passing an old copy around. See [compliance.md](../compliance.md) for the data-protection posture, and
[security.md](../security.md) for what the platform does and does not store.

The in-product feedback sheet **never contains an IP address**: the rate limiter keeps the client address in
Redis for an hour and nothing writes it to the database.
