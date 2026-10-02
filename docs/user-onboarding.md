# User onboarding: the feedback form and what happens to the answers

<!-- nav -->
[Documentation](README.md) &middot; [Readme](../README.md) &middot; [Compliance](compliance.md) &middot; [Security](security.md) &middot; [Roadmap](product-roadmap.md)
<!-- nav -->

BountyFlow collects onboarding details and product feedback through a Google Form. Responses land in a linked
Google Sheet, which is exported to `.xlsx` for analysis and record-keeping, and the themes that come out of it
set the next development phase.

- [Create the form](#create-the-form)
- [What the form asks](#what-the-form-asks)
- [Export the responses to Excel](#export-the-responses-to-excel)
- [Link it from the README](#link-it-from-the-readme)
- [Turning responses into the next phase](#turning-responses-into-the-next-phase)

## Create the form

The form lives in the Google account that owns it; it is not provisioned from this repository. Build it once
from the specification in [What the form asks](#what-the-form-asks) — that table is the source of truth, so
change it here in the same commit as any change to the form itself.

1. Open [forms.new](https://forms.new) signed in as the account that should own the form.
2. Title it **BountyFlow — user onboarding**, and add the nine questions in the order listed below, with the
   types and validation given.
3. Split it into two sections — *About you* (questions 1–4) and *How it went* (5–9) — so the wallet field is
   not the first thing a browser-only visitor is confronted with.
4. Under **Settings**, leave *Collect email addresses* and *Limit to 1 response* **off**. Question 2 already
   asks for an address, and requiring a sign-in would exclude anyone without a Google account.
5. In **Responses**, use *Link to Sheets* to create the responses spreadsheet.
6. **Send → link**, and turn on *Shorten URL* if you want a tidier link to share.

| Setting | Value | Why |
|---|---|---|
| Collect email addresses | Off | Question 2 asks, and the Google account address is often not the one they use here |
| Limit to 1 response | Off | It forces a Google sign-in |
| Response receipts | Off | Nothing is promised in return |

## What the form asks

Nine questions across two sections. The four required onboarding fields are name, email, wallet address and a
product rating; the rest exist because they make the answers actionable.

| # | Question | Type | Required |
|---|---|---|---|
| 1 | Full name | Short text | Yes |
| 2 | Email address | Short text, email validation | Yes |
| 3 | Stellar wallet address (public key) | Short text, `^G[A-Z2-7]{55}$` validation | Yes |
| 4 | How did you use BountyFlow? | Choice — requester / contributor / both / browsed | Yes |
| 5 | Overall rating | Scale 1–5, *Poor* → *Excellent* | Yes |
| 6 | Ease of connecting a wallet and moving money | Scale 1–5, *Confusing* → *Effortless* | Yes |
| 7 | Likelihood to recommend | Scale 0–10 | Yes |
| 8 | Kind of feedback | Choice — Bug / Idea / Praise / Other | Yes |
| 9 | What worked, what did not / one thing to change | Two paragraph fields | One of two |

Two details are deliberate:

- **The wallet field is pattern-validated.** A Stellar public key is 56 characters, starts with `G`, and uses the
  base32 alphabet. Validating at submission time keeps unusable addresses out of the sheet, so a testnet reward
  for completing onboarding can be paid straight from the export.
- **Question 8 reuses the in-product categories.** `Bug`, `Idea`, `Praise` and `Other` are exactly the kinds the
  in-app feedback widget sends (`FEEDBACK_KIND_LABELS` in
  [`frontend/src/lib/format.ts`](../frontend/src/lib/format.ts)), so form responses and in-app feedback can be
  triaged in one queue instead of two.

The form asks for a **public key only**. The help text says so, and no question ever asks for a secret key or a
recovery phrase — BountyFlow is non-custodial and nothing about it needs one. See [security.md](security.md).

## Export the responses to Excel

The committed record is a single workbook,
[`docs/onboarding/bountyflow-onboarding.xlsx`](onboarding/bountyflow-onboarding.xlsx), taken straight from the
responses Sheet.

1. Open the responses Sheet.
2. **File → Download → Microsoft Excel (.xlsx)**.
3. Save it over `docs/onboarding/bountyflow-onboarding.xlsx` and commit it.

Or hit the export URL directly — replace `SPREADSHEET_ID` with the id from the Sheet's own URL:

```
https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/export?format=xlsx
```

Re-export whenever a meaningful batch of responses lands. Committing the workbook means the record survives
independently of the Google account that owns the Sheet.

In-product feedback is a **separate** stream and is not merged into this file: it lives in the `bountyflow_feedback`
table and is triaged in the admin console at `/admin/feedback`. Form answers and in-app notes use the same
four categories, so they can be read together without being mixed into one sheet, where it would stop being
clear which evidence came from where.

> Responses contain email addresses. Keep the Sheet itself restricted (do **not** share it as *Anyone with the
> link*), and before committing an export, confirm you are willing to publish those rows — a committed file is
> public forever, even if deleted later.

## Link it from the README

The README's [User onboarding & feedback](../README.md#user-onboarding--feedback) section carries three links:
the live form, the responses Sheet, and the committed `.xlsx`. Fill in the two Google URLs there after the first
run of the script — they are the only values that cannot be known until the form exists.

## Turning responses into the next phase

The loop is: collect → group → ship → link the commit.

1. **Group by theme, not by response.** Ten people describing the same confusing step is one problem, not ten.
2. **Weigh the scales against the prose.** Question 6 scoring low while question 5 scores high means the product
   is wanted but the money path is hard — that ordering decides what gets built first.
3. **Only two things make the next phase**: a theme that appears across several responses, or a single response
   describing something actually broken.
4. **Every shipped item gets its commit linked** in the README's improvement table, so a reader can go from a
   piece of feedback to the diff that answered it.
