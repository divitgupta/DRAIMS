# DRAIMS web application (checkpoint 8: forms, security and validation)

A Flask web app on top of the `draims` MySQL database. It runs fully offline: the server, the database and every
CSS/JS file live on one computer, and other computers on the local network open it in a browser.

The interface is a dark operations console. Bootstrap, the two fonts (Archivo and JetBrains Mono, both under the
SIL Open Font License) and the images are stored in `static/`, so no page loads anything from the internet.

## Setup (once)

1. Load the database (as MySQL root):
   ```
   mysql -u root -p < ../DRAIMS_database.sql
   ```
2. Create the restricted application account. Edit the password in `create_app_user.sql` first:
   ```
   mysql -u root -p < create_app_user.sql
   ```
3. Install the Python packages:
   ```
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

## Run

```
./run.sh
```
It asks for the `draims_app` MySQL password and starts the app at http://localhost:8000. Other computers on the
same network use `http://<this computer's IP>:8000`. Port 8000 is used because macOS keeps port 5000 for AirPlay Receiver.
To use another port: `DRAIMS_PORT=8080 ./run.sh`.

Settings come from environment variables: `DRAIMS_DB_HOST`, `DRAIMS_DB_PORT`, `DRAIMS_DB_USER`,
`DRAIMS_DB_PASSWORD`, `DRAIMS_DB_NAME`, `DRAIMS_HOST`, `DRAIMS_PORT`.

## Demo logins

All demo users in the database script use the password `Relief@2026`.

| Username | Role |
|---|---|
| admin | Administrator |
| coord.kodagu | Relief Coordinator |
| wm.madikeri | Warehouse Manager |
| fo.kodagu | Field Officer |

## Forms

Login, users, disasters and zones, donors and donations, new relief request (with item rows), request list,
priority allocation, dispatch and delivery, inventory reorder levels.

## Security in brief

- Passwords stored as salted PBKDF2-SHA256 hashes (600,000 iterations); password policy on new users
- Account locked for 10 minutes after 5 failed logins; generic login error
- Role checks on every page and action on the server; menu shows only allowed pages
- CSRF token on every form; session cookie HttpOnly and SameSite=Strict; 30-minute idle timeout
- Parameterised SQL everywhere; Jinja2 auto-escaping; Content-Security-Policy with no inline scripts
- Restricted MySQL account (no DELETE, DROP or ALTER); security events written to `logs/security.log`

## Tests

The tests reload the database from `DRAIMS_database.sql`, so run them only against a test database:
```
DRAIMS_DB_USER=root DRAIMS_DB_PASSWORD=<root password> .venv/bin/pytest -q tests
```
