from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk
from typing import Any

from repositories import PatientRepository, format_diagnosis
from ui.date_widgets import DateEntry
from validation import normalize_date, normalize_time


STATUS_LABELS = {
    "planned": "Запланировано",
    "done": "Посещено",
    "missed": "Пропущено",
    "cancelled": "Отменено",
}
STATUS_BY_LABEL = {label: key for key, label in STATUS_LABELS.items()}
STATUS_COLORS = {"planned": "#777777", "done": "#111111", "missed": "#1b5ec9", "cancelled": "#9a9a9a"}
YEAR_COLUMNS = 12
WEEKDAY_NAMES = ("Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье")


class ScrollFrame(ttk.Frame):
    def __init__(self, master: tk.Misc):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", self._sync_scroll_region)
        self.canvas.bind("<Configure>", self._sync_width)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)

    def _sync_scroll_region(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _sync_width(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _bind_mousewheel(self, _event: tk.Event) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event: tk.Event) -> None:
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event: tk.Event) -> None:
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")


class HorizontalScrollFrame(ttk.Frame):
    def __init__(self, master: tk.Misc, height: int = 140):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0, height=height)
        self.scrollbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.inner = ttk.Frame(self.canvas)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(xscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="ew")
        self.scrollbar.grid(row=1, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.inner.bind("<Configure>", self._sync_scroll_region)

    def _sync_scroll_region(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))


class GridScrollFrame(ttk.Frame):
    def __init__(self, master: tk.Misc, height: int = 220):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0, height=height)
        self.xscrollbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.yscrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.window_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(xscrollcommand=self.xscrollbar.set, yscrollcommand=self.yscrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.yscrollbar.grid(row=0, column=1, sticky="ns")
        self.xscrollbar.grid(row=1, column=0, sticky="ew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.inner.bind("<Configure>", self._sync_scroll_region)

    def _sync_scroll_region(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))


class PatientApp(tk.Tk):
    def __init__(self, conn):
        super().__init__()
        self.title("База пациентов психотерапевта")
        self.geometry("1480x920")
        self.minsize(1080, 720)
        self.repo = PatientRepository(conn)
        self.selected_patient_id: int | None = None
        self.current_card: dict[str, Any] | None = None
        self.schedule_row_patients: dict[str, int] = {}
        self.matrix_event_ids: dict[str, int] = {}
        self.protocol_row_ids: dict[str, int] = {}
        self.diagnosis_options: dict[str, dict[str, Any]] = {}
        self.selected_prescription_id: int | None = None

        self.search_var = tk.StringVar()
        self.year_var = tk.StringVar(value=str(date.today().year))
        self.patient_vars = {key: tk.StringVar() for key in [
            "last_name", "first_name", "middle_name", "birth_date", "address", "first_visit_date"
        ]}
        self.diagnosis_var = tk.StringVar()
        self.diagnosis_code_var = tk.StringVar()
        self.diagnosis_date_var = tk.StringVar()
        self.diagnosis_text_var = tk.StringVar()
        self.hads_vars: list[dict[str, tk.StringVar]] = []
        self.manual_visit_row_var = tk.StringVar(value="Плановые осмотры")
        self.manual_visit_date_var = tk.StringVar(value=date.today().isoformat())
        self.manual_visit_status_var = tk.StringVar(value=STATUS_LABELS["planned"])
        self.plan_mode_var = tk.StringVar(value="Еженедельная индивидуальная ПТ")
        self.plan_count_var = tk.StringVar(value="10")
        self.plan_date_var = tk.StringVar(value=date.today().isoformat())
        self.plan_time_var = tk.StringVar()
        self.group_var = tk.StringVar()
        self.group_count_var = tk.StringVar(value="8")
        self.group_date_var = tk.StringVar(value=date.today().isoformat())
        self.med_date_var = tk.StringVar(value=date.today().isoformat())
        self.med_name_var = tk.StringVar()
        self.med_end_var = tk.StringVar()
        self.med_comment_var = tk.StringVar()
        self.protocol_title_var = tk.StringVar()

        self._build_layout()
        self.refresh_patients()
        self.refresh_references()

    def _build_layout(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self, padding=8)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.rowconfigure(2, weight=1)
        ttk.Label(sidebar, text="Пациенты").grid(row=0, column=0, sticky="w")
        search = ttk.Entry(sidebar, textvariable=self.search_var, width=32)
        search.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        search.bind("<KeyRelease>", lambda _event: self.refresh_patients())

        self.patient_tree = ttk.Treeview(sidebar, columns=("birth",), show="tree headings", height=24)
        self.patient_tree.heading("#0", text="ФИО")
        self.patient_tree.heading("birth", text="Рожд.")
        self.patient_tree.column("#0", width=210)
        self.patient_tree.column("birth", width=90, anchor="center")
        self.patient_tree.grid(row=2, column=0, sticky="nsew")
        self.patient_tree.bind("<<TreeviewSelect>>", self._on_patient_select)

        side_buttons = ttk.Frame(sidebar)
        side_buttons.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(side_buttons, text="Новый", command=self.new_patient).pack(side="left")
        ttk.Button(side_buttons, text="Удалить", command=self.delete_patient).pack(side="left", padx=(6, 0))

        ttk.Separator(sidebar).grid(row=4, column=0, sticky="ew", pady=10)
        ttk.Button(sidebar, text="Справочники", command=self.open_references).grid(row=5, column=0, sticky="ew", pady=2)

        self.scroll = ScrollFrame(self)
        self.scroll.grid(row=0, column=1, sticky="nsew", padx=(0, 8), pady=8)
        self.dashboard = self.scroll.inner
        self.dashboard.columnconfigure(0, weight=1)

        header = ttk.Frame(self.dashboard)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(header, text="Карточка пациента", font=("", 16, "bold")).pack(side="left")
        ttk.Label(header, text="Год").pack(side="left", padx=(16, 4))
        ttk.Entry(header, textvariable=self.year_var, width=8).pack(side="left")
        ttk.Button(header, text="Показать год", command=self.reload_card).pack(side="left", padx=(6, 0))
        ttk.Button(header, text="Сохранить карточку", command=self.save_patient).pack(side="right")

        self._build_patient_info()
        self._build_hads()
        self._build_visits_matrix()
        self._build_planning()
        self._build_prescriptions()
        self._build_protocols()

    def _build_patient_info(self) -> None:
        frame = ttk.LabelFrame(self.dashboard, text="2. Данные пациента", padding=8)
        frame.grid(row=1, column=0, sticky="ew", pady=4)
        for col in (1, 3, 5):
            frame.columnconfigure(col, weight=1)

        fields = [
            ("last_name", "Фамилия", 0, 0),
            ("first_name", "Имя", 0, 2),
            ("middle_name", "Отчество", 0, 4),
            ("birth_date", "Дата рождения", 1, 0),
            ("first_visit_date", "Принят", 1, 2),
            ("address", "Адрес", 1, 4),
        ]
        for key, label, row, col in fields:
            ttk.Label(frame, text=label).grid(row=row, column=col, sticky="w", padx=(0, 4), pady=3)
            if key in {"birth_date", "first_visit_date"}:
                DateEntry(frame, self.patient_vars[key], width=12).grid(row=row, column=col + 1, sticky="ew", pady=3)
            else:
                ttk.Entry(frame, textvariable=self.patient_vars[key]).grid(row=row, column=col + 1, sticky="ew", pady=3)

        ttk.Label(frame, text="Диагноз").grid(row=2, column=0, sticky="w", padx=(0, 4), pady=3)
        self.diagnosis_combo = ttk.Combobox(frame, textvariable=self.diagnosis_var, width=28)
        self.diagnosis_combo.grid(row=2, column=1, columnspan=3, sticky="ew", pady=3)
        self.diagnosis_combo.bind("<<ComboboxSelected>>", self.on_diagnosis_select)
        ttk.Label(frame, text="Код").grid(row=2, column=4, sticky="w", padx=(8, 4), pady=3)
        ttk.Entry(frame, textvariable=self.diagnosis_code_var, width=10, state="readonly").grid(
            row=2, column=5, sticky="ew", pady=3
        )
        ttk.Label(frame, text="Расшифровка").grid(row=3, column=0, sticky="w", padx=(0, 4), pady=3)
        ttk.Entry(frame, textvariable=self.diagnosis_text_var, state="readonly").grid(
            row=3, column=1, columnspan=5, sticky="ew", pady=3
        )

    def _build_hads(self) -> None:
        frame = ttk.LabelFrame(self.dashboard, text="3. Тест HADS", padding=8)
        frame.grid(row=2, column=0, sticky="ew", pady=4)
        frame.columnconfigure(0, weight=1)
        hscroll = HorizontalScrollFrame(frame, height=118)
        hscroll.grid(row=0, column=0, sticky="ew")
        self.hads_frame = hscroll.inner
        ttk.Label(self.hads_frame, text="Дата", width=12).grid(row=0, column=0, sticky="ew")
        ttk.Label(self.hads_frame, text="Тревога", width=12).grid(row=1, column=0, sticky="ew")
        ttk.Label(self.hads_frame, text="Депрессия", width=12).grid(row=2, column=0, sticky="ew")
        for idx in range(YEAR_COLUMNS):
            vars_for_col = {"date": tk.StringVar(), "anxiety": tk.StringVar(), "depression": tk.StringVar()}
            self.hads_vars.append(vars_for_col)
            DateEntry(self.hads_frame, vars_for_col["date"], width=10).grid(row=0, column=idx + 1, padx=2, pady=1)
            ttk.Entry(self.hads_frame, textvariable=vars_for_col["anxiety"], width=8).grid(
                row=1, column=idx + 1, padx=2, pady=1
            )
            ttk.Entry(self.hads_frame, textvariable=vars_for_col["depression"], width=8).grid(
                row=2, column=idx + 1, padx=2, pady=1
            )
        ttk.Button(frame, text="Сохранить HADS", command=self.save_hads).grid(row=1, column=0, sticky="w", pady=(6, 0))

    def _build_visits_matrix(self) -> None:
        frame = ttk.LabelFrame(self.dashboard, text="4. Посещения и сеансы", padding=8)
        frame.grid(row=3, column=0, sticky="ew", pady=4)
        frame.columnconfigure(0, weight=1)
        matrix_scroll = GridScrollFrame(frame, height=220)
        matrix_scroll.grid(row=0, column=0, sticky="ew")
        self.visits_matrix_frame = matrix_scroll.inner
        controls = ttk.Frame(frame)
        controls.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        controls.columnconfigure(1, weight=1)
        self.manual_visit_row_combo = ttk.Combobox(controls, textvariable=self.manual_visit_row_var, width=26)
        self.manual_visit_row_combo.grid(row=0, column=0, sticky="ew")
        DateEntry(controls, self.manual_visit_date_var, width=12).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Combobox(
            controls,
            textvariable=self.manual_visit_status_var,
            values=tuple(STATUS_LABELS.values()),
            state="readonly",
            width=14,
        ).grid(row=0, column=2, sticky="ew")
        ttk.Button(controls, text="Добавить дату", command=self.add_matrix_event).grid(row=0, column=3, padx=(6, 0))
        ttk.Label(
            controls,
            text="Черный - посещено, синий - пропущено, серый - запланировано",
            wraplength=460,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

    def _build_planning(self) -> None:
        frame = ttk.LabelFrame(self.dashboard, text="5. Планирование дат", padding=8)
        frame.grid(row=4, column=0, sticky="ew", pady=4)
        for col in (1, 5):
            frame.columnconfigure(col, weight=1)
        ttk.Label(frame, text="Вид").grid(row=0, column=0, sticky="w")
        self.plan_mode_combo = ttk.Combobox(
            frame,
            textvariable=self.plan_mode_var,
            values=(
                "Наблюдение и консультации",
                "Наблюдение",
                "Еженедельная индивидуальная ПТ",
                "Индивидуальная ПТ раз в 2 недели",
                "Индивидуальная поддерживающая ПТ",
                "Гипнотерапия",
            ),
            width=32,
        )
        self.plan_mode_combo.grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(frame, text="№").grid(row=0, column=2)
        ttk.Entry(frame, textvariable=self.plan_count_var, width=5).grid(row=0, column=3, sticky="w")
        ttk.Label(frame, text="с").grid(row=0, column=4)
        DateEntry(frame, self.plan_date_var, width=12).grid(row=0, column=5, sticky="ew", padx=4)
        ttk.Button(frame, text="Запланировать", command=self.plan_course).grid(row=0, column=6, padx=4)

        ttk.Label(frame, text="Группа").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.group_combo = ttk.Combobox(frame, textvariable=self.group_var, width=32)
        self.group_combo.grid(row=1, column=1, sticky="ew", padx=4, pady=(8, 0))
        ttk.Label(frame, text="№").grid(row=1, column=2, pady=(8, 0))
        ttk.Entry(frame, textvariable=self.group_count_var, width=5).grid(row=1, column=3, sticky="w", pady=(8, 0))
        ttk.Label(frame, text="с").grid(row=1, column=4, pady=(8, 0))
        DateEntry(frame, self.group_date_var, width=12).grid(row=1, column=5, sticky="ew", padx=4, pady=(8, 0))
        ttk.Button(frame, text="Добавить группу", command=self.plan_group).grid(row=1, column=6, padx=4, pady=(8, 0))
        self.patient_group_tree = ttk.Treeview(frame, columns=("name", "joined"), show="headings", height=4)
        self.patient_group_tree.heading("name", text="Группы пациента")
        self.patient_group_tree.heading("joined", text="Дата")
        self.patient_group_tree.column("name", width=320, anchor="w")
        self.patient_group_tree.column("joined", width=100, anchor="w")
        self.patient_group_tree.grid(row=2, column=0, columnspan=6, sticky="ew", pady=(10, 0))
        self.patient_group_tree.bind("<<TreeviewSelect>>", self.on_patient_group_select)
        ttk.Button(frame, text="Удалить группу", command=self.remove_patient_group).grid(
            row=2, column=6, sticky="ew", padx=4, pady=(10, 0)
        )

    def _build_prescriptions(self) -> None:
        frame = ttk.LabelFrame(self.dashboard, text="6. Препараты", padding=8)
        frame.grid(row=5, column=0, sticky="ew", pady=4)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.prescription_tree = ttk.Treeview(
            frame,
            columns=("start", "med", "end", "comment"),
            show="headings",
            height=8,
        )
        for col, heading, width in [
            ("start", "Дата", 90),
            ("med", "Назначение", 420),
            ("end", "Дата окончания", 110),
            ("comment", "Комментарий", 300),
        ]:
            self.prescription_tree.heading(col, text=heading)
            self.prescription_tree.column(col, width=width, anchor="w")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.prescription_tree.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.prescription_tree.xview)
        self.prescription_tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.prescription_tree.grid(row=0, column=0, sticky="nsew")
        self.prescription_tree.bind("<<TreeviewSelect>>", self.on_prescription_select)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")

        form = ttk.Frame(frame)
        form.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=2)
        ttk.Label(form, text="Дата").grid(row=0, column=0, sticky="w")
        DateEntry(form, self.med_date_var, width=12).grid(row=0, column=1, sticky="ew", padx=(4, 10))
        ttk.Label(form, text="Препарат").grid(row=0, column=2, sticky="w")
        self.med_combo = ttk.Combobox(form, textvariable=self.med_name_var, width=34)
        self.med_combo.grid(row=0, column=3, columnspan=2, sticky="ew", padx=(4, 0))
        ttk.Label(form, text="Окончание").grid(row=1, column=0, sticky="w", pady=(6, 0))
        DateEntry(form, self.med_end_var, width=12).grid(row=1, column=1, sticky="ew", padx=(4, 10), pady=(6, 0))
        ttk.Label(form, text="Комментарий").grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Entry(form, textvariable=self.med_comment_var).grid(
            row=1, column=3, sticky="ew", padx=(4, 10), pady=(6, 0)
        )
        ttk.Button(form, text="Добавить препарат", command=self.add_prescription_from_dashboard).grid(
            row=1, column=4, sticky="e", pady=(6, 0)
        )
        ttk.Button(form, text="Сохранить", command=self.save_selected_prescription).grid(
            row=2, column=3, sticky="e", padx=(4, 10), pady=(6, 0)
        )
        ttk.Button(form, text="Удалить", command=self.delete_selected_prescription).grid(
            row=2, column=4, sticky="e", pady=(6, 0)
        )

    def _build_protocols(self) -> None:
        frame = ttk.LabelFrame(self.dashboard, text="7. Подробности сеансов", padding=8)
        frame.grid(row=6, column=0, sticky="nsew", pady=4)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)
        self.protocol_tree = ttk.Treeview(frame, columns=("date", "title"), show="headings", height=8)
        self.protocol_tree.heading("date", text="Дата")
        self.protocol_tree.heading("title", text="Сеанс")
        self.protocol_tree.column("date", width=100, anchor="w")
        self.protocol_tree.column("title", width=260, anchor="w")
        self.protocol_tree.grid(row=0, column=0, rowspan=3, sticky="nsw", padx=(0, 8))
        self.protocol_tree.bind("<<TreeviewSelect>>", self.on_protocol_select)
        ttk.Entry(frame, textvariable=self.protocol_title_var).grid(row=0, column=1, sticky="ew")
        self.protocol_text = tk.Text(frame, height=14, wrap="word")
        self.protocol_text.grid(row=1, column=1, sticky="nsew", pady=4)
        ttk.Button(frame, text="Сохранить текст", command=self.save_protocol_text).grid(row=2, column=1, sticky="w")

    def refresh_references(self) -> None:
        diagnoses = self.repo.list_reference("diagnoses")
        self.diagnosis_options = {format_diagnosis(row): row for row in diagnoses}
        self.diagnosis_combo.configure(values=list(self.diagnosis_options))
        group_names = [row["name"] for row in self.repo.list_reference("groups")]
        self.group_combo.configure(values=group_names)
        self.med_combo.configure(values=[row["name"] for row in self.repo.list_reference("medications")])

    def on_diagnosis_select(self, _event: Any | None = None) -> None:
        row = self.diagnosis_options.get(self.diagnosis_var.get())
        if not row:
            self.diagnosis_code_var.set("")
            self.diagnosis_text_var.set(self.diagnosis_var.get())
            return
        self.diagnosis_code_var.set(row.get("code") or "")
        self.diagnosis_text_var.set(row.get("description") or row.get("name") or "")

    def refresh_patients(self) -> None:
        self.patient_tree.delete(*self.patient_tree.get_children())
        patients = self.repo.list_patients(self.search_var.get())
        for patient in patients:
            name = f"{patient['last_name']} {patient['first_name']} {patient['middle_name']}".strip()
            self.patient_tree.insert("", "end", iid=str(patient["id"]), text=name, values=(patient["birth_date"],))
        if self.search_var.get().strip() and len(patients) == 1:
            patient_id = int(patients[0]["id"])
            self.patient_tree.selection_set(str(patient_id))
            self.patient_tree.focus(str(patient_id))
            if self.selected_patient_id != patient_id:
                self.selected_patient_id = patient_id
                self.load_patient()

    def refresh_all(self) -> None:
        self.refresh_references()
        self.refresh_patients()
        if self.selected_patient_id:
            self.load_patient()

    def _on_patient_select(self, _event: Any) -> None:
        selection = self.patient_tree.selection()
        if not selection:
            return
        self.selected_patient_id = int(selection[0])
        self.load_patient()

    def new_patient(self) -> None:
        self.selected_patient_id = None
        self.current_card = None
        self.patient_tree.selection_remove(self.patient_tree.selection())
        for var in self.patient_vars.values():
            var.set("")
        self.diagnosis_var.set("")
        self.diagnosis_code_var.set("")
        self.diagnosis_text_var.set("")
        self.diagnosis_date_var.set("")
        self.clear_dashboard_tables()

    def clear_dashboard_tables(self) -> None:
        for col in self.hads_vars:
            for var in col.values():
                var.set("")
        self.render_visits_matrix([])
        self.load_patient_groups([])
        self.prescription_tree.delete(*self.prescription_tree.get_children())
        self.selected_prescription_id = None
        self.protocol_tree.delete(*self.protocol_tree.get_children())
        self.protocol_text.delete("1.0", "end")
        self.protocol_title_var.set("")

    def load_patient(self) -> None:
        if not self.selected_patient_id:
            return
        patient = self.repo.get_patient(self.selected_patient_id)
        if not patient:
            return
        year = self.card_year(patient)
        self.year_var.set(str(year))
        self.current_card = self.repo.annual_card(self.selected_patient_id, year)
        for key, var in self.patient_vars.items():
            var.set(patient.get(key) or "")

        diagnoses = self.current_card["diagnoses"]
        if diagnoses:
            latest = diagnoses[0]
            display = self.format_patient_diagnosis(latest)
            self.diagnosis_var.set(display)
            self.diagnosis_code_var.set(latest.get("diagnosis_code") or "")
            self.diagnosis_text_var.set(
                latest.get("diagnosis_description") or latest.get("diagnosis_name") or latest["diagnosis_text"]
            )
            self.diagnosis_date_var.set(latest["set_date"])
        else:
            self.diagnosis_var.set("")
            self.diagnosis_code_var.set("")
            self.diagnosis_text_var.set("")
            self.diagnosis_date_var.set("")

        self.load_hads(self.current_card["hads"])
        self.load_patient_groups(self.current_card["groups"])
        self.render_visits_matrix(self.current_card["schedule"])
        self.load_prescriptions(self.current_card["prescriptions"])
        self.load_protocols(self.current_card["protocols"])

    def reload_card(self) -> None:
        if not self.selected_patient_id:
            return
        self.load_patient()

    def format_patient_diagnosis(self, row: dict[str, Any]) -> str:
        code = str(row.get("diagnosis_code") or "").strip()
        name = str(row.get("diagnosis_name") or row.get("diagnosis_text") or "").strip()
        if code and name:
            return f"{code} — {name}"
        return name

    def card_year(self, patient: dict[str, Any]) -> int:
        if self.year_var.get().strip().isdigit():
            return int(self.year_var.get().strip())
        source = patient.get("first_visit_date") or date.today().isoformat()
        try:
            return int(normalize_date(source, required=False)[:4])
        except (ValueError, TypeError):
            return date.today().year

    def save_patient(self) -> None:
        data = {
            "last_name": self.patient_vars["last_name"].get().strip(),
            "first_name": self.patient_vars["first_name"].get().strip(),
            "middle_name": self.patient_vars["middle_name"].get().strip(),
            "birth_date": self.patient_vars["birth_date"].get().strip(),
            "address": self.patient_vars["address"].get().strip(),
            "first_visit_date": self.patient_vars["first_visit_date"].get().strip(),
            "passport": "",
            "phone": "",
            "notes": "",
        }
        if not data["last_name"] or not data["first_name"]:
            messagebox.showerror("Ошибка", "Фамилия и имя обязательны.")
            return
        try:
            self.selected_patient_id = self.repo.save_patient(data, self.selected_patient_id)
            if self.diagnosis_var.get().strip():
                self.repo.add_diagnosis(
                    self.selected_patient_id,
                    self.diagnosis_var.get().strip(),
                    self.patient_vars["first_visit_date"].get().strip() or date.today().isoformat(),
                )
        except ValueError as exc:
            messagebox.showerror("Ошибка", str(exc))
            return
        self.refresh_patients()
        self.patient_tree.selection_set(str(self.selected_patient_id))
        self.load_patient()

    def delete_patient(self) -> None:
        if not self.selected_patient_id:
            return
        if not messagebox.askyesno("Удалить пациента", "Удалить выбранного пациента и все связанные записи?"):
            return
        self.repo.delete_patient(self.selected_patient_id)
        self.new_patient()
        self.refresh_patients()

    def require_patient(self) -> int | None:
        if not self.selected_patient_id:
            messagebox.showwarning("Пациент не выбран", "Сначала выберите или сохраните пациента.")
            return None
        return self.selected_patient_id

    def load_hads(self, rows: list[dict[str, Any]]) -> None:
        for col in self.hads_vars:
            for var in col.values():
                var.set("")
        year = int(self.year_var.get())
        filtered = [row for row in rows if str(row["test_date"]).startswith(str(year))]
        for idx, row in enumerate(sorted(filtered, key=lambda item: item["test_date"])[:YEAR_COLUMNS]):
            self.hads_vars[idx]["date"].set(row["test_date"])
            self.hads_vars[idx]["anxiety"].set(str(row["anxiety"]))
            self.hads_vars[idx]["depression"].set(str(row["depression"]))

    def save_hads(self) -> None:
        patient_id = self.require_patient()
        if not patient_id:
            return
        try:
            for col in self.hads_vars:
                test_date = col["date"].get().strip()
                if not test_date:
                    continue
                anxiety = int(col["anxiety"].get().strip() or "0")
                depression = int(col["depression"].get().strip() or "0")
                self.repo.upsert_hads(patient_id, test_date, anxiety, depression)
        except ValueError as exc:
            messagebox.showerror("Ошибка HADS", str(exc))
            return
        self.load_patient()

    def matrix_rows(self, schedule: list[dict[str, Any]]) -> list[str]:
        base = ["Плановые осмотры", "Индивидуальная ПТ", "Гипнотерапия"]
        groups = [row["name"] for row in (self.current_card or {}).get("groups", [])]
        labels = base + groups
        for item in schedule:
            label = self.matrix_label(item)
            if label not in labels:
                labels.append(label)
        return labels

    def matrix_label(self, item: dict[str, Any]) -> str:
        title = self.event_name(item)
        folded = title.casefold()
        if "осмотр" in folded or "наблюдение" in folded:
            return "Плановые осмотры"
        if "гипно" in folded:
            return "Гипнотерапия"
        if "групп" in folded:
            return title
        if "индивиду" in folded or "пт" in folded:
            return "Индивидуальная ПТ"
        return title

    def render_visits_matrix(self, schedule: list[dict[str, Any]]) -> None:
        for child in self.visits_matrix_frame.winfo_children():
            child.destroy()
        self.matrix_event_ids.clear()
        rows = self.matrix_rows(schedule)
        self.manual_visit_row_combo.configure(values=rows)
        events_by_label: dict[str, list[dict[str, Any]]] = {label: [] for label in rows}
        for item in schedule:
            events_by_label.setdefault(self.matrix_label(item), []).append(item)
        column_count = max(
            YEAR_COLUMNS,
            *(len(items) for items in events_by_label.values()),
        )
        ttk.Label(self.visits_matrix_frame, text="Вид сеанса", width=24, font=("", 10, "bold")).grid(row=0, column=0, sticky="ew")
        for col in range(column_count):
            ttk.Label(self.visits_matrix_frame, text=str(col + 1), width=10, anchor="center").grid(row=0, column=col + 1)
        for row_idx, label in enumerate(rows, start=1):
            ttk.Label(self.visits_matrix_frame, text=label, width=24, font=("", 10, "bold")).grid(row=row_idx, column=0, sticky="w")
            events = sorted(events_by_label.get(label, []), key=lambda item: (item["event_date"], item["event_time"]))
            for col_idx in range(column_count):
                text = ""
                fg = "#999999"
                event_id = None
                if col_idx < len(events):
                    event = events[col_idx]
                    text = self.short_date(event["event_date"])
                    fg = STATUS_COLORS.get(event["status"], "#111111")
                    event_id = int(event["id"])
                if event_id:
                    var = tk.StringVar(value=text)
                    cell = tk.Entry(
                        self.visits_matrix_frame,
                        textvariable=var,
                        width=10,
                        fg=fg,
                        relief="solid",
                        borderwidth=1,
                        justify="center",
                    )
                    cell.grid(row=row_idx, column=col_idx + 1, sticky="nsew")
                    cell.bind(
                        "<FocusOut>",
                        lambda _event, eid=event_id, value=var: self.update_matrix_event_date(eid, value.get()),
                    )
                    cell.bind(
                        "<Return>",
                        lambda _event, eid=event_id, value=var: self.update_matrix_event_date(eid, value.get()),
                    )
                    cell.bind("<Double-Button-1>", lambda event, eid=event_id: self.show_status_menu(event, eid))
                    cell.bind("<Button-3>", lambda event, eid=event_id: self.show_status_menu(event, eid))
                    cell.bind("<Control-Button-1>", lambda event, eid=event_id: self.show_status_menu(event, eid))
                    continue
                cell = tk.Label(
                    self.visits_matrix_frame,
                    text=text,
                    width=10,
                    relief="solid",
                    borderwidth=1,
                    fg=fg,
                    bg="white",
                    padx=3,
                    pady=2,
                )
                cell.grid(row=row_idx, column=col_idx + 1, sticky="nsew")

    def update_matrix_event_date(self, event_id: int, value: str) -> str:
        try:
            self.repo.update_schedule_event_date(event_id, value)
        except ValueError as exc:
            messagebox.showerror("Ошибка даты", str(exc))
            self.load_patient()
            return "break"
        self.load_patient()
        return "break"

    def show_status_menu(self, event: tk.Event, event_id: int) -> None:
        menu = tk.Menu(self, tearoff=False)
        for status, label in STATUS_LABELS.items():
            menu.add_command(label=label, command=lambda s=status: self.set_event_status(event_id, s))
        menu.add_separator()
        menu.add_command(label="Очистить дату", command=lambda: self.clear_event(event_id))
        menu.tk_popup(event.x_root, event.y_root)

    def set_event_status(self, event_id: int, status: str) -> None:
        self.repo.set_schedule_event_status(event_id, status)
        self.load_patient()

    def clear_event(self, event_id: int) -> None:
        if messagebox.askyesno("Очистить дату", "Удалить эту дату из плана пациента?"):
            self.repo.clear_schedule_event(event_id)
            self.load_patient()

    def add_matrix_event(self) -> None:
        patient_id = self.require_patient()
        if not patient_id:
            return
        try:
            self.repo.upsert_matrix_event(
                patient_id,
                self.manual_visit_row_var.get(),
                self.manual_visit_date_var.get(),
                self.status_key(self.manual_visit_status_var.get()),
            )
        except ValueError as exc:
            messagebox.showerror("Ошибка даты", str(exc))
            return
        self.load_patient()

    def plan_course(self) -> None:
        patient_id = self.require_patient()
        if not patient_id:
            return
        try:
            self.repo.add_therapy_course(
                patient_id,
                self.plan_mode_var.get(),
                self.plan_date_var.get(),
                self.plan_time_var.get(),
                int(self.plan_count_var.get() or "0"),
            )
        except ValueError as exc:
            messagebox.showerror("Ошибка планирования", str(exc))
            return
        self.load_patient()

    def plan_group(self) -> None:
        patient_id = self.require_patient()
        if not patient_id:
            return
        group = self.group_var.get().strip()
        if not group:
            messagebox.showwarning("Группа", "Выберите или введите группу.")
            return
        try:
            self.repo.add_patient_group(patient_id, group, self.group_date_var.get())
            self.repo.add_therapy_course(
                patient_id,
                group,
                self.group_date_var.get(),
                "",
                int(self.group_count_var.get() or "0"),
            )
        except ValueError as exc:
            messagebox.showerror("Ошибка группы", str(exc))
            return
        self.refresh_references()
        self.load_patient()

    def load_patient_groups(self, rows: list[dict[str, Any]]) -> None:
        self.patient_group_tree.delete(*self.patient_group_tree.get_children())
        for row in rows:
            self.patient_group_tree.insert("", "end", iid=str(row["id"]), values=(row["name"], row["joined_date"]))

    def on_patient_group_select(self, _event: Any) -> None:
        selection = self.patient_group_tree.selection()
        if not selection:
            return
        values = self.patient_group_tree.item(selection[0], "values")
        if values:
            self.group_var.set(values[0])

    def remove_patient_group(self) -> None:
        patient_id = self.require_patient()
        if not patient_id:
            return
        selection = self.patient_group_tree.selection()
        if not selection:
            messagebox.showwarning("Группа", "Выберите группу пациента.")
            return
        group_name = self.patient_group_tree.item(selection[0], "values")[0]
        if not messagebox.askyesno(
            "Удалить группу",
            "Удалить группу из пациента? Запланированные даты этой группы тоже будут удалены.",
        ):
            return
        self.repo.remove_patient_group(patient_id, group_name)
        self.load_patient()

    def load_prescriptions(self, rows: list[dict[str, Any]]) -> None:
        self.prescription_tree.delete(*self.prescription_tree.get_children())
        self.selected_prescription_id = None
        for row in rows:
            self.prescription_tree.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(row["start_date"], row["prescription_text"], row["end_date"], row["comment"]),
            )

    def on_prescription_select(self, _event: Any) -> None:
        selection = self.prescription_tree.selection()
        if not selection:
            return
        self.selected_prescription_id = int(selection[0])
        start_date, prescription, end_date, comment = self.prescription_tree.item(selection[0], "values")
        self.med_date_var.set(start_date)
        self.med_name_var.set(prescription)
        self.med_end_var.set(end_date)
        self.med_comment_var.set(comment)

    def add_prescription_from_dashboard(self) -> None:
        patient_id = self.require_patient()
        if not patient_id:
            return
        if not self.med_name_var.get().strip():
            messagebox.showwarning("Препарат", "Выберите или введите препарат.")
            return
        try:
            self.repo.add_prescription(
                patient_id,
                self.med_name_var.get().strip(),
                self.med_date_var.get().strip(),
                self.med_end_var.get().strip(),
                self.med_comment_var.get().strip(),
            )
        except ValueError as exc:
            messagebox.showerror("Ошибка препарата", str(exc))
            return
        self.med_name_var.set("")
        self.med_end_var.set("")
        self.med_comment_var.set("")
        self.load_patient()

    def save_selected_prescription(self) -> None:
        if not self.selected_prescription_id:
            messagebox.showwarning("Препарат", "Выберите назначение в таблице.")
            return
        if not self.med_name_var.get().strip():
            messagebox.showwarning("Препарат", "Выберите или введите препарат.")
            return
        try:
            self.repo.update_prescription(
                self.selected_prescription_id,
                self.med_name_var.get().strip(),
                self.med_date_var.get().strip(),
                self.med_end_var.get().strip(),
                self.med_comment_var.get().strip(),
            )
        except ValueError as exc:
            messagebox.showerror("Ошибка препарата", str(exc))
            return
        self.load_patient()

    def delete_selected_prescription(self) -> None:
        if not self.selected_prescription_id:
            messagebox.showwarning("Препарат", "Выберите назначение в таблице.")
            return
        if not messagebox.askyesno("Удалить назначение", "Удалить выбранное назначение?"):
            return
        self.repo.delete_prescription(self.selected_prescription_id)
        self.med_name_var.set("")
        self.med_end_var.set("")
        self.med_comment_var.set("")
        self.load_patient()

    def load_protocols(self, rows: list[dict[str, Any]]) -> None:
        self.protocol_tree.delete(*self.protocol_tree.get_children())
        self.protocol_row_ids.clear()
        for row in rows:
            iid = str(row["id"])
            self.protocol_row_ids[iid] = int(row["id"])
            self.protocol_tree.insert("", "end", iid=iid, values=(row["protocol_date"], row["title"]))
        self.protocol_text.delete("1.0", "end")
        self.protocol_title_var.set("")

    def on_protocol_select(self, _event: Any) -> None:
        selection = self.protocol_tree.selection()
        if not selection or not self.current_card:
            return
        protocol_id = int(selection[0])
        row = next((item for item in self.current_card["protocols"] if int(item["id"]) == protocol_id), None)
        if not row:
            return
        self.protocol_title_var.set(row["title"])
        self.protocol_text.delete("1.0", "end")
        self.protocol_text.insert("1.0", row["body"])

    def save_protocol_text(self) -> None:
        selection = self.protocol_tree.selection()
        if not selection:
            messagebox.showwarning("Протокол", "Выберите протокол.")
            return
        self.repo.update_protocol_body(
            int(selection[0]),
            self.protocol_title_var.get().strip() or "Протокол сессии",
            self.protocol_text.get("1.0", "end").strip(),
        )
        self.load_patient()

    def open_references(self) -> None:
        window = tk.Toplevel(self)
        window.title("Справочники")
        window.geometry("860x520")
        notebook = ttk.Notebook(window)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)
        self.build_diagnoses_tab(notebook)
        for table, title in [
            ("medications", "Препараты"),
            ("groups", "Группы"),
            ("therapy_types", "Виды ПТ"),
        ]:
            frame = ttk.Frame(notebook, padding=8)
            notebook.add(frame, text=title)
            frame.columnconfigure(0, weight=1)
            tree = ttk.Treeview(frame, columns=("name",), show="headings", height=14)
            tree.heading("name", text="Название")
            tree.column("name", width=640)
            tree.grid(row=0, column=0, sticky="nsew")
            frame.rowconfigure(0, weight=1)
            for row in self.repo.list_reference(table):
                tree.insert("", "end", values=(row["name"],))
            value = tk.StringVar()
            ttk.Entry(frame, textvariable=value).grid(row=1, column=0, sticky="ew", pady=(8, 0))
            ttk.Button(frame, text="Добавить", command=lambda t=table, v=value, tr=tree: self.add_reference(t, v, tr)).grid(
                row=2, column=0, sticky="w", pady=(6, 0)
            )
        self.build_schedule_slots_tab(notebook)

    def build_diagnoses_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text="Диагнозы")
        frame.columnconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=("code", "name", "description"), show="headings", height=14)
        for col, heading, width in [
            ("code", "Код", 90),
            ("name", "Название", 280),
            ("description", "Расшифровка", 420),
        ]:
            tree.heading(col, text=heading)
            tree.column(col, width=width)
        tree.grid(row=0, column=0, columnspan=4, sticky="nsew")
        frame.rowconfigure(0, weight=1)
        for row in self.repo.list_reference("diagnoses"):
            tree.insert("", "end", values=(row.get("code", ""), row["name"], row.get("description", "")))

        code_var = tk.StringVar()
        name_var = tk.StringVar()
        description_var = tk.StringVar()
        ttk.Entry(frame, textvariable=code_var, width=12).grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Entry(frame, textvariable=name_var).grid(row=1, column=1, sticky="ew", padx=4, pady=(8, 0))
        ttk.Entry(frame, textvariable=description_var).grid(row=1, column=2, sticky="ew", pady=(8, 0))
        ttk.Button(
            frame,
            text="Добавить/обновить",
            command=lambda: self.add_diagnosis_reference(code_var, name_var, description_var, tree),
        ).grid(row=1, column=3, sticky="w", padx=(6, 0), pady=(8, 0))

    def add_diagnosis_reference(
        self,
        code_var: tk.StringVar,
        name_var: tk.StringVar,
        description_var: tk.StringVar,
        tree: ttk.Treeview,
    ) -> None:
        try:
            self.repo.add_diagnosis_reference(code_var.get(), name_var.get(), description_var.get())
        except ValueError as exc:
            messagebox.showerror("Ошибка диагноза", str(exc))
            return
        tree.delete(*tree.get_children())
        for row in self.repo.list_reference("diagnoses"):
            tree.insert("", "end", values=(row.get("code", ""), row["name"], row.get("description", "")))
        code_var.set("")
        name_var.set("")
        description_var.set("")
        self.refresh_references()

    def build_schedule_slots_tab(self, notebook: ttk.Notebook) -> None:
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text="Рабочие слоты")
        frame.columnconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=("weekday", "time", "slots", "label"), show="headings", height=15)
        for col, heading, width in [("weekday", "День", 130), ("time", "Время", 90), ("slots", "Слоты", 90), ("label", "Комментарий", 360)]:
            tree.heading(col, text=heading)
            tree.column(col, width=width)
        tree.grid(row=0, column=0, columnspan=4, sticky="nsew")
        for row in self.repo.list_reference("schedule_slots"):
            tree.insert("", "end", values=(WEEKDAY_NAMES[int(row["weekday"])], row["start_time"], row["slots"], row["label"]))
        weekday = tk.StringVar(value=WEEKDAY_NAMES[0])
        start_time = tk.StringVar(value="09:00")
        slots = tk.StringVar(value="1")
        label = tk.StringVar()
        ttk.Combobox(frame, textvariable=weekday, values=WEEKDAY_NAMES, state="readonly").grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Entry(frame, textvariable=start_time, width=10).grid(row=1, column=1, pady=(8, 0))
        ttk.Combobox(frame, textvariable=slots, values=("1", "2", "3", "4"), width=6).grid(row=1, column=2, pady=(8, 0))
        ttk.Entry(frame, textvariable=label).grid(row=1, column=3, sticky="ew", pady=(8, 0))

        def add_slot() -> None:
            try:
                self.repo.add_schedule_slot(WEEKDAY_NAMES.index(weekday.get()), start_time.get(), int(slots.get()), label.get())
            except ValueError as exc:
                messagebox.showerror("Ошибка", str(exc), parent=frame)
                return
            tree.insert("", "end", values=(weekday.get(), normalize_time(start_time.get()), slots.get(), label.get()))

        ttk.Button(frame, text="Добавить слот", command=add_slot).grid(row=2, column=0, sticky="w", pady=(8, 0))

    def add_reference(self, table: str, value: tk.StringVar, tree: ttk.Treeview) -> None:
        name = value.get().strip()
        if not name:
            return
        self.repo.add_reference(table, name)
        tree.insert("", "end", values=(name,))
        value.set("")
        self.refresh_references()

    @staticmethod
    def short_date(value: str) -> str:
        try:
            normalized = normalize_date(value)
            return f"{normalized[8:10]}.{normalized[5:7]}.{normalized[2:4]}"
        except ValueError:
            return value

    @staticmethod
    def format_status(status: str) -> str:
        return STATUS_LABELS.get(status, status)

    @staticmethod
    def status_key(status: str) -> str:
        return STATUS_BY_LABEL.get(status, status)

    @staticmethod
    def format_slots(slots: Any) -> str:
        try:
            value = int(slots or 1)
        except (TypeError, ValueError):
            value = 1
        return f"{value} слот ({value * 30} мин)"

    @staticmethod
    def patient_name_from_schedule(row: dict[str, Any]) -> str:
        parts = [row.get("last_name") or "", row.get("first_name") or "", row.get("middle_name") or ""]
        return " ".join(part for part in parts if part).strip() or "Без пациента"

    @staticmethod
    def event_name(row: dict[str, Any]) -> str:
        title = row.get("title") or ""
        if " - " in title:
            return title.split(" - ", 1)[1].strip() or "Событие"
        return title or "Событие"
