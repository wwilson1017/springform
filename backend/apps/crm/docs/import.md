---
title: Importing people
summary: Bring people and their organizations in from a CSV or vCard file, review them, then save
order: 15
---
## What you can import

A **CSV** file (a spreadsheet saved as CSV) or a **vCard** file (`.vcf`, exported from a phone or an
address book), up to 2 MB.

## How it works

1. Choose the file. The CRM reads it and shows you the people it found. Nothing is saved yet.
2. Review the list: fix a name, drop a row you do not want.
3. Save. Each person is created in the shared directory with their email, phone, title, source,
   tags and notes. Their organization is matched by name (ignoring case and spacing), created if it
   is new, and linked.

A row that cannot be saved is skipped and listed with its reason; the rest are saved.

## Columns

Common headers are recognised on their own: name (or first and last name), email, phone,
organization or company, title, source, tags and notes. When the headers are unusual and an AI
provider is set up, the light model maps them for you; without one, rename the columns to the
common headers and try again.

## Duplicates

The import does not merge people. After importing, the People page's duplicate finder shows people
who look like the same person, and merging keeps every deal and note.
