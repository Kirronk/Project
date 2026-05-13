from __future__ import annotations

import calendar
import tkinter as tk
from datetime import date, datetime
from tkinter import ttk

from validation import is_valid_optional_date, normalize_date


class DateEntry(ttk.Frame):
    def __init__(self, master, textvariable: tk.StringVar, required: bool = False, width: int = 18):
        super().__init__(master)
        self.variable = textvariable
        self.required = required
        self.entry = tk.Entry(self, textvariable=textvariable, width=width)
        self.entry.pack(side="left", fill="x", expand=True)
        ttk.Button(self, text="...", width=3, command=self.open_calendar).pack(side="left", padx=(4, 0))
        self.variable.trace_add("write", lambda *_args: self._mark_validity())
        self.entry.bind("<FocusOut>", self._normalize_on_focus_out)
        self._mark_validity()

    def open_calendar(self) -> None:
        CalendarPopup(self, self.variable, self.required)

    def get(self) -> str:
        return self.variable.get().strip()

    def _normalize_on_focus_out(self, _event=None) -> None:
        value = self.variable.get().strip()
        if not value:
            self._mark_validity()
            return
        try:
            self.variable.set(normalize_date(value, required=self.required))
        except ValueError:
            self._mark_validity()

    def _mark_validity(self) -> None:
        value = self.variable.get().strip()
        valid = is_valid_optional_date(value) and (value or not self.required)
        self.entry.configure(bg="white" if valid else "#ffd6d6")


class CalendarPopup(tk.Toplevel):
    def __init__(self, master, variable: tk.StringVar, required: bool = False):
        super().__init__(master)
        self.variable = variable
        self.required = required
        self.title("Выбор даты")
        self.transient(master.winfo_toplevel())
        self.resizable(False, False)

        current = self._current_date()
        self.year = current.year
        self.month = current.month

        self.header = ttk.Frame(self, padding=8)
        self.header.grid(row=0, column=0, sticky="ew")
        ttk.Button(self.header, text="<", width=3, command=self.prev_month).pack(side="left")
        self.title_var = tk.StringVar()
        ttk.Label(self.header, textvariable=self.title_var, width=18, anchor="center").pack(side="left", padx=6)
        ttk.Button(self.header, text=">", width=3, command=self.next_month).pack(side="left")

        self.days = ttk.Frame(self, padding=(8, 0, 8, 8))
        self.days.grid(row=1, column=0)

        footer = ttk.Frame(self, padding=(8, 0, 8, 8))
        footer.grid(row=2, column=0, sticky="ew")
        ttk.Button(footer, text="Сегодня", command=lambda: self.select(date.today())).pack(side="left")
        ttk.Button(footer, text="Очистить", command=self.clear).pack(side="left", padx=(6, 0))

        self.render()
        self.grab_set()
        self.wait_visibility()

    def _current_date(self) -> date:
        text = self.variable.get().strip()
        if text:
            try:
                return datetime.strptime(normalize_date(text, required=False), "%Y-%m-%d").date()
            except ValueError:
                pass
        return date.today()

    def prev_month(self) -> None:
        self.month -= 1
        if self.month == 0:
            self.month = 12
            self.year -= 1
        self.render()

    def next_month(self) -> None:
        self.month += 1
        if self.month == 13:
            self.month = 1
            self.year += 1
        self.render()

    def render(self) -> None:
        for child in self.days.winfo_children():
            child.destroy()

        month_name = calendar.month_name[self.month]
        self.title_var.set(f"{month_name} {self.year}")
        for col, label in enumerate(("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")):
            ttk.Label(self.days, text=label, anchor="center", width=4).grid(row=0, column=col, pady=(0, 4))

        cal = calendar.Calendar(firstweekday=0)
        for row_index, week in enumerate(cal.monthdayscalendar(self.year, self.month), start=1):
            for col_index, day in enumerate(week):
                if day == 0:
                    ttk.Label(self.days, text="", width=4).grid(row=row_index, column=col_index)
                    continue
                value = date(self.year, self.month, day)
                ttk.Button(
                    self.days,
                    text=str(day),
                    width=4,
                    command=lambda selected=value: self.select(selected),
                ).grid(row=row_index, column=col_index, padx=1, pady=1)

    def select(self, value: date) -> None:
        self.variable.set(value.isoformat())
        self.destroy()

    def clear(self) -> None:
        if not self.required:
            self.variable.set("")
        self.destroy()
