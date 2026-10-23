"""
generate_actions.py - Generate STEP/PDF (Part menu): the window, then making the files in the vault or in a folder
outside it; and making them straight after a release (run_releasing), which never holds the release up.
"""

from tkinter import messagebox

from litterbox.exporting import part_files_export
from litterbox.exporting import step_pdf
from litterbox.gui.dialogs import generate_files_dialog
from litterbox.gui.logic import action_rules
from litterbox.gui.logic import error_text
from litterbox.gui.logic import export_text
from litterbox.gui.logic import generate_text
from litterbox.parts import generate_files
from litterbox.user import settings


class GenerateActions:
    """Generate STEP/PDF, and the files made after a release. One part of the main window (App)."""

    def generate_step_pdf(self, pns=None):
        """The Generate STEP/PDF window for the ticked parts (or the highlighted one), or for `pns` (the Details
        tab's button)."""
        allowed, why = self.identity.allows("export_step_pdf")
        if not allowed:
            self._say(why, "warn")
            return
        if pns is None:
            plan = action_rules.plan_action("generate_step_pdf", self._selected_pns("generate_step_pdf"),
                                            self.rows_by_pn, self.jobs.pending_parts())
            if plan.message:
                self._say(plan.message, "warn")
                return
            pns = plan.targets
        rows = [self.rows_by_pn[pn] for pn in pns if pn in self.rows_by_pn]
        if not rows:
            return
        title = str(rows[0].pn) if len(rows) == 1 else f"{len(rows)} parts"
        answer = generate_files_dialog.GenerateFilesDialog(
            self, title, rows, export_text.start_folder(self.settings), settings.ROOT,
            may_vault=self.identity.allows(generate_files.GENERATE)[0],
            is_admin=self.identity.allows(generate_files.REMAKE)[0]).show()
        if answer is None:
            return
        if answer["where"] == generate_text.OUTSIDE:
            self._generate_outside(rows, answer)
        else:
            self._generate_in_vault(answer)

    def _generate_outside(self, rows, answer):
        repo, pns, kinds, folder = self.repo(), answer["pns"], answer["kinds"], answer["folder"]
        names = [step_pdf.target_name(row.pn, row.revision, kind) for row in rows if row.pn in pns
                 for kind in kinds if kind in step_pdf.possible_kinds(row.files)]
        clash = part_files_export.already_there(names, folder)
        if clash and not messagebox.askyesno("Generate STEP/PDF",
                                             export_text.replace_question(folder, clash, "the new files"),
                                             parent=self):
            return
        self._remember_export_folder(folder)

        def work():
            jobs, _notes = step_pdf.jobs_for(repo, pns, kinds)
            return step_pdf.make(repo, jobs, folder)

        self.run_task(work, "", on_success=lambda made: self._saved_outside(folder, made), refresh=False,
                      label="Making STEP/PDF")

    def _saved_outside(self, folder, made):
        self._say(generate_text.saved_text(folder, made), "warn" if made.errors else "normal")
        if made.errors:
            messagebox.showerror("Generate STEP/PDF", error_text.shorten(
                generate_text.failure_lines(list(made.errors.items()))))

    def _generate_in_vault(self, answer):
        repo, pns, kinds, force = self.repo(), answer["pns"], answer["kinds"], answer["force"]
        self.run_task(lambda: generate_files.generate(repo, pns, kinds, force=force), "",
                      on_success=self._generated, label="Making STEP/PDF", parts=pns)

    def _generated(self, result):
        self.note = generate_text.done_text(result)
        self._say(self.note, "warn" if result.failed else "normal")
        if result.failed:
            messagebox.showerror("Generate STEP/PDF", error_text.shorten(generate_text.failure_lines(result.failed)))

    # -- after a release ------------------------------------------------------------------------------------------
    def run_releasing(self, work, pns, done_text, on_success=None, **options):
        """Queue work() (something that may release `pns`: Release, a sign-off, Complete, Override), then in the
        same job make the STEP and PDF of whichever of them it released. A failure there never undoes or stops the
        release: the part stays flagged, and the status line says so."""
        repo = self.repo()

        def run():
            try:
                result = work()
            except BaseException:
                generate_files.after_release(repo, pns)     # a part done before the failure still gets its files
                raise
            return result, generate_files.after_release(repo, pns)

        def finished(both):
            result, files = both
            if on_success:
                on_success(result)
            self._report_release_files(files)

        self.run_task(run, done_text, on_success=finished, **options)

    def _report_release_files(self, files):
        if files.boms:
            saved = generate_text.boms_saved_text(files.boms)
            self.note = f"{self.note}. {saved}" if self.note else saved
        if files.bom_failed:
            self._log(f"BOM not saved after release: {generate_text.failure_lines(files.bom_failed)}")
            self.note = (f"{self.note}. " if self.note else "") + "The BOM couldn't be saved with the release (see the log)"
        if not (files.done or files.failed):
            if files.boms or files.bom_failed:
                self._say(self.note, "warn" if files.bom_failed else "normal")
            return
        if files.done:
            made = generate_text.done_text(files)
            self.note = f"{self.note}. {made}" if self.note else made
        if files.failed:
            reason = files.failed[0][1].splitlines()[0]
            self._log(f"STEP/PDF not made after release: {generate_text.failure_lines(files.failed)}")
            self.note = (f"{self.note}. " if self.note else "") + (
                f"STEP/PDF not made ({reason}): the part is flagged. Use Part > Generate STEP/PDF... with SolidWorks.")
        self._say(self.note, "warn" if files.failed else "normal")
