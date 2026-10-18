"""
Engineering change orders (ECOs): one file per change, in the vault's ECO folder (ECO/ECO-0001.yaml).

A workflow whose template says "Require ECO" asks for an ECO (a name and a description) when it is started. The
ECO is written in the same commit as the request, lists the parts it changes, and is closed when the request ends:
released when the workflow completes, rejected or withdrawn otherwise. A closed ECO is never changed again, and
on disk every ECO file is read-only, like the files of a released part.
"""
