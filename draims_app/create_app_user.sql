-- Least-privilege MySQL account for the DRAIMS web application.
-- Run once as root:  mysql -u root -p < create_app_user.sql   (change the password first)
-- The app can read, insert and update rows and call the procedures, but it cannot
-- DELETE rows, DROP or ALTER tables, or create users.
CREATE USER IF NOT EXISTS 'draims_app'@'localhost' IDENTIFIED BY 'Change-This-Password-1';
GRANT SELECT, INSERT, UPDATE ON draims.* TO 'draims_app'@'localhost';
GRANT EXECUTE ON draims.* TO 'draims_app'@'localhost';
FLUSH PRIVILEGES;
