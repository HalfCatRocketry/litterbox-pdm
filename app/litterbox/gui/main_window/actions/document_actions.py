"""
document_actions.py - documents: New Document, opening, adding and removing a document's files, Team > Document
Types..., and linking documents to parts (a part's Documents tab). Check out, release and the rest are the parts'
own actions, pointed at documents by the Documents screen (App.act_on).
"""

from tkinter import filedialog, messagebox

from litterbox.core import doc_number
from litterbox.documents import doc_create
from litterbox.documents import doc_files
from litterbox.documents import doc_links
from litterbox.documents import doc_types
from litterbox.errors import LitterboxError
from litterbox.git import lfs_download
from litterbox.gui.dialogs import bom_item_dialog
from litterbox.gui.dialogs import doc_types_dialog
from litterbox.gui.dialogs import new_document_dialog
from litterbox.gui.dialogs import revision_picker
from litterbox.gui.dialogs.workflow import request_dialog
from litterbox.gui.logic import document_text
from litterbox.gui.logic import error_text
from litterbox.parts import checkout
from litterbox.parts import downloads
from litterbox.records import record_model
from litterbox.records import record_store
from litterbox.workflows import workflow_request
from litterbox.workflows import workflow_store
from litterbox.workflows import workflow_templates


class DocumentActions:
    """Documents and their links to parts. (a part of the main window, App)."""

    def _doc_types(self):
        try:
            return doc_types.load(self.repo())
        except LitterboxError as e:
            messagebox.showerror("Litterbox", str(e), parent=self)
            return None

    def _refresh_documents(self):
        screen = getattr(self, "screens", {}).get("documents")
        if screen is not None:
            screen.reload()

    def new_document(self):
        if not self._may("create"):
            return
        types = self._doc_types()
        if types is None:
            return
        offered = [t for t in types if not t.hidden]
        if not offered:
            self._say("This org has no document types yet. An Admin adds them in Team > Document Types....", "warn")
            return
        request = new_document_dialog.NewDocumentDialog(self, offered).show()
        if not request:
            return
        repo = self.repo()

        def work():
            number = doc_create.new_document(repo, request["type"], request["title"], request["description"])
            try:
                checkout.checkout(repo, number)            # a new document starts out checked out to its creator
            except LitterboxError as e:
                return number, str(e)
            return number, ""

        def created(result):
            number, problem = result
            self.note = f"Created {number}" + (f" (could not check it out: {problem})" if problem else
                                               " and checked it out to you. Add Files... puts its files in.")
            self.show_screen("documents")

        self.run_task(work, "Created", on_success=created, label="Creating a document")

    # -- files ---------------------------------------------------------------------------------------------------
    def _pick_file(self, number, title, revision=None):
        row = self.rows_by_pn.get(number)
        choices = document_text.file_choices(row, revision) if row else []
        if not choices:
            self._say(f"{number} has no files" + (f" in Rev {revision}." if revision else " yet."), "warn")
            return None
        if len(choices) == 1:
            return choices[0][1]
        return revision_picker.RevisionPickerDialog(self, number, choices, title).show()

    def open_document(self, number):
        row = self.rows_by_pn.get(number)
        if row is None:
            return
        released = row.released_revision if row.record_status != "released" and row.released_revision else None
        if released and messagebox.askyesno("Open", f"{number} has a working Rev {row.revision} and a released "
                                                    f"Rev {released}. Open the released one?", parent=self):
            path = self._pick_file(number, "Open", released)
        else:
            path = self._pick_file(number, "Open")
        if path is None:
            return
        repo = self.repo()
        if lfs_download.is_stub(repo, path):
            self.run_task(lambda: downloads.download_files(repo, [path], f"{number}'s file"), "",
                          on_success=lambda _done: self._open_path(path), label=f"Downloading {number}",
                          parts=[number])
            return
        self._open_path(path)

    def add_document_files(self, number):
        row = self.rows_by_pn.get(number)
        if row is None or row.kind != "mine":
            self._say(f"Check {number} out first to change its files.", "warn")
            return
        chosen = filedialog.askopenfilenames(parent=self, title=f"Add files to {number}")
        if not chosen:
            return
        repo = self.repo()
        try:
            replaced = doc_files.clashes(repo, number, chosen)
        except LitterboxError as e:
            messagebox.showerror("Add Files", str(e), parent=self)
            return
        if replaced and not messagebox.askyesno("Add Files", "Replace " + ", ".join(p.rsplit("/", 1)[-1] for p in replaced)
                                                + "? A revision keeps one file of each type.", parent=self):
            return
        self.run_task(lambda: doc_files.add_files(repo, number, chosen, replace=True),
                      f"Added files to {number}. Check In to upload them.", label=f"Adding files to {number}",
                      parts=[number])

    def remove_document_file(self, number):
        row = self.rows_by_pn.get(number)
        if row is None or row.kind != "mine":
            self._say(f"Check {number} out first to change its files.", "warn")
            return
        path = self._pick_file(number, "Remove")
        if path is None or not messagebox.askyesno("Remove File", f"Take {path.rsplit('/', 1)[-1]} out of {number}? "
                                                                  "Check In uploads the change; Undo Checkout puts "
                                                                  "it back.", parent=self):
            return
        repo = self.repo()
        self.run_task(lambda: doc_files.remove_file(repo, number, path), f"Removed a file from {number}.",
                      label=f"Removing a file from {number}", parts=[number])

    # -- types ---------------------------------------------------------------------------------------------------
    def manage_doc_types(self, window=None):
        allowed, why = self.identity.allows("manage_doc_types")
        if not allowed:
            self._say(why, "warn")
            return
        types = self._doc_types()
        if types is None:
            return
        repo = self.repo()
        try:
            used = doc_types.in_use(repo)
        except LitterboxError:
            used = {}
        chosen = doc_types_dialog.DocTypesDialog(window or self, types, used).show()
        if chosen is None:
            return

        def change(current):
            current[:] = chosen

        self.run_task(lambda: doc_types.edit_types(repo, change, "Document types changed"),
                      "Saved the document types", on_success=lambda _r: self._refresh_documents(),
                      label="Saving the document types")

    # -- links to parts ------------------------------------------------------------------------------------------
    @staticmethod
    def _doc_number(text):
        return doc_number.parse(text)

    def document_link_rows(self, record, revision):
        """The Documents tab's rows for one revision of a part (document_text.link_rows)."""
        try:
            types = doc_types.by_key(doc_types.load(self.repo()))
        except LitterboxError:
            types = {}
        return document_text.link_rows(record, revision, {str(row.pn): row for row in self.doc_rows}, types)

    def _open_document_text(self, number):
        self.open_document(self._doc_number(number))

    def _reshow_pane(self):
        """After a link changed: show the part's record again in the details pane."""
        self.pane_pn = None
        self._selection_changed()

    def _may_link_released(self):
        identity = self.identity
        if identity.allows("link_released_documents")[0]:
            return True
        directory, person = getattr(identity, "directory", None), getattr(identity, "person", None)
        return bool(directory is not None and person is not None and directory.is_superuser(person))

    def link_document(self, pn, revision, then=None):
        """The Documents tab's Add...: link a document to a part revision."""
        row = self.rows_by_pn.get(pn)
        mode, why = document_text.link_mode(row, revision, self._may_link_released())
        if not mode or why:
            self._say(why, "warn")
            return
        choices = document_text.linkable(list(self.doc_rows), self._linked(pn, revision))
        answer = bom_item_dialog.BomItemDialog(
            self, pn, choices, "Pick the document to link." + (" It is uploaded at once and recorded."
                                                              if mode == "released" else ""),
            heading=f"Link a document to {pn} Rev {revision}", quantity=False).show()
        if answer is None:
            return
        repo, number = self.repo(), answer[0]
        if mode == "checkout":
            work, done = (lambda: doc_links.link(repo, pn, number),
                          f"Linked {number} to {pn}. Save Progress or Check In to upload it.")
        else:
            work, done = lambda: doc_links.link_released(repo, pn, number), f"Linked {number} to {pn}"
        self.run_task(work, done, on_success=lambda _r: then() if then else None,
                      label=f"Linking {number}", parts=[pn])

    def _linked(self, pn, revision):
        """The documents linked to a part revision now (read from its record)."""
        try:
            return record_store.load(self.repo(), pn).documents.get(revision, [])
        except record_model.RegistryError:
            return []

    def unlink_document(self, pn, revision, number, then=None):
        """The Documents tab's Remove: on your checkout at once; on a released part, a Remove document link
        workflow (it needs sign-offs, and only an Admin or a superuser may ask)."""
        row = self.rows_by_pn.get(pn)
        mode, why = document_text.link_mode(row, revision, self._may_link_released())
        if not mode or why:
            self._say(why.replace("link a document to", "remove a document from"), "warn")
            return
        repo = self.repo()
        if mode == "checkout":
            if messagebox.askyesno("Remove link", f"Take {number} off {pn} Rev {revision}?", parent=self):
                self.run_task(lambda: doc_links.unlink(repo, pn, number),
                              f"Took {number} off {pn}. Save Progress or Check In to upload it.",
                              on_success=lambda _r: then() if then else None, label=f"Removing {number}", parts=[pn])
            return
        action = workflow_templates.REMOVE_DOC
        try:
            templates = workflow_store.templates_for(repo, action)
        except LitterboxError as e:
            messagebox.showerror("Litterbox", error_text.shorten(str(e)), parent=self)
            return
        directory, me = self.identity.directory, self.identity.person
        if not templates or directory is None or me is None:
            messagebox.showinfo("Remove link", f"Taking a document off a released part needs sign-offs, but this "
                                               f"vault has no {workflow_templates.label_of(action)} workflow. Ask an "
                                               "Admin to add one (Team > Workflows...).", parent=self)
            return
        chosen = request_dialog.WorkflowRequestDialog(self, action, [(pn, row.name)], templates, directory,
                                                      me.id).show()
        if not chosen:
            return
        self.run_task(lambda: workflow_request.request(repo, [pn], action, chosen["template"], chosen["assignments"],
                                                       chosen["extras"], chosen["reason"], chosen["eco"],
                                                       document=number),
                      f"Asked for sign-offs to take {number} off {pn}")
