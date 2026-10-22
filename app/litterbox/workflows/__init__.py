"""
Sign-off workflows: templates, requests, signing, the task list.

workflow.py - sign-offs before a part's status changes.

An Admin can say "a release (or unrelease, void, make COTS) needs sign-offs". After that, pressing the button no
longer does it: it opens the Workflow window, where you pick a template and a person for each sign-off. The
people named approve (or reject), and when everyone has signed the action happens.

THE TEMPLATES   .litterbox/workflows.yaml, shared through Git like the team file. Admins edit it (Team > Part
    Workflows... and Doc Workflows...). Each action can have several named templates (T1, T2... or your own):

        workflows:
          release:
            T1:
              allow_same_person: false      one person may fill more than one row (default false)
              requester_may_sign: true      the person who asked may be one of the signers (default true)
              signoffs:
              - roles: [Responsible Engineer]
              - roles: [Manager, Chief]     OR: a Manager or a Chief may fill this row
              - roles: [Responsible Engineer]   a role listed twice is two sign-offs

    An action with no templates works as it always did (it just happens).

THE REQUEST   One request can cover several parts (a batch). It is saved in each part's record under `pending`:
    id (the same for the whole batch), action, revision, requested_by (+ _id, _at), template_name and the
    template AS IT WAS (editing it later changes nothing in flight), reason (reopen / void), parts, the hash of
    every CAD file, `slots` (one per sign-off row: the roles allowed, and the person named) and `signoffs` (who
    signed which slot, and when). A part with a pending request can't be checked out or changed, so what gets
    approved is what happens.

THE STEPS     request -> sign_off (each named person) -> complete
    The last sign-off completes the action straight away for release, reopen and void. Make COTS waits for
    someone to press the button again. If completing fails (offline, behind the vault...) the sign-off is still
    saved and the part shows "approved, ready".
    reject      a named signer (or Admin) sends the whole batch back with a comment.
    withdraw    the requester (or Admin) cancels the batch.
    reassign    the requester (or Admin) swaps the person named for a sign-off that hasn't been given.
    override    an Admin does the action without the sign-offs. A reason is required and it is recorded.

THE TRAIL     A finished action adds an entry to the record's `approvals`: who asked, the template, who signed
    (with roles and times), the file hashes, and any override with its reason. Every step is in the history too.

Everything here that changes a record uses the same lock, pull, change, commit, push, unlock routine as the rest
of Litterbox (parts/batch_core.edit_record). A batch is done one part at a time; if a step fails part-way, the
parts already done stay done, and the message says which.
"""
