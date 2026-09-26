from __future__ import annotations

import argparse
import os
import queue
import sqlite3
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from pathlib import Path

from .service import Service, METHODS, uid, rupees
from .printing import (receipt_text, procedure_receipt_text, shift_report_text,
                       print_receipt, default_printer)
from .instance import InstanceLock


BG = "#F2F6F5"
SURFACE = "#FFFFFF"
INK = "#18313B"
MUTED = "#5E737B"
TEAL = "#147D78"
TEAL_DARK = "#0E625E"
BORDER = "#D9E5E2"
HEADER = "#16343D"


class App:
    def __init__(self, root, service):
        self.root, self.s = root, service
        self.user = None
        self.last_activity = time.monotonic()
        self.printing = False
        self.last_sr = None
        root.title("Furqan Hospital · Reception")
        root.geometry("1120x760")
        root.minsize(960, 660)
        root.configure(background=BG)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), background=BG, foreground=INK)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=INK)
        style.configure("TButton", padding=(13, 8), background=SURFACE,
                        foreground=INK, bordercolor=BORDER, relief="flat")
        style.map("TButton", background=[("active", "#EAF2F0"), ("pressed", "#DFEAE7")],
                  bordercolor=[("focus", TEAL)])
        style.configure("Accent.TButton", background=TEAL, foreground=SURFACE,
                        bordercolor=TEAL, font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", TEAL_DARK), ("pressed", TEAL_DARK)],
                  foreground=[("disabled", "#D6E3E1")])
        style.configure("TEntry", padding=7, fieldbackground=SURFACE, bordercolor=BORDER)
        style.configure("TCombobox", padding=6, fieldbackground=SURFACE, bordercolor=BORDER)
        style.map("TEntry", bordercolor=[("focus", TEAL)])
        style.map("TCombobox", bordercolor=[("focus", TEAL)])
        style.configure("Treeview", rowheight=33, background=SURFACE,
                        fieldbackground=SURFACE, foreground=INK, borderwidth=0,
                        font=("Segoe UI", 10))
        style.map("Treeview", background=[("selected", "#D8EEEA")],
                  foreground=[("selected", INK)])
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"),
                        background="#E8F0EE", foreground=INK, padding=(9, 8),
                        relief="flat")
        style.map("Treeview.Heading", background=[("active", "#DDEAE6")])
        style.configure("Header.TFrame", background=HEADER)
        style.configure("Brand.TLabel", background=HEADER, foreground=SURFACE,
                        font=("Segoe UI", 17, "bold"))
        style.configure("HeaderMeta.TLabel", background=HEADER, foreground="#B8D0D0")
        style.configure("Nav.TFrame", background=SURFACE)
        style.configure("Nav.TButton", background=SURFACE, foreground=MUTED,
                        borderwidth=0, padding=(15, 11))
        style.map("Nav.TButton", background=[("active", "#EAF2F0")])
        style.configure("ActiveNav.TButton", background="#DDEFEA", foreground=TEAL_DARK,
                        borderwidth=0, padding=(15, 11), font=("Segoe UI", 10, "bold"))
        style.map("ActiveNav.TButton", background=[("active", "#D4E8E2")])
        style.configure("PageTitle.TLabel", font=("Segoe UI", 20, "bold"), foreground=INK)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Eyebrow.TLabel", foreground=TEAL_DARK,
                        font=("Segoe UI", 9, "bold"))
        style.configure("Card.TFrame", background=SURFACE, bordercolor=BORDER,
                        borderwidth=1, relief="solid")
        style.configure("CardInner.TFrame", background=SURFACE)
        style.configure("Card.TLabel", background=SURFACE, foreground=INK)
        style.configure("CardTitle.TLabel", background=SURFACE, foreground=INK,
                        font=("Segoe UI", 13, "bold"))
        style.configure("CardMuted.TLabel", background=SURFACE, foreground=MUTED)
        style.configure("Card.TLabelframe", background=SURFACE, bordercolor=BORDER, padding=14)
        style.configure("Card.TLabelframe.Label", background=BG, foreground=INK,
                        font=("Segoe UI", 11, "bold"))
        style.configure("Card.TCheckbutton", background=SURFACE, foreground=INK)
        style.configure("Footer.TLabel", background="#E8F0EE", foreground=MUTED,
                        padding=(22, 9))
        self.shell = ttk.Frame(root)
        self.shell.pack(fill="both", expand=True)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind_all("<KeyPress>", self.touch, add=True)
        root.bind_all("<ButtonPress>", self.touch, add=True)
        root.bind_all("<MouseWheel>", self.scroll_content, add=True)
        root.report_callback_exception = self.callback_error
        root.after(15_000, self.idle_check)
        self.login_screen()

    def touch(self, _=None):
        self.last_activity = time.monotonic()

    def scroll_content(self, event):
        canvas = getattr(self, "content_canvas", None)
        if (not canvas or not canvas.winfo_exists() or
                event.widget.winfo_toplevel() != self.root or
                isinstance(event.widget, (ttk.Treeview, tk.Text, tk.Listbox))):
            return
        x, y = event.x_root, event.y_root
        if (canvas.winfo_rootx() <= x < canvas.winfo_rootx() + canvas.winfo_width() and
                canvas.winfo_rooty() <= y < canvas.winfo_rooty() + canvas.winfo_height()):
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"

    def callback_error(self, kind, error, trace):
        messagebox.showerror("Reception", str(error), parent=self.root)

    def safe(self, fn):
        def run():
            try:
                before = self.s.db.total_changes
                result = fn()
                if self.s.actor and self.s.db.total_changes != before:
                    self.backup_check()
                return result
            except (ValueError, PermissionError, sqlite3.Error, OSError, RuntimeError) as exc:
                messagebox.showerror("Please check", str(exc), parent=self.root)
        return run

    def backup_check(self, force=False):
        try:
            self.s.auto_backup(force)
        except Exception as exc:
            messagebox.showwarning("Records saved; backup needs attention",
                                   f"The live records are saved, but backup failed: {exc}", parent=self.root)

    def button(self, parent, text, command, accent=False):
        b = ttk.Button(parent, text=text, command=self.safe(command),
                       style="Accent.TButton" if accent else "TButton")
        b.pack(side="left", padx=(0, 8), pady=4)
        return b

    def clear(self, widget):
        for child in widget.winfo_children():
            child.destroy()

    def login_screen(self):
        self.clear(self.shell)
        box = ttk.Frame(self.shell, style="Card.TFrame", padding=32)
        box.place(relx=.5, rely=.47, anchor="center", width=420)
        setup = not self.s.is_setup()
        ttk.Label(box, text="FURQAN HOSPITAL", style="Eyebrow.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Label(box, text="Set up reception" if setup else "Welcome back",
                  style="CardTitle.TLabel", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        ttk.Label(box, text="Create your administrator account" if setup else "Sign in to continue to reception",
                  style="CardMuted.TLabel").pack(anchor="w", pady=(5, 24))
        username, password, confirm = tk.StringVar(), tk.StringVar(), tk.StringVar()
        ttk.Label(box, text="Username", style="Card.TLabel").pack(anchor="w")
        user_entry = ttk.Entry(box, textvariable=username, width=35)
        user_entry.pack(fill="x", pady=(3, 12))
        ttk.Label(box, text="Password (at least 10 characters)" if setup else "Password",
                  style="Card.TLabel").pack(anchor="w")
        entry = ttk.Entry(box, textvariable=password, show="•", width=35)
        entry.pack(fill="x", pady=(3, 12))
        if setup:
            ttk.Label(box, text="Confirm password", style="Card.TLabel").pack(anchor="w")
            ttk.Entry(box, textvariable=confirm, show="•", width=35).pack(fill="x", pady=(3,12))

        def submit():
            if setup and password.get() != confirm.get():
                raise ValueError("Passwords do not match.")
            self.user = self.s.setup(username.get(), password.get()) if setup else self.s.login(username.get(), password.get())
            password.set("")
            confirm.set("")
            self.touch()
            self.home()
            self.backup_check()

        ttk.Button(box, text="Create account" if setup else "Log in", command=self.safe(submit),
                   style="Accent.TButton").pack(fill="x", pady=(14, 0))
        entry.bind("<Return>", lambda _: self.safe(submit)())
        user_entry.focus_set()

    def home(self):
        self.clear(self.shell)
        header = ttk.Frame(self.shell, style="Header.TFrame", padding=(22, 16))
        header.pack(fill="x")
        ttk.Label(header, text="Furqan Hospital  /  Reception", style="Brand.TLabel").pack(side="left")
        ttk.Label(header, text=f"{self.user['username']}  ·  {self.user['role'].title()}  ·  Offline",
                  style="HeaderMeta.TLabel").pack(side="right")
        nav = ttk.Frame(self.shell, style="Nav.TFrame", padding=(10, 4))
        nav.pack(fill="x")
        self.nav_buttons = {}
        for title, fn in (("Reception", self.reception), ("Procedures", self.procedures_page),
                          ("Daily register", self.register), ("Shift report", self.shift_report),
                          ("Patients", self.patients), ("Doctors", self.doctors),
                          ("Settings", self.settings)):
            button = ttk.Button(nav, text=title, command=self.safe(fn), style="Nav.TButton")
            button.pack(side="left", padx=2)
            self.nav_buttons[title] = button
        ttk.Button(nav, text="Lock", command=self.safe(self.lock),
                   style="Nav.TButton").pack(side="right", padx=2)
        self.status = tk.StringVar(value="Ready · Records are saved on this computer")
        self.status_label = ttk.Label(self.shell, textvariable=self.status, style="Footer.TLabel")
        self.status_label.pack(side="bottom", fill="x")
        content_area = ttk.Frame(self.shell)
        content_area.pack(side="top", fill="both", expand=True)
        self.content_canvas = tk.Canvas(content_area, background=BG, highlightthickness=0,
                                        borderwidth=0)
        content_scroll = ttk.Scrollbar(content_area, orient="vertical",
                                       command=self.content_canvas.yview)
        self.content_canvas.configure(yscrollcommand=content_scroll.set)
        self.content_canvas.pack(side="left", fill="both", expand=True)
        content_scroll.pack(side="right", fill="y")
        self.content = ttk.Frame(self.content_canvas, padding=(22, 18))
        content_window = self.content_canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda _: self.content_canvas.configure(
            scrollregion=self.content_canvas.bbox("all")))
        self.content_canvas.bind("<Configure>", lambda event: self.content_canvas.itemconfigure(
            content_window, width=event.width))
        self.reception()

    def page(self, title, help_text=""):
        self.clear(self.content)
        self.content_canvas.yview_moveto(0)
        section = {"New visit": "Reception", "Daily register": "Daily register",
                   "Patient visit history": "Daily register", "Patients": "Patients",
                   "Doctors": "Doctors", "Settings": "Settings",
                   "Procedure receipts": "Procedures", "Saved procedures": "Procedures",
                   "Shift report": "Shift report",
                   "Staff accounts": "Settings"}.get(title)
        for name, button in self.nav_buttons.items():
            button.configure(style="ActiveNav.TButton" if name == section else "Nav.TButton")
        ttk.Label(self.content, text=title, style="PageTitle.TLabel").pack(anchor="w", pady=(0, 4))
        if help_text:
            ttk.Label(self.content, text=help_text, style="Muted.TLabel",
                      wraplength=1000).pack(anchor="w", pady=(0, 17))

    def table(self, parent, columns, height=10):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=height)
        for key, label, width in columns:
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=55,
                        anchor="e" if key in ("fee", "due", "paid", "balance") else "w")
        tree.tag_configure("even", background=SURFACE)
        tree.tag_configure("odd", background="#F5F9F8")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return tree

    @staticmethod
    def add_row(tree, **kwargs):
        kwargs["tags"] = ("even" if len(tree.get_children()) % 2 == 0 else "odd",)
        return tree.insert("", "end", **kwargs)

    def selected(self, tree):
        selection = tree.selection()
        if not selection:
            raise ValueError("Select a row first.")
        return selection[0]

    def form(self, title, fields, submit):
        """fields: key,label,default,optional choices or 'password'."""
        win = tk.Toplevel(self.root)
        win.title(title)
        win.transient(self.root)
        win.configure(background=BG)
        win.geometry(f"520x{max(270, 115 + 49 * len(fields))}")
        win.resizable(False, False)
        box = ttk.Frame(win, padding=24)
        box.pack(fill="both", expand=True)
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text=title, style="PageTitle.TLabel",
                  font=("Segoe UI", 16, "bold")).grid(row=0, column=0, columnspan=2,
                                                       sticky="w", pady=(0, 13))
        variables = {}
        first = None
        for i, (key, label, initial, options) in enumerate(fields):
            ttk.Label(box, text=label).grid(row=i + 1, column=0, sticky="w", padx=(0, 20), pady=7)
            variable = tk.StringVar(value=str(initial))
            variables[key] = variable
            if options and options != "password":
                entry = ttk.Combobox(box, textvariable=variable, values=options, state="readonly", width=35)
            else:
                entry = ttk.Entry(box, textvariable=variable, width=38, show="•" if options == "password" else "")
            entry.grid(row=i + 1, column=1, sticky="ew", pady=7)
            first = first or entry
        buttons = ttk.Frame(box)
        buttons.grid(row=len(fields) + 1, column=0, columnspan=2, sticky="e", pady=(18, 0))

        def save():
            submit({k:v.get() for k,v in variables.items()})
            for key, _, _, options in fields:
                if options == "password":
                    variables[key].set("")
            win.destroy()

        self.button(buttons, "Save", save, True)
        ttk.Button(buttons, text="Cancel", command=win.destroy).pack(side="left")
        win.grab_set()
        if first:
            first.focus_set()
        return win

    def patient_form(self, patient_id=None, callback=None):
        patient = self.s.patient(patient_id) if patient_id else {}
        fields = [("name", "Patient name *", "", None), ("age", "Reported age *", "", None),
                  ("age_unit", "Age unit", "Years", ("Years","Months","Days")),
                  ("sex", "Sex", "Unknown", ("Male","Female","Other","Unknown")),
                  ("phone", "Phone (optional)", "", None), ("address", "Address (optional)", "", None),
                  ("guardian", "Guardian (optional)", "", None)]
        fields = [(k,l,patient.get(k,d),o) for k,l,d,o in fields]

        def save(values):
            new_id = self.s.save_patient(values, patient_id)
            if callback:
                callback(new_id)

        self.form("Edit patient" if patient_id else "Register patient", fields, save)

    def reception(self):
        self.page("New visit", "Search before registering. A returning patient keeps their patient ID. Review their age for this visit.")
        searchbar = ttk.Frame(self.content)
        searchbar.pack(fill="x", pady=(0, 10))
        query = tk.StringVar()
        ttk.Label(searchbar, text="Find patient", style="Eyebrow.TLabel").pack(side="left", padx=(0, 12))
        search = ttk.Entry(searchbar, textvariable=query, width=35)
        search.pack(side="left", padx=(0,8))
        body = ttk.Frame(self.content)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 18))
        ttk.Label(left, text="Matching patients", style="Eyebrow.TLabel").pack(anchor="w", pady=(0, 9))
        tree = self.table(left, [("id","ID",60),("name","Patient",180),("phone","Phone",120)], 9)
        right = ttk.Frame(body, style="Card.TFrame", padding=18)
        right.pack(side="right", fill="y")
        right.columnconfigure(1, weight=1)
        ttk.Label(right, text="Visit and collection", style="CardTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        selected_patient = {"id": None}
        patient_label = tk.StringVar(value="Select a patient")
        ttk.Label(right, textvariable=patient_label, wraplength=310,
                  style="CardMuted.TLabel").grid(row=1, column=0, columnspan=2,
                                                  sticky="w", pady=(0, 16))
        age, unit = tk.StringVar(), tk.StringVar(value="Years")
        doctor, fee, paid, method = tk.StringVar(), tk.StringVar(value="0.00"), tk.StringVar(value="0.00"), tk.StringVar(value="Cash")
        discount, reason = tk.StringVar(value="0.00"), tk.StringVar()
        doctor_rows = self.s.doctors(True)
        choices = {f"{i+1}. {r['name']} · {r['department']}":r for i,r in enumerate(doctor_rows)}
        for row, label in enumerate(("Age", "Unit", "Doctor", "Charge fee (PKR)", "Paid now (PKR)", "Method", "Discount (admin)", "Discount reason"), 2):
            ttk.Label(right, text=label, style="Card.TLabel").grid(
                row=row, column=0, sticky="w", pady=6, padx=(0, 12))
        ttk.Entry(right,textvariable=age,width=24).grid(row=2,column=1,sticky="ew")
        ttk.Combobox(right,textvariable=unit,values=("Years","Months","Days"),state="readonly",width=22).grid(row=3,column=1,sticky="ew")
        doctor_box = ttk.Combobox(right,textvariable=doctor,values=list(choices),state="readonly",width=28)
        doctor_box.grid(row=4,column=1,sticky="ew")
        ttk.Entry(right,textvariable=fee,width=24).grid(row=5,column=1,sticky="ew")
        ttk.Entry(right,textvariable=paid,width=24).grid(row=6,column=1,sticky="ew")
        ttk.Combobox(right,textvariable=method,values=METHODS,state="readonly",width=22).grid(row=7,column=1,sticky="ew")
        ttk.Entry(right,textvariable=discount,width=24,state="normal" if self.user["role"]=="admin" else "disabled").grid(row=8,column=1,sticky="ew")
        ttk.Entry(right,textvariable=reason,width=24,state="normal" if self.user["role"]=="admin" else "disabled").grid(row=9,column=1,sticky="ew")
        previous_fee = {"value": fee.get()}

        def fee_changed(*_):
            if paid.get() == previous_fee["value"]:
                paid.set(fee.get())
            previous_fee["value"] = fee.get()

        fee.trace_add("write", fee_changed)

        def refresh():
            self.clear_tree(tree)
            for p in self.s.patients(query.get()):
                self.add_row(tree, iid=str(p["id"]), values=(p["id"], p["name"], p["phone"]))

        def choose(patient_id):
            p = self.s.patient(patient_id)
            selected_patient["id"] = patient_id
            patient_label.set(f"#{p['id']} · {p['name']}")
            age.set(p["age"])
            unit.set(p["age_unit"])
            refresh()

        def doctor_changed(_=None):
            if doctor.get() in choices:
                value = rupees(choices[doctor.get()]["fee"])
                fee.set(value)
                paid.set(value)
                discount.set("0.00")

        doctor_box.bind("<<ComboboxSelected>>",doctor_changed)
        tree.bind("<<TreeviewSelect>>",lambda _: self.safe(lambda: choose_selection())())

        def choose_selection():
            if tree.selection():
                p = self.s.patient(int(tree.selection()[0]))
                selected_patient["id"] = p["id"]
                patient_label.set(f"#{p['id']} · {p['name']}")
                age.set(p["age"])
                unit.set(p["age_unit"])

        self.button(searchbar,"Search",refresh)
        self.button(searchbar,"New patient",lambda: self.patient_form(callback=choose))
        search.bind("<Return>",lambda _: self.safe(refresh)())
        actions = ttk.Frame(left)
        actions.pack(fill="x",pady=8)
        self.button(actions,"Edit selected",lambda: self.patient_form(int(self.selected(tree)),choose))
        request = uid()
        saved = {"sr":None}

        def save(print_now=False):
            if saved["sr"] is None:
                if not selected_patient["id"] or doctor.get() not in choices:
                    raise ValueError("Select a patient and an active doctor.")
                saved["sr"] = self.s.create_visit(selected_patient["id"], choices[doctor.get()]["id"],
                    age.get(),unit.get(),paid.get(),method.get(),request,discount.get(),reason.get(),fee.get())
                self.last_sr = saved["sr"]
                self.backup_check()
                self.reception()
            self.show_receipt(saved["sr"], print_now)

        buttons = ttk.Frame(right)
        buttons.grid(row=10,column=0,columnspan=2,sticky="w",pady=(18, 0))
        self.button(buttons,"Save + print",lambda: save(True),True)
        self.button(buttons,"Save only",save)
        if self.last_sr:
            self.button(searchbar,f"Last receipt #{self.last_sr}",lambda: self.show_receipt(self.last_sr))
        refresh()
        if choices:
            doctor.set(next(iter(choices)))
            doctor_changed()
        else:
            self.status.set("Admin: add at least one doctor in Doctors before recording visits.")
        search.focus_set()

    def procedures_page(self):
        self.page("Procedure receipts", "Choose a patient, then select a saved procedure or enter a custom name. Procedure receipts do not use doctor tokens. Double-click a saved receipt to reprint; the latest 500 in the date range are shown.")
        searchbar = ttk.Frame(self.content)
        searchbar.pack(fill="x", pady=(0, 10))
        ttk.Label(searchbar, text="Find patient", style="Eyebrow.TLabel").pack(side="left", padx=(0, 12))
        query = tk.StringVar()
        search = ttk.Entry(searchbar, textvariable=query, width=35)
        search.pack(side="left", padx=(0, 8))
        body = ttk.Frame(self.content)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True, padx=(0, 18))
        ttk.Label(left, text="Matching patients", style="Eyebrow.TLabel").pack(anchor="w", pady=(0, 8))
        patients = self.table(left, [("id", "ID", 60), ("name", "Patient", 180),
                                     ("phone", "Phone", 120)], 6)
        ttk.Label(left, text="Saved procedure receipts", style="Eyebrow.TLabel").pack(
            anchor="w", pady=(20, 8))
        receipt_filters = ttk.Frame(left)
        receipt_filters.pack(fill="x", pady=(0, 8))
        receipt_start = tk.StringVar(value=self.s.today())
        receipt_end = tk.StringVar(value=self.s.today())
        for label, variable in (("From", receipt_start), ("To", receipt_end)):
            ttk.Label(receipt_filters, text=label).pack(side="left", padx=(0, 5))
            ttk.Entry(receipt_filters, textvariable=variable, width=12).pack(
                side="left", padx=(0, 10))
        recent = self.table(left, [("sr", "Sr. No.", 65), ("date", "Date", 95),
                                   ("patient", "Patient", 120),
                                   ("procedure", "Procedure", 135), ("fee", "PKR", 75)], 6)
        right = ttk.Frame(body, style="Card.TFrame", padding=18)
        right.pack(side="right", fill="y")
        right.columnconfigure(1, weight=1)
        ttk.Label(right, text="New procedure receipt", style="CardTitle.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 7))
        selected_patient = {"id": None}
        patient_label = tk.StringVar(value="Select a patient")
        ttk.Label(right, textvariable=patient_label, style="CardMuted.TLabel",
                  wraplength=300).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 16))
        name, fee, method = tk.StringVar(), tk.StringVar(value="0.00"), tk.StringVar(value="Cash")
        save_name = tk.BooleanVar(value=False)
        saved = {r["name"]: r for r in self.s.procedures(True)}
        for row, label in ((2, "Procedure"), (3, "Fee paid (PKR)"), (4, "Method")):
            ttk.Label(right, text=label, style="Card.TLabel").grid(
                row=row, column=0, sticky="w", pady=7, padx=(0, 12))
        procedure_box = ttk.Combobox(right, textvariable=name, values=list(saved), width=28)
        procedure_box.grid(row=2, column=1, sticky="ew")
        ttk.Entry(right, textvariable=fee, width=24).grid(row=3, column=1, sticky="ew")
        ttk.Combobox(right, textvariable=method, values=METHODS, state="readonly",
                     width=22).grid(row=4, column=1, sticky="ew")
        ttk.Checkbutton(right, text="Save new name for future receipts",
                        variable=save_name, style="Card.TCheckbutton").grid(
                            row=5, column=0, columnspan=2, sticky="w", pady=(13, 6))

        def choose(patient_id):
            patient = self.s.patient(patient_id)
            selected_patient["id"] = patient_id
            patient_label.set(f"#{patient['id']} · {patient['name']}")
            refresh_patients()

        def choose_selection(_=None):
            if patients.selection():
                choose(int(patients.selection()[0]))

        def refresh_patients():
            self.clear_tree(patients)
            for patient in self.s.patients(query.get()):
                self.add_row(patients, iid=str(patient["id"]),
                             values=(patient["id"], patient["name"], patient["phone"]))

        def refresh_recent():
            self.clear_tree(recent)
            for receipt in self.s.procedure_receipts(receipt_start.get(), receipt_end.get()):
                self.add_row(recent, iid=str(receipt["sr"]),
                             values=(receipt["sr"], receipt["receipt_date"],
                                     receipt["snapshot"]["patient"]["name"],
                                     receipt["procedure_name"], rupees(receipt["fee"])))

        def procedure_changed(_=None):
            if name.get() in saved:
                fee.set(rupees(saved[name.get()]["default_fee"]))

        procedure_box.bind("<<ComboboxSelected>>", procedure_changed)
        patients.bind("<<TreeviewSelect>>", choose_selection)
        recent.bind("<Double-1>", lambda _: self.safe(
            lambda: self.show_procedure_receipt(int(self.selected(recent))))())
        self.button(searchbar, "Search", refresh_patients)
        self.button(searchbar, "New patient", lambda: self.patient_form(callback=choose))
        self.button(searchbar, "Saved procedures", self.manage_procedures)
        self.button(receipt_filters, "Apply", refresh_recent)
        self.button(receipt_filters, "Print selected", lambda: self.show_procedure_receipt(
            int(self.selected(recent)), True), True)
        search.bind("<Return>", lambda _: self.safe(refresh_patients)())
        request = uid()
        issued = {"sr": None}

        def issue(print_now=False):
            if issued["sr"] is None:
                if selected_patient["id"] is None:
                    raise ValueError("Select a patient first.")
                issued["sr"] = self.s.create_procedure_receipt(
                    selected_patient["id"], name.get(), fee.get(), method.get(),
                    request, save_name.get())
                self.backup_check()
                self.procedures_page()
            self.show_procedure_receipt(issued["sr"], print_now)

        actions = ttk.Frame(right, style="CardInner.TFrame")
        actions.grid(row=6, column=0, columnspan=2, sticky="w", pady=(12, 0))
        self.button(actions, "Save + print", lambda: issue(True), True)
        self.button(actions, "Save only", issue)
        refresh_patients()
        refresh_recent()
        search.focus_set()

    def manage_procedures(self):
        self.page("Saved procedures", "Keep a reusable name and default fee. The charge on an existing receipt never changes.")
        rows = {r["id"]: r for r in self.s.procedures()}
        tree = self.table(self.content, [("name", "Procedure", 300),
                                         ("fee", "Default fee (PKR)", 160)], 10)
        for procedure_id, row in rows.items():
            self.add_row(tree, iid=procedure_id,
                         values=(row["name"], rupees(row["default_fee"])))

        def edit(procedure_id=None):
            row = rows.get(procedure_id, {})

            def save(values):
                self.s.save_procedure(values["name"], values["fee"], procedure_id)
                self.manage_procedures()

            self.form("Edit procedure" if procedure_id else "Add procedure",
                      [("name", "Procedure name", row.get("name", ""), None),
                       ("fee", "Default fee (PKR)",
                        rupees(row.get("default_fee", 0)), None)], save)

        actions = ttk.Frame(self.content)
        actions.pack(fill="x", pady=(12, 0))
        self.button(actions, "Add procedure", edit, True)
        self.button(actions, "Edit selected", lambda: edit(self.selected(tree)))
        self.button(actions, "Back to receipts", self.procedures_page)

    @staticmethod
    def clear_tree(tree):
        tree.delete(*tree.get_children())

    def patients(self):
        self.page("Patients", "Search by name, phone or patient ID. Latest 200 matches are shown; narrow the search if needed.")
        bar = ttk.Frame(self.content)
        bar.pack(fill="x",pady=6)
        query = tk.StringVar()
        entry = ttk.Entry(bar,textvariable=query,width=40)
        entry.pack(side="left",padx=(0,8))
        tree = self.table(self.content,[("id","Patient ID",80),("name","Name",220),
            ("age","Last reported age",130),("sex","Sex",80),("phone","Phone",150),
            ("registered_by","Receptionist",140)],13)

        def refresh(_=None):
            self.clear_tree(tree)
            for p in self.s.patients(query.get()):
                self.add_row(tree, iid=str(p["id"]),
                             values=(p["id"], p["name"], f"{p['age']} {p['age_unit']}",
                                     p["sex"], p["phone"], p["registered_by"]))

        self.button(bar,"Search",refresh)
        self.button(bar,"New patient",lambda: self.patient_form(callback=refresh))
        self.button(bar,"Edit",lambda: self.patient_form(int(self.selected(tree)),refresh))
        self.button(bar,"Visit history",lambda: self.register(int(self.selected(tree))))
        entry.bind("<Return>",lambda _: self.safe(refresh)())
        refresh()

    def doctors(self):
        self.page("Doctors", "Changing a fee affects new visits only. Deactivated doctors remain in historical records.")
        tree = self.table(self.content,[("name","Name",230),("department","Department",230),("fee","Fee (PKR)",120),("active","Active",80)],13)
        rows = {r["id"]:r for r in self.s.doctors()}
        for key,r in rows.items():
            self.add_row(tree, iid=key,
                         values=(r["name"], r["department"], rupees(r["fee"]), "Yes" if r["active"] else "No"))

        def edit(doctor_id=None):
            r = rows.get(doctor_id,{})
            fields = [("name","Doctor name",r.get("name",""),None),("department","Department",r.get("department",""),None),
                      ("fee","Fee (PKR)",rupees(r.get("fee",0)),None),("active","Active","Yes" if r.get("active",1) else "No",("Yes","No"))]

            def submit(v):
                self.s.save_doctor(v["name"],v["department"],v["fee"],v["active"]=="Yes",doctor_id)
                self.doctors()
            self.form("Doctor",fields,submit)

        if self.user["role"]=="admin":
            bar = ttk.Frame(self.content)
            bar.pack(fill="x",pady=8)
            self.button(bar,"Add doctor",edit)
            self.button(bar,"Edit selected",lambda: edit(self.selected(tree)))

    def register(self, patient_id=None):
        self.page("Patient visit history" if patient_id else "Daily register",
                  "Consultation collections are grouped by payment date. Balances are current balances for visits in the selected date range. Latest 1,000 visits displayed; totals cover all matches. Procedure receipts are on the Procedures screen.")
        bar = ttk.Frame(self.content)
        bar.pack(fill="x",pady=6)
        start = tk.StringVar(value="2000-01-01" if patient_id else self.s.today())
        end = tk.StringVar(value=self.s.today())
        for label,var in (("From",start),("To",end)):
            ttk.Label(bar,text=label).pack(side="left",padx=(0,5))
            ttk.Entry(bar,textvariable=var,width=12).pack(side="left",padx=(0,10))
        doctor = tk.StringVar(value="All doctors")
        choices = {"All doctors":None}
        choices.update({f"{i+1}. {d['name']}":d["id"] for i,d in enumerate(self.s.doctors())})
        ttk.Combobox(bar,textvariable=doctor,values=list(choices),state="readonly",width=23).pack(side="left",padx=(0,8))
        totals = tk.StringVar()
        ttk.Label(self.content, textvariable=totals, wraplength=950,
                  foreground=TEAL_DARK, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(10, 14))
        tree = self.table(self.content,[("sr","Sr. No.",65),("date","Date",95),("token","Token",60),("patient","Patient",160),
            ("doctor","Doctor",150),("due","Total",75),("paid","Net paid",75),("balance","Balance",75),("status","Status",90)],11)

        def refresh():
            self.clear_tree(tree)
            doc_id = choices[doctor.get()]
            rows = self.s.visits(start.get(),end.get(),doc_id,patient_id)
            for v in rows:
                self.add_row(tree, iid=str(v["sr"]),
                             values=(v["sr"], v["visit_date"], v["token"], v["snapshot"]["patient"]["name"],
                                     v["snapshot"]["doctor"]["name"], rupees(v["due"]),
                                     rupees(v["net_paid"]), rupees(v["balance"]), v["status"]))
            if patient_id:
                totals.set(f"Patient #{patient_id} · {len(rows)} visits displayed")
            else:
                s = self.s.summary(start.get(),end.get(),doc_id)
                methods = "   ".join(f"{m['method']}: {rupees(m['gross']-m['refunds'])}" for m in s["methods"])
                totals.set(f"Visits: {s['visits']} · Cancelled: {s['cancelled']}  |  Collected: {rupees(s['gross'])}  |  Refunded: {rupees(s['refunds'])}  |  Net: {rupees(s['gross']-s['refunds'])} PKR\nOutstanding: {rupees(s['balance'])} PKR  |  {methods}")

        self.button(bar,"Apply",refresh)
        bar2 = ttk.Frame(self.content)
        bar2.pack(fill="x",pady=8)
        self.button(bar2,"Receipt / details",lambda: self.show_receipt(int(self.selected(tree))))

        def payment(refund=False):
            sr = int(self.selected(tree))
            visit = self.s.visit(sr)
            fields = [("amount","Refund (PKR)" if refund else "Collect (PKR)",rupees(visit["net_paid"] if refund else visit["balance"]),None),
                      ("method","Method","Cash",METHODS)]
            if refund:
                fields.append(("reason","Reason *","",None))
            request = uid()

            def submit(v):
                self.s.payment(sr,v["amount"],v["method"],request,refund,v.get("reason",""))
                refresh()
            self.form("Refund" if refund else "Collect balance",fields,submit)

        def cancel():
            sr = int(self.selected(tree))
            reason = simpledialog.askstring("Cancel visit","Reason (does not refund money):",parent=self.root)
            if reason is not None:
                self.s.cancel(sr,reason)
                refresh()

        self.button(bar2,"Collect balance",payment)
        self.button(bar2,"Cancel visit",cancel)
        if self.user["role"]=="admin":
            self.button(bar2,"Refund",lambda: payment(True))
        tree.bind("<Double-1>",lambda _: self.safe(lambda: self.show_receipt(int(self.selected(tree))))())
        refresh()

    def shift_report(self):
        self.page("Shift report", "Filter consultation visits by date and doctor. Counts exclude cancelled visits; distinct patients are counted once across the selected period.")
        filters = ttk.Frame(self.content)
        filters.pack(fill="x", pady=(0, 12))
        actions = ttk.Frame(self.content)
        actions.pack(fill="x", pady=(0, 14))
        start, end = tk.StringVar(value=self.s.today()), tk.StringVar(value=self.s.today())
        for label, variable in (("From", start), ("To", end)):
            ttk.Label(filters, text=label).pack(side="left", padx=(0, 5))
            ttk.Entry(filters, textvariable=variable, width=12).pack(side="left", padx=(0, 14))
        doctor = tk.StringVar(value="All doctors")
        choices = {"All doctors": None}
        choices.update({f"{i+1}. {d['name']}": d["id"] for i, d in enumerate(self.s.doctors())})
        ttk.Combobox(filters, textvariable=doctor, values=list(choices), state="readonly",
                     width=24).pack(side="left", padx=(0, 10))
        overview = tk.StringVar()
        ttk.Label(self.content, textvariable=overview, foreground=TEAL_DARK,
                  font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))
        breakdown = tk.StringVar()
        ttk.Label(self.content, textvariable=breakdown, wraplength=960,
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 13))
        ttk.Label(self.content, text="Patient list", style="Eyebrow.TLabel").pack(anchor="w", pady=(0, 8))
        tree = self.table(self.content, [("sr", "Sr. No.", 70), ("date", "Date", 100),
            ("token", "Token", 65), ("patient", "Patient", 165), ("doctor", "Doctor", 155),
            ("charged", "Charged", 90), ("paid", "Net paid", 90),
            ("status", "Status", 90)], 12)
        current = {"report": None}

        def refresh():
            report = self.s.shift_report(start.get(), end.get(), choices[doctor.get()])
            current["report"] = report
            overview.set(f"{report['visits']} consultation visits  ·  "
                         f"{report['patients']} consultation patients  ·  "
                         f"{report['cancelled']} cancelled  ·  PKR {rupees(report['charged'])} charged"
                         + (f"\n{len(report['procedure_rows'])} procedure receipts  ·  "
                            f"{report['total_patients']} total distinct patients" if report["doctor_id"] is None else ""))
            breakdown.set("By doctor: " + ("   |   ".join(
                f"{r['doctor_name']}: {r['visits']} visits, {r['patients']} patients"
                for r in report["by_doctor"]) or "No consultations in this period"))
            self.clear_tree(tree)
            for row in report["rows"]:
                self.add_row(tree, iid=str(row["sr"]),
                    values=(row["sr"], row["visit_date"], row["token"],
                            row["patient_name"], row["doctor_name"],
                            rupees(row["charged"]), rupees(row["net_paid"]), row["status"]))

        self.button(filters, "Apply", refresh)
        def report_text():
            refresh()
            return shift_report_text(current["report"], self.s.settings()["hospital_name"])

        self.button(actions, "Preview report", lambda: self.text_window("Shift report", report_text()))
        self.button(actions, "Print report", lambda: self.send_document(
            "Shift report", f"report:{start.get()}:{end.get()}:{choices[doctor.get()] or 'all'}",
            report_text(), self.s.settings()["report_printer_name"], "210"), True)
        ttk.Label(actions, text="Set the A4 report printer in Settings.",
                  style="Muted.TLabel").pack(side="left", padx=(12, 0))
        refresh()

    def show_receipt(self, sr, print_now=False):
        visit = self.s.visit(sr)
        settings = self.s.settings()
        text = receipt_text(visit,settings["paper_width"])
        win = tk.Toplevel(self.root)
        win.title(f"Receipt · Sr. {sr} · Token {visit['token']}")
        win.geometry("600x640")
        win.transient(self.root)
        pane = ttk.Frame(win,padding=12)
        pane.pack(fill="both",expand=True)
        receipt = tk.Text(pane,font=("Consolas",10),wrap="none",height=24)
        scroll = ttk.Scrollbar(pane,command=receipt.yview)
        receipt.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right",fill="y")
        receipt.pack(fill="both",expand=True)
        receipt.insert("1.0",text)
        receipt.configure(state="disabled")
        buttons = ttk.Frame(win,padding=10)
        buttons.pack(fill="x")
        self.button(buttons,"Print receipt",lambda: self.send_print(sr,text,settings),True)
        self.button(buttons,"Payment history",lambda: self.payment_history(visit))
        ttk.Button(buttons,text="Close",command=win.destroy).pack(side="right")
        if print_now:
            self.send_print(sr,text,settings)

    def show_procedure_receipt(self, sr, print_now=False):
        receipt_data = self.s.procedure_receipt(sr)
        settings = self.s.settings()
        text = procedure_receipt_text(receipt_data, settings["paper_width"])
        win = tk.Toplevel(self.root)
        win.title(f"Procedure receipt · Sr. {sr}")
        win.geometry("600x640")
        win.transient(self.root)
        pane = ttk.Frame(win, padding=12)
        pane.pack(fill="both", expand=True)
        receipt = tk.Text(pane, font=("Consolas", 10), wrap="none", height=24)
        scroll = ttk.Scrollbar(pane, command=receipt.yview)
        receipt.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        receipt.pack(fill="both", expand=True)
        receipt.insert("1.0", text)
        receipt.configure(state="disabled")
        buttons = ttk.Frame(win, padding=10)
        buttons.pack(fill="x")
        self.button(buttons, "Print receipt", lambda: self.send_document(
            f"Procedure receipt #{sr}", f"procedure:{sr}", text,
            settings["printer_name"], settings["paper_width"]), True)
        ttk.Button(buttons, text="Close", command=win.destroy).pack(side="right")
        if print_now:
            self.send_document(f"Procedure receipt #{sr}", f"procedure:{sr}", text,
                               settings["printer_name"], settings["paper_width"])

    def payment_history(self, visit):
        parts = [f"Sr. No. {visit['sr']} · {visit['status']}"]
        if visit["cancel_reason"]:
            parts.append("Cancellation: "+visit["cancel_reason"])
        if visit["discount_reason"]:
            parts.append("Discount: "+visit["discount_reason"])
        for p in visit["payments"]:
            parts.append(f"{p['created_at']} | {p['method']} | PKR {rupees(p['amount'])}\n{p['reason']}")
        self.text_window("Payment history", "\n\n".join(parts))

    def text_window(self, title, text):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("850x500")
        from tkinter.scrolledtext import ScrolledText
        widget = ScrolledText(win,wrap="word",font=("Consolas",10))
        widget.pack(fill="both",expand=True)
        widget.insert("1.0",text)
        widget.configure(state="disabled")

    def send_print(self, sr, text, settings):
        self.send_document(f"Receipt #{sr}", sr, text,
                           settings["printer_name"], settings["paper_width"])

    def send_document(self, label, audit_ref, text, printer_name, width):
        self.s.require()
        if self.printing:
            raise ValueError("A print submission is in progress. Please wait.")
        print_actor = self.s.actor
        self.s.record_print(audit_ref, "requested")
        self.printing = True
        result = queue.Queue()
        self.status.set(f"Submitting {label} to the printer…")

        def work():
            try:
                print_receipt(text, printer_name, width, label)
                result.put(None)
            except Exception as exc:
                result.put(str(exc))

        def poll():
            try:
                error = result.get_nowait()
            except queue.Empty:
                self.root.after(150,poll)
                return
            self.printing = False
            if self.s.actor == print_actor:
                self.s.record_print(audit_ref, "failed" if error else "submitted")
                self.status.set(f"{label}: " + ("print failed; record remains saved" if error else "submitted; check printer output"))
                if error:
                    messagebox.showwarning("Printing needs attention",
                                           error + "\n\nThe record is saved. Check the Windows print queue before trying again.",
                                           parent=self.root)
        threading.Thread(target=work,daemon=True).start()
        self.root.after(150,poll)

    def settings(self):
        self.page("Settings", "Back up to a separate device regularly. Keep the Windows date/time correct for daily token numbering.")
        bar = ttk.Frame(self.content)
        bar.pack(fill="x",pady=8)

        def password():
            def submit(v):
                if v["new"] != v["confirm"]:
                    raise ValueError("Passwords do not match.")
                self.s.change_password(v["old"],v["new"])
            self.form("Change password",[("old","Current password","","password"),("new","New password","","password"),("confirm","Confirm new password","","password")],submit)
        self.button(bar,"Change my password",password)
        if self.user["role"] != "admin":
            ttk.Label(self.content,text="Hospital, printer, staff, exports and restore are managed by an administrator.").pack(anchor="w")
            return
        settings = self.s.settings()
        form = ttk.LabelFrame(self.content, text="Hospital and printer",
                              style="Card.TLabelframe", padding=14)
        form.pack(fill="x",pady=8)
        variables = {}
        for i,(key,label) in enumerate((("hospital_name","Hospital name"),("hospital_address","Hospital address"),
                          ("footer","Receipt footer"),("paper_width","Paper width (mm)"),
                          ("printer_name","Thermal printer name"),
                          ("report_printer_name","A4 report printer name"))):
            ttk.Label(form,text=label).grid(row=i,column=0,sticky="w",padx=(0,20),pady=5)
            v = tk.StringVar(value=settings[key])
            variables[key] = v
            if key == "paper_width":
                w = ttk.Combobox(form,textvariable=v,values=("58","80"),state="readonly",width=12)
            else:
                w = ttk.Entry(form,textvariable=v,width=72)
            w.grid(row=i,column=1,sticky="w",pady=5)
        line = ttk.Frame(form)
        line.grid(row=6,column=0,columnspan=2,sticky="w",pady=5)

        def save():
            self.s.save_settings({k:v.get() for k,v in variables.items()})
            self.status.set("Settings saved. Configure the same paper width in the Windows printer driver.")
        self.button(line,"Save settings",save,True)
        self.button(line,"Use Windows default printer",lambda: variables["printer_name"].set(default_printer()))
        backups = ttk.Frame(self.content)
        backups.pack(fill="x",pady=8)

        def backup():
            file = filedialog.asksaveasfilename(title="Save database backup (USB recommended)",defaultextension=".sqlite3",initialfile=f"furqan-backup-{self.s.today()}.sqlite3",parent=self.root)
            if file:
                self.s.backup(file)
                self.status.set("Backup saved and integrity checked.")

        def export():
            file = filedialog.asksaveasfilename(title="Export records for migration",defaultextension=".json",initialfile="furqan-records.json",parent=self.root)
            if file:
                self.s.export(file)
                self.status.set("Structured export saved.")

        def restore():
            if self.printing:
                raise ValueError("Wait for print submission to finish before restoring.")
            file = filedialog.askopenfilename(title="Select database backup",filetypes=[("SQLite backup","*.sqlite3")],parent=self.root)
            if file and messagebox.askyesno("Restore replaces current records",
                "Records created after this backup will disappear from the live database. A safety backup will be kept.\n\nUse this only for recovery. Close and reopen the app afterward; verify the last issued serial before new visits.\n\nRestore now?",parent=self.root):
                self.s.restore(file)
                messagebox.showinfo("Restored","Backup restored. The app will close. Reopen and log in using an account from that backup.",parent=self.root)
                self.user = None
                self.root.after_idle(self.root.destroy)

        self.button(backups,"Backup to file / USB",backup)
        self.button(backups,"Restore backup",restore)
        self.button(backups,"Export all records",export)
        self.button(backups,"Audit log",lambda: self.text_window("Audit log — latest 500 events","\n".join(
            f"{r['created_at']} | {r['username']} | {r['action']} | {r['entity']} | {r['detail']}" for r in self.s.audit_rows())))
        self.button(backups,"Staff accounts",self.staff)

    def staff(self):
        self.s.require(True)
        self.page("Staff accounts", "Each receptionist should use their own account. Keep at least one active administrator.")
        tree = self.table(self.content,[("username","Username",220),("role","Role",150),("active","Active",100)],10)
        for r in self.s.users():
            self.add_row(tree, iid=r["id"],
                         values=(r["username"], r["role"], "Yes" if r["active"] else "No"))
        bar = ttk.Frame(self.content)
        bar.pack(fill="x",pady=8)

        def add():
            def submit(v):
                if v["password"] != v["confirm"]:
                    raise ValueError("Passwords do not match.")
                self.s.add_user(v["username"],v["password"],v["role"])
                self.staff()
            self.form("New staff account",[("username","Username","",None),("password","Password","","password"),
                ("confirm","Confirm password","","password"),("role","Role","reception",("reception","admin"))],submit)

        def toggle():
            self.s.toggle_user(self.selected(tree))
            self.staff()
        self.button(bar,"Add staff",add)
        self.button(bar,"Enable / disable selected",toggle)

    def lock(self):
        if self.s.actor:
            self.backup_check(True)
        for w in self.root.winfo_children():
            if isinstance(w,tk.Toplevel):
                w.destroy()
        self.s.logout()
        self.user = None
        self.last_sr = None
        self.login_screen()

    def idle_check(self):
        if self.user and time.monotonic()-self.last_activity > 600:
            self.safe(self.lock)()
        self.root.after(15_000,self.idle_check)

    def close(self):
        if self.printing and not messagebox.askyesno("Printing in progress","A print job is still being submitted. Close anyway? Check the Windows queue before reprinting.",parent=self.root):
            return
        if self.s.actor:
            self.backup_check(True)
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="Furqan Hospital offline reception")
    parser.add_argument("--data-dir",type=Path,help="Separate test/installation data directory")
    args = parser.parse_args()
    directory = args.data_dir or Path(os.environ.get("LOCALAPPDATA",str(Path.home()/".local"/"share")))/"FurqanReception"
    root = tk.Tk()
    root.withdraw()
    lock, service = None, None
    try:
        lock = InstanceLock(directory)
        service = Service(directory/"reception.sqlite3")
        App(root,service)
        root.deiconify()
        root.mainloop()
    except Exception as exc:
        messagebox.showerror("Reception could not start",str(exc),parent=root)
    finally:
        if service:
            service.close()
        if lock:
            lock.close()


if __name__ == "__main__":
    main()
