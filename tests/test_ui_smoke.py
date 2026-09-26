"""Run on Windows or a Linux desktop; skipped without a graphical display."""
import os
import tempfile
import unittest
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from reception.service import Service, uid
from reception.ui import App


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "Graphical display required")
class DesktopSmokeTest(unittest.TestCase):
    def test_screens_and_receipt_open(self):
        with tempfile.TemporaryDirectory() as folder:
            service = Service(Path(folder)/"reception.sqlite3")
            user = service.setup("smoke-admin", "Synthetic-only-123")
            patient = service.save_patient({"name":"Synthetic UI Patient","age":"25","age_unit":"Years","sex":"Unknown"})
            doctor = service.save_doctor("Dr. UI Example","Medicine","500")
            sr = service.create_visit(patient,doctor,"25","Years","500","Cash",uid())
            procedure_sr = service.create_procedure_receipt(patient, "ECG", "250",
                                                            "Cash", uid(), True)
            root = tk.Tk()
            try:
                app = App(root, service)
                app.user = user
                app.home()
                root.geometry("960x660")
                root.update()
                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)
                save_button = next(w for w in descendants(app.content)
                                   if isinstance(w, ttk.Button) and w.cget("text") == "Save + print")
                app.content_canvas.yview_moveto(1)
                root.update_idletasks()
                self.assertLessEqual(save_button.winfo_rooty() + save_button.winfo_height(),
                                     app.status_label.winfo_rooty())
                for page in (app.reception, app.procedures_page, app.manage_procedures, app.patients,
                             app.doctors, app.register, app.shift_report,
                             app.settings, app.staff):
                    page()
                    root.update_idletasks()
                    self.assertGreater(len(app.content.winfo_children()),1)
                app.show_receipt(sr)
                app.show_procedure_receipt(procedure_sr)
                root.update_idletasks()
                self.assertTrue(any(isinstance(w,tk.Toplevel) for w in root.winfo_children()))
                app.lock()
                self.assertIsNone(service.actor)
            finally:
                root.destroy()
                service.close()


if __name__ == "__main__":
    unittest.main()
