# Demo script — four minutes

One command to start: `.\run.ps1 demo` (Windows) or `make demo`. It checks the
artifacts, boots the API, waits until it actually answers, starts the frontend
and opens the browser. Do not start the two servers by hand on stage.

**Before you begin.** Browser at 1366×768 or larger. Console tab closed. The
case defaults to **S1 — Digital arrest, ₹15,00,000, reported after 42 minutes**,
the harm limit defaults to **B = 0.25**, and the policy defaults to
**Chakravyuh**. Nothing needs setting up.

---

## 0:00 — The case

> "An Indian citizen was defrauded of fifteen lakh rupees in a digital arrest
> scam. She reported it 42 minutes later. That delay is the whole problem: the
> money is already three layers deep."

Point at the case docket: case number, complaint reference, reporting bank, and
the **golden-hour meter** reading `T+42 · 48 min of recoverable window
remaining`. The window closes at 90 minutes because that is when this money
typically leaves the banking system.

> "Banks today freeze the one account the victim can name. Watch what that gets
> you."

## 0:45 — Run it

Press **Run interdiction**. The solve takes about a second; the replay runs six
simulated hours in about thirty.

While it plays:

> "Fourteen freeze instructions, ordered, each with a time it goes out. The
> ordering matters — instruction fourteen lands minutes after instruction one
> and intercepts strictly less. The solver picks each next freeze knowing when
> that freeze would actually take effect."

When the ledger settles: **₹8,25,778 saved against ₹2,32,866** for current
practice, at **zero innocent accounts frozen**.

## 1:30 — The harm limit

Drag the harm limit from **0.25** down to **0.05**, then up to **0.50**. Watch
the composition line under the slider, not the count:

| B | Plan | What it issues |
|---|---|---|
| 0.05 | 18 | 18 × step-up verification |
| 0.25 | 14 | 13 freezes + 1 hold |
| 0.50 | 25 | 25 full freezes |

> "This is the answer to 'what if your classifier is wrong'. Tighten the harm
> limit and the plan does not just get shorter — it gets *gentler*. Step-up
> verification instead of a freeze. And gentler actions are genuinely less
> effective, 0.55 against 0.98, so this is a real trade-off, not a free win."

Leave it at **0.25**. Run again.

## 2:15 — Same case, different planner

Switch the policy to **Top-K classifier** and run. Then **Current practice**.
The comparison strip under the canvas keeps every result on this case.

> "Same case. Same detector scores — top-K is reading the identical model
> output. It spends all twenty-five freezes and still loses more money.
> Detection is an input to this problem, not the answer to it."

If you have a spare fifteen seconds, run **One hop downstream** too — it is the
policy that later produces instructions the model believes are innocent.

Switch back to **Chakravyuh** and run.

## 3:00 — The fraudster fights back

Tick **Fraudster fights back** and run.

> "That assumes the operator reroutes the money when we block a path, instead
> of giving up."

Recovery drops from about **40% to about 26%**, and the caption under our own
column says so: `10 transfers rerouted · recovery 40% → 26%`.

> "We report that next to the good number, because assuming a passive adversary
> is the most flattering assumption available and it should not pass unstated."

Untick it and run once more before the next beat.

## 3:30 — The signed order

Press **Generate freeze orders**.

> "A real Cyber Fraud Mitigation Centre does not show a list on a screen. It
> issues an instruction to each holding bank — and it is a different
> instruction to each of the seven banks here, because each one can only act on
> its own accounts."

Expand a bank panel. Point at the **justification column**:

> "Every instruction carries the reason in plain English. 'Why was my customer's
> account frozen' is the first question a bank asks, and almost no fraud system
> answers it in the document itself."

Press **Download all instructions (PDF)**. Open it.

> "Formal memorandum, grouped by bank, masked account identifiers, a
> countersignature block, and the non-affiliation notice on every page. And it
> is byte-identical: download it twice with the same inputs and you get the same
> file, because the timestamp comes from the case rather than the clock."

**If a demo needs the four-eyes gate:** switch the policy to **One hop
downstream** first. That policy produces instructions the detector scores at
0.00 — they are held with `REQUIRES SECOND APPROVAL`, and the download is
disabled until each is approved or waived with a typed reason.

> "The system flags which of its own recommendations are shaky. Chakravyuh's
> plan here needs no second signature. The naive policy's does, on three of its
> twelve instructions, because it is freezing people the model says are
> innocent."

---

## The eight judge questions

| Question | Where you point |
|---|---|
| Isn't this just MuleHunter.AI? | Policy switcher. Both Chakravyuh and top-K read the *same* detector scores. Detection is an input. |
| How many innocent people did you freeze? | Ledger inset, headline on both sides. 5 vs 148 across the benchmark. |
| What if the classifier is wrong? | Harm-limit slider — the composition changes, not just the count. Then the four-eyes gate on the order. |
| Is your data real? | Data Provenance tab + `simulator/README.md`. Synthetic, calibrated, hard-negative contrast printed. |
| Does it run fast enough? | Solver line in the left rail (~300 ms here), p50/p95 on Benchmark & Assurance. |
| How do you know greedy is good enough? | Benchmark → measured CP-SAT gap 0.03% against the (1−1/e) bound of 36.8%. |
| Why would banks share data? | Deployment path in the README. Secure aggregation needs topology and timing, never identity. |
| What's the single most important variable? | Benchmark → recovery-vs-delay curve, and the golden-hour meter on every case. |

## Things worth saying out loud

- **"Two commands, no keys, runs air-gapped."** No Docker, no cloud, no auth, no
  LLM. Anyone who has worked in a bank knows what that is worth.
- **"38% is not a production claim."** The data is synthetic and calibrated, not
  validated. The method is the claim; the Limitations section lists six things
  that are wrong with it, and we would rather state them than have you find one.
- **"Nothing here is affiliated with RBI or I4C."** It is what such a console
  would look like. That is a stronger position than pretending to be one.

## If something breaks

- **Backend not answering** — every route shows the exact command to run rather
  than an empty chart. `cd backend && uvicorn app.main:app --port 8000`.
- **No data** — `.\run.ps1 all` regenerates everything in about four minutes.
- **The replay looks stuck** — it is server-paced at 12 fps over six simulated
  hours, so a full run is about thirty seconds. The timeline shows `replaying`.
- **Empty plan on S2 or S6** — expected at B = 0.25. Those cases need a looser
  harm limit before the solver considers anything worth doing. Raise B to 0.5.
