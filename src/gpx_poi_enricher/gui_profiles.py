"""Qt UI: manage custom search profiles (edit, import, export, delete)."""

from __future__ import annotations

import dataclasses
from typing import Any

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .profiles import (
    SearchProfile,
    default_user_profiles_dir,
    delete_user_profile,
    dump_profile_yaml,
    load_all_profiles_with_sources,
    normalize_profile_id,
    profile_from_mapping,
    profile_from_yaml_text,
    save_profile,
    template_profile,
)


class _ProfileEditorDialog(QDialog):
    """Create or edit a profile using a form and/or raw YAML."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        profile: SearchProfile,
        id_editable: bool,
        title: str,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 520)
        self._id_editable = id_editable
        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._on_tab_changed)

        form = QWidget()
        form_l = QVBoxLayout(form)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form)

        fg = QFormLayout()
        self._id_edit = QLineEdit(profile.id)
        self._id_edit.setReadOnly(not id_editable)
        self._id_edit.setPlaceholderText("letters, digits, underscore; start with a letter")
        self._desc_edit = QLineEdit(profile.description)
        self._symbol_edit = QLineEdit(profile.symbol)

        self._max_km = QDoubleSpinBox()
        self._max_km.setRange(0.1, 500.0)
        self._max_km.setDecimals(2)
        self._max_km.setValue(profile.max_km)

        self._sample_km = QDoubleSpinBox()
        self._sample_km.setRange(0.1, 500.0)
        self._sample_km.setDecimals(2)
        self._sample_km.setValue(profile.sample_km)

        self._batch_size = QSpinBox()
        self._batch_size.setRange(1, 200)
        self._batch_size.setValue(profile.batch_size)

        self._retries = QSpinBox()
        self._retries.setRange(0, 20)
        self._retries.setValue(profile.retries)

        self._early_cancel = QCheckBox("Stop early after consecutive empty batches")
        self._early_cancel.setChecked(profile.early_cancel_if_no_pois)

        self._early_after = QSpinBox()
        self._early_after.setRange(1, 99)
        self._early_after.setValue(profile.early_cancel_after_batches)

        self._must_match = QCheckBox("Require OSM tags AND matching name text (stricter)")
        self._must_match.setChecked(profile.must_match_terms)

        fg.addRow("Id:", self._id_edit)
        fg.addRow("Description:", self._desc_edit)
        fg.addRow("GPX symbol:", self._symbol_edit)
        fg.addRow("max_km:", self._max_km)
        fg.addRow("sample_km:", self._sample_km)
        fg.addRow("batch_size:", self._batch_size)
        fg.addRow("retries:", self._retries)
        fg.addRow("", self._early_cancel)
        fg.addRow("early_cancel_after_batches:", self._early_after)
        fg.addRow("", self._must_match)

        tags_box = QGroupBox("OSM tags (key / value — e.g. tourism / camp_site)")
        tags_outer = QVBoxLayout(tags_box)
        self._tags_table = QTableWidget(0, 2)
        self._tags_table.setHorizontalHeaderLabels(["key", "value"])
        self._tags_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for t in profile.tags:
            self._add_tag_row(str(t.get("key", "")), str(t.get("value", "")))
        if self._tags_table.rowCount() == 0:
            self._add_tag_row("", "")
        tags_btns = QHBoxLayout()
        add_tag = QPushButton("Add tag row")
        add_tag.clicked.connect(lambda: self._add_tag_row("", ""))
        tags_btns.addWidget(add_tag)
        rem_tag = QPushButton("Remove selected row")
        rem_tag.clicked.connect(self._remove_tag_row)
        tags_btns.addWidget(rem_tag)
        tags_outer.addWidget(self._tags_table)
        tags_outer.addLayout(tags_btns)

        terms_box = QGroupBox("Search terms by language (ISO code, e.g. DE, EN)")
        terms_outer = QVBoxLayout(terms_box)
        self._terms_table = QTableWidget(0, 2)
        self._terms_table.setHorizontalHeaderLabels(["language", "terms (comma-separated)"])
        self._terms_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for lang, terms in sorted(profile.terms.items()):
            self._add_term_row(lang, ", ".join(terms))
        if self._terms_table.rowCount() == 0:
            self._add_term_row("EN", "")
        tb = QHBoxLayout()
        add_t = QPushButton("Add language row")
        add_t.clicked.connect(lambda: self._add_term_row("", ""))
        tb.addWidget(add_t)
        rem_t = QPushButton("Remove selected row")
        rem_t.clicked.connect(self._remove_term_row)
        tb.addWidget(rem_t)
        terms_outer.addWidget(self._terms_table)
        terms_outer.addLayout(tb)

        form_l.addLayout(fg)
        form_l.addWidget(tags_box)
        form_l.addWidget(terms_box)

        self._yaml_edit = QPlainTextEdit()
        self._yaml_edit.setPlainText(dump_profile_yaml(profile))

        self._tabs.addTab(scroll, "Form")
        self._tabs.addTab(self._yaml_edit, "YAML")

        root = QVBoxLayout(self)
        root.addWidget(self._tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._result_profile: SearchProfile | None = None

    def _on_tab_changed(self, idx: int) -> None:
        if idx == 1:
            try:
                p = self._read_from_form()
                self._yaml_edit.setPlainText(dump_profile_yaml(p))
            except Exception:
                pass

    def _add_tag_row(self, k: str, v: str) -> None:
        r = self._tags_table.rowCount()
        self._tags_table.insertRow(r)
        self._tags_table.setItem(r, 0, QTableWidgetItem(k))
        self._tags_table.setItem(r, 1, QTableWidgetItem(v))

    def _remove_tag_row(self) -> None:
        r = self._tags_table.currentRow()
        if r >= 0:
            self._tags_table.removeRow(r)

    def _add_term_row(self, lang: str, terms: str) -> None:
        r = self._terms_table.rowCount()
        self._terms_table.insertRow(r)
        self._terms_table.setItem(r, 0, QTableWidgetItem(lang))
        self._terms_table.setItem(r, 1, QTableWidgetItem(terms))

    def _remove_term_row(self) -> None:
        r = self._terms_table.currentRow()
        if r >= 0:
            self._terms_table.removeRow(r)

    def _read_from_form(self) -> SearchProfile:
        if self._id_editable:
            pid = normalize_profile_id(self._id_edit.text())
        else:
            pid = self._id_edit.text().strip().lower()
            if not pid:
                raise ValueError("Profile id is empty.")
        tags: list[dict[str, Any]] = []
        for row in range(self._tags_table.rowCount()):
            k = self._tags_table.item(row, 0)
            v = self._tags_table.item(row, 1)
            ks = k.text().strip() if k else ""
            vs = v.text().strip() if v else ""
            if ks and vs:
                tags.append({"key": ks, "value": vs})
        terms: dict[str, list[str]] = {}
        for row in range(self._terms_table.rowCount()):
            li = self._terms_table.item(row, 0)
            ti = self._terms_table.item(row, 1)
            lang = li.text().strip().upper() if li else ""
            raw = ti.text().strip() if ti else ""
            if not lang:
                continue
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            if parts:
                terms[lang] = parts
        data: dict[str, Any] = {
            "id": pid,
            "description": self._desc_edit.text().strip() or pid,
            "symbol": self._symbol_edit.text().strip() or "Pin",
            "defaults": {
                "max_km": float(self._max_km.value()),
                "sample_km": float(self._sample_km.value()),
                "batch_size": int(self._batch_size.value()),
                "retries": int(self._retries.value()),
                "early_cancel_if_no_pois": self._early_cancel.isChecked(),
                "early_cancel_after_batches": int(self._early_after.value()),
            },
            "tags": tags,
            "terms": terms,
            "must_match_terms": self._must_match.isChecked(),
        }
        return profile_from_mapping(data, path_hint="form")

    def _on_save(self) -> None:
        try:
            if self._tabs.currentIndex() == 1:
                prof = profile_from_yaml_text(self._yaml_edit.toPlainText())
                if not self._id_editable:
                    locked = self._id_edit.text().strip().lower()
                    prof = dataclasses.replace(prof, id=locked)
                else:
                    prof = dataclasses.replace(prof, id=normalize_profile_id(prof.id))
            else:
                prof = self._read_from_form()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid profile", str(exc))
            return
        self._result_profile = prof
        self.accept()

    def result_profile(self) -> SearchProfile | None:
        return self._result_profile


class ProfilesManagerTab(QWidget):
    """Expert tab: list profiles, edit user copies, import/export YAML."""

    profiles_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Id", "Description", "Storage"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        btn_row = QHBoxLayout()
        for label, slot in (
            ("New…", self._new),
            ("Edit…", self._edit),
            ("Duplicate…", self._duplicate),
            ("Delete", self._delete),
            ("Import YAML…", self._import),
            ("Export YAML…", self._export),
            ("Open user folder", self._open_user_dir),
        ):
            b = QPushButton(label)
            b.clicked.connect(slot)
            btn_row.addWidget(b)

        help_lbl = QLabel(
            "Built-in profiles ship with the app. Saving creates or updates a file in your "
            "user profile folder and overrides a built-in profile with the same id. "
            "Tags limit OSM objects; terms add free-text name search per language."
        )
        help_lbl.setWordWrap(True)

        root = QVBoxLayout(self)
        root.addWidget(self._table, 1)
        root.addLayout(btn_row)
        root.addWidget(help_lbl)
        self._refresh_table()

    def _selected_row(self) -> int:
        return self._table.currentRow()

    def _row_meta(self, row: int) -> tuple[str, str, str] | None:
        if row < 0 or row >= self._table.rowCount():
            return None
        id_item = self._table.item(row, 0)
        src_item = self._table.item(row, 2)
        if id_item is None or src_item is None:
            return None
        desc_item = self._table.item(row, 1)
        desc = desc_item.text() if desc_item else ""
        return id_item.text(), desc, src_item.data(Qt.ItemDataRole.UserRole) or src_item.text()

    def _refresh_table(self) -> None:
        self._table.setRowCount(0)
        meta = load_all_profiles_with_sources(None)
        for pid, (prof, src) in sorted(
            meta.items(), key=lambda x: (x[1][0].description.lower(), x[0])
        ):
            r = self._table.rowCount()
            self._table.insertRow(r)
            id_it = QTableWidgetItem(pid)
            self._table.setItem(r, 0, id_it)
            self._table.setItem(r, 1, QTableWidgetItem(prof.description))
            label = {"builtin": "Built-in", "user": "User", "profiles": "Folder"}.get(src, src)
            src_it = QTableWidgetItem(label)
            src_it.setData(Qt.ItemDataRole.UserRole, src)
            self._table.setItem(r, 2, src_it)
        if self._table.rowCount() > 0:
            self._table.selectRow(0)

    def _profile_by_id(self, pid: str) -> SearchProfile:
        m = load_all_profiles_with_sources(None)
        if pid not in m:
            raise KeyError(pid)
        return m[pid][0]

    def _new(self) -> None:
        dlg = _ProfileEditorDialog(
            self, profile=template_profile(), id_editable=True, title="New profile"
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        prof = dlg.result_profile()
        if prof is None:
            return
        try:
            save_profile(prof, None)
        except Exception as exc:
            QMessageBox.warning(self, "Could not save", str(exc))
            return
        self._after_save()

    def _edit(self) -> None:
        meta = self._row_meta(self._selected_row())
        if not meta:
            QMessageBox.information(self, "Profiles", "Select a profile row first.")
            return
        pid, _desc, src = meta
        try:
            prof = self._profile_by_id(pid)
        except KeyError:
            return
        dlg = _ProfileEditorDialog(
            self,
            profile=prof,
            id_editable=False,
            title=f"Edit profile: {pid}",
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_p = dlg.result_profile()
        if new_p is None:
            return
        try:
            save_profile(new_p, None)
        except Exception as exc:
            QMessageBox.warning(self, "Could not save", str(exc))
            return
        self._after_save()

    def _duplicate(self) -> None:
        meta = self._row_meta(self._selected_row())
        if not meta:
            QMessageBox.information(self, "Profiles", "Select a profile row first.")
            return
        pid, _desc, _src = meta
        try:
            prof = self._profile_by_id(pid)
        except KeyError:
            return
        copy = dataclasses.replace(prof, id=f"{pid}_copy")
        dlg = _ProfileEditorDialog(self, profile=copy, id_editable=True, title="Duplicate profile")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_p = dlg.result_profile()
        if new_p is None:
            return
        try:
            save_profile(new_p, None)
        except Exception as exc:
            QMessageBox.warning(self, "Could not save", str(exc))
            return
        self._after_save()

    def _delete(self) -> None:
        meta = self._row_meta(self._selected_row())
        if not meta:
            QMessageBox.information(self, "Profiles", "Select a profile row first.")
            return
        pid, _desc, src = meta
        if src != "user":
            QMessageBox.information(
                self,
                "Profiles",
                "Only user-saved profiles can be deleted. Built-ins are restored from the app.",
            )
            return
        if (
            QMessageBox.question(
                self,
                "Delete profile",
                f"Remove user profile “{pid}” from disk?",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        delete_user_profile(pid, None)
        self._after_save()

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import profile YAML", "", "YAML (*.yaml *.yml);;All files (*)"
        )
        if not path:
            return
        try:
            text = open(path, encoding="utf-8").read()
            prof = profile_from_yaml_text(text)
            dlg = _ProfileEditorDialog(
                self, profile=prof, id_editable=True, title="Import profile — review and save"
            )
        except Exception as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_p = dlg.result_profile()
        if new_p is None:
            return
        try:
            save_profile(new_p, None)
        except Exception as exc:
            QMessageBox.warning(self, "Could not save", str(exc))
            return
        self._after_save()

    def _export(self) -> None:
        meta = self._row_meta(self._selected_row())
        if not meta:
            QMessageBox.information(self, "Profiles", "Select a profile row first.")
            return
        pid, _desc, _src = meta
        try:
            prof = self._profile_by_id(pid)
        except KeyError:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export profile YAML", f"{pid}.yaml", "YAML (*.yaml);;All files (*)"
        )
        if not path:
            return
        try:
            open(path, "w", encoding="utf-8").write(dump_profile_yaml(prof))
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def _open_user_dir(self) -> None:
        d = default_user_profiles_dir()
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def _after_save(self) -> None:
        self._refresh_table()
        self.profiles_changed.emit()
