"""The Litterbox user guide's text, as blocks for build_guide.py.

("h1", text) ("h2", text) ("h3", text)    headings
("p", text)                                a paragraph; **bold** and `code` work inline
("ul", [items]) ("ol", [items])           lists
("table", [headings], [[cells]], [widths in inches])
("tip", text)                              a shaded box for tips and warnings
"""

VERSION = "0.5.3"

BLOCKS = [
("h1", "What Litterbox is"),
("p", "Litterbox is a product data manager (PDM) for small hardware teams that design in SolidWorks. It keeps "
      "everyone's CAD files in one shared place, makes sure only one person edits a part at a time, numbers parts, "
      "tracks revisions and releases, and works out bills of materials. If you have ever lost a day to two people "
      "saving over each other's assembly, or found three different files called bracket_final_v2.SLDPRT, this is "
      "the problem it solves."),
("p", "What makes it different from the big commercial PDMs is that there's **no server**. A Litterbox vault is "
      "an ordinary Git repository using Git LFS (Git's add-on for large files), hosted wherever your team already "
      "keeps code: GitHub, Azure DevOps, GitLab and so on. Litterbox is the Windows program on top that turns Git's "
      "commits, branches and file locks into check out, check in, release and revise. You never need to use Git "
      "yourself."),
("p", "That design brings a few things for free:"),
("ul", [
    "**Cost.** Nothing beyond the Git host, which is often free.",
    "**Offline work.** Everything you've downloaded is on your own disk. You only need a connection to check out, "
    "check in and get other people's changes.",
    "**A complete history.** Every change is a commit with who, when and why. The host backs it up for you.",
    "**Readable data.** Part records are plain text (YAML) files. Anyone can script against the vault, and nothing "
    "is locked away in a database you can't get out of.",
]),
("p", "Litterbox is aimed at student competition teams (rocketry, robotics, Formula SAE, CubeSats), small "
      "start-ups, labs and makerspaces: groups of a few to a few dozen people who need release control and a "
      "history that outlives the people who made it, without paying for or running a PDM server."),
("h2", "The ideas you need"),
("p", "A handful of words come up everywhere in this guide:"),
("table", ["Term", "What it means"], [
    ["Vault", "The shared Git repository that holds your team's parts, and its copy on your computer under "
              "C:\\Litterbox\\<vault name>."],
    ["Org", "The team or company a vault belongs to. It has a short code (HCR) that starts every part number. You "
            "can belong to several orgs and switch between them."],
    ["Part number", "A part's permanent identity, for example HCR-100010-001: the org code, a base number and a "
                    "variant. A number is never reused, even if the part is voided."],
    ["Revision", "A version of a part that has been or will be released: A, B, C ... A part's files carry it in "
                 "their names (HCR-100010-001_A.SLDPRT)."],
    ["Record", "The small text file that describes a part: its name, status, revisions, history, purchasing info, "
               "what it uses and so on. Records live in the PN-logs folder."],
    ["Check out / check in", "Taking the lock on a part so you can edit it, and uploading your changes and giving "
                             "the lock back."],
    ["Release", "Freezing a revision. Released files can't be changed; to change the part you revise it, which "
                "starts the next revision."],
    ["Workflow", "A set of sign-offs (by role) that an action needs before it happens, such as a release."],
], [1.6, 4.9]),

("h1", "Getting started"),
("p", "This part is for people and teams who are new to Litterbox. If someone has already set your team up, read "
      "\"What you need\", \"Installing Litterbox\" and \"Joining your team's vault\", then skip to \"A first look at "
      "the window\". If you're the one setting a team up, read all of it."),
("h2", "What you need"),
("ul", [
    "A Windows computer. Litterbox is a Windows program.",
    "**Git for Windows** (git-scm.com). It includes Git LFS. Install it with the default options.",
    "An account on your team's Git host with access to the vault's repository. Your team lead adds you there.",
    "**SolidWorks**, if you're going to model. You can use Litterbox without it to look at parts, open PDFs, run "
    "workflows, manage purchasing and documents, but anything that reads or writes SolidWorks files needs it.",
]),
("p", "The first time you use Git it needs your name and email. Litterbox asks for them if they're missing, or "
      "you can set them yourself in a terminal:"),
("code", ['git config --global user.name "Alex Smith"', 'git config --global user.email "alex@example.com"']),
("h2", "Installing Litterbox"),
("ol", [
    "Download Litterbox-Setup-<version>.exe from the latest release on the Litterbox GitHub page.",
    "Run it. It installs for your Windows user only and doesn't need administrator rights.",
    "Windows SmartScreen may say the app is unrecognised, because the installer isn't code-signed yet. Choose "
    "**More info**, then **Run anyway**.",
]),
("p", "Litterbox checks for a newer version when it starts and asks before updating. Updates are signed, and "
      "Litterbox refuses one that isn't. To turn the check off, add `update_check: false` to "
      "C:\\Litterbox\\settings.yaml. Help > Check for updates... checks by hand."),
("h2", "Joining your team's vault"),
("ol", [
    "Ask whoever runs your team for the vault's repository URL: the https address from the host's Clone button.",
    "In Litterbox, choose **File > Add org...** and paste it. Litterbox copies the vault into "
    "C:\\Litterbox\\<repository name> in the background and opens it.",
    "Your team lead adds you to the team list (Team screen > Add Person) with your host user name. Until they do, "
    "Litterbox lets you look at everything but not change anything, and says so.",
]),
("p", "Litterbox **downloads on demand**: a new copy gets every part record and its history, but leaves the CAD "
      "files on the server until you need them. Checking out a part downloads its files; opening one downloads "
      "what it needs first (for an assembly, every part it uses). Vault > Download All... gets everything at once, "
      "and `download: all` in settings.yaml keeps it that way."),
("tip", "Don't move or rename the vault folder. Litterbox always keeps vaults under C:\\Litterbox, and because "
        "every computer uses the same path, SolidWorks assemblies find their parts on everyone's machine."),
("h2", "Setting up a new team"),
("p", "One person, who becomes the vault's **Owner**, sets the team up. Plan this before you start, because the "
      "org code and the part number format can't be changed afterwards."),
("ol", [
    "On your Git host, create an **empty** repository (no README) for the vault. Make sure the host supports Git "
    "LFS file locking; GitHub, Azure DevOps and GitLab all do. Note that hosts limit LFS storage differently: "
    "GitHub's free allowance is small, Azure DevOps has no practical limit.",
    "In Litterbox, choose **File > Create new org...** and paste the repository's URL.",
    "Fill in the org: the **code** (2 to 6 letters, it starts every part number), the full **name**, how many "
    "**digits** the base and variant numbers have (6 and 3 gives HCR-100010-001), the **first number** to hand "
    "out, and the variant where assemblies start (500 by default).",
    "Litterbox shows it all once more for you to check, then sets up the repository: Git LFS and lock rules, the "
    "settings file, and the team list with you as Owner. It uploads the lot as the vault's first commit.",
]),
("p", "Then set the team up from the **Team** screen (in the sidebar):"),
("ul", [
    "**Add Person** for each team member: their name, email, the user name(s) they use on the Git host, their "
    "access level and their roles.",
    "**Roles...** for the jobs people do (Responsible Engineer, Manufacturing, Quality, Manager, Chief ...). "
    "Workflows ask for sign-offs by role. Add the standard roles gives you a sensible set.",
    "**Part Workflows...** and **Doc Workflows...** if releases need sign-offs (see Sign-off workflows below).",
    "**Projects...**, **Document Types...** and **Vault Settings...** as you need them.",
    "Press **Save** at the top right. Team changes are drafted on the Team screen and uploaded together.",
]),
("p", "If you already have CAD files, bring them in with Create > **Import...** (see Importing existing CAD)."),
("h2", "A first look at the window"),
("table", ["Area", "What it's for"], [
    ["Menu bar", "File (orgs, exit), Vault (refresh, get latest, download, file rules, vault size, new parts), View "
                 "(screens, sidebar, details pane, log, columns, text size) and Help. The org's name sits in the "
                 "middle."],
    ["Header", "The org box (switch orgs), who you are, and how many changes others have uploaded that you haven't "
               "got yet. Click that to Get Latest."],
    ["Sidebar", "Views of the parts list (All, Mine, Checked out, Released, Not downloaded, Void, with counts), "
                "then the Workflows, ECOs, Documents and Team screens. Ctrl+1 to Ctrl+5 jump between them."],
    ["Toolbar", "Check Out, Check In, Save Progress and Undo Checkout, then the Part, Lifecycle and Create menus. "
                "A greyed-out button tells you why if you rest the mouse on it."],
    ["Parts list", "One row per part. The first column has a tick box and a status icon: a different shape per "
                   "status, so colour is never the only clue (Help > Status icons explains them)."],
    ["Details pane", "Everything about the highlighted part, in tabs. The button at its top opens it in a window "
                     "of its own; double-clicking a part does the same."],
    ["Status bar", "A coloured dot (ready, working, error), what just happened, the jobs waiting, and the Log."],
], [1.4, 5.1]),
("p", "There's a difference between **ticking** a part and **highlighting** it. Actions that change parts (Check "
      "Out, Release ...) act on the ticked parts, so a stray click on a row can never be what you release. Actions "
      "that only look (Open, References, Details) use the highlighted row. Right-click a part for its menu; it "
      "ticks that part on its own first, so it's always clear what the menu acts on."),
("p", "Everything runs in the background. You can keep browsing, ticking and queueing actions while Litterbox "
      "uploads, and a part with a job waiting shows it in its status."),
("h2", "Your first part"),
("ol", [
    "Choose Create > **New Part**. Give it a name and (optionally) a description and project. Litterbox suggests "
    "the next free part number; you can type another.",
    "Litterbox creates the part's record, checks it out to you, and shows the exact file name its model must have, "
    "for example HCR-100010-001_A, with a Copy button.",
    "In SolidWorks, model the part and **Save As** into the vault's cad folder "
    "(C:\\Litterbox\\<vault>\\cad\\) under that name. A drawing gets the same name with .SLDDRW.",
    "Back in Litterbox, tick the part and press **Check In**. Add a comment if you like. Litterbox uploads the "
    "files and the record, and gives the lock back.",
]),
("p", "That's the whole loop. Everyone else sees your part after their next Get Latest."),

("h1", "Everyday work"),
("h2", "Part numbers and file names"),
("p", "A part number is the org code, a base number and a variant: HCR-100010-001. Variants let related parts "
      "share a base (a family of brackets, say). New Part hands out variants below the assembly start (001 to 499 by "
      "default) and **New Assembly** starts at 500, so you can tell at a glance which numbers are assemblies."),
("p", "Every file in the cad folder is named after its part and revision: HCR-100010-001_A.SLDPRT, "
      "HCR-100010-001_A.SLDDRW, HCR-100010-001_A.STEP, HCR-100010-001_A.PDF. That's how Litterbox knows which files "
      "belong to which part and revision, so the names matter. Files that don't follow the pattern are ignored."),
("p", "**Projects** (set up by an Admin) reserve a block of numbers: with 6 digits, project Rover starting 12 owns "
      "120000 to 129999. Choose a project in New Part and Litterbox suggests the next number in its block. With no "
      "project, Litterbox never hands out a number inside one."),
("h2", "Finding parts"),
("ul", [
    "The sidebar views filter the list: your checkouts, everything checked out, released parts, parts not "
    "downloaded, and void parts (hidden everywhere else).",
    "The search box looks in every column, or one column you pick beside it. It takes wildcards: `*` for any "
    "characters and `?` for one, matching the whole value (Te*rt finds Test Part but not My Test Part).",
    "Click a column heading to sort. View > Columns adds more columns: Project, Kind, COTS, Status, Checked out "
    "by, Released rev, Imported from and Material.",
]),
("h2", "Checking out and checking in"),
("p", "Files you don't have checked out are **read-only** on your disk, so SolidWorks opens them read-only and "
      "you can't save over someone else's work by accident. To edit a part:"),
("ol", [
    "Tick it and press **Check Out**. Litterbox takes the lock on the part's record and files, downloads the "
    "latest version if needed, and makes the files writable. If you already had the part open in SolidWorks, "
    "Litterbox makes it writable there too, so you can save straight away.",
    "Edit and save in SolidWorks as usual.",
    "Press **Check In** to upload your changes and give the lock back, or **Save Progress** to upload them and "
    "keep the lock (useful at the end of a day, so your work is backed up).",
]),
("p", "**Undo Checkout** throws your changes away and puts the part back as it is in the vault. Check In notices "
      "parts with nothing changed and asks before going ahead, and refuses a part you saved in SolidWorks after "
      "pressing it (the save could end up half uploaded): that part stays checked out and you check it in again."),
("tip", "Until the status bar says Ready after a check-in, don't save those parts in SolidWorks. Litterbox warns "
        "you, but it's worth knowing why: a save in the middle of an upload can end up half in the vault."),
("p", "When an assembly is checked in with SolidWorks open, Litterbox also reads which parts it uses and how many "
      "of each, and when a part is checked in it reads its material. Without SolidWorks open the check-in still "
      "works; Litterbox notes that those need updating (see Assemblies, references and BOMs, and Materials)."),
("h2", "Getting other people's changes"),
("p", "**Get Latest** (Vault menu, or click \"N changes to get\" in the header) downloads what others have "
      "uploaded. It keeps the files you already have up to date without fetching the rest. If a file it replaces is "
      "open in SolidWorks, close and reopen it there so you aren't looking at an old copy. **Refresh** (F5) "
      "re-reads your copy without going to the server."),
("h2", "Opening files"),
("p", "The **Part** menu has Open, Open Drawing and **Open PDF**. When a part has a working revision and released "
      "ones, Litterbox asks which you want. Files open in whatever Windows uses for them, so SolidWorks files open "
      "in SolidWorks. To use another program for a file type, add it to settings.yaml:"),
("code", ["open_with:", "  .pdf: C:\\Program Files\\Adobe\\Acrobat\\Acrobat.exe"]),
("h2", "The details pane"),
("table", ["Tab", "What it shows"], [
    ["Details", "Pick a revision: its state, who released it and when, the workflow and who signed, its ECO, its "
                "files, material, STEP/PDF, and the part's purchasing info."],
    ["History", "Every revision, with buttons to open older ones, and everything that ever happened to the part."],
    ["Uses / Where used", "What an assembly uses, and which assemblies use this part, with whether each use is "
                          "up to date."],
    ["BOM", "The bill of materials of an assembly revision (see below)."],
    ["Documents", "Documents linked to the revision picked on the Details tab."],
], [1.5, 5.0]),

("h1", "Revisions and the lifecycle"),
("p", "A part is **in work** until it's released. Its first revision is A. The Lifecycle menu moves it along:"),
("table", ["Action", "What it does"], [
    ["Release", "Freezes the working revision. Its files become read-only for everyone, and nobody can check it "
                "out. Litterbox checks first that the files are there and warns (or, if your org chooses, refuses) "
                "when an assembly uses parts that aren't released or are out of date."],
    ["Revise", "Starts the next revision of a released part: copies its files to the new letter (B), re-points "
               "drawings at the new model, and checks it out to you. The released revision stays as it was."],
    ["Cancel Revision", "Throws away a revision that was never released. Its files go to a cancelled-revs folder, "
                        "not the bin, and the letter isn't used again."],
    ["Unrelease", "Takes a part back to in work (with a reason), for when a release was a mistake."],
    ["Void", "Retires a part that was never released. Its number is never used again."],
    ["Make COTS", "Records a part as commercial off-the-shelf: something you bought and didn't modify. It's "
                  "frozen like a release."],
    ["Edit Details", "Changes a part's name and description, and switches it between CAD and non-CAD until it's "
                     "first released."],
], [1.5, 5.0]),
("p", "Revision letters skip I, O, Q, S, X and Z, which are easily mistaken for numbers (ASME Y14.35 recommends "
      "this): H is followed by J, and Y by AA."),
("p", "Release, Unrelease, Void and Make COTS work on several ticked parts at once, and each part's history "
      "records who did it. If your vault has a workflow for the action, pressing it starts a sign-off request "
      "instead (see Sign-off workflows)."),

("h1", "Assemblies, references and BOMs"),
("h2", "What a part uses, and where it's used"),
("p", "Litterbox keeps a list of the parts each assembly revision uses, read from the assembly when it's checked "
      "in. That gives you **Uses** and **Where used** on the details pane, and Part > **References...** for a "
      "fuller view. Each use says whether it's up to date: a newer revision may have been released, or the part "
      "used may not be released yet, or may be void."),
("p", "**Update references...** points in-work assemblies at the latest released revisions of their parts, in "
      "SolidWorks, and checks them in. It never touches a released assembly; revise it first."),
("h2", "The BOM tab"),
("p", "An assembly's bill of materials is worked out from those lists every time you look, so it's never out of "
      "step with the models. Three ways to list it:"),
("ul", [
    "**Single level**: what the assembly itself uses.",
    "**Indented**: the same, with each sub-assembly's parts under it.",
    "**Every part once**: each part revision anywhere in the tree once, with its total quantity. A buying list.",
]),
("p", "Each line shows the part's revision, quantity, name, material, supplier, unit cost, total cost and lead "
      "time, and whether that use is out of date. The line above the table gives the assembly's **total cost**, "
      "worked out from every part in the tree once, and says how many parts have no unit cost or no count. "
      "**Export...** saves the list you're looking at as a .csv file that opens in Excel, to a folder outside the "
      "vault."),
("p", "Quantities are counted by SolidWorks at check-in: each copy at the top of the assembly, leaving out "
      "suppressed copies and those excluded from the BOM. If an assembly was checked in without SolidWorks open, "
      "the BOM says it needs updating and **Update BOM** counts it again (starting SolidWorks out of sight if it "
      "isn't running)."),
("p", "When an assembly is released, Litterbox saves its indented BOM beside the model as "
      "HCR-100010-500_A_BOM.csv, so the released revision keeps a fixed record of what it was made of."),
("h2", "Non-CAD parts and kits"),
("p", "Not everything in a product is modelled: paint, glue, wire, raw stock, labels. New Part and New Assembly "
      "have a **Kind**: CAD or **Non-CAD**. A non-CAD part has a part number, revisions, a lifecycle and "
      "purchasing info like any other, just no files."),
("p", "On a CAD assembly you have checked out, the BOM tab's **Add item...** adds a non-CAD part to its BOM with a "
      "quantity (two cans of paint, say), and **Remove** takes it off. A **kit** is a non-CAD assembly, built only "
      "from lines added this way, of any parts. Lines added by hand freeze at release and carry on to the next "
      "revision like the rest."),

("h1", "Purchasing, costs and materials"),
("h2", "Purchasing info"),
("p", "Lifecycle > **Purchasing Info...** gives a part a supplier, a supplier part number, a unit cost and a lead "
      "time in days. Purchasing info belongs to the part, not to a revision (a price changes without the design "
      "changing), so it needs no check-out and works on released parts too: the change is uploaded at once and "
      "the part's history records it."),
("p", "An Admin chooses the **team's currency** in Team > Vault Settings.... Costs are then shown with its symbol "
      "($12.50) on the Details tab, in the BOM and beside the Unit cost box. Unit costs are stored as plain numbers, "
      "so changing the currency doesn't convert anything. An exported BOM names the currency in its column "
      "headings and keeps the cells as numbers, so a spreadsheet can add them up."),
("h2", "Materials"),
("p", "Each revision's material is read from SolidWorks when the part is checked in with SolidWorks open (from "
      "its active configuration), and shows on the Details tab, in the BOM and in the Material column. A part "
      "with no material assigned shows blank. One checked in without SolidWorks open, or from before Litterbox "
      "read materials, shows **Not read yet**: tick it and choose Part > **Update Material**, which reads it "
      "through SolidWorks (starting it out of sight if needed)."),

("h1", "Release outputs and sharing files"),
("h2", "STEP and PDF files"),
("p", "Most people around the engineers want a STEP and a drawing PDF, not SolidWorks files. Litterbox makes them "
      "for you:"),
("ul", [
    "**At release.** Straight after a part is released, Litterbox makes a STEP (always AP214) of the model and a "
    "PDF of every sheet of the drawing, from the frozen files, and uploads them as HCR-100010-001_A.STEP and "
    "_A.PDF. If the person releasing has no SolidWorks, the release still happens; the part is flagged "
    "**STEP/PDF needs updating** and anyone with SolidWorks can make them later.",
    "**On demand.** Part > **Generate STEP/PDF...** makes them for the ticked parts, either into the vault (as "
    "above) or straight into a folder outside it. An Admin can tick Make released parts' files again to replace "
    "damaged ones.",
]),
("p", "Litterbox starts SolidWorks out of sight if it isn't running, and closes it again afterwards. Your own "
      "STEP settings are put back."),
("h2", "Exporting"),
("p", "Part > **Export Files...** copies the ticked parts' files to a folder you pick, for a vendor or a machinist: "
      "any of model, drawing, STEP and PDF, of the latest released revision (or the working one, or one you pick), "
      "and optionally the parts each assembly uses. Exports always go outside C:\\Litterbox and outside any Git "
      "repository, so a copy can never end up uploaded or locked with the vault."),

("h1", "Documents"),
("p", "Test procedures, plans, datasheets and design-review slides deserve revision control too. The **Documents** "
      "screen keeps them. Documents don't use part numbers: an Admin sets up **document types** in Team > "
      "Document Types... (a name and a prefix, like Propulsion Document, PROP), and **New Document** numbers each "
      "one with the next free number for its type: PROP-0001, PROP-0002 ..."),
("p", "A document goes through the same life as a part: check out, check in, release, revise (its files are "
      "copied to the new revision), unrelease, void and cancel revision, from the buttons on the Documents screen. "
      "**Add Files...** puts files of any type into its working revision (one of each type: PROP-0001_A.docx, "
      "PROP-0001_A.pdf), **Remove File...** takes one out, and **Open** opens one. **Details...** shows its revisions, "
      "files, history, and every part revision that links to it."),
("p", "**Linking documents to parts.** A part's Documents tab lists the documents linked to a revision, with "
      "Open, Add... and Remove. A link belongs to the part revision: it's frozen at release and carried to the next "
      "revision. On a part you have checked out you can add and remove links freely. An Admin or a superuser can "
      "add a link to a released part at any time; taking one off a released part needs sign-offs through a "
      "Remove document link workflow."),
("p", "An Admin can hide a document type nobody should use any more (Hide / Offer in Document Types). Documents "
      "of that type stay as they are; it just isn't offered by New Document."),

("h1", "Sign-off workflows and ECOs"),
("h2", "How workflows work"),
("p", "A workflow is a list of sign-offs that an action needs before it happens. Each sign-off asks for someone "
      "holding a role (Responsible Engineer), or any of several roles (Manager or Chief). An action with no "
      "workflow just happens when you press it. An Admin sets them up in Team > **Part Workflows...** (Release, "
      "Unrelease, Void and Make COTS) and **Doc Workflows...** (Release document, Unrelease document, Void document "
      "and Remove document link). An action can have several workflows, named T1, T2 or whatever you like, and "
      "**Add standard workflows** gives you a starting set."),
("p", "Each workflow also says whether one person may fill more than one sign-off, whether the person asking may "
      "sign, and whether it **requires an ECO**."),
("h2", "Asking for sign-off"),
("ol", [
    "Tick the parts and press the action (Release, say). With a workflow in place, the Workflow window opens "
    "instead.",
    "Pick the workflow, choose a person for each sign-off, add parts or extra sign-offs if you need to, and "
    "submit. Several parts go through one request together; people sign once for the lot.",
    "The parts show as waiting for sign-offs. Everyone named sees the request under **Workflows > My Tasks**.",
    "When the last person signs, the action happens: Release, Unrelease and Void at once, Make COTS when the "
    "person who asked presses it again.",
]),
("p", "Signers can reject with a reason. The person who asked (or an Admin) can reassign a sign-off or withdraw "
      "the request. An Admin can **Override Approve** or **Override Reject**, which is recorded as an override with "
      "a reason."),
("p", "**Superusers.** An Admin can mark a role as a superuser role (Team > Roles...). Whoever holds it can give "
      "any sign-off on any request, recorded as \"as Quality for Bea Jones (superuser)\". It's meant for someone at "
      "the top of the org who can sign for anyone. Admins, the Owner and superusers also see **All Workflows**."),
("h2", "Engineering change orders"),
("p", "A workflow that requires an ECO asks for a name and description when it starts, and Litterbox saves it as "
      "ECO-0001, ECO-0002 ... in the vault. The ECO closes when the request ends (released, rejected or withdrawn), "
      "with the sign-offs and comments, and is never changed again. The **ECOs** screen lists and searches them, "
      "and a released revision's Details tab links to the ECO it was released with."),

("h1", "Running the team"),
("p", "This part is for Admins and the Owner. Everything here is on the **Team** screen, and changes to people, "
      "roles and workflows are drafted there and uploaded together when you press Save."),
("h2", "People and access"),
("table", ["Access", "What they can do"], [
    ["Owner", "Everything, plus renaming the org and handing Ownership to someone else. There's exactly one."],
    ["Admin", "Manage people, roles, workflows, projects, document types and vault settings; override workflows; "
              "break a checkout; remake released STEP/PDF files; link documents to released parts."],
    ["Member", "Everyday work: create, check out and in, release (subject to workflows), sign off."],
    ["Not listed, or switched off", "Read-only: look, open, export. Litterbox says why they can't do more."],
], [1.7, 4.8]),
("p", "Litterbox knows who you are from the account you're signed in to on the Git host, matched against each "
      "person's host user names. **Who am I?** checks it. Optionally, an Admin can require **signed commits** "
      "(Vault Settings), and each person sets up a signing key with Signing...; Litterbox then refuses uploads that "
      "aren't signed by a key on the team list."),
("p", "When someone can't check a part in (they've left, or their laptop died), an Admin can **Break Checkout** "
      "(Lifecycle menu). Their changes aren't uploaded; when they next sync, Litterbox saves their copies of any "
      "files that changed meanwhile beside the vault and tells them where."),
("h2", "Vault settings"),
("table", ["Setting", "What it controls"], [
    ["Organization name", "Shown beside the org code. Only the Owner can change it."],
    ["Commits for a batch", "One commit per part (clear histories) or one for the batch (faster)."],
    ["Release rule", "Warn, block or say nothing when a release uses parts that are out of date or not released."],
    ["Signed commits", "Whether uploads must be signed by a key on the team list."],
    ["Assembly variant start", "Where New Assembly's variants start (500)."],
    ["SolidWorks version", "The version everyone works in. Anyone with a newer SolidWorks can't check out or "
                           "revise, because SolidWorks upgrades files when it saves them and older versions can't "
                           "open them."],
    ["Team's currency", "The symbol costs are shown with."],
], [1.8, 4.7]),
("h2", "Keeping the vault healthy"),
("ul", [
    "**Vault > Update file rules...** appears when Litterbox has newer rules for which files Git LFS stores and "
    "locks. An Admin is asked once per session; the update changes only Litterbox's own lines.",
    "**Vault > Vault Size...** shows how much the vault takes up on the host (its history and every version of "
    "every file in Git LFS) and how much is downloaded on your computer. Worth checking on hosts with small LFS "
    "allowances.",
    "Some features raise the oldest Litterbox version the vault accepts (workflows, projects, documents ...). "
    "Litterbox tells anyone on an older version to update before they upload anything.",
]),

("h1", "Importing existing CAD"),
("p", "Create > **Import...** brings a folder of existing SolidWorks files into the vault, giving each part a "
      "number and renaming the files to match, with their references updated so assemblies still find their parts."),
("ol", [
    "Pick the folders to import (or a saved scan). Litterbox scans them with SolidWorks: which files are parts, "
    "assemblies and drawings, what each assembly uses, and which files the vault already has.",
    "Review the table. Each item gets a proposed part number, which you can change, and a name. Choose a project "
    "if you use them, or import a family under one base number. Untick anything you don't want.",
    "**Finish & Import** copies the files into the vault under their new names through SolidWorks, creates the "
    "records and uploads everything. STEP and PDF files with the same name as a model or drawing come along too.",
]),
("p", "**Import COTS...** does the same for purchased parts and records them as COTS straight away. If an import "
      "stops part-way, Litterbox remembers what it had done and can pick up or clean up next time."),
("tip", "Try an import on a copy of a small, self-contained assembly first. Imported files are renamed, so "
        "anything outside the import that pointed at the old files won't follow them."),

("h1", "Working with SolidWorks"),
("p", "Litterbox talks to SolidWorks through its API for the things that need it: reading references, counting "
      "parts, reading materials, copying files at Revise and Import, and making STEP and PDF files. Some notes on "
      "how that behaves:"),
("ul", [
    "When it needs SolidWorks and it isn't running, Litterbox starts one **out of sight** and closes it afterwards. "
    "When it is running, Litterbox uses it, and leaves documents you have open as they are.",
    "At check-in it only uses a SolidWorks that's already running; it never starts one just to check in.",
    "Litterbox reads your installed SolidWorks version from Windows, without starting it, for the org's version "
    "check.",
    "Litterbox can also **watch** what SolidWorks has open (add `solidworks_watch: true` to settings.yaml): it then "
    "warns before checking in parts with unsaved changes, and before Get Latest replaces a file you have open.",
]),

("h1", "Settings and troubleshooting"),
("h2", "Your settings"),
("p", "Your personal settings live in C:\\Litterbox\\settings.yaml, outside every vault, and are never shared. "
      "Most are set from the program (columns, text size, the open org). A few are only in the file:"),
("table", ["Setting", "Effect"], [
    ["update_check: false", "Don't look for a newer Litterbox at start-up."],
    ["download: all", "Download every CAD file, not just those you use."],
    ["open_with", "Which program opens each file type."],
    ["solidworks_watch: true", "Watch what SolidWorks has open (see Working with SolidWorks)."],
    ["solidworks_popups: false", "Send the watcher's warnings to the log instead of pop-ups."],
    ["debug_mode: true", "More detail in the log, including how long each step took."],
], [2.2, 4.3]),
("p", "View > **Text size** (Ctrl+= and Ctrl+-) makes everything bigger or smaller, and Litterbox follows Windows' "
      "display scaling on each monitor."),
("h2", "When something goes wrong"),
("ul", [
    "A real problem turns the status bar's dot red. Press **Details...** for what went wrong and what to do about "
    "it. Problems don't interrupt you with pop-ups.",
    "The **Log** (View > Log, or the status bar) shows every Git command and its result. The full log is "
    "C:\\Litterbox\\logs\\litterbox.log; send it along when you ask for help.",
    "If an upload is refused because someone uploaded first, Litterbox gets their changes and tries again. If it "
    "can't, your commits are kept and nothing is left half done; try again in a minute.",
    "If Git LFS's lock cache gets damaged, Litterbox moves it aside and carries on.",
]),
("h2", "The command line"),
("p", "For scripting and bulk work, the same features run from a terminal in the app folder of a source copy: "
      "`python -m litterbox <command>`, with status and the part actions (checkout, checkin, release ...), "
      "new-part, scan, import and init-vault. `python -m litterbox <command> --help` lists each one's options."),

("h1", "Quick reference"),
("table", ["Keys", "Does"], [
    ["Ctrl+1 ... Ctrl+5", "Parts, Workflows, ECOs, Team, Documents"],
    ["F5", "Refresh"],
    ["Ctrl+= / Ctrl+- / Ctrl+0", "Text larger, smaller, reset"],
    ["Alt+F, Alt+A, Alt+V, Alt+H", "Open the File, Vault, View and Help menus"],
    ["Double-click a part", "Its details in a window of its own"],
    ["Shift-click a tick box", "Tick everything between the last click and this one"],
], [2.3, 4.2]),
]
