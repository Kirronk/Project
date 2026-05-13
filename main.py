from __future__ import annotations

from database import connect
from ui.app import PatientApp


def main() -> None:
    conn = connect()
    app = PatientApp(conn)
    app.mainloop()


if __name__ == "__main__":
    main()
