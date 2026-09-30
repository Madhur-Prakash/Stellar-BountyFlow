# User onboarding: the feedback form and what happens to the answers

BountyFlow collects onboarding details and product feedback through a Google Form. Responses land in a linked
Google Sheet, which is exported to `.xlsx` for analysis and record-keeping, and the themes that come out of it
set the next development phase.

- [Create the form](#create-the-form)
- [What the form asks](#what-the-form-asks)
- [Export the responses to Excel](#export-the-responses-to-excel)
- [Link it from the README](#link-it-from-the-readme)
- [Turning responses into the next phase](#turning-responses-into-the-next-phase)

## Create the form

The form is defined as code in
[`scripts/google-form/create-onboarding-form.gs`](../scripts/google-form/create-onboarding-form.gs) so that it is
reviewable and reproducible rather than click-assembled.

1. Open [script.google.com](https://script.google.com) signed in as the account that should own the form, and
   create a **New project**.
2. Replace the contents of `Code.gs` with the script, and save.
3. Pick `createBountyFlowOnboardingForm` in the function dropdown, then **Run**.
4. Approve the Forms/Drive authorisation prompt the first time. It is your own account creating a form and a
   sheet in your own Drive — no data leaves it.
5. Open **Execution log**. It prints four URLs:

   | Line | What it is |
   |---|---|
   | `Live form` | The public URL to share with users |
   | `Edit the form` | The Forms editor, for later wording changes |
   | `Responses spreadsheet` | The Sheet every submission is appended to |
   | `Download as .xlsx` | A direct Excel export of that Sheet |

6. In the Forms editor, **Send → link** and turn on **Shorten URL** if you want a tidier link to share.

Running the script again creates a *second*, independent form. Once responses exist, change wording in the Forms
editor instead of re-running — and mirror the change back into the `.gs` file so the two do not drift.

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
[`docs/onboarding/bountyflow-onboarding.xlsx`](onboarding/bountyflow-onboarding.xlsx), built by
`backend/app/scripts/export_onboarding.py`. It keeps form responses and in-product feedback on separate sheets,
because they are not the same evidence, and adds a participant sheet from the database.

1. In the responses Sheet: **File → Download → Comma-separated values (.csv)**.
2. From `backend/`, merge that export with the in-product feedback:

   ```bash
   uv run python -m app.scripts.export_onboarding --form-csv ~/Downloads/responses.csv
   ```

   Without `--form-csv` the form sheet is written with headers and a note saying no export was supplied —
   nothing is invented to fill it.
3. Commit the resulting workbook, and re-run it whenever a meaningful batch of responses lands.

For the raw Sheet on its own, without the merge, use **File → Download → Microsoft Excel (.xlsx)** or hit the
export URL the Apps Script prints — replace `SPREADSHEET_ID` with the id from the Sheet's own URL:

```
https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/export?format=xlsx
```

Committing the workbook means the record survives independently of the Google account that owns the Sheet.

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
