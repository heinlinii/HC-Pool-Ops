HEINLIN ADMIN DELETE PACKAGE

Adds admin-only delete actions for:
- Photos
- Clients
- Properties
- Jobs

Important behavior:
- Client delete also removes related properties, jobs, photo records, job costs, invoices, equipment, and local uploaded files where possible.
- Property delete also removes related equipment, jobs, photo records, job costs, invoices, and local uploaded files where possible.
- Job delete removes related photo records, job costs, invoices, and local uploaded files where possible.
- Photo delete removes the photo log and local uploaded file if it is under /static/uploads/.

Install:
1. Extract this ZIP.
2. Copy the app folder into:
   C:\dev\HC-Pool-Ops-2\HC-Pool-Ops-Jarvis-Built\HC-Pool-Ops
3. Replace files.
4. In VS Code terminal:
   cd "C:\dev\HC-Pool-Ops-2\HC-Pool-Ops-Jarvis-Built\HC-Pool-Ops"
   git add app/app.py app/models.py app/templates/client_detail.html app/templates/property_detail.html app/templates/job_detail.html app/templates/photos.html app/static/style.css
   git commit -m "Add admin delete controls"
   git push origin main
5. Render -> Deploy latest commit.

Test:
- Open a client detail page and use Delete Client.
- Open a property detail page and use Delete Property.
- Open a job detail page and use Delete Job.
- Open Photos and use Delete Photo.
