"""Receipt layout and Windows driver-based printing. No network or extra packages."""
from __future__ import annotations

import os
import textwrap
from datetime import datetime
from .service import rupees


def receipt_text(visit, width="80"):
    columns = 32 if str(width) == "58" else 44
    snap = visit["snapshot"]
    patient, doctor, hospital = snap["patient"], snap["doctor"], snap["hospital"]
    lines = []

    def add(text="", center=False):
        for part in textwrap.wrap(str(text), columns, break_long_words=True, break_on_hyphens=False) or [""]:
            lines.append(part.center(columns) if center else part)

    add(hospital["hospital_name"], True)
    add(hospital["hospital_address"], True)
    add("-"*columns)
    moment = datetime.fromisoformat(visit["created_at"])
    add(moment.strftime("%d-%m-%Y  %A  %H:%M"))
    add(f"Sr. No: {visit['sr']}    Token No: {visit['token']:02d}")
    add(f"Receptionist: {snap.get('receptionist', 'Unknown')}")
    add(f"Consultant: {doctor['name']}")
    add(f"Department: {doctor['department']}")
    add("-"*columns)
    add(f"Patient ID: {patient['id']}")
    add(f"Patient: {patient['name']}")
    add(f"Age: {patient['age']} {patient['age_unit']}    Sex: {patient['sex']}")
    if patient["phone"]:
        add(f"Contact: {patient['phone']}")
    if patient["address"]:
        add(f"Address: {patient['address']}")
    if patient["guardian"]:
        add(f"Guardian: {patient['guardian']}")
    add("-"*columns)
    add(f"Fee:             PKR {rupees(visit['fee'])}")
    if visit["discount"]:
        add(f"Discount:        PKR {rupees(visit['discount'])}")
    add(f"Total:           PKR {rupees(visit['due'])}")
    refunded = -sum(p["amount"] for p in visit["payments"] if p["amount"] < 0)
    if refunded:
        add(f"Refunded:        PKR {rupees(refunded)}")
    add(f"Net paid:        PKR {rupees(visit['net_paid'])}")
    if visit["status"] == "cancelled":
        add("*** CANCELLED ***", True)
        add("Cancellation does not confirm refund.")
    else:
        add(f"Balance:         PKR {rupees(visit['balance'])}")
    add("-"*columns)
    add(hospital["footer"], True)
    add()
    return "\n".join(lines)


def procedure_receipt_text(receipt, width="80"):
    columns = 32 if str(width) == "58" else 44
    snap = receipt["snapshot"]
    patient, hospital = snap["patient"], snap["hospital"]
    lines = []

    def add(value="", center=False):
        for part in textwrap.wrap(str(value), columns, break_long_words=True,
                                  break_on_hyphens=False) or [""]:
            lines.append(part.center(columns) if center else part)

    add(hospital["hospital_name"], True)
    add(hospital["hospital_address"], True)
    add("-" * columns)
    moment = datetime.fromisoformat(receipt["created_at"])
    add(moment.strftime("%d-%m-%Y  %A  %H:%M"))
    add(f"Sr. No: {receipt['sr']}    Procedure receipt")
    add(f"Receptionist: {snap.get('receptionist', 'Unknown')}")
    add("-" * columns)
    add(f"Patient ID: {patient['id']}")
    add(f"Patient: {patient['name']}")
    add(f"Age: {patient['age']} {patient['age_unit']}    Sex: {patient['sex']}")
    if patient["phone"]:
        add(f"Contact: {patient['phone']}")
    add("-" * columns)
    add(f"Procedure: {receipt['procedure_name']}")
    add(f"Fee paid: PKR {rupees(receipt['fee'])}")
    add(f"Method: {receipt['method']}")
    add("-" * columns)
    add(hospital["footer"], True)
    add()
    return "\n".join(lines)


def shift_report_text(report, hospital_name):
    """Plain-text A4 report; counts use visit dates and exclude cancellations."""
    lines = [hospital_name, "SHIFT REPORT",
             f"Visit dates: {report['start']} to {report['end']}",
             f"Consultation visits: {report['visits']}   Consultation patients: {report['patients']}   Cancelled: {report['cancelled']}",
             f"Charged (active visits): PKR {rupees(report['charged'])}",
             f"Net paid on listed visits: PKR {rupees(report['net_paid'])}",
             "Net paid reflects later collections and refunds through the time of printing.",
             "", "BY DOCTOR", "-" * 83]
    if report["doctor_id"] is None:
        lines[4:4] = [f"Procedure receipts: {len(report['procedure_rows'])}   "
                       f"Procedure patients: {report['procedure_patients']}   "
                       f"Procedure fees: PKR {rupees(report['procedure_total'])}",
                       f"Total distinct patients across consultations and procedures: {report['total_patients']}"]
    for group in report["by_doctor"]:
        lines.append(f"{group['doctor_name']}: {group['visits']} visits, "
                     f"{group['patients']} patients, {group['cancelled']} cancelled, "
                     f"PKR {rupees(group['charged'])} charged")
    lines.extend(["", "PATIENT LIST", "-" * 83,
                  f"{'Sr':>5} {'Date':10} {'Tok':>3} {'Patient':20} {'Doctor':18} {'Fee':>9} {'Paid':>9}  Status",
                  "-" * 83])
    for row in report["rows"]:
        patient = textwrap.shorten(row["patient_name"], width=20, placeholder="…")
        doctor = textwrap.shorten(row["doctor_name"], width=18, placeholder="…")
        lines.append(f"{row['sr']:>5} {row['visit_date']:10} {row['token']:>3} "
                     f"{patient:20} {doctor:18} {rupees(row['charged']):>9} "
                     f"{rupees(row['net_paid']):>9}  {row['status']}")
    if report["doctor_id"] is None and report["procedure_rows"]:
        lines.extend(["", "PROCEDURE RECEIPTS", "-" * 83,
                      f"{'Sr':>5} {'Date':10} {'Patient':23} {'Procedure':27} {'Fee':>10}  Method",
                      "-" * 83])
        for row in report["procedure_rows"]:
            patient = textwrap.shorten(row["patient_name"], width=23, placeholder="…")
            name = textwrap.shorten(row["procedure_name"], width=27, placeholder="…")
            lines.append(f"{row['sr']:>5} {row['receipt_date']:10} {patient:23} "
                         f"{name:27} {rupees(row['fee']):>10}  {row['method']}")
    lines.extend(["-" * 83, f"Printed: {datetime.now().strftime('%Y-%m-%d %H:%M')}"])
    return "\n".join(part for line in lines for part in
                     (textwrap.wrap(line, 96, break_long_words=True) or [""]))


def default_printer():
    if os.name != "nt":
        return ""
    import ctypes as c
    from ctypes import wintypes as w
    spool = c.WinDLL("winspool.drv", use_last_error=True)
    get = spool.GetDefaultPrinterW
    get.argtypes, get.restype = [w.LPWSTR, c.POINTER(w.DWORD)], w.BOOL
    size = w.DWORD()
    get(None, c.byref(size))
    if not size.value:
        return ""
    buf = c.create_unicode_buffer(size.value)
    if not get(buf, c.byref(size)):
        raise c.WinError(c.get_last_error())
    return buf.value


def print_receipt(text, printer_name="", width="80", document_name="Furqan Hospital receipt"):
    """Submit a print job. Run off the UI thread; success means spool submission."""
    if os.name != "nt":
        raise OSError("Direct thermal printing requires Windows and an installed printer driver.")
    import ctypes as c
    from ctypes import wintypes as w

    class DOCINFO(c.Structure):
        _fields_ = [("cbSize", c.c_int), ("lpszDocName", w.LPCWSTR),
                    ("lpszOutput", w.LPCWSTR), ("lpszDatatype", w.LPCWSTR), ("fwType", w.DWORD)]

    class SIZE(c.Structure):
        _fields_ = [("cx", w.LONG), ("cy", w.LONG)]

    g = c.WinDLL("gdi32", use_last_error=True)
    handle = c.c_void_p
    signatures = {
        "CreateDCW": ([w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, handle], handle),
        "DeleteDC": ([handle], w.BOOL),
        "GetDeviceCaps": ([handle, c.c_int], c.c_int),
        "StartDocW": ([handle, c.POINTER(DOCINFO)], c.c_int),
        "StartPage": ([handle], c.c_int), "EndPage": ([handle], c.c_int),
        "EndDoc": ([handle], c.c_int), "AbortDoc": ([handle], c.c_int),
        "CreateFontW": ([c.c_int]*5 + [w.DWORD]*8 + [w.LPCWSTR], handle),
        "SelectObject": ([handle, handle], handle), "DeleteObject": ([handle], w.BOOL),
        "TextOutW": ([handle, c.c_int, c.c_int, w.LPCWSTR, c.c_int], w.BOOL),
        "GetTextExtentPoint32W": ([handle, w.LPCWSTR, c.c_int, c.POINTER(SIZE)], w.BOOL),
    }
    for name, (args, result) in signatures.items():
        getattr(g, name).argtypes = args
        getattr(g, name).restype = result
    printer_name = printer_name.strip() or default_printer()
    if not printer_name:
        raise OSError("No Windows default printer. Install/select the thermal printer first.")
    dc = g.CreateDCW("WINSPOOL", printer_name, None, None)
    if not dc:
        raise OSError("Cannot open printer. Check its exact Windows printer name.")
    font, old, started = None, None, False
    try:
        dpi_x, dpi_y = g.GetDeviceCaps(dc, 88), g.GetDeviceCaps(dc, 90)
        device_width, device_height = g.GetDeviceCaps(dc, 8), g.GetDeviceCaps(dc, 10)
        if min(dpi_x, dpi_y, device_width, device_height) <= 0:
            raise OSError("Printer returned invalid page dimensions.")
        margin = max(1, int(dpi_x * 1.5 / 25.4))
        page_width = min(device_width, int(int(width)*dpi_x/25.4)) - 2*margin
        size = SIZE()
        rows = text.splitlines()
        # Fit all wrapped lines to available driver width; account for actual glyph widths.
        for point in (10, 9, 8, 7):
            font = g.CreateFontW(-round(point*dpi_y/72), 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 0, 49, "Consolas")
            if not font:
                raise OSError("Cannot create printer font.")
            old = g.SelectObject(dc, font)
            widest = 0
            for line in rows:
                if not g.GetTextExtentPoint32W(dc, line, len(line.encode('utf-16-le'))//2, c.byref(size)):
                    raise OSError("Cannot measure receipt text.")
                widest = max(widest, size.cx)
            if widest <= page_width:
                break
            g.SelectObject(dc, old)
            g.DeleteObject(font)
            font, old = None, None
        if font is None:
            raise OSError("Receipt does not fit. Check paper width and driver settings.")
        line_height = max(1, round(point*dpi_y/72*1.4))
        doc = DOCINFO(c.sizeof(DOCINFO), document_name, None, None, 0)
        if g.StartDocW(dc, c.byref(doc)) <= 0:
            raise OSError("Printer did not accept the job.")
        started = True
        if g.StartPage(dc) <= 0:
            raise OSError("Printer could not start a page.")
        y = margin
        for line in rows:
            if y + line_height > device_height-margin:
                if g.EndPage(dc) <= 0 or g.StartPage(dc) <= 0:
                    raise OSError("Printer page failed.")
                y = margin
            if not g.TextOutW(dc, margin, y, line, len(line.encode('utf-16-le'))//2):
                raise OSError("Printer could not render receipt.")
            y += line_height
        if g.EndPage(dc) <= 0 or g.EndDoc(dc) <= 0:
            raise OSError("Print submission failed. Check the Windows print queue before reprinting.")
        started = False
    finally:
        if started:
            g.AbortDoc(dc)
        if old:
            g.SelectObject(dc, old)
        if font:
            g.DeleteObject(font)
        g.DeleteDC(dc)
