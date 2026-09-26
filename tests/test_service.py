import json
import os
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from reception.service import Service, PKT, money, uid
from reception.printing import (receipt_text, procedure_receipt_text,
                                shift_report_text, print_receipt)
from reception.instance import InstanceLock


class ReceptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/"reception.sqlite3"
        self.time = datetime(2026,9,26,9,0,tzinfo=PKT)
        self.s = Service(self.path,lambda:self.time)
        self.admin = self.s.setup("admin","Test-password-123")["id"]
        self.patient = self.s.save_patient({"name":"Synthetic Patient","age":"25","age_unit":"Years","sex":"Unknown","phone":"03000000000"})
        self.doctor = self.s.save_doctor("Dr. Example","Medicine","500")

    def tearDown(self):
        self.s.close()
        self.tmp.cleanup()

    def visit(self, doctor=None, paid="500", key=None):
        return self.s.create_visit(self.patient,doctor or self.doctor,"25","Years",paid,"Cash",key or uid())

    def test_system_serial_doctor_daily_tokens_and_second_shift(self):
        other = self.s.save_doctor("Dr. Second","Surgery","500")
        a,b = self.visit(),self.visit(other)
        self.time = self.time.replace(hour=19)
        c = self.visit()
        self.time = self.time.replace(day=27,hour=9)
        d,e = self.visit(),self.visit(other)
        self.assertEqual([a,b,c,d,e],[1,2,3,4,5])
        self.assertEqual([self.s.visit(n)["token"] for n in (a,b,c,d,e)],[1,1,2,1,1])

    def test_receptionist_can_set_one_visit_fee_without_changing_doctor_default(self):
        self.s.add_user("desk", "Reception-pass-123", "reception")
        self.s.logout()
        self.s.login("desk", "Reception-pass-123")
        key = uid()
        sr = self.s.create_visit(self.patient, self.doctor, "25", "Years",
                                 "375", "Cash", key, fee="375")
        self.assertEqual(self.s.visit(sr)["fee"], 37500)
        self.assertEqual(self.s.visit(sr)["net_paid"], 37500)
        self.assertEqual(self.s.doctors()[0]["fee"], 50000)
        self.assertEqual(self.s.create_visit(self.patient, self.doctor, "25", "Years",
                                             "375", "Cash", key, fee="375"), sr)
        with self.assertRaises(ValueError):
            self.s.create_visit(self.patient, self.doctor, "25", "Years",
                                "375", "Cash", key, fee="400")
        with self.assertRaises(ValueError):
            self.s.create_visit(self.patient, self.doctor, "25", "Years",
                                "400", "Cash", uid(), fee="375")

    def test_procedure_receipts_share_serials_without_doctor_tokens(self):
        first = self.visit()
        self.s.add_user("desk", "Reception-pass-123", "reception")
        self.s.logout()
        self.s.login("desk", "Reception-pass-123")
        key = uid()
        procedure = self.s.create_procedure_receipt(self.patient, "ECG", "750",
                                                     "Cash", key, True)
        next_visit = self.visit()
        self.assertEqual((first, procedure, next_visit), (1, 2, 3))
        self.assertEqual(self.s.visit(next_visit)["token"], 2)
        self.assertEqual(self.s.procedures()[0]["name"], "ECG")
        self.assertEqual(self.s.procedures()[0]["default_fee"], 75000)
        self.assertEqual(self.s.create_procedure_receipt(self.patient, "ECG", "750",
                                                         "Cash", key, True), procedure)
        with self.assertRaises(ValueError):
            self.s.create_procedure_receipt(self.patient, "ECG", "800", "Cash", key)
        text = procedure_receipt_text(self.s.procedure_receipt(procedure), "58")
        self.assertIn("Procedure: ECG", text)
        self.assertNotIn("Token No", text)
        self.assertTrue(all(len(line) <= 32 for line in text.splitlines()))
        custom = self.s.create_procedure_receipt(self.patient, "Wound dressing", "200",
                                                  "Card", uid())
        self.assertEqual(custom, 4)
        self.assertEqual(len(self.s.procedures()), 1)

    def test_shift_report_counts_distinct_patients_and_filters_doctors(self):
        other = self.s.save_doctor("Dr. Second", "Surgery", "600")
        procedure_patient = self.s.save_patient({"name": "Procedure Only", "age": "31",
            "age_unit": "Years", "sex": "Unknown"})
        first = self.visit()
        self.visit()
        self.s.create_visit(self.patient, other, "25", "Years", "600", "Cash", uid())
        cancelled = self.s.create_visit(self.patient, other, "25", "Years", "600", "Cash", uid())
        self.s.cancel(cancelled, "Entered in error")
        self.s.create_procedure_receipt(procedure_patient, "ECG", "250", "Cash", uid())
        report = self.s.shift_report("2026-09-26", "2026-09-26")
        self.assertEqual((report["visits"], report["patients"], report["cancelled"]), (3, 1, 1))
        self.assertEqual(len(report["rows"]), 4)
        self.assertEqual((report["total_patients"], len(report["procedure_rows"])), (2, 1))
        doctor_report = self.s.shift_report("2026-09-26", "2026-09-26", self.doctor)
        self.assertEqual((doctor_report["visits"], doctor_report["patients"]), (2, 1))
        self.assertEqual(doctor_report["procedure_rows"], [])
        printed = shift_report_text(report, "Furqan Hospital")
        self.assertIn(str(first), printed)
        self.assertIn("PROCEDURE RECEIPTS", printed)
        self.assertTrue(all(len(line) <= 96 for line in printed.splitlines()))

    def test_midnight_uses_pakistan_date_not_utc(self):
        self.time = datetime(2026,9,26,18,59,59,tzinfo=timezone.utc)
        a = self.visit()
        self.time = datetime(2026,9,26,19,0,0,tzinfo=timezone.utc)
        b = self.visit()
        self.assertEqual(self.s.visit(a)["visit_date"],"2026-09-26")
        self.assertEqual(self.s.visit(b)["visit_date"],"2026-09-27")
        self.assertEqual(self.s.visit(b)["token"],1)

    def test_duplicate_visit_is_idempotent_and_changed_payload_rejected(self):
        key=uid()
        a=self.visit(key=key)
        self.assertEqual(a,self.visit(key=key))
        self.assertEqual(len(self.s.visit(a)["payments"]),1)
        with self.assertRaises(ValueError):
            self.visit(paid="400",key=key)
        self.assertEqual(self.visit(),2)

    def test_cancel_preserves_numbers_and_does_not_refund(self):
        a=self.visit()
        self.s.cancel(a,"Patient left")
        v=self.s.visit(a)
        self.assertEqual(v["net_paid"],50000)
        self.assertEqual(v["balance"],0)
        b=self.visit()
        self.assertEqual((b,self.s.visit(b)["token"]),(2,2))
        with self.assertRaises(ValueError):
            self.s.payment(a,"1","Cash",uid())
        self.s.payment(a,"500","Cash",uid(),True,"Cancelled consultation")
        self.assertEqual(self.s.visit(a)["net_paid"],0)

    def test_failure_rolls_back_token_visit_and_payment(self):
        # Simulate a database failure at the final audit insert after all allocations.
        self.s.db.execute("CREATE TRIGGER fail_visit BEFORE INSERT ON audit_log WHEN NEW.action='visit_created' BEGIN SELECT RAISE(ABORT,'simulated failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.visit()
        self.assertEqual(self.s.db.execute("SELECT count(*) FROM payments").fetchone()[0],0)
        self.assertEqual(self.s.db.execute("SELECT count(*) FROM token_counters").fetchone()[0],0)
        self.s.db.execute("DROP TRIGGER fail_visit")
        a=self.visit()
        self.assertEqual((a,self.s.visit(a)["token"]),(1,1))

    def test_restart_preserves_patient_serial_and_tokens(self):
        self.visit()
        self.s.close()
        self.s=Service(self.path,lambda:self.time)
        self.s.login("admin","Test-password-123")
        a=self.visit()
        self.assertEqual((a,self.s.visit(a)["token"]),(2,2))
        self.assertEqual(len(self.s.patients()),1)

    def test_historical_snapshots_survive_edits(self):
        a=self.visit()
        p=self.s.patient(self.patient)
        p["name"]="Changed name"
        self.s.save_patient(p,self.patient)
        self.s.save_doctor("Renamed doctor","New department","900",True,self.doctor)
        settings=self.s.settings()
        settings["hospital_name"]="Changed hospital"
        self.s.save_settings(settings)
        v=self.s.visit(a)
        self.assertEqual(v["snapshot"]["patient"]["name"],"Synthetic Patient")
        self.assertEqual(v["snapshot"]["doctor"]["name"],"Dr. Example")
        self.assertEqual(v["snapshot"]["hospital"]["hospital_name"],"Furqan Hospital")
        self.assertEqual(v["fee"],50000)

    def test_shared_phone_is_allowed(self):
        self.s.save_patient({"name":"Synthetic Child","age":"8","age_unit":"Months","sex":"Unknown","phone":"03000000000"})
        self.assertEqual(len(self.s.patients("03000000000")),2)

    def test_partial_payment_ledger_refund_and_payment_dates(self):
        a=self.visit(paid="200")
        self.assertEqual(self.s.visit(a)["balance"],30000)
        self.time=self.time.replace(day=27)
        key=uid()
        self.s.payment(a,"300","Card",key)
        self.s.payment(a,"300","Card",key)
        with self.assertRaises(ValueError):
            self.s.payment(a,"301","Card",key)
        self.s.payment(a,"100","Cash",uid(),True,"Partial refund")
        v=self.s.visit(a)
        self.assertEqual((v["net_paid"],v["balance"]),(40000,10000))
        first=self.s.summary("2026-09-26","2026-09-26")
        second=self.s.summary("2026-09-27","2026-09-27")
        self.assertEqual(first["gross"],20000)
        self.assertEqual((second["gross"],second["refunds"]),(30000,10000))

    def test_cannot_overpay_or_overrefund(self):
        a=self.visit(paid="100")
        with self.assertRaises(ValueError):
            self.s.payment(a,"401","Cash",uid())
        with self.assertRaises(ValueError):
            self.s.payment(a,"101","Cash",uid(),True,"Too much")

    def test_discount_requires_admin_and_reason(self):
        with self.assertRaises(ValueError):
            self.s.create_visit(self.patient,self.doctor,"25","Years","400","Cash",uid(),"100","")
        a=self.s.create_visit(self.patient,self.doctor,"25","Years","400","Cash",uid(),"100","Approved discount")
        self.assertEqual(self.s.visit(a)["due"],40000)
        self.s.add_user("desk","Reception-pass-123","reception")
        self.s.login("desk","Reception-pass-123")
        with self.assertRaises(PermissionError):
            self.s.create_visit(self.patient,self.doctor,"25","Years","400","Cash",uid(),"100","Attempt")

    def test_reception_permissions_enforced_in_service(self):
        a=self.visit()
        self.s.add_user("desk","Reception-pass-123","reception")
        self.s.login("desk","Reception-pass-123")
        operations=[lambda:self.s.save_doctor("X","Y","1"),lambda:self.s.save_settings({}),
                    lambda:self.s.add_user("x","Another-pass-123","admin"),
                    lambda:self.s.payment(a,"10","Cash",uid(),True,"Attempt"),
                    lambda:self.s.restore(self.path),lambda:self.s.export(Path(self.tmp.name)/"export.json"),
                    self.s.audit_rows]
        for op in operations:
            with self.assertRaises(PermissionError):
                op()
        self.assertEqual(self.visit(),2)

    def test_logged_out_access_and_disabled_account(self):
        self.s.add_user("desk","Reception-pass-123","reception")
        desk=next(u for u in self.s.users() if u["username"]=="desk")
        self.s.toggle_user(desk["id"])
        with self.assertRaises(PermissionError):
            self.s.login("desk","Reception-pass-123")
        with self.assertRaises(PermissionError):
            self.s.patients()
        with self.assertRaises(ValueError):
            self.s.setup("new","Another-pass-123")

    def test_password_change_and_login_lockout(self):
        self.s.change_password("Test-password-123","New-password-456")
        self.s.logout()
        with self.assertRaises(PermissionError):
            self.s.login("admin","Test-password-123")
        self.s.login("admin","New-password-456")
        for _ in range(5):
            with self.assertRaises(PermissionError):
                self.s.login("admin","wrong")
        with self.assertRaises(PermissionError):
            self.s.login("admin","New-password-456")

    def test_inactive_doctor_cannot_receive_new_visits(self):
        self.s.save_doctor("Dr. Example","Medicine","500",False,self.doctor)
        with self.assertRaises(ValueError):
            self.visit()

    def test_amount_and_demographic_validation(self):
        for invalid in ("NaN","Infinity","-1","5.001","not money","10000001"):
            with self.assertRaises(ValueError):
                money(invalid)
        self.assertEqual(money("500.50"),50050)
        for invalid in ("-1","1.5","999999"):
            with self.assertRaises(ValueError):
                self.s.save_patient({"name":"Example","age":invalid,"age_unit":"Years","sex":"Unknown"})

    def test_backup_restore_integrity_and_known_number_preservation(self):
        self.visit()
        backup=self.s.backup(Path(self.tmp.name)/"copy.sqlite3")
        self.visit()
        self.s.restore(backup)
        self.s.login("admin","Test-password-123")
        self.assertEqual(len(self.s.visits("2026-09-26","2026-09-26")),1)
        a=self.visit()
        self.assertEqual((a,self.s.visit(a)["token"]),(3,3))
        self.assertTrue(list((Path(self.tmp.name)/"backups").glob("before-restore-*")))

    def test_restore_version_one_backup_migrates_and_preserves_receipt_numbers(self):
        self.visit()
        legacy = self.s.backup(Path(self.tmp.name) / "legacy.sqlite3")
        connection = sqlite3.connect(legacy)
        try:
            connection.executescript("""DROP TABLE procedure_receipts;
                DROP TABLE procedures; DROP TABLE receipt_counter;
                DELETE FROM settings WHERE key='report_printer_name';
                PRAGMA user_version=1;""")
        finally:
            connection.close()
        self.assertEqual(self.s.create_procedure_receipt(self.patient, "ECG", "500",
                                                         "Cash", uid()), 2)
        self.s.restore(legacy)
        self.s.login("admin", "Test-password-123")
        self.assertEqual(self.visit(), 3)
        self.assertEqual(self.s.settings()["report_printer_name"], "")
        self.assertEqual(self.s.db.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_invalid_restore_preserves_live_records(self):
        a=self.visit()
        bad=Path(self.tmp.name)/"bad.sqlite3"
        bad.write_bytes(b"not a database")
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.restore(bad)
        self.assertEqual(self.s.visit(a)["net_paid"],50000)

    def test_export_has_stable_ids_and_no_password_hashes(self):
        self.visit()
        self.s.create_procedure_receipt(self.patient, "ECG", "250", "Cash", uid(), True)
        destination=Path(self.tmp.name)/"export.json"
        self.s.export(destination)
        data=json.loads(destination.read_text())
        self.assertEqual(data["money_unit"],"paisa")
        self.assertIn("uuid",data["visits"][0])
        self.assertNotIn("password_hash",data["users"][0])
        self.assertEqual(data["patients"][0]["uuid"],self.s.patient(self.patient)["uuid"])
        self.assertEqual(data["format"], "furqan-reception-v2")
        self.assertEqual(data["procedure_receipts"][0]["procedure_name"], "ECG")

    def test_receipt_widths_and_reprinting_do_not_allocate_numbers(self):
        a=self.visit()
        for width,columns in (("58",32),("80",44)):
            text=receipt_text(self.s.visit(a),width)
            self.assertIn("Sr. No: 1",text)
            self.assertIn("Token No: 01",text)
            self.assertTrue(all(len(line)<=columns for line in text.splitlines()))
        self.assertEqual(self.visit(),2)

    def test_concurrent_visits_have_unique_numbers(self):
        errors=[]
        serials=[]
        def work():
            s=Service(self.path,lambda:self.time)
            try:
                s.login("admin","Test-password-123")
                serials.append(s.create_visit(self.patient,self.doctor,"25","Years","500","Cash",uid()))
            except Exception as exc:
                errors.append(exc)
            finally:
                s.close()
        threads=[threading.Thread(target=work) for _ in range(4)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(errors,[])
        self.assertEqual(sorted(serials),[1,2,3,4])
        self.assertEqual(sorted(self.s.visit(sr)["token"] for sr in serials),[1,2,3,4])

    def test_app_instance_lock_is_released(self):
        lock=InstanceLock(self.tmp.name)
        with self.assertRaises(RuntimeError):
            InstanceLock(self.tmp.name)
        lock.close()
        lock2=InstanceLock(self.tmp.name)
        lock2.close()

    @unittest.skipIf(os.name=="nt","Linux adapter guard")
    def test_non_windows_print_failure_keeps_visit(self):
        a=self.visit()
        with self.assertRaises(OSError):
            print_receipt(receipt_text(self.s.visit(a)))
        self.assertEqual(self.s.visit(a)["sr"],a)


if __name__=="__main__":
    unittest.main()
