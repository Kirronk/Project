from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from planning import format_date, generate_sessions
from validation import normalize_date, normalize_time


SLOT_MINUTES = 30
DEFAULT_PROTOCOL_TEXT = (
    ""
)


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def format_diagnosis(row: dict[str, Any] | sqlite3.Row) -> str:
    code = str(row["code"] or "").strip() if "code" in row.keys() else ""
    name = str(row["name"] or "").strip() if "name" in row.keys() else ""
    if code and name:
        return f"{code} — {name}"
    return name or code


@dataclass
class PatientRepository:
    conn: sqlite3.Connection

    def list_patients(self, query: str = "") -> list[dict[str, Any]]:
        rows = [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM patients ORDER BY last_name, first_name, middle_name"
            )
        ]
        needle = query.strip().casefold()
        if not needle:
            return rows
        result = []
        for row in rows:
            haystack = " ".join(
                str(row.get(key) or "")
                for key in ("last_name", "first_name", "middle_name", "birth_date", "passport")
            ).casefold()
            if needle in haystack:
                result.append(row)
        return result

    def get_patient(self, patient_id: int) -> dict[str, Any] | None:
        return row_to_dict(self.conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone())

    def save_patient(self, data: dict[str, Any], patient_id: int | None = None) -> int:
        data = dict(data)
        data["birth_date"] = normalize_date(data.get("birth_date", ""), "Дата рождения", required=False)
        data["first_visit_date"] = normalize_date(
            data.get("first_visit_date", ""), "Дата первичного приема", required=False
        )
        fields = [
            "last_name",
            "first_name",
            "middle_name",
            "birth_date",
            "passport",
            "address",
            "phone",
            "first_visit_date",
            "notes",
        ]
        values = [data.get(field, "") for field in fields]
        if patient_id:
            set_clause = ", ".join(f"{field} = ?" for field in fields)
            self.conn.execute(
                f"UPDATE patients SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (*values, patient_id),
            )
            self.conn.commit()
            return patient_id
        cur = self.conn.execute(
            f"INSERT INTO patients({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
            values,
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def delete_patient(self, patient_id: int) -> None:
        self.conn.execute("DELETE FROM patients WHERE id = ?", (patient_id,))
        self.conn.commit()

    def list_reference(self, table: str) -> list[dict[str, Any]]:
        if table not in {"diagnoses", "medications", "therapy_types", "schedule_slots", "groups"}:
            raise ValueError(f"Unsupported reference table: {table}")
        if table == "schedule_slots":
            return [
                dict(r)
                for r in self.conn.execute(
                    """
                    SELECT * FROM schedule_slots
                    ORDER BY weekday, start_time
                    """
                )
            ]
        if table == "diagnoses":
            return [
                dict(r)
                for r in self.conn.execute(
                    """
                    SELECT * FROM diagnoses
                    ORDER BY code, name
                    """
                )
            ]
        order = "name"
        return [dict(r) for r in self.conn.execute(f"SELECT * FROM {table} ORDER BY {order}")]

    def add_reference(self, table: str, name: str, default_slots: int = 1) -> int:
        if table == "therapy_types":
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO therapy_types(name, default_slots) VALUES (?, ?)",
                (name.strip(), default_slots),
            )
        elif table == "diagnoses":
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO diagnoses(name, code, description) VALUES (?, '', '')",
                (name.strip(),),
            )
        elif table in {"medications", "groups"}:
            cur = self.conn.execute(f"INSERT OR IGNORE INTO {table}(name) VALUES (?)", (name.strip(),))
        else:
            raise ValueError(f"Unsupported reference table: {table}")
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def add_diagnosis_reference(self, code: str, name: str, description: str = "") -> int:
        code = code.strip()
        name = name.strip()
        description = description.strip() or name
        if not name:
            raise ValueError("Название диагноза обязательно.")
        existing = self.conn.execute(
            """
            SELECT id FROM diagnoses
            WHERE name = ? OR (code <> '' AND code = ?)
            ORDER BY id
            LIMIT 1
            """,
            (name, code),
        ).fetchone()
        if existing:
            diagnosis_id = int(existing["id"])
            self.conn.execute(
                """
                UPDATE diagnoses
                SET code = ?, name = ?, description = ?
                WHERE id = ?
                """,
                (code, name, description, diagnosis_id),
            )
            self.conn.commit()
            return diagnosis_id
        cur = self.conn.execute(
            "INSERT INTO diagnoses(code, name, description) VALUES (?, ?, ?)",
            (code, name, description),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_patient_group(self, patient_id: int, group_name: str, joined_date: str = "") -> int:
        joined_date = normalize_date(joined_date, "Дата вступления в группу", required=False)
        current_count = self.conn.execute(
            "SELECT COUNT(*) FROM patient_groups WHERE patient_id = ?",
            (patient_id,),
        ).fetchone()[0]
        group_id = self._get_or_create_named("groups", group_name)
        existing = self.conn.execute(
            "SELECT id FROM patient_groups WHERE patient_id = ? AND group_id = ?",
            (patient_id, group_id),
        ).fetchone()
        if existing:
            return int(existing["id"])
        if current_count >= 5:
            raise ValueError("У пациента может быть не больше 5 групп.")
        cur = self.conn.execute(
            "INSERT INTO patient_groups(patient_id, group_id, joined_date) VALUES (?, ?, ?)",
            (patient_id, group_id, joined_date),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def remove_patient_group(self, patient_id: int, group_name: str) -> None:
        group_name = group_name.strip()
        if not group_name:
            return
        group = self.conn.execute("SELECT id FROM groups WHERE name = ?", (group_name,)).fetchone()
        if not group:
            return
        with self.conn:
            self.conn.execute(
                "DELETE FROM patient_groups WHERE patient_id = ? AND group_id = ?",
                (patient_id, group["id"]),
            )
            self._delete_planned_sessions_for_mode(patient_id, group_name)

    def add_schedule_slot(self, weekday: int, start_time: str, slots: int = 1, label: str = "") -> int:
        start_time = normalize_time(start_time, "Время слота", required=True)
        cur = self.conn.execute(
            """
            INSERT OR IGNORE INTO schedule_slots(weekday, start_time, slots, label)
            VALUES (?, ?, ?, ?)
            """,
            (weekday, start_time, slots, label),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def add_diagnosis(self, patient_id: int, diagnosis_text: str, set_date: str, comment: str = "") -> int:
        set_date = normalize_date(set_date, "Дата диагноза")
        diagnosis_text = diagnosis_text.strip()
        diagnosis = self.find_diagnosis(diagnosis_text)
        if diagnosis:
            diagnosis_id = int(diagnosis["id"])
            diagnosis_text = format_diagnosis(diagnosis)
        else:
            diagnosis_id = self._get_or_create_named("diagnoses", diagnosis_text)
        cur = self.conn.execute(
            """
            INSERT INTO patient_diagnoses(patient_id, diagnosis_id, diagnosis_text, set_date, comment)
            VALUES (?, ?, ?, ?, ?)
            """,
            (patient_id, diagnosis_id, diagnosis_text, set_date, comment),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def find_diagnosis(self, value: str) -> dict[str, Any] | None:
        value = value.strip()
        if not value:
            return None
        code_guess = value.split("—", 1)[0].strip()
        row = self.conn.execute(
            """
            SELECT * FROM diagnoses
            WHERE code = ?
               OR name = ?
               OR description = ?
               OR TRIM(code || ' — ' || name) = ?
            ORDER BY id
            LIMIT 1
            """,
            (code_guess, value, value, value),
        ).fetchone()
        return row_to_dict(row)

    def add_hads(self, patient_id: int, test_date: str, anxiety: int, depression: int, comment: str = "") -> int:
        test_date = normalize_date(test_date, "Дата HADS")
        cur = self.conn.execute(
            """
            INSERT INTO hads_tests(patient_id, test_date, anxiety, depression, comment)
            VALUES (?, ?, ?, ?, ?)
            """,
            (patient_id, test_date, anxiety, depression, comment),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def upsert_hads(self, patient_id: int, test_date: str, anxiety: int, depression: int, comment: str = "") -> int:
        test_date = normalize_date(test_date, "Дата HADS")
        row = self.conn.execute(
            "SELECT id FROM hads_tests WHERE patient_id = ? AND test_date = ?",
            (patient_id, test_date),
        ).fetchone()
        if row:
            self.conn.execute(
                """
                UPDATE hads_tests
                SET anxiety = ?, depression = ?, comment = ?
                WHERE id = ?
                """,
                (anxiety, depression, comment, row["id"]),
            )
            self.conn.commit()
            return int(row["id"])
        return self.add_hads(patient_id, test_date, anxiety, depression, comment)

    def add_visit(
        self,
        patient_id: int,
        visit_date: str,
        visit_time: str,
        visit_type: str,
        status: str = "planned",
        source: str = "",
        slots: int = 1,
        comment: str = "",
    ) -> int:
        visit_date = normalize_date(visit_date, "Дата посещения")
        visit_time = normalize_time(visit_time, "Время посещения", required=False)
        cur = self.conn.execute(
            """
            INSERT INTO visits(patient_id, visit_date, visit_time, visit_type, status, source, slots, comment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (patient_id, visit_date, visit_time, visit_type, status, source, slots, comment),
        )
        visit_id = int(cur.lastrowid)
        title = self._patient_title(patient_id, visit_type)
        self.conn.execute(
            """
            INSERT INTO schedule_events(patient_id, visit_id, event_date, event_time, title, status, slots, comment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (patient_id, visit_id, visit_date, visit_time, title, status, slots, comment),
        )
        self.conn.commit()
        return visit_id

    def add_prescription(
        self,
        patient_id: int,
        prescription_text: str,
        start_date: str,
        end_date: str = "",
        comment: str = "",
    ) -> int:
        start_date = normalize_date(start_date, "Дата назначения")
        end_date = normalize_date(end_date, "Дата отмены", required=False)
        medication_id = self._get_or_create_named("medications", prescription_text)
        cur = self.conn.execute(
            """
            INSERT INTO prescriptions(patient_id, medication_id, prescription_text, start_date, end_date, comment)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (patient_id, medication_id, prescription_text, start_date, end_date, comment),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_prescription(
        self,
        prescription_id: int,
        prescription_text: str,
        start_date: str,
        end_date: str = "",
        comment: str = "",
    ) -> None:
        start_date = normalize_date(start_date, "Дата назначения")
        end_date = normalize_date(end_date, "Дата отмены", required=False)
        medication_id = self._get_or_create_named("medications", prescription_text)
        self.conn.execute(
            """
            UPDATE prescriptions
            SET medication_id = ?, prescription_text = ?, start_date = ?, end_date = ?, comment = ?
            WHERE id = ?
            """,
            (medication_id, prescription_text, start_date, end_date, comment, prescription_id),
        )
        self.conn.commit()

    def delete_prescription(self, prescription_id: int) -> None:
        self.conn.execute("DELETE FROM prescriptions WHERE id = ?", (prescription_id,))
        self.conn.commit()

    def add_protocol(self, patient_id: int, protocol_date: str, title: str, body: str) -> int:
        protocol_date = normalize_date(protocol_date, "Дата протокола")
        cur = self.conn.execute(
            """
            INSERT INTO session_protocols(patient_id, protocol_date, title, body)
            VALUES (?, ?, ?, ?)
            """,
            (patient_id, protocol_date, title, body),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_protocol_body(self, protocol_id: int, title: str, body: str) -> None:
        self.conn.execute(
            "UPDATE session_protocols SET title = ?, body = ? WHERE id = ?",
            (title, body, protocol_id),
        )
        self.conn.commit()

    def add_therapy_course(
        self,
        patient_id: int,
        mode: str,
        start_date: str,
        start_time: str,
        session_count: int,
        comment: str = "",
    ) -> int:
        start_date = normalize_date(start_date, "Дата начала курса")
        start_time = normalize_time(start_time, "Время начала курса", required=False)
        therapy_type_id = self._get_or_create_therapy_type(mode)
        if mode.startswith("Групповая"):
            self.add_patient_group(patient_id, mode, start_date)
        sessions = generate_sessions(mode, start_date, session_count)
        with self.conn:
            self._delete_planned_sessions_for_mode(patient_id, mode)
            cur = self.conn.execute(
                """
                INSERT INTO therapy_courses(
                    patient_id, therapy_type_id, mode, start_date, start_time, session_count, comment
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (patient_id, therapy_type_id, mode, start_date, start_time, session_count, comment),
            )
            course_id = int(cur.lastrowid)
            for item in sessions:
                session_date = format_date(item.session_date)
                session_cur = self.conn.execute(
                    """
                    INSERT INTO therapy_sessions(
                        course_id, patient_id, session_date, session_time, status, slots, comment
                    )
                    VALUES (?, ?, ?, ?, 'planned', ?, ?)
                    """,
                    (course_id, patient_id, session_date, start_time, item.slots, comment),
                )
                session_id = int(session_cur.lastrowid)
                self.conn.execute(
                    """
                    INSERT INTO schedule_events(
                        patient_id, session_id, event_date, event_time, title, status, slots, comment
                    )
                    VALUES (?, ?, ?, ?, ?, 'planned', ?, ?)
                    """,
                    (patient_id, session_id, session_date, start_time, self._patient_title(patient_id, mode), item.slots, comment),
                )
        return course_id

    def _delete_planned_sessions_for_mode(self, patient_id: int, mode: str) -> None:
        planned = self.conn.execute(
            """
            SELECT ts.id
            FROM therapy_sessions ts
            JOIN therapy_courses tc ON tc.id = ts.course_id
            WHERE ts.patient_id = ?
              AND tc.mode = ?
              AND ts.status = 'planned'
            """,
            (patient_id, mode),
        ).fetchall()
        for row in planned:
            session_id = int(row["id"])
            self.conn.execute("DELETE FROM session_protocols WHERE session_id = ?", (session_id,))
            self.conn.execute("DELETE FROM therapy_sessions WHERE id = ?", (session_id,))

    def upsert_matrix_event(
        self,
        patient_id: int,
        row_label: str,
        event_date: str,
        status: str = "planned",
        event_time: str = "",
        slots: int = 1,
    ) -> int:
        event_date = normalize_date(event_date, "Дата посещения")
        event_time = normalize_time(event_time, "Время посещения", required=False)
        row = self.conn.execute(
            """
            SELECT id FROM visits
            WHERE patient_id = ? AND visit_type = ? AND visit_date = ?
            """,
            (patient_id, row_label, event_date),
        ).fetchone()
        if row:
            visit_id = int(row["id"])
            self.conn.execute(
                """
                UPDATE visits
                SET visit_time = ?, status = ?, slots = ?
                WHERE id = ?
                """,
                (event_time, status, slots, visit_id),
            )
            self.conn.execute(
                """
                UPDATE schedule_events
                SET event_time = ?, status = ?, slots = ?
                WHERE visit_id = ?
                """,
                (event_time, status, slots, visit_id),
            )
            self.conn.commit()
            return visit_id
        return self.add_visit(patient_id, event_date, event_time, row_label, status, "matrix", slots)

    def update_status(self, table: str, item_id: int, status: str) -> None:
        if table == "visits":
            self.conn.execute("UPDATE visits SET status = ? WHERE id = ?", (status, item_id))
            self.conn.execute(
                "UPDATE schedule_events SET status = ? WHERE visit_id = ?",
                (status, item_id),
            )
        elif table == "therapy_sessions":
            self.conn.execute("UPDATE therapy_sessions SET status = ? WHERE id = ?", (status, item_id))
            self.conn.execute(
                "UPDATE schedule_events SET status = ? WHERE session_id = ?",
                (status, item_id),
            )
        else:
            raise ValueError(f"Unsupported status table: {table}")
        self.conn.commit()

    def set_schedule_event_status(self, event_id: int, status: str) -> None:
        row = self.conn.execute("SELECT * FROM schedule_events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            raise ValueError("Запись расписания не найдена.")
        if row["visit_id"]:
            self.update_status("visits", int(row["visit_id"]), status)
        elif row["session_id"]:
            self.update_status("therapy_sessions", int(row["session_id"]), status)
        else:
            self.conn.execute("UPDATE schedule_events SET status = ? WHERE id = ?", (status, event_id))
            self.conn.commit()
        if status == "done":
            self.ensure_protocol_for_event(event_id)

    def update_schedule_event_date(self, event_id: int, event_date: str) -> None:
        event_date = normalize_date(event_date, "Дата посещения")
        row = self.conn.execute("SELECT * FROM schedule_events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            raise ValueError("Запись расписания не найдена.")
        with self.conn:
            self.conn.execute("UPDATE schedule_events SET event_date = ? WHERE id = ?", (event_date, event_id))
            if row["visit_id"]:
                self.conn.execute("UPDATE visits SET visit_date = ? WHERE id = ?", (event_date, row["visit_id"]))
                self.conn.execute(
                    "UPDATE session_protocols SET protocol_date = ? WHERE visit_id = ?",
                    (event_date, row["visit_id"]),
                )
            elif row["session_id"]:
                self.conn.execute(
                    "UPDATE therapy_sessions SET session_date = ? WHERE id = ?",
                    (event_date, row["session_id"]),
                )
                self.conn.execute(
                    "UPDATE session_protocols SET protocol_date = ? WHERE session_id = ?",
                    (event_date, row["session_id"]),
                )

    def clear_schedule_event(self, event_id: int) -> None:
        row = self.conn.execute("SELECT * FROM schedule_events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            return
        with self.conn:
            if row["visit_id"]:
                self.conn.execute("DELETE FROM session_protocols WHERE visit_id = ?", (row["visit_id"],))
                self.conn.execute("DELETE FROM visits WHERE id = ?", (row["visit_id"],))
            elif row["session_id"]:
                self.conn.execute("DELETE FROM session_protocols WHERE session_id = ?", (row["session_id"],))
                self.conn.execute("DELETE FROM therapy_sessions WHERE id = ?", (row["session_id"],))
            else:
                self.conn.execute("DELETE FROM schedule_events WHERE id = ?", (event_id,))

    def patient_detail(self, patient_id: int) -> dict[str, Any]:
        patient = self.get_patient(patient_id)
        if patient is None:
            raise ValueError("Patient not found")
        return {
            "patient": patient,
            "diagnoses": self.patient_diagnoses(patient_id),
            "hads": self._list("hads_tests", patient_id, "test_date DESC, id DESC"),
            "visits": self._list("visits", patient_id, "visit_date DESC, visit_time DESC, id DESC"),
            "courses": self._list("therapy_courses", patient_id, "start_date DESC, id DESC"),
            "sessions": self._list("therapy_sessions", patient_id, "session_date DESC, session_time DESC, id DESC"),
            "prescriptions": self._list("prescriptions", patient_id, "start_date DESC, id DESC"),
            "protocols": self._list("session_protocols", patient_id, "protocol_date DESC, id DESC"),
            "groups": self.patient_groups(patient_id),
        }

    def patient_diagnoses(self, patient_id: int) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.conn.execute(
                """
                SELECT
                    pd.*,
                    d.code AS diagnosis_code,
                    d.name AS diagnosis_name,
                    d.description AS diagnosis_description
                FROM patient_diagnoses pd
                LEFT JOIN diagnoses d ON d.id = pd.diagnosis_id
                WHERE pd.patient_id = ?
                ORDER BY pd.set_date DESC, pd.id DESC
                """,
                (patient_id,),
            )
        ]

    def annual_card(self, patient_id: int, year: int) -> dict[str, Any]:
        start = f"{year}-01-01"
        end = f"{year}-12-31"
        detail = self.patient_detail(patient_id)
        detail["year"] = year
        detail["schedule"] = [
            row for row in self.schedule(start, end) if int(row["patient_id"] or 0) == patient_id
        ]
        return detail

    def patient_groups(self, patient_id: int) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.conn.execute(
                """
                SELECT pg.*, g.name, g.description
                FROM patient_groups pg
                JOIN groups g ON g.id = pg.group_id
                WHERE pg.patient_id = ?
                ORDER BY g.name
                """,
                (patient_id,),
            )
        ]

    def schedule(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        start_date = normalize_date(start_date, "Начало расписания")
        end_date = normalize_date(end_date, "Конец расписания")
        return [
            dict(r)
            for r in self.conn.execute(
                """
                SELECT se.*, p.last_name, p.first_name, p.middle_name
                FROM schedule_events se
                LEFT JOIN patients p ON p.id = se.patient_id
                WHERE se.event_date BETWEEN ? AND ?
                ORDER BY se.event_date, se.event_time, se.id
                """,
                (start_date, end_date),
            )
        ]

    def ensure_protocol_for_event(self, event_id: int) -> int:
        row = self.conn.execute("SELECT * FROM schedule_events WHERE id = ?", (event_id,)).fetchone()
        if not row or not row["patient_id"]:
            raise ValueError("Нельзя создать протокол без пациента.")
        existing = None
        if row["visit_id"]:
            existing = self.conn.execute(
                "SELECT id FROM session_protocols WHERE visit_id = ?",
                (row["visit_id"],),
            ).fetchone()
        elif row["session_id"]:
            existing = self.conn.execute(
                "SELECT id FROM session_protocols WHERE session_id = ?",
                (row["session_id"],),
            ).fetchone()
        if existing:
            return int(existing["id"])

        title = row["title"].split(" - ", 1)[-1] if row["title"] else "Сеанс"
        body = load_protocol_template(title)
        cur = self.conn.execute(
            """
            INSERT INTO session_protocols(patient_id, protocol_date, title, body, visit_id, session_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (row["patient_id"], row["event_date"], title, body, row["visit_id"], row["session_id"]),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def available_start_times(self, event_date: str, required_slots: int = 1) -> list[str]:
        event_date = normalize_date(event_date, "Дата")
        required_slots = max(int(required_slots or 1), 1)
        weekday = __import__("datetime").date.fromisoformat(event_date).weekday()
        slot_rows = [
            dict(r)
            for r in self.conn.execute(
                """
                SELECT start_time FROM schedule_slots
                WHERE weekday = ? AND active = 1
                ORDER BY start_time
                """,
                (weekday,),
            )
        ]
        template_times = [row["start_time"] for row in slot_rows]
        occupied = {
            row["event_time"]: int(row["slots"] or 1)
            for row in self.conn.execute(
                """
                SELECT event_time, slots FROM schedule_events
                WHERE event_date = ? AND status NOT IN ('cancelled', 'missed') AND event_time <> ''
                """,
                (event_date,),
            )
        }
        busy = set()
        for event_time, slots in occupied.items():
            if event_time in template_times:
                index = template_times.index(event_time)
                for offset in range(slots):
                    if index + offset < len(template_times):
                        busy.add(template_times[index + offset])

        result = []
        for index, start_time in enumerate(template_times):
            needed = template_times[index : index + required_slots]
            if len(needed) == required_slots and all(time not in busy for time in needed):
                result.append(start_time)
        return result

    def statistics(self) -> dict[str, Any]:
        patient_count = self.conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0]
        visit_statuses = {
            row["status"]: row["count"]
            for row in self.conn.execute(
                "SELECT status, COUNT(*) AS count FROM visits GROUP BY status ORDER BY status"
            )
        }
        missed_sessions = self.conn.execute(
            "SELECT COUNT(*) FROM therapy_sessions WHERE status = 'missed'"
        ).fetchone()[0]
        active_prescriptions = self.conn.execute(
            "SELECT COUNT(*) FROM prescriptions WHERE end_date = '' OR end_date IS NULL"
        ).fetchone()[0]
        return {
            "patient_count": patient_count,
            "visit_statuses": visit_statuses,
            "missed_sessions": missed_sessions,
            "active_prescriptions": active_prescriptions,
        }

    def all_for_export(self) -> dict[str, list[dict[str, Any]]]:
        tables = [
            "patients",
            "diagnoses",
            "patient_diagnoses",
            "hads_tests",
            "visits",
            "therapy_types",
            "therapy_courses",
            "therapy_sessions",
            "medications",
            "prescriptions",
            "session_protocols",
            "schedule_events",
            "schedule_slots",
            "groups",
            "patient_groups",
        ]
        return {table: [dict(r) for r in self.conn.execute(f"SELECT * FROM {table}")] for table in tables}

    def _list(self, table: str, patient_id: int, order_by: str) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.conn.execute(
                f"SELECT * FROM {table} WHERE patient_id = ? ORDER BY {order_by}",
                (patient_id,),
            )
        ]

    def _get_or_create_named(self, table: str, name: str) -> int:
        row = self.conn.execute(f"SELECT id FROM {table} WHERE name = ?", (name,)).fetchone()
        if row:
            return int(row["id"])
        cur = self.conn.execute(f"INSERT INTO {table}(name) VALUES (?)", (name,))
        return int(cur.lastrowid)

    def _get_or_create_therapy_type(self, name: str) -> int:
        row = self.conn.execute("SELECT id FROM therapy_types WHERE name = ?", (name,)).fetchone()
        if row:
            return int(row["id"])
        cur = self.conn.execute(
            "INSERT INTO therapy_types(name, default_slots) VALUES (?, ?)",
            (name, 1),
        )
        return int(cur.lastrowid)

    def _patient_title(self, patient_id: int, suffix: str) -> str:
        patient = self.get_patient(patient_id)
        if not patient:
            return suffix
        initials = "".join(part[:1] for part in [patient["first_name"], patient["middle_name"]] if part)
        return f"{patient['last_name']} {initials}. - {suffix}"


def load_protocol_template(session_type: str) -> str:
    source = Path("/Users/name/Downloads/primer_paneli_7.docx")
    if not source.exists():
        return DEFAULT_PROTOCOL_TEXT
    try:
        from docx import Document

        paragraphs = [" ".join(p.text.split()) for p in Document(source).paragraphs]
        body = "\n\n".join(text for text in paragraphs if text and not text.startswith("Дата "))
        return body or DEFAULT_PROTOCOL_TEXT
    except Exception:
        return DEFAULT_PROTOCOL_TEXT
