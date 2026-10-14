"""
Bringing existing CAD files into a vault: scan, manifest, import.

importer.py - bring the files listed in a manifest into the vault.

    python importer.py <vault> <manifest.yaml> [--dry-run] [--allow-external] [--recover]

What it does
  Every included item that has no part number yet gets a NEW one. Its SolidWorks files are
  copied (never moved, never changed) into the vault's cad folder as HCR-00042-001.SLDPRT and
  so on, and every reference inside the copies is pointed at the other copies, so the imported
  files only know about each other. Your old folders are not written to.

  Nothing is reserved while this runs. The part numbers are only picked from the vault as it
  is now; they become yours when the records and the CAD files are committed and pushed in ONE
  step at the very end. That is why cancelling is clean:

    * Cancel (or an error, or closing the window) deletes exactly the files this import copied,
      and nothing else, and leaves git as it was. The numbers were never taken, so there is
      nothing to give back and the next attempt starts from the same place.
    * If the computer dies in the middle, a note kept inside the vault's .git folder lists the
      files that were copied. The next import (or `--recover`) removes them first.
    * If somebody else uses one of the numbers while you were copying, the copies are removed
      and the import starts again with the newest numbers (up to 3 tries).

  The manifest is only updated (each item's pn) after everything is in the vault.

PART NUMBERS
  prepare() refreshes the vault and PROPOSES a block of numbers well above the highest one in
  use (100 or more above it), so other people creating parts meanwhile are very unlikely to
  reach them. Nothing is reserved or pushed. The proposal is a table (Proposal.entries) the user
  can edit: part number, name, description. finish() then downloads the newest records and
  checks every number again:
    * an automatic number that has been taken is quietly replaced by a free one;
    * a number the user typed that has been taken is never changed: PNConflict is raised before
      anything is copied, listing the rows to highlight, and finish() can simply be called again
      after the table is corrected.

  --dry-run      do all the checking and show what would happen, without writing anything
  --allow-external   go ahead even though some files reference files that are not part of this
                 import (those references are left pointing at the original files)
  --recover      clean up after an interrupted import, then stop
"""
