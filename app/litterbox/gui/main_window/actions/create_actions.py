"""
create_actions.py - New Part, Create Variant, Import and Import COTS.
"""

from pathlib import Path

from litterbox.errors import LitterboxError
from litterbox.gui.dialogs import create_variant_dialog
from litterbox.gui.dialogs import filename_dialog
from litterbox.gui.dialogs import new_part_dialog
from litterbox.gui.windows.import_window import import_window
from litterbox.parts import checkout
from litterbox.parts import create
from litterbox.parts import create_variant
from litterbox.records import record_store
from litterbox.references import reference_rescan


class CreateActions:
    """New Part, New Assembly, Create Variant, Import and Import COTS. One part of the main window (App)."""

    def new_assembly(self):
        """New Assembly: New Part, with the variants set aside for assemblies (from 500, or the org's choice)."""
        self.new_part(kind=create.ASSEMBLY)

    def new_part(self, kind=create.PART):
        """Open the New Part (or New Assembly) pop-up, then create the number in the background."""
        if not self._may("create"):
            return
        if not self.org or not Path(self.repo()).is_dir():
            self._say("Choose an org with a vault folder first (the org box at the top, or File > Add org...).", "warn")
            return
        repo, org = self.repo(), self.org
        request = new_part_dialog.NewPartDialog(self, repo, org, kind).show()
        if not request:
            return
        def work():
            pn = create.new_part(repo, request["name"], request["description"],
                                 base=request["base"], variant=request["variant"], org=org,
                                 project=request.get("project"), kind=request.get("kind", create.PART),
                                 noncad=request.get("noncad", False))
            try:
                checkout.checkout(repo, pn)            # a new part starts out checked out to its creator
            except LitterboxError as e:
                return pn, str(e)
            return pn, ""

        def created(result):
            pn, problem = result
            self.note = f"Created {pn}" + (f" (could not check it out: {problem})" if problem else " and checked it out to you")
            self.pending_select = str(pn)
            self.search.delete(0, "end")            # make sure the new row isn't filtered out
            if not request.get("noncad"):
                filename_dialog.FilenameDialog(self, pn)            # where to save its CAD file

        self.run_task(work, "Created", on_success=created)

    def create_variant(self):
        """Create Variant: copy the highlighted part to a new variant of its number, checked out to you."""
        plan = self._plan("create_variant")
        if not plan:
            return
        pn, repo = plan.targets[0], self.repo()
        row = self.rows_by_pn.get(pn)
        try:
            record = record_store.load(repo, pn)
            next_free = create.next_variant_number(repo, pn.base, pn.org, create_variant.kind_of(repo, record))
        except Exception:
            record, next_free = None, None
        request = create_variant_dialog.CreateVariantDialog(
            self, pn, record.name if record else getattr(row, "name", ""), record.description if record else "",
            next_free).show()
        if not request:
            return
        log = lambda text: self.queue.put(("log", text))

        def created(result):
            new_pn, _files = result
            self.note = f"Created {new_pn} as a copy of {pn}, checked out to you"
            self.pending_select = str(new_pn)
            self.search.delete(0, "end")            # make sure the new row isn't filtered out

        self.run_task(lambda: create_variant.create_variant(repo, pn, request["name"], request["description"],
                                                            request["variant"], log=log),
                      "Created", on_success=created, label=f"Making a variant of {pn}")

    def import_cots(self):
        """Open the Import COTS window: the same as Import, but every part is recorded as purchased."""
        self.import_cad(cots=True)

    def import_cad(self, cots=False):
        """Open the Import window (choose old CAD folders, review the table, Finish & Import)."""
        if not self._may("create"):
            return
        if self.busy:
            self._say("Import needs the vault to itself. Wait for the banner to turn green, then try again.", "warn")
            return
        if not self.org or not Path(self.repo()).is_dir():
            self._say("Choose an org with a vault folder first (the org box at the top, or File > Add org...).", "warn")
            return

        def imported(result):
            self.note = f"Imported {len(result.pns)} {'COTS ' if cots else ''}part(s)"
            self.search.delete(0, "end")
            repo, pns = self.repo(), list(result.pns)
            if cots or not pns:
                self.refresh()
                return
            # Record which parts each imported assembly uses (a separate small step after the import)
            self.run_task(lambda: reference_rescan.rescan(repo, pns, log=lambda text: self.queue.put(("log", text))),
                          self.note)

        import_window.ImportWindow(self, self.repo(), self.org, imported, log=lambda text: self.queue.put(("log", text)), cots=cots)
