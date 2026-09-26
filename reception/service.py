"""Local data service. Every mutating public operation validates permissions here."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, InvalidOperation
from pathlib import Path

PKT = timezone(timedelta(hours=5))
METHODS = ("Cash", "Card", "Bank transfer", "Other")
DEFAULTS = {
    "hospital_name": "Furqan Hospital",
    "hospital_address": "23km Main Ferozepur Road, Gajjumatta Sua, Lahore",
    "footer": "Your health is our priority.",
    "paper_width": "80", "printer_name": "", "report_printer_name": "",
}


def now():
    return datetime.now(PKT)


def uid():
    return str(uuid.uuid4())


def money(value):
    """Convert user-entered rupees to exact integer paisa."""
    try:
        amount = Decimal(str(value).strip())
        if not amount.is_finite() or amount < 0 or amount > 10_000_000:
            raise ValueError("Amount must be between 0 and 10,000,000 PKR.")
        if amount * 100 != (amount * 100).to_integral_value():
            raise ValueError("Use at most two decimal places.")
        return int(amount * 100)
    except (InvalidOperation, TypeError):
        raise ValueError("Enter a valid amount, such as 500 or 500.50.") from None


def rupees(paisa):
    return f"{paisa / 100:.2f}"


def clean(value, label, max_len=120, required=True):
    value = str(value).strip()
    if (required and not value) or len(value) > max_len:
        raise ValueError(f"{label}: {'required; ' if required else ''}maximum {max_len} characters.")
    if any(ord(c) < 32 for c in value):
        raise ValueError(f"{label} must be a single line without control characters.")
    return value


def password_hash(password, salt=None):
    if len(password) < 10 or len(password) > 256:
        raise ValueError("Password must contain 10 to 256 characters.")
    salt = salt or secrets.token_hex(16)
    return salt, hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000).hex()


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(
 id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, salt TEXT NOT NULL,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','reception')),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 failed INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS patients(
 id INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT NOT NULL UNIQUE,
 name TEXT NOT NULL, age INTEGER NOT NULL, age_unit TEXT NOT NULL,
 sex TEXT NOT NULL, phone TEXT NOT NULL, address TEXT NOT NULL,
 guardian TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS patient_phone ON patients(phone);
CREATE INDEX IF NOT EXISTS patient_name ON patients(name COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS doctors(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, department TEXT NOT NULL,
 fee INTEGER NOT NULL CHECK(fee >= 0), active INTEGER NOT NULL CHECK(active IN (0,1)));
CREATE TABLE IF NOT EXISTS token_counters(
 doctor_id TEXT NOT NULL REFERENCES doctors(id), visit_date TEXT NOT NULL,
 last_token INTEGER NOT NULL, PRIMARY KEY(doctor_id, visit_date));
CREATE TABLE IF NOT EXISTS visits(
 sr INTEGER PRIMARY KEY AUTOINCREMENT, uuid TEXT NOT NULL UNIQUE,
 request_key TEXT NOT NULL UNIQUE, patient_id INTEGER NOT NULL REFERENCES patients(id),
 doctor_id TEXT NOT NULL REFERENCES doctors(id), visit_date TEXT NOT NULL,
 created_at TEXT NOT NULL, token INTEGER NOT NULL,
 fee INTEGER NOT NULL CHECK(fee >= 0), discount INTEGER NOT NULL CHECK(discount >= 0 AND discount <= fee),
 discount_reason TEXT NOT NULL, snapshot TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'recorded' CHECK(status IN ('recorded','cancelled')),
 cancel_reason TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL REFERENCES users(id),
 UNIQUE(doctor_id, visit_date, token));
CREATE INDEX IF NOT EXISTS visit_date_idx ON visits(visit_date,doctor_id);
CREATE INDEX IF NOT EXISTS visit_patient_idx ON visits(patient_id);
CREATE TABLE IF NOT EXISTS receipt_counter(
 id INTEGER PRIMARY KEY CHECK(id=1), last_sr INTEGER NOT NULL CHECK(last_sr >= 0));
CREATE TABLE IF NOT EXISTS procedures(
 id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
 default_fee INTEGER NOT NULL CHECK(default_fee >= 0),
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)));
CREATE TABLE IF NOT EXISTS procedure_receipts(
 sr INTEGER PRIMARY KEY, uuid TEXT NOT NULL UNIQUE,
 request_key TEXT NOT NULL UNIQUE, patient_id INTEGER NOT NULL REFERENCES patients(id),
 procedure_name TEXT NOT NULL, receipt_date TEXT NOT NULL, created_at TEXT NOT NULL,
 fee INTEGER NOT NULL CHECK(fee >= 0), method TEXT NOT NULL,
 snapshot TEXT NOT NULL, created_by TEXT NOT NULL REFERENCES users(id));
CREATE INDEX IF NOT EXISTS procedure_receipt_date_idx ON procedure_receipts(receipt_date);
CREATE INDEX IF NOT EXISTS procedure_receipt_patient_idx ON procedure_receipts(patient_id);
CREATE TABLE IF NOT EXISTS payments(
 id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
 visit_sr INTEGER NOT NULL REFERENCES visits(sr), amount INTEGER NOT NULL CHECK(amount != 0),
 method TEXT NOT NULL, created_at TEXT NOT NULL, payment_date TEXT NOT NULL,
 reason TEXT NOT NULL, created_by TEXT NOT NULL REFERENCES users(id));
CREATE INDEX IF NOT EXISTS payment_date_idx ON payments(payment_date);
CREATE INDEX IF NOT EXISTS payment_visit_idx ON payments(visit_sr);
CREATE TABLE IF NOT EXISTS audit_log(
 id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT REFERENCES users(id),
 created_at TEXT NOT NULL, action TEXT NOT NULL, entity TEXT NOT NULL, detail TEXT NOT NULL);
PRAGMA user_version=2;
"""


class Service:
    def __init__(self, path, clock=now):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.actor = None
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2):
            self.db.close()
            raise ValueError("Database version is newer than this application.")
        self.db.executescript(SCHEMA)
        with self.tx():
            for k, v in DEFAULTS.items():
                self.db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (k, v))
            self.db.execute("INSERT OR IGNORE INTO receipt_counter(id,last_sr) VALUES (1,0)")
            self.db.execute("""UPDATE receipt_counter SET last_sr=MAX(last_sr,
                COALESCE((SELECT MAX(sr) FROM visits),0),
                COALESCE((SELECT MAX(sr) FROM procedure_receipts),0)) WHERE id=1""")

    @contextmanager
    def tx(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def stamp(self):
        return self.clock().astimezone(PKT).isoformat(timespec="seconds")

    def today(self):
        return self.clock().astimezone(PKT).date().isoformat()

    def require(self, admin=False):
        actor = self.db.execute("SELECT * FROM users WHERE id=? AND active=1", (self.actor,)).fetchone()
        if not actor or (admin and actor["role"] != "admin"):
            raise PermissionError("Administrator access required." if admin else "Please log in.")
        return dict(actor)

    def audit(self, action, entity, detail=""):
        self.db.execute("INSERT INTO audit_log(actor,created_at,action,entity,detail) VALUES (?,?,?,?,?)",
                        (self.actor, self.stamp(), action, str(entity), detail))

    def _next_receipt_sr(self):
        self.db.execute("UPDATE receipt_counter SET last_sr=last_sr+1 WHERE id=1")
        return self.db.execute("SELECT last_sr FROM receipt_counter WHERE id=1").fetchone()[0]

    def is_setup(self):
        return self.db.execute("SELECT count(*) FROM users").fetchone()[0] > 0

    def setup(self, username, password):
        username = clean(username, "Username", 50).lower()
        salt, hashed = password_hash(password)
        with self.tx():
            if self.is_setup():
                raise ValueError("Setup has already been completed.")
            actor = uid()
            self.db.execute("INSERT INTO users(id,username,salt,password_hash,role) VALUES (?,?,?,?,?)",
                            (actor, username, salt, hashed, "admin"))
            self.actor = actor
            self.audit("setup", actor)
        return self.require()

    def login(self, username, password):
        self.actor = None
        username = str(username).strip().lower()
        with self.tx():
            row = self.db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            locked = row and row["locked_until"] > time.time()
            valid = False
            if row and row["active"] and not locked and len(password) <= 256:
                digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(row["salt"]), 600_000).hex()
                valid = hmac.compare_digest(digest, row["password_hash"])
            if valid:
                self.actor = row["id"]
                self.db.execute("UPDATE users SET failed=0,locked_until=0 WHERE id=?", (self.actor,))
                self.audit("login", self.actor)
            elif row and not locked:
                failed = row["failed"] + 1
                until = time.time() + 300 if failed >= 5 else 0
                self.db.execute("UPDATE users SET failed=?,locked_until=? WHERE id=?",
                                (0 if until else failed, until, row["id"]))
        if not valid:
            raise PermissionError("Login failed. After 5 failed attempts, wait 5 minutes.")
        return self.require()

    def logout(self):
        self.actor = None

    def add_user(self, username, password, role):
        self.require(True)
        if role not in ("admin", "reception"):
            raise ValueError("Invalid role.")
        salt, hashed = password_hash(password)
        with self.tx():
            new_id = uid()
            self.db.execute("INSERT INTO users(id,username,salt,password_hash,role) VALUES (?,?,?,?,?)",
                            (new_id, clean(username, "Username", 50).lower(), salt, hashed, role))
            self.audit("create_user", new_id)

    def users(self):
        self.require(True)
        return [dict(r) for r in self.db.execute("SELECT id,username,role,active FROM users ORDER BY username")]

    def toggle_user(self, user_id):
        self.require(True)
        with self.tx():
            row = self.db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                raise ValueError("User not found.")
            if user_id == self.actor:
                raise ValueError("You cannot disable your own account.")
            if row["active"] and row["role"] == "admin" and self.db.execute(
                "SELECT count(*) FROM users WHERE active=1 AND role='admin'").fetchone()[0] <= 1:
                raise ValueError("Keep at least one active administrator.")
            self.db.execute("UPDATE users SET active=? WHERE id=?", (1-row["active"], user_id))
            self.audit("toggle_user", user_id)

    def change_password(self, old, new):
        user = self.require()
        digest = hashlib.pbkdf2_hmac("sha256", old.encode(), bytes.fromhex(user["salt"]), 600_000).hex()
        if not hmac.compare_digest(digest, user["password_hash"]):
            raise ValueError("Current password is incorrect.")
        salt, hashed = password_hash(new)
        with self.tx():
            self.db.execute("UPDATE users SET salt=?,password_hash=? WHERE id=?", (salt, hashed, self.actor))
            self.audit("change_password", self.actor)

    def settings(self):
        self.require()
        return dict(self.db.execute("SELECT key,value FROM settings"))

    def save_settings(self, values):
        self.require(True)
        checked = {}
        for key in DEFAULTS:
            checked[key] = clean(values.get(key, DEFAULTS[key]), key, 240,
                                 required=key not in ("printer_name", "report_printer_name",
                                                      "hospital_address", "footer"))
        if checked["paper_width"] not in ("58", "80"):
            raise ValueError("Paper width must be 58 or 80 mm.")
        with self.tx():
            self.db.executemany("UPDATE settings SET value=? WHERE key=?", [(v,k) for k,v in checked.items()])
            self.audit("settings_updated", "settings")

    def patients(self, query=""):
        self.require()
        query = str(query).strip()
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM patients WHERE name LIKE ? OR phone LIKE ? OR CAST(id AS TEXT)=? ORDER BY id DESC LIMIT 200",
            (f"%{query}%", f"%{query}%", query))]

    def patient(self, patient_id):
        self.require()
        row = self.db.execute("SELECT * FROM patients WHERE id=?", (patient_id,)).fetchone()
        if not row:
            raise ValueError("Patient not found.")
        return dict(row)

    @staticmethod
    def validate_age(age, unit):
        try:
            age = int(str(age))
        except ValueError:
            raise ValueError("Age must be a whole number.") from None
        limit = {"Years": 130, "Months": 1560, "Days": 47500}.get(unit)
        if limit is None or not 0 <= age <= limit:
            raise ValueError("Check age and age unit.")
        return age

    def save_patient(self, values, patient_id=None):
        self.require()
        age = self.validate_age(values.get("age", ""), values.get("age_unit"))
        sex = values.get("sex")
        if sex not in ("Male", "Female", "Other", "Unknown"):
            raise ValueError("Select a sex.")
        fields = (clean(values.get("name", ""), "Patient name"), age, values["age_unit"], sex,
                  clean(values.get("phone", ""), "Phone", 30, False),
                  clean(values.get("address", ""), "Address", 240, False),
                  clean(values.get("guardian", ""), "Guardian", 120, False))
        with self.tx():
            stamp = self.stamp()
            if patient_id is None:
                cur = self.db.execute("INSERT INTO patients(uuid,name,age,age_unit,sex,phone,address,guardian,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                                      (uid(), *fields, stamp, stamp))
                patient_id = cur.lastrowid
            else:
                self.patient(patient_id)
                self.db.execute("UPDATE patients SET name=?,age=?,age_unit=?,sex=?,phone=?,address=?,guardian=?,updated_at=? WHERE id=?",
                                (*fields, stamp, patient_id))
            self.audit("patient_saved", patient_id)
        return patient_id

    def doctors(self, active_only=False):
        self.require()
        return [dict(r) for r in self.db.execute("SELECT * FROM doctors " +
                 ("WHERE active=1 " if active_only else "") + "ORDER BY name")]

    def save_doctor(self, name, department, fee, active=True, doctor_id=None):
        self.require(True)
        name, department, fee = clean(name, "Doctor name"), clean(department, "Department"), money(fee)
        with self.tx():
            if doctor_id:
                if not self.db.execute("SELECT 1 FROM doctors WHERE id=?", (doctor_id,)).fetchone():
                    raise ValueError("Doctor not found.")
                self.db.execute("UPDATE doctors SET name=?,department=?,fee=?,active=? WHERE id=?",
                                (name, department, fee, int(bool(active)), doctor_id))
            else:
                doctor_id = uid()
                self.db.execute("INSERT INTO doctors VALUES (?,?,?,?,?)",
                                (doctor_id, name, department, fee, int(bool(active))))
            self.audit("doctor_saved", doctor_id)
        return doctor_id

    def procedures(self, active_only=False):
        self.require()
        return [dict(r) for r in self.db.execute("SELECT * FROM procedures " +
                ("WHERE active=1 " if active_only else "") + "ORDER BY name COLLATE NOCASE")]

    def save_procedure(self, name, default_fee, procedure_id=None):
        self.require()
        name, default_fee = clean(name, "Procedure name", 100), money(default_fee)
        with self.tx():
            duplicate = self.db.execute("SELECT id FROM procedures WHERE name=? COLLATE NOCASE",
                                        (name,)).fetchone()
            if duplicate and duplicate["id"] != procedure_id:
                raise ValueError("A saved procedure already uses this name.")
            if procedure_id:
                if not self.db.execute("SELECT 1 FROM procedures WHERE id=?", (procedure_id,)).fetchone():
                    raise ValueError("Procedure not found.")
                self.db.execute("UPDATE procedures SET name=?,default_fee=?,active=1 WHERE id=?",
                                (name, default_fee, procedure_id))
            else:
                procedure_id = uid()
                self.db.execute("INSERT INTO procedures(id,name,default_fee) VALUES (?,?,?)",
                                (procedure_id, name, default_fee))
            self.audit("procedure_saved", procedure_id, name)
        return procedure_id

    def create_procedure_receipt(self, patient_id, name, fee, method, request_key,
                                 save_name=False):
        actor = self.require()
        name = clean(name, "Procedure name", 100)
        fee = money(fee)
        request_key = clean(request_key, "Request key", 100)
        if method not in METHODS:
            raise ValueError("Select a valid payment method.")
        with self.tx():
            existing = self.db.execute("SELECT * FROM procedure_receipts WHERE request_key=?",
                                       (request_key,)).fetchone()
            if existing:
                if (existing["patient_id"] != patient_id or existing["procedure_name"] != name or
                        existing["fee"] != fee or existing["method"] != method):
                    raise ValueError("This request was already used with different procedure details.")
                return existing["sr"]
            patient = self.patient(patient_id)
            stamp = self.stamp()
            sr = self._next_receipt_sr()
            snapshot = {"patient": patient, "hospital": self.settings(), "procedure": name}
            self.db.execute("""INSERT INTO procedure_receipts
                (sr,uuid,request_key,patient_id,procedure_name,receipt_date,created_at,fee,method,snapshot,created_by)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (sr, uid(), request_key, patient_id, name, stamp[:10], stamp,
                 fee, method, json.dumps(snapshot), actor["id"]))
            if save_name:
                self.db.execute("INSERT OR IGNORE INTO procedures(id,name,default_fee) VALUES (?,?,?)",
                                (uid(), name, fee))
            self.audit("procedure_receipt_created", sr, f"{name}; {fee} paisa")
        return sr

    def procedure_receipt(self, sr):
        self.require()
        row = self.db.execute("SELECT * FROM procedure_receipts WHERE sr=?", (sr,)).fetchone()
        if not row:
            raise ValueError("Procedure receipt not found.")
        return {**dict(row), "snapshot": json.loads(row["snapshot"])}

    def procedure_receipts(self, start, end, patient_id=None):
        self.require()
        date.fromisoformat(start)
        date.fromisoformat(end)
        if start > end:
            raise ValueError("Start date must not be after end date.")
        sql = "SELECT sr FROM procedure_receipts WHERE receipt_date BETWEEN ? AND ?"
        args = [start, end]
        if patient_id:
            sql += " AND patient_id=?"
            args.append(patient_id)
        sql += " ORDER BY sr DESC LIMIT 500"
        return [self.procedure_receipt(r[0]) for r in self.db.execute(sql, args).fetchall()]

    def create_visit(self, patient_id, doctor_id, age, age_unit, paid, method, request_key,
                     discount="0", reason="", fee=None):
        actor = self.require()
        request_key = clean(request_key, "Request key", 100)
        paid, discount = money(paid), money(discount)
        charged_fee = money(fee) if fee is not None else None
        age = self.validate_age(age, age_unit)
        if method not in METHODS:
            raise ValueError("Select a valid payment method.")
        if discount:
            self.require(True)
            reason = clean(reason, "Discount reason", 240)
        else:
            reason = ""
        with self.tx():
            existing = self.db.execute("SELECT * FROM visits WHERE request_key=?", (request_key,)).fetchone()
            if existing:
                snapshot = json.loads(existing["snapshot"])
                initial = self.db.execute("SELECT * FROM payments WHERE request_key=?", (request_key+":initial",)).fetchone()
                if (existing["patient_id"] != patient_id or existing["doctor_id"] != doctor_id
                    or existing["discount"] != discount or existing["discount_reason"] != reason
                    or (charged_fee is not None and existing["fee"] != charged_fee)
                    or snapshot["patient"]["age"] != age or snapshot["patient"]["age_unit"] != age_unit
                    or (initial["amount"] if initial else 0) != paid
                    or (initial and initial["method"] != method)):
                    raise ValueError("This request was already used with different visit details.")
                return existing["sr"]
            patient = self.patient(patient_id)
            doctor = self.db.execute("SELECT * FROM doctors WHERE id=? AND active=1", (doctor_id,)).fetchone()
            if not doctor:
                raise ValueError("Choose an active doctor.")
            charged_fee = doctor["fee"] if charged_fee is None else charged_fee
            if discount > charged_fee or paid > charged_fee - discount:
                raise ValueError("Discount/payment exceeds the visit amount.")
            # Derive date and timestamp from ONE clock read, including at midnight.
            stamp = self.stamp()
            day = stamp[:10]
            self.db.execute("INSERT INTO token_counters VALUES (?,?,1) ON CONFLICT(doctor_id,visit_date) DO UPDATE SET last_token=last_token+1",
                            (doctor_id, day))
            token = self.db.execute("SELECT last_token FROM token_counters WHERE doctor_id=? AND visit_date=?", (doctor_id, day)).fetchone()[0]
            snapshot = {"patient": {**patient, "age": age, "age_unit": age_unit},
                        "doctor": dict(doctor), "hospital": self.settings()}
            sr = self._next_receipt_sr()
            self.db.execute("INSERT INTO visits(sr,uuid,request_key,patient_id,doctor_id,visit_date,created_at,token,fee,discount,discount_reason,snapshot,created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (sr, uid(), request_key, patient_id, doctor_id, day, stamp, token,
                             charged_fee, discount, reason, json.dumps(snapshot), actor["id"]))
            if paid:
                self.db.execute("INSERT INTO payments VALUES (?,?,?,?,?,?,?,?,?)",
                                  (uid(), request_key+":initial", sr, paid, method, stamp, day, "Initial collection", actor["id"]))
            self.db.execute("UPDATE patients SET age=?,age_unit=?,updated_at=? WHERE id=?", (age, age_unit, stamp, patient_id))
            self.audit("visit_created", sr,
                       f"Default fee {doctor['fee']} paisa; charged fee {charged_fee} paisa")
        return sr

    def visit(self, sr):
        self.require()
        row = self.db.execute("SELECT * FROM visits WHERE sr=?", (sr,)).fetchone()
        if not row:
            raise ValueError("Visit not found.")
        result = dict(row)
        result["snapshot"] = json.loads(result["snapshot"])
        result["payments"] = [dict(r) for r in self.db.execute("SELECT * FROM payments WHERE visit_sr=? ORDER BY created_at,rowid", (sr,))]
        result["net_paid"] = sum(p["amount"] for p in result["payments"])
        result["due"] = result["fee"] - result["discount"]
        result["balance"] = max(0, result["due"] - result["net_paid"]) if result["status"] != "cancelled" else 0
        return result

    def visits(self, start, end, doctor_id=None, patient_id=None):
        self.require()
        date.fromisoformat(start)
        date.fromisoformat(end)
        if start > end:
            raise ValueError("Start date must not be after end date.")
        sql = "SELECT sr FROM visits WHERE visit_date BETWEEN ? AND ?"
        args = [start, end]
        if doctor_id:
            sql += " AND doctor_id=?"
            args.append(doctor_id)
        if patient_id:
            sql += " AND patient_id=?"
            args.append(patient_id)
        sql += " ORDER BY sr DESC LIMIT 1000"
        return [self.visit(r[0]) for r in self.db.execute(sql, args).fetchall()]

    def payment(self, sr, amount, method, request_key, refund=False, reason=""):
        actor = self.require(refund)
        amount = money(amount)
        if not amount or method not in METHODS:
            raise ValueError("Enter a positive amount and valid payment method.")
        reason = clean(reason, "Refund reason", 240) if refund else "Balance collection"
        request_key = clean(request_key, "Request key", 100)
        signed = -amount if refund else amount
        with self.tx():
            existing = self.db.execute("SELECT * FROM payments WHERE request_key=?", (request_key,)).fetchone()
            if existing:
                if existing["visit_sr"] != sr or existing["amount"] != signed or existing["method"] != method:
                    raise ValueError("This request was already used for another payment.")
                return
            visit = self.visit(sr)
            if refund and amount > visit["net_paid"]:
                raise ValueError("Refund exceeds the net amount received.")
            if not refund and (visit["status"] == "cancelled" or amount > visit["balance"]):
                raise ValueError("Payment exceeds the balance, or the visit is cancelled.")
            stamp = self.stamp()
            self.db.execute("INSERT INTO payments VALUES (?,?,?,?,?,?,?,?,?)",
                            (uid(), request_key, sr, signed, method, stamp, stamp[:10], reason, actor["id"]))
            self.audit("refund" if refund else "payment", sr, reason)

    def cancel(self, sr, reason):
        self.require()
        reason = clean(reason, "Cancellation reason", 240)
        with self.tx():
            visit = self.visit(sr)
            if visit["status"] == "cancelled":
                return
            self.db.execute("UPDATE visits SET status='cancelled',cancel_reason=? WHERE sr=?", (reason, sr))
            self.audit("visit_cancelled", sr, reason)

    def summary(self, start, end, doctor_id=None):
        self.require()
        date.fromisoformat(start)
        date.fromisoformat(end)
        if start > end:
            raise ValueError("Start date must not be after end date.")
        extra = " AND v.doctor_id=?" if doctor_id else ""
        args = [start, end] + ([doctor_id] if doctor_id else [])
        rows = self.db.execute("SELECT p.method, SUM(CASE WHEN p.amount>0 THEN p.amount ELSE 0 END) AS gross, SUM(CASE WHEN p.amount<0 THEN -p.amount ELSE 0 END) AS refunds FROM payments p JOIN visits v ON v.sr=p.visit_sr WHERE p.payment_date BETWEEN ? AND ?" + extra + " GROUP BY p.method", args).fetchall()
        stats = self.db.execute("SELECT COUNT(*) AS visits, SUM(CASE WHEN v.status='cancelled' THEN 1 ELSE 0 END) AS cancelled, SUM(CASE WHEN v.status='cancelled' THEN 0 ELSE v.fee-v.discount-COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.visit_sr=v.sr),0) END) AS balance FROM visits v WHERE v.visit_date BETWEEN ? AND ?"+extra, args).fetchone()
        return {**dict(stats), "balance": stats["balance"] or 0, "cancelled": stats["cancelled"] or 0,
                "methods": [dict(r) for r in rows], "gross": sum(r["gross"] for r in rows),
                "refunds": sum(r["refunds"] for r in rows)}

    def shift_report(self, start, end, doctor_id=None):
        """All matching consultations, with counts independent of the register's display limit."""
        self.require()
        date.fromisoformat(start)
        date.fromisoformat(end)
        if start > end:
            raise ValueError("Start date must not be after end date.")
        if doctor_id and not self.db.execute("SELECT 1 FROM doctors WHERE id=?", (doctor_id,)).fetchone():
            raise ValueError("Doctor not found.")
        sql = """SELECT v.sr,v.visit_date,v.created_at,v.token,v.patient_id,v.doctor_id,
                        v.fee-v.discount AS charged,v.status,v.snapshot,
                        COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.visit_sr=v.sr),0) AS net_paid
                 FROM visits v WHERE v.visit_date BETWEEN ? AND ?"""
        args = [start, end]
        if doctor_id:
            sql += " AND v.doctor_id=?"
            args.append(doctor_id)
        sql += " ORDER BY v.visit_date,v.doctor_id,v.token,v.sr"
        rows = []
        groups = {}
        active_patients = set()
        for r in self.db.execute(sql, args):
            snap = json.loads(r["snapshot"])
            item = {**dict(r), "patient_name": snap["patient"]["name"],
                    "doctor_name": snap["doctor"]["name"]}
            del item["snapshot"]
            rows.append(item)
            group = groups.setdefault(r["doctor_id"], {"doctor_id": r["doctor_id"],
                "doctor_name": item["doctor_name"], "visits": 0, "patients": set(),
                "cancelled": 0, "charged": 0, "net_paid": 0})
            if r["status"] == "cancelled":
                group["cancelled"] += 1
            else:
                group["visits"] += 1
                group["patients"].add(r["patient_id"])
                group["charged"] += r["charged"]
                active_patients.add(r["patient_id"])
            group["net_paid"] += r["net_paid"]
        by_doctor = [{**g, "patients": len(g["patients"])} for g in groups.values()]
        procedure_rows = []
        procedure_patients = set()
        if doctor_id is None:
            for r in self.db.execute("""SELECT sr,receipt_date,patient_id,procedure_name,fee,method,snapshot
                                       FROM procedure_receipts WHERE receipt_date BETWEEN ? AND ? ORDER BY sr""",
                                     (start, end)):
                item = {**dict(r), "patient_name": json.loads(r["snapshot"])["patient"]["name"]}
                del item["snapshot"]
                procedure_rows.append(item)
                procedure_patients.add(r["patient_id"])
        return {"start": start, "end": end, "doctor_id": doctor_id, "rows": rows,
                "by_doctor": by_doctor, "visits": sum(g["visits"] for g in by_doctor),
                "patients": len(active_patients),
                "total_patients": len(active_patients | procedure_patients),
                "cancelled": sum(g["cancelled"] for g in by_doctor),
                "charged": sum(g["charged"] for g in by_doctor),
                "net_paid": sum(g["net_paid"] for g in by_doctor),
                "procedure_rows": procedure_rows, "procedure_patients": len(procedure_patients),
                "procedure_total": sum(r["fee"] for r in procedure_rows)}

    def audit_rows(self):
        self.require(True)
        return [dict(r) for r in self.db.execute("SELECT a.created_at,COALESCE(u.username,'system') AS username,a.action,a.entity,a.detail FROM audit_log a LEFT JOIN users u ON u.id=a.actor ORDER BY a.id DESC LIMIT 500")]

    def record_print(self, sr, outcome):
        self.require()
        with self.tx():
            self.audit("print_"+outcome, sr)

    def backup(self, destination, automatic=False):
        self.require(not automatic)
        dest = Path(destination)
        if dest.resolve() == self.path.resolve():
            raise ValueError("Backup must be separate from the live database.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_name(dest.name+"."+uid()+".tmp")
        try:
            with closing(sqlite3.connect(temp)) as other:
                self.db.backup(other)
                if other.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Backup integrity check failed.")
            os.replace(temp, dest)
        finally:
            temp.unlink(missing_ok=True)
        return dest

    def auto_backup(self, force=False):
        self.require()
        folder = self.path.parent / "backups"
        previous = sorted(folder.glob("auto-*.sqlite3")) if folder.exists() else []
        day_prefix = "auto-"+self.clock().astimezone(PKT).strftime("%Y%m%d")
        if force or not previous or not previous[-1].name.startswith(day_prefix) or time.time() - previous[-1].stat().st_mtime > 3600:
            return self.backup(folder / ("auto-"+self.clock().astimezone(PKT).strftime("%Y%m%d-%H%M%S")+"-"+uid()[:8]+".sqlite3"), True)
        return previous[-1]

    def restore(self, source):
        self.require(True)
        source = Path(source).resolve()
        if not source.is_file() or source == self.path.resolve():
            raise ValueError("Choose a separate valid backup file.")
        with closing(sqlite3.connect(source.as_uri()+"?mode=ro", uri=True)) as other:
            if other.execute("PRAGMA user_version").fetchone()[0] not in (1, 2):
                raise ValueError("Unsupported backup version.")
            if other.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or other.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Backup failed integrity checks.")
            for table in ("users", "patients", "doctors", "visits", "payments", "settings", "token_counters", "audit_log"):
                incoming = [tuple(r) for r in other.execute(f"PRAGMA table_info({table})")]
                current = [tuple(r) for r in self.db.execute(f"PRAGMA table_info({table})")]
                if incoming != current:
                    raise ValueError("Backup schema does not match this application.")
            for table in ("receipt_counter", "procedures", "procedure_receipts"):
                incoming = [tuple(r) for r in other.execute(f"PRAGMA table_info({table})")]
                current = [tuple(r) for r in self.db.execute(f"PRAGMA table_info({table})")]
                if incoming and incoming != current:
                    raise ValueError("Backup schema does not match this application.")
            if not other.execute("SELECT 1 FROM users WHERE role='admin' AND active=1").fetchone():
                raise ValueError("Backup has no active administrator.")
            safety = self.backup(self.path.parent / "backups" / ("before-restore-"+uid()+".sqlite3"))
            # Preserve numbers known to the live database even when restoring older records.
            sequences = dict(self.db.execute("SELECT name,seq FROM sqlite_sequence WHERE name IN ('visits','patients')"))
            counters = [tuple(r) for r in self.db.execute("SELECT doctor_id,visit_date,last_token FROM token_counters")]
            receipt_high_water = self.db.execute("SELECT last_sr FROM receipt_counter WHERE id=1").fetchone()[0]
            other.backup(self.db)
        # Version-1 backups predate procedure receipts and the shared serial counter.
        self.db.executescript(SCHEMA)
        with self.tx():
            for key, value in DEFAULTS.items():
                self.db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (key, value))
            self.db.execute("INSERT OR IGNORE INTO receipt_counter(id,last_sr) VALUES (1,0)")
            self.db.execute("""UPDATE receipt_counter SET last_sr=MAX(last_sr, ?,
                COALESCE((SELECT MAX(sr) FROM visits),0),
                COALESCE((SELECT MAX(sr) FROM procedure_receipts),0)) WHERE id=1""",
                (receipt_high_water,))
            for name, seq in sequences.items():
                row = self.db.execute("SELECT seq FROM sqlite_sequence WHERE name=?", (name,)).fetchone()
                if row:
                    self.db.execute("UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name=?", (seq, name))
                else:
                    self.db.execute("INSERT INTO sqlite_sequence(name,seq) VALUES (?,?)", (name, seq))
            for doctor_id, day, token in counters:
                if self.db.execute("SELECT 1 FROM doctors WHERE id=?", (doctor_id,)).fetchone():
                    self.db.execute("INSERT INTO token_counters VALUES (?,?,?) ON CONFLICT(doctor_id,visit_date) DO UPDATE SET last_token=MAX(last_token,excluded.last_token)", (doctor_id, day, token))
            # The prior actor might not exist in the older backup.
            self.actor = None
            self.audit("backup_restored", "database", "Known serial and token high-water marks preserved")
        self.actor = None
        return safety

    def export(self, destination):
        self.require(True)
        data = {"format": "furqan-reception-v2", "exported_at": self.stamp(), "currency": "PKR",
                "money_unit": "paisa", "timezone": "UTC+05:00"}
        # Exclude password hashes. Keep stable IDs, full ledger, and historical snapshots.
        with self.tx():
            for table in ("patients", "doctors", "visits", "payments", "token_counters",
                          "procedures", "procedure_receipts", "receipt_counter", "audit_log", "settings"):
                data[table] = [dict(r) for r in self.db.execute(f"SELECT * FROM {table}")]
            data["users"] = self.users()
            self.audit("export", "all_records")
        dest = Path(destination)
        if dest.resolve() == self.path.resolve():
            raise ValueError("Cannot overwrite the database.")
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def close(self):
        self.db.close()
