# G3 screen-reader journey (owner run)

**Tester:** owner · **Date:** · **Screen reader and browser:** (for example NVDA 2025 with Chrome, or Narrator with Edge) · **Stack:** the dev stack through the DevSpaces proxy · **Build:** `feat/M9-preferences`

For each step, note what was announced, put Pass or Fail, and add any notes. "Expected" is what the build is designed to say.

| # | Step | Expected | Heard | Pass or fail | Notes |
| --- | --- | --- | --- | --- | --- |
| 1 | Open the sign-in page, then Tab to Email, Password and Sign in | Labels "Email", "Password" and the "Sign in" button; a wrong password is announced as an alert | | | |
| 2 | After sign-in, press H (next heading), then D (next landmark) | The heading "Map", then the landmarks banner, navigation "Main", main and contentinfo; the skip link "Skip to main content" is first in Tab order | | | |
| 3 | Tab through the left rail | Links "Map", "Items", "User" and "Settings"; the current page is announced as current | | | |
| 4 | On the map page, Tab to Period, View and Colour by | Comboboxes with their labels; changing one announces the status line ("N jurisdictions with changes in the last N days") | | | |
| 5 | Tab to the jurisdiction list and use the Down arrow | Listbox "Jurisdictions with changes in the last 30 days, newest first"; each option reads its name and summary (items changed, last date, highest severity) | | | |
| 6 | Press Enter on a jurisdiction | The status line says "Selected: …"; focus moves to the side panel heading; Escape closes it and returns focus to the list | | | |
| 7 | Choose Show as: Table | A table with a caption that states the count and the sort; the column headers are announced; the sorted column is announced as sorted | | | |
| 8 | In the panel, open the latest item | The item heading; Tab reaches the tab list; Left and Right arrows move between Summary, Content, Versions and Diff, and each panel is read | | | |
| 9 | On Items, search for a word | Search landmark, the "Search items" box; the result caption is announced; highlighted words are read as normal text | | | |
| 10 | User tab: change Text size and Theme | Comboboxes with labels; "Saved; it applies on every device you sign in on." is announced | | | |
| 11 | User tab: the sessions table | The caption "Where you are signed in"; each "Sign out this session" button names its session | | | |
| 12 | Idle warning (optional: on the User tab set "Sign out after inactivity" to 15 minutes and wait about 13 minutes without input) | An alert dialog "You will be signed out soon" with its text; focus on "Stay signed in"; the time is announced at 60, 30 and 10 seconds; Tab stays inside the dialog | | | |

**Overall:** pass or fail · **Notes:**
