# Furqan Hospital Reception — version 0.3

Status: version 0.3 source implementation complete; automated test history is
recorded in the validation handoff; target printer acceptance remains pending.

## Purpose
A small offline reception application for one low-spec Windows computer while
the full HMS is developed. Register patients, maintain doctors, record each
attendance, collect consultation fees, print thermal slips, and find daily history.

## Confirmed requirements
- Local persistent patient and doctor records; no internet needed for normal use.
- Every attendance creates a new visit; returning patients retain their patient ID.
- Sr. No. is one increasing series for the whole system, starting at 1. Never
  reset it daily or by doctor. Cancelled numbers are retained and never reused.
- Token No. is allocated per doctor and calendar date in Pakistan (UTC+05:00).
  A second shift on the same day continues the sequence. A new date starts at 1.
- Consultation slips show Sr. No. and Token No.; procedure slips show Sr. No. only.
  Reprinting does not allocate numbers.
- Consultation and procedure slips record the signed-in receptionist. Patient
  records retain the receptionist who first registered them.
- Consultation fees, payments, receipts, daily records, and thermal printing.
- Reference layout: hospital name/address, date/day, doctor/department, patient
  name/age/sex/phone/address, fee, and footer, with both numbering fields added.

## Explicit implementation defaults
These keep development moving and may be changed after the first demonstration.
- One standalone workstation; no LAN access, cloud sync, or doctor login.
- Native Python 3.12+ / Tkinter UI and SQLite database. No third-party runtime
  Python packages; optional PyInstaller is used only to build a Windows executable.
- Consultation billing and paid-in-full procedure fee receipts. Clinical procedure
  records, lab/pharmacy ordering, and admissions are outside this release.
- PKR stored as integer paisa; fees shown with two decimal places.
- Cash, card, bank transfer, and other payment methods; partial payments supported.
- Admin controls doctors' default fees, discounts, refunds, restore, staff and
  settings. Reception can change the charge for one visit and issue procedure
  receipts, while also controlling registration, collections and reprints.
- Age is reported as whole years/months/days, captured at the visit. No fabricated DOB.
- English interface/receipt. Correct footer: “Your health is our priority.”
- Configurable 58/80 mm receipt layout; Windows-installed printer selected by name.
  Exact hardware/driver/paper length and cutting require an on-site print test.
- No automatic clinical completion workflow. A visit is recorded or cancelled.
- A daily summary is a report, not a locked accounting close or cash-drawer system.

## Screens and workflow
1. First run: create the admin account (no default password).
2. Login: staff authenticate; inactivity locks the app after 10 minutes.
3. Reception: search patient by ID/name/phone; register or edit; select doctor;
   review age and set this visit's fee; enter payment; save and print. New visits require a fresh
   explicit action. A repeated save uses the same request key.
4. Register: filter date range/doctor; inspect visits, reprint, collect balance,
   cancel with reason, or admin-refund. See gross collections, refunds and net
   collections by payment date/method, plus current balances for selected visits.
5. Patients: search and edit demographics; open all historical visits.
6. Doctors: admin creates/edits fees and specialties and deactivates doctors.
7. Procedures: issue a patient receipt using a saved or custom procedure name and
   fee, optionally saving the name for reuse. No doctor token is allocated.
8. Shift report: filter consultation visits by date and doctor, see visit and
   distinct-patient counts per doctor, and print the patient list on an A4 printer.
   The all-doctor report includes procedure receipts separately.
9. Settings: hospital details, thermal/report printer names, user creation, backup/restore,
   structured export, password changes, and audit log viewing.

## Data model
| Table | Purpose and key constraints |
|---|---|
| users | Unique username, salted PBKDF2 hash, role, enabled flag, failed-login lock |
| patients | Internal UUID and increasing display ID; demographics; phone not unique; registering staff account |
| doctors | UUID, name, department, default fee, active flag |
| receipt_counter | Shared increasing Sr. No. for visits and procedure receipts |
| visits | Sr. No.; UUID; patient/doctor links; Pakistan date; token; charged fee/discount; immutable receipt snapshot including receptionist; unique request key; cancellation |
| procedures | Reusable procedure names and default fees |
| procedure_receipts | Sr. No.; patient, procedure, fee, method, date, receptionist, and immutable receipt snapshot |
| token_counters | Primary key (doctor_id, visit_date), next token allocated transactionally |
| payments | UUID, visit link, signed amount, payment method/date, reason, actor; unique request key |
| audit_log | Actor, time, action, entity reference; append-only through app |
| settings | Hospital and printer settings, schema version |

Visits enforce UNIQUE(doctor_id, visit_date, token). Create visit, allocate token,
save initial payment and audit in one transaction. Monetary changes use a ledger;
never overwrite or delete an existing payment. Refunds cannot exceed the net
received amount. Cancellation removes the receivable but does not itself refund.
Payments on cancelled visits are disallowed; refunds remain possible.

## Validation and historical correctness
- Required patient name and age/unit; optional contact/address/guardian.
- Same phone may belong to multiple patients. Search before registering.
- Nonnegative bounded amounts, maximum two decimal places. Discount requires a
  reason and admin permission; payment cannot exceed the remaining balance.
- Doctor must be active at booking. No backdated visits in this release.
- Doctor/patient details, hospital header and age are snapshotted for the visit.
  Later edits never silently rewrite historical slips. Payment/refund totals and
  cancellation markers reflect the current ledger at reprint time.
- Allocated numbers must survive restart; no reset-number feature.
- A saved visit survives a print failure. “Submitted to printer” does not confirm
  physical printing. Reprint from the register if the printer is offline/out of paper.
- Use stable UUIDs in exports so a later HMS import can map IDs safely.

## Storage, backup, restore and security
- Windows data: %LOCALAPPDATA%\FurqanReception\reception.sqlite3, outside app files.
- One running app per data directory; SQLite foreign keys, WAL, FULL synchronous,
  explicit transactions and busy timeout. No network-shared database file.
- SQLite online backup API; backup on login/start of a working day, after writes
  at most hourly, and on clean exit. Backups are integrity-checked. Keep copies;
  this version does not silently prune them. Show backup errors to the user.
- Admin can save backup to USB. Same-disk backups do not protect from disk failure.
- Restore requires current admin authentication, validates schema/integrity,
  saves a pre-restore backup and requires restarting. Restoration rolls data back:
  visits created after the backup will be absent. Restore carries forward known
  serial/patient counters and tokens from the current live DB to avoid reuse.
  If the live DB was lost, reconcile numbers issued since the backup before
  resuming; do not restore casually to fix an ordinary error.
- App access control is enforced in service methods as well as UI. Passwords use
  per-user salts; account lock after repeated failed attempts; no network service.
- Local DB and backup files are not application-encrypted. A Windows account with
  file access can bypass app roles. Use a dedicated Windows account, appropriate
  disk encryption/access controls, and controlled USB custody before real use.
- Do not enter real patient data into development/demo builds or test fixtures.

## Delivery gates
Automated: serial/token numbering including midnight and second shifts, atomic
rollback, duplicate submission, balances/refunds, permissions, receipt snapshots,
backup integrity/restore and concurrent numbering. Tests use synthetic patients.

Windows acceptance (must pass before real hospital use):
1. Build/run on actual Windows version/architecture; record RAM and startup time.
2. Register -> payment -> receipt -> search -> reprint entirely offline.
3. Print long names/addresses on actual thermal printer, both width profiles if
   used; configure driver paper length, no clipping/extra pages, verify cut.
4. Unplug printer; saved visit remains and reprint works after reconnection.
5. Restart app/PC; confirm records and numbering persist.
6. Restore a synthetic backup into a separate test data directory; verify totals.
7. Reception can change a single visit's charge and issue procedure receipts,
   but cannot change doctor defaults, discount, refund, restore or manage staff.
8. Verify local time/date, midnight token rollover, and separate doctor queues.
9. Check 1024x768 display with Windows scaling and keyboard-only normal entry.

## Out of scope
Clinical records, prescriptions, laboratory workflow, pharmacy, admissions,
insurance, payroll, doctor commissions, multi-PC sync, online booking, automatic
updates and the full HMS. This release supplies a consultation register, payment
ledger and procedure fee receipts, not a full financial accounting system.

## Build sequence
1. Lock this spec and schema.
2. Implement database/service rules and tests.
3. Implement reception, registers, accounts and settings UI.
4. Add thermal formatting and Windows print adapter.
5. Package source, Windows build instructions and validation results.
6. Build and validate on the hospital PC before production use.

## References
- Python SQLite: https://docs.python.org/3/library/sqlite3.html
- Tkinter: https://docs.python.org/3/library/tkinter.html
- Microsoft GDI printing: https://learn.microsoft.com/en-us/windows/win32/printdocs/how-to--print-using-the-gdi-print-api
