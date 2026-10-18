"""
The part records in PN-logs/*.yaml: reading, writing and the status rules. Never runs git.

Every part number gets one small YAML file in the vault's PN-logs folder:

    hcr-litterbox/
      PN-logs/
        HCR-00042-001.yaml        <- the record for part number HCR-00042-001
      cad/
        HCR-00042-001_A.SLDPRT    <- the CAD files that belong to it (revision A)
        HCR-00042-001_A.SLDDRW

A record holds the name, description, status, revision, who created it, and a history of events (created, checked
out, checked in, released, ...).

    record_model.py       the Record and how it is written as YAML
    record_store.py       reading and writing records; which numbers are taken
    record_files.py       which CAD files belong to which part and revision
    record_lifecycle.py   the status rules (check out, check in, release, void, ...)
    record_revisions.py   revising and cancelling revisions
    error_conversion.py   turning record errors into LitterboxError

These files read and write records on disk. They do NOT run git: whoever calls them (parts/, workflows/, ...) is
responsible for locking, committing and pushing.

Rules enforced here:
  * A record is never deleted. A number that has been assigned stays used forever. A part that is abandoned is
    marked "void" and its number is still treated as taken.
  * A record can only be created once (two people can't both create the same PN).
  * Status changes follow the rules: in_work -> released -> (reopen) in_work, and in_work -> void.
"""
