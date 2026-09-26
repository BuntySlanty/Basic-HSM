# Validation and installation handoff

Version: 0.2.0. Updated 26 September 2026 (Pakistan date).

## Verified in this delivery
- Python compilation completed successfully for all source and test modules.
- `python -m unittest discover -s tests -v`: **27 passed, 1 skipped**.
- Full run: 28 discovered tests.
- Environment: Windows, Python 3.14.7, SQLite 3.50.4.
- Synthetic test data only; no uploaded patient information copied into fixtures.

| Area | Automated result |
|---|---|
| Continuous shared receipt serials and separate doctor tokens | Passed |
| Receptionist per-visit charge without changing doctor default | Passed |
| Saved/custom procedure receipts with no doctor token | Passed |
| Shift report patient counts, doctor filter and printable text width | Passed |
| Version-1 backup migration preserves issued receipt numbers | Passed |
| Morning/evening continuity and next-day reset | Passed |
| Pakistan midnight with UTC clock input | Passed |
| Duplicate visit/payment requests and changed request rejection | Passed |
| Database error rollback after allocation/payment | Passed |
| App restart preserves IDs and sequence | Passed |
| Concurrent bookings produce unique tokens/serials | Passed |
| Patient/doctor/hospital receipt snapshots survive edits | Passed |
| Shared family phone numbers | Passed |
| Partial payments, refunds, and collections by payment date | Passed |
| Overpayment/over-refund rejection | Passed |
| Cancellation retains numbers and does not imply a refund | Passed |
| Admin/reception permissions, logged-out/disabled accounts | Passed |
| Password change and failed-login lockout | Passed |
| Inactive doctors and input validation | Passed |
| Backup integrity and restore with known number preservation | Passed |
| Invalid backup does not replace live records | Passed |
| Migration export includes stable IDs and excludes password hashes | Passed |
| Receipt wrapping at 58/80 mm column profiles | Passed |
| Failed non-Windows print call leaves visit intact | Passed |
| Single-instance lock and release | Passed on Linux |
| Desktop screen/receipt smoke test | Passed on Windows, including new screens |

## Not verified here
- Windows executable generation: build script supplied, no EXE included.
- Human review of Tkinter screen rendering, keyboard flow and display scaling.
- GDI printing with actual thermal and A4 printer drivers.
- Physical thermal paper width/length, cutting, clipping or printer-offline recovery.
- Actual reception PC RAM use, startup/search latency and supported OS architecture.
- Power-loss behaviour on actual hardware/storage; transactional rollback was
  simulated in tests, not tested by cutting power to a hospital computer.
- End-user acceptance or production deployment.

## Windows acceptance checklist
- [ ] Record Windows version, 32/64-bit architecture, RAM, screen resolution/scaling.
- [ ] Run source with synthetic data in a separate test data directory.
- [ ] Run the test suite; the UI smoke test should run on Windows, not skip.
- [ ] Build using `build-windows.cmd`; launch the packaged executable offline.
- [ ] Create admin and receptionist; verify allowed/denied actions for each.
- [ ] Register a patient, add a second doctor, save visits across both doctors.
- [ ] Repeat attendance for the same patient; verify patient ID stays fixed.
- [ ] Verify continuous serials, same-day shifts, next-day tokens with test data.
- [ ] Print with actual thermal hardware; check both numbers, long names, fees,
      address wrapping, paper feed, clipping and cut.
- [ ] Enter a one-off consultation charge as a receptionist; verify the receipt
      and that the doctor's saved default fee is unchanged.
- [ ] Print saved and custom procedure receipts; verify they have Sr. No. but no
      doctor token. Reprint from the Procedures screen.
- [ ] Set an A4 report printer, filter a shift by date and doctor, preview and
      print its complete patient list. Confirm totals and page breaks.
- [ ] Disconnect printer, save visit, reconnect and reprint the existing visit.
- [ ] Check pending Windows queue before reprint to avoid duplicate physical slips.
- [ ] Partial payment, later collection, cancellation and refund match totals.
- [ ] Restart PC and verify records and sequences.
- [ ] Back up to USB and restore a synthetic copy into a separate test directory.
- [ ] Verify dedicated Windows account, disk/backup access and storage protection.
- [ ] Clear only the separate synthetic data directory; never delete production data.
- [ ] Hospital receptionist approves the daily flow before real records are entered.

## Decision after acceptance
If these checks pass, package the tested build for this single PC. If Windows
compatibility or printer output fails, fix that specific adapter/layout before
production use. No claim of production readiness is made by the source package.
