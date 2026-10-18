"""
Actions on parts: status, check out, check in, undo, release, Make COTS, Unrelease, void, create, revise.

HOW A PART NUMBER (PN) IS LOCKED
  Everything for one PN is treated as a unit:
      cad/HCR-00042-001_A.SLDPRT    the part (revision A)
      cad/HCR-00042-001_A.SLDDRW    its drawing (if there is one)
      PN-logs/HCR-00042-001.yaml    the record (history, status)
  Checking out a PN locks ALL of them. The lock on the record is the one that
  matters: it is taken first, and it is the only thing that has to succeed for
  someone to be "first". Nobody can edit the record unless they hold that lock.

  Check-out events are written to the record on your computer and uploaded
  together with your files at check-in, so check-out never has to push.

The vault's .gitattributes (written by vault/create_vault.py) makes the CAD files Git LFS files that can be locked,
and the records lockable.

The git and git-lfs commands themselves are in litterbox/git/. The command line for these actions is
litterbox/cli/status.py.
"""
