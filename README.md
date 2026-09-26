# Furqan Hospital Reception

**Version 0.4.0 — functional source build for Windows acceptance testing.**

Offline patient/doctor records, visits, continuous serial numbers, doctor-specific
daily tokens, per-visit fees, procedure receipts, fee collection, thermal receipts,
patient history, printable shift reports, refunds, staff accounts, backups and
structured export. Consultation and procedure slips identify the logged-in
receptionist by full name and unique username; the Patients screen shows who registered each patient.

Documentation is in `docs/RECEPTION_SPEC.md`; implementation is in `reception/`.

## Fast start on your Windows development PC
1. Extract this entire folder.
2. Install Python 3.12+ with Tcl/Tk and the Windows `py` launcher.
3. Double-click `run-windows.cmd`, or run `py -3 run.py` in this folder.
4. Create an admin full name, username and password; there are no default credentials.
5. Add a doctor, register a synthetic patient and save a test visit.

For a separate test database, run:

```powershell
py -3 run.py --data-dir .\test-data
```

The normal database lives in `%LOCALAPPDATA%\FurqanReception\reception.sqlite3`.
Deleting or replacing the app folder does not delete that database. Use one
Windows account for this installation; staff log in separately inside the app.
Do not put the database on a network share or a cloud-synchronised folder.

## Build an executable on Windows
Run `build-windows.cmd` from the extracted folder. It creates an isolated build
environment, installs the pinned build tool (internet needed on the development
PC), runs tests, and builds `dist\FurqanReception\FurqanReception.exe`.

Copy the **whole `dist\FurqanReception` folder**, including `_internal`, onto the
reception PC. Create a desktop shortcut to its EXE. Python does not need to be
installed on the reception PC after packaging. This is a portable application
folder, not an MSI installer. A folder build avoids self-extraction on each launch.

**No Windows executable is included in this delivery.** PyInstaller must run on
Windows to build a Windows application. The target Windows version/architecture,
display scaling, low-spec performance and physical printers still need acceptance
checks before use with real patients. Do not disable Windows security checks to
run a build.

## Thermal printer
1. Install the printer's Windows driver and print its Windows test page.
2. Set the driver's paper width (58/80 mm), receipt paper length and cut behaviour.
3. In the app, Settings -> choose matching width -> Use Windows default printer,
   or enter the exact installed thermal printer name -> Save settings. Set the
   separate A4 report printer name for shift lists, or leave it blank to use the
   Windows default printer.
4. Save and print a synthetic visit. Check long names, address wrapping, fees,
   both numbers, no clipping, feed length and cut.
5. Test unplugging/reconnecting the printer. The visit is saved before printing;
   reprint from Daily register. Check the Windows queue before reprinting a job
   that might already be queued, to avoid two physical copies.

The adapter uses the Windows GDI print API, not raw ESC/POS commands. Driver
configuration controls paper length/cutting. A successful submission is not proof
that paper physically printed. Blank printer name uses the Windows default.
No browser or internet service is involved in printing.

## Reception routine
Search patient -> select/register -> review reported age -> choose doctor ->
adjust the charge fee for this visit if needed -> enter amount paid -> Save + print.
Changing the charge does not change the doctor's default fee. Each new visit gets
a new Sr. No. and token. Partial payment leaves a balance. Discounts require
admin access and a reason; adjust “Paid now” to the discounted total before saving.

For a procedure receipt, open Procedures, choose/register a patient, select a
saved procedure or type a custom name, enter its fee and save/print. Check “Save
new name” to add a custom procedure to the reusable list. Procedure receipts are
paid in full when issued and have a Sr. No. but no doctor token. Their fees are
listed separately in the all-doctor shift report.
Use the date filters on Procedures to find and reprint an earlier receipt.

Open Shift report to filter by date range and doctor, preview the complete patient
list, and print it on the configured A4 printer. The report shows consultation
visits, distinct patients, cancelled visits, and per-doctor counts. With all
doctors selected it also shows procedure receipts and total distinct patients.

The serial is continuous across the hospital. Tokens restart per doctor on the
next Pakistan calendar date, not on the doctor's evening shift. There is no
manual reset. Reprints retain the original numbers and demographic snapshot.

The register shows receipts, cancellations, collections and refunds. Cancellation
does not itself refund money. An admin records the refund separately. Refunding
an active visit reopens its balance; cancel it as well if the visit was cancelled.
Net collection summaries use payment dates (including later balance payments),
not just visit dates. Balances are current balances for visits in the filter.

## Backup and recovery
- Automatic verified backups on first use each day, at most hourly after writes,
  at logout/lock and clean exit. Stored in the data folder's `backups` directory.
- Admin -> Settings -> Backup to file / USB creates a full restorable backup.
- Keep off-device copies. Automatic backups are retained, not automatically pruned;
  monitor available disk space and archive backups under hospital control.
- Restore only for recovery: it replaces live data with the backup's records.
  A pre-restore backup is saved. Known issued serials/patient IDs and per-doctor
  token counters from the current database are carried forward to avoid reuse.
- If the current disk/database was lost, numbers issued since the last backup
  cannot be inferred. Reconcile with printed receipts and have the developer
  advance the counters before resuming. Never blindly restore and issue numbers.
- Restore logs out and closes the app. Log in using an account from the backup.
- Test restoration into a separate test data directory before production use.
- Keep an authorised second admin account. This version has no unauthenticated
  password-reset backdoor; loss of all admin credentials requires controlled
  developer-assisted recovery.

## Local access
Passwords are salted and hashed; five failed attempts lock the account for five
minutes. The app locks after ten minutes of inactivity. Roles are enforced in the
service layer. Database/backup files are **not application-encrypted**; someone
with Windows file access can bypass app permissions. Use a dedicated restricted
Windows account and appropriate disk protection. Do not share backups casually.

## Tests
```powershell
py -3 -m unittest discover -s tests -v
```

The data-service tests run without third-party packages. The GUI smoke test runs
only where a display is available. It opens the main screens with synthetic data,
but it is not a substitute for the Windows/hardware acceptance checks.

## Project structure
| Path | Purpose |
|---|---|
| `reception/service.py` | SQLite schema, authentication, rules, ledger, backup/restore |
| `reception/ui.py` | Tkinter reception, registers, accounts and settings |
| `reception/printing.py` | Thermal receipt formatting and Windows printing |
| `reception/instance.py` | Single-instance database-folder lock |
| `tests/` | Record-integrity and desktop smoke checks |
| `docs/` | Specification and test/acceptance report |
| `run-windows.cmd` | Run source on Windows with Python |
| `build-windows.cmd` | Test and package executable on Windows |

Consultations and procedure fee receipts only: no prescriptions, clinical procedure
records, labs, pharmacy, admissions or multi-PC sync.
Later HMS migration can use the JSON export's UUIDs, patient IDs, complete payment
ledger and historical visit snapshots. No real patient records are bundled.

References: [Tkinter](https://docs.python.org/3/library/tkinter.html),
[SQLite](https://docs.python.org/3/library/sqlite3.html),
[Windows printing](https://learn.microsoft.com/en-us/windows/win32/printdocs/how-to--print-using-the-gdi-print-api),
[PyInstaller](https://pyinstaller.org/en/stable/).
