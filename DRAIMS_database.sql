-- =====================================================================
--  Disaster Resource Allocation and Dynamic Inventory Management System
--  (DRAIMS) - MySQL database script
--  Course : Database Management Systems (CD252IA) - Mini Project, RVCE
--  Needs  : MySQL Community Server 8.0.16 or later. Runs fully offline.
--  Run    : mysql -u root -p < DRAIMS_database.sql
--  Builds : 11 tables, 1 function, 4 procedures, 6 triggers, 4 views
--           and a simulated flood scenario for testing.
-- =====================================================================

DROP DATABASE IF EXISTS draims;
CREATE DATABASE draims CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE draims;

-- =====================================================================
-- 1. TABLES
-- =====================================================================

CREATE TABLE app_user (
  user_id        INT           AUTO_INCREMENT PRIMARY KEY,
  full_name      VARCHAR(80)   NOT NULL,
  username       VARCHAR(30)   NOT NULL UNIQUE,
  password_hash  VARCHAR(255)  NOT NULL,
  role           ENUM('ADMIN','COORDINATOR','WAREHOUSE_MANAGER','FIELD_OFFICER') NOT NULL
);

CREATE TABLE disaster (
  disaster_id    INT           AUTO_INCREMENT PRIMARY KEY,
  disaster_name  VARCHAR(100)  NOT NULL,
  disaster_type  ENUM('FLOOD','CYCLONE','EARTHQUAKE','LANDSLIDE','DROUGHT','FIRE','OTHER') NOT NULL,
  start_date     DATE          NOT NULL,
  status         ENUM('ACTIVE','CLOSED') NOT NULL DEFAULT 'ACTIVE'
);

-- an area affected by one disaster
CREATE TABLE zone (
  zone_id              INT          AUTO_INCREMENT PRIMARY KEY,
  disaster_id          INT          NOT NULL,
  zone_name            VARCHAR(80)  NOT NULL,
  district             VARCHAR(50)  NOT NULL,
  affected_population  INT          NOT NULL,
  damage_level         TINYINT      NOT NULL,
  CONSTRAINT uq_zone          UNIQUE (disaster_id, zone_name),
  CONSTRAINT chk_zone_pop     CHECK (affected_population >= 0),
  CONSTRAINT chk_zone_damage  CHECK (damage_level BETWEEN 1 AND 5),
  CONSTRAINT fk_zone_disaster FOREIGN KEY (disaster_id) REFERENCES disaster (disaster_id)
);

CREATE TABLE warehouse (
  warehouse_id    INT          AUTO_INCREMENT PRIMARY KEY,
  warehouse_name  VARCHAR(80)  NOT NULL UNIQUE,
  district        VARCHAR(50)  NOT NULL,
  phone           CHAR(10)     NOT NULL,
  CONSTRAINT chk_wh_phone CHECK (phone REGEXP '^[6-9][0-9]{9}$')
);

CREATE TABLE item (
  item_id    INT          AUTO_INCREMENT PRIMARY KEY,
  item_name  VARCHAR(80)  NOT NULL UNIQUE,
  category   ENUM('FOOD','WATER','MEDICAL','SHELTER','HYGIENE') NOT NULL,
  unit       VARCHAR(20)  NOT NULL
);

-- M:N "STOCKS" between WAREHOUSE and ITEM: the live stock level
CREATE TABLE inventory (
  warehouse_id   INT  NOT NULL,
  item_id        INT  NOT NULL,
  quantity       INT  NOT NULL DEFAULT 0,
  reorder_level  INT  NOT NULL DEFAULT 0,
  PRIMARY KEY (warehouse_id, item_id),
  CONSTRAINT chk_inv_qty     CHECK (quantity >= 0),
  CONSTRAINT chk_inv_reorder CHECK (reorder_level >= 0),
  CONSTRAINT fk_inv_wh   FOREIGN KEY (warehouse_id) REFERENCES warehouse (warehouse_id),
  CONSTRAINT fk_inv_item FOREIGN KEY (item_id)      REFERENCES item (item_id)
);

CREATE TABLE donor (
  donor_id    INT           AUTO_INCREMENT PRIMARY KEY,
  donor_name  VARCHAR(100)  NOT NULL,
  donor_type  ENUM('INDIVIDUAL','NGO','CORPORATE','GOVERNMENT') NOT NULL,
  phone       CHAR(10)      NULL,
  CONSTRAINT chk_donor_phone CHECK (phone IS NULL OR phone REGEXP '^[6-9][0-9]{9}$')
);

-- one item received from one donor at one warehouse
CREATE TABLE donation (
  donation_id    INT   AUTO_INCREMENT PRIMARY KEY,
  donor_id       INT   NOT NULL,
  warehouse_id   INT   NOT NULL,
  item_id        INT   NOT NULL,
  quantity       INT   NOT NULL,
  donation_date  DATE  NOT NULL,
  CONSTRAINT chk_don_qty  CHECK (quantity > 0),
  CONSTRAINT fk_don_donor FOREIGN KEY (donor_id)     REFERENCES donor (donor_id),
  CONSTRAINT fk_don_wh    FOREIGN KEY (warehouse_id) REFERENCES warehouse (warehouse_id),
  CONSTRAINT fk_don_item  FOREIGN KEY (item_id)      REFERENCES item (item_id)
);

CREATE TABLE relief_request (
  request_id    INT       AUTO_INCREMENT PRIMARY KEY,
  zone_id       INT       NOT NULL,
  raised_by     INT       NOT NULL,
  request_date  DATETIME  NOT NULL DEFAULT CURRENT_TIMESTAMP,
  urgency       TINYINT   NOT NULL,
  status        ENUM('PENDING','PARTIAL','ALLOCATED','DELIVERED','CANCELLED') NOT NULL DEFAULT 'PENDING',
  CONSTRAINT chk_req_urgency CHECK (urgency BETWEEN 1 AND 5),
  CONSTRAINT fk_req_zone FOREIGN KEY (zone_id)   REFERENCES zone (zone_id),
  CONSTRAINT fk_req_user FOREIGN KEY (raised_by) REFERENCES app_user (user_id)
);

-- M:N "REQUESTS" between RELIEF_REQUEST and ITEM
CREATE TABLE request_item (
  request_id     INT  NOT NULL,
  item_id        INT  NOT NULL,
  qty_requested  INT  NOT NULL,
  PRIMARY KEY (request_id, item_id),
  CONSTRAINT chk_ri_qty CHECK (qty_requested > 0),
  CONSTRAINT fk_ri_req  FOREIGN KEY (request_id) REFERENCES relief_request (request_id) ON DELETE CASCADE,
  CONSTRAINT fk_ri_item FOREIGN KEY (item_id)    REFERENCES item (item_id)
);

-- stock given from one warehouse to one line of a request
CREATE TABLE allocation (
  allocation_id  INT       AUTO_INCREMENT PRIMARY KEY,
  request_id     INT       NOT NULL,
  item_id        INT       NOT NULL,
  warehouse_id   INT       NOT NULL,
  quantity       INT       NOT NULL,
  allocated_on   DATETIME  NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status         ENUM('ALLOCATED','DISPATCHED','DELIVERED','CANCELLED') NOT NULL DEFAULT 'ALLOCATED',
  CONSTRAINT chk_alloc_qty   CHECK (quantity > 0),
  -- the item must be on the request, and the warehouse must stock the item
  CONSTRAINT fk_alloc_line  FOREIGN KEY (request_id, item_id)
                            REFERENCES request_item (request_id, item_id),
  CONSTRAINT fk_alloc_stock FOREIGN KEY (warehouse_id, item_id)
                            REFERENCES inventory (warehouse_id, item_id)
);

DELIMITER $$

-- =====================================================================
-- 2. FUNCTION: priority score (0-100) of a relief request
--    35% damage level + 30% urgency + 20% affected population
--    (full marks at 10,000 people) + 15% waiting time (full marks at 48 h)
-- =====================================================================
CREATE FUNCTION fn_priority_score (p_request_id INT)
RETURNS DECIMAL(5,2)
NOT DETERMINISTIC READS SQL DATA
BEGIN
  DECLARE v_damage, v_urgency, v_people INT;
  DECLARE v_hours DECIMAL(10,2);

  SELECT z.damage_level, r.urgency, z.affected_population,
         TIMESTAMPDIFF(MINUTE, r.request_date, NOW()) / 60
    INTO v_damage, v_urgency, v_people, v_hours
    FROM relief_request r
    JOIN zone z ON z.zone_id = r.zone_id
   WHERE r.request_id = p_request_id;

  RETURN ROUND(100 * ( 0.35 * v_damage / 5
                     + 0.30 * v_urgency / 5
                     + 0.20 * LEAST(v_people / 10000, 1)
                     + 0.15 * LEAST(GREATEST(v_hours, 0) / 48, 1) ), 2);
END$$

-- =====================================================================
-- 3. STORED PROCEDURES
-- =====================================================================

-- Sets a request's status from its allocations (called by triggers).
CREATE PROCEDURE sp_refresh_request_status (IN p_request_id INT)
BEGIN
  DECLARE v_requested, v_allocated, v_delivered INT DEFAULT 0;

  SELECT COALESCE(SUM(qty_requested), 0) INTO v_requested
    FROM request_item WHERE request_id = p_request_id;

  SELECT COALESCE(SUM(quantity), 0),
         COALESCE(SUM(CASE WHEN status = 'DELIVERED' THEN quantity ELSE 0 END), 0)
    INTO v_allocated, v_delivered
    FROM allocation
   WHERE request_id = p_request_id AND status <> 'CANCELLED';

  UPDATE relief_request
     SET status = CASE
                    WHEN v_allocated = 0            THEN 'PENDING'
                    WHEN v_allocated < v_requested  THEN 'PARTIAL'
                    WHEN v_delivered = v_requested  THEN 'DELIVERED'
                    ELSE 'ALLOCATED'
                  END
   WHERE request_id = p_request_id AND status <> 'CANCELLED';
END$$

-- Allocates the unmet quantity of each item of one request.
-- Rule: a warehouse in the same district first, then the one with most stock.
CREATE PROCEDURE sp_allocate_request (IN p_request_id INT)
BEGIN
  DECLARE v_district VARCHAR(50);
  DECLARE v_item, v_unmet INT;
  DECLARE v_done BOOLEAN DEFAULT FALSE;
  DECLARE cur_items CURSOR FOR
    SELECT ri.item_id,
           ri.qty_requested - COALESCE((SELECT SUM(a.quantity) FROM allocation a
                                         WHERE a.request_id = ri.request_id
                                           AND a.item_id = ri.item_id
                                           AND a.status <> 'CANCELLED'), 0)
      FROM request_item ri
     WHERE ri.request_id = p_request_id;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done = TRUE;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;

  START TRANSACTION;
  SELECT z.district INTO v_district
    FROM relief_request r JOIN zone z ON z.zone_id = r.zone_id
   WHERE r.request_id = p_request_id AND r.status IN ('PENDING', 'PARTIAL');
  IF v_district IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Request is not open for allocation';
  END IF;
  SET v_done = FALSE;

  OPEN cur_items;
  item_loop: LOOP
    FETCH cur_items INTO v_item, v_unmet;
    IF v_done THEN LEAVE item_loop; END IF;
    IF v_unmet > 0 THEN
      BEGIN
        DECLARE v_wh, v_stock INT;
        DECLARE v_wh_done BOOLEAN DEFAULT FALSE;
        DECLARE cur_wh CURSOR FOR
          SELECT i.warehouse_id, i.quantity
            FROM inventory i JOIN warehouse w ON w.warehouse_id = i.warehouse_id
           WHERE i.item_id = v_item AND i.quantity > 0
           ORDER BY (w.district = v_district) DESC, i.quantity DESC;
        DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_wh_done = TRUE;

        OPEN cur_wh;
        wh_loop: LOOP
          FETCH cur_wh INTO v_wh, v_stock;
          IF v_wh_done OR v_unmet = 0 THEN LEAVE wh_loop; END IF;
          INSERT INTO allocation (request_id, item_id, warehouse_id, quantity)
          VALUES (p_request_id, v_item, v_wh, LEAST(v_stock, v_unmet));
          SET v_unmet = v_unmet - LEAST(v_stock, v_unmet);
        END LOOP;
        CLOSE cur_wh;
      END;
    END IF;
  END LOOP;
  CLOSE cur_items;
  COMMIT;
END$$

-- Allocates every open request of active disasters, highest priority first.
CREATE PROCEDURE sp_allocate_pending ()
BEGIN
  DECLARE v_request INT;
  DECLARE v_done BOOLEAN DEFAULT FALSE;
  DECLARE cur_requests CURSOR FOR
    SELECT r.request_id
      FROM relief_request r
      JOIN zone z     ON z.zone_id = r.zone_id
      JOIN disaster d ON d.disaster_id = z.disaster_id
     WHERE r.status IN ('PENDING', 'PARTIAL') AND d.status = 'ACTIVE'
     ORDER BY fn_priority_score(r.request_id) DESC, r.request_date;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done = TRUE;

  OPEN cur_requests;
  request_loop: LOOP
    FETCH cur_requests INTO v_request;
    IF v_done THEN LEAVE request_loop; END IF;
    CALL sp_allocate_request(v_request);
  END LOOP;
  CLOSE cur_requests;
END$$

-- Cancels a request; stock that has not left the warehouse goes back.
CREATE PROCEDURE sp_cancel_request (IN p_request_id INT)
BEGIN
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  IF EXISTS (SELECT 1 FROM allocation
              WHERE request_id = p_request_id AND status IN ('DISPATCHED', 'DELIVERED')) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Stock for this request is already dispatched';
  END IF;
  UPDATE allocation SET status = 'CANCELLED'
   WHERE request_id = p_request_id AND status = 'ALLOCATED';
  UPDATE relief_request SET status = 'CANCELLED' WHERE request_id = p_request_id;
  COMMIT;
END$$

-- =====================================================================
-- 4. TRIGGERS
-- =====================================================================

-- T1 a donation adds to the warehouse stock immediately
CREATE TRIGGER trg_donation_ai AFTER INSERT ON donation
FOR EACH ROW
BEGIN
  INSERT INTO inventory (warehouse_id, item_id, quantity)
  VALUES (NEW.warehouse_id, NEW.item_id, NEW.quantity)
  ON DUPLICATE KEY UPDATE quantity = quantity + NEW.quantity;
END$$

-- T2 requests only for active disasters, only by field officers or coordinators
CREATE TRIGGER trg_request_bi BEFORE INSERT ON relief_request
FOR EACH ROW
BEGIN
  DECLARE v_status VARCHAR(10);
  DECLARE v_role VARCHAR(20);
  SELECT d.status INTO v_status
    FROM zone z JOIN disaster d ON d.disaster_id = z.disaster_id
   WHERE z.zone_id = NEW.zone_id;
  SELECT role INTO v_role FROM app_user WHERE user_id = NEW.raised_by;
  IF v_status <> 'ACTIVE' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Requests can be raised only for active disasters';
  END IF;
  IF v_role NOT IN ('FIELD_OFFICER', 'COORDINATOR') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only field officers or coordinators can raise requests';
  END IF;
  SET NEW.status = 'PENDING';
END$$

-- T3 never allocate more than is requested or more than is in stock
CREATE TRIGGER trg_allocation_bi BEFORE INSERT ON allocation
FOR EACH ROW
BEGIN
  DECLARE v_status VARCHAR(20);
  DECLARE v_requested, v_already, v_stock INT DEFAULT 0;

  SELECT status INTO v_status FROM relief_request WHERE request_id = NEW.request_id;
  IF v_status NOT IN ('PENDING', 'PARTIAL') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Request is not open for allocation';
  END IF;

  SELECT COALESCE(SUM(qty_requested), 0) INTO v_requested
    FROM request_item WHERE request_id = NEW.request_id AND item_id = NEW.item_id;
  IF v_requested = 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This item is not part of the request';
  END IF;
  SELECT COALESCE(SUM(quantity), 0) INTO v_already
    FROM allocation
   WHERE request_id = NEW.request_id AND item_id = NEW.item_id AND status <> 'CANCELLED';
  IF v_already + NEW.quantity > v_requested THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Allocation exceeds the unmet quantity of the request';
  END IF;

  -- lock the stock row so two coordinators cannot take the same units
  SELECT COALESCE(SUM(quantity), 0) INTO v_stock
    FROM inventory WHERE warehouse_id = NEW.warehouse_id AND item_id = NEW.item_id
     FOR UPDATE;
  IF NEW.quantity > v_stock THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Not enough stock in the warehouse';
  END IF;
  SET NEW.status = 'ALLOCATED';
END$$

-- T4 take the stock out and refresh the request status
CREATE TRIGGER trg_allocation_ai AFTER INSERT ON allocation
FOR EACH ROW
BEGIN
  UPDATE inventory SET quantity = quantity - NEW.quantity
   WHERE warehouse_id = NEW.warehouse_id AND item_id = NEW.item_id;
  CALL sp_refresh_request_status(NEW.request_id);
END$$

-- T5 allowed changes: ALLOCATED -> DISPATCHED / CANCELLED, DISPATCHED -> DELIVERED
CREATE TRIGGER trg_allocation_bu BEFORE UPDATE ON allocation
FOR EACH ROW
BEGIN
  IF NEW.request_id <> OLD.request_id OR NEW.item_id <> OLD.item_id
     OR NEW.warehouse_id <> OLD.warehouse_id OR NEW.quantity <> OLD.quantity THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'An allocation cannot be edited; cancel it and allocate again';
  END IF;
  IF NEW.status <> OLD.status AND NOT (
       (OLD.status = 'ALLOCATED'  AND NEW.status IN ('DISPATCHED', 'CANCELLED')) OR
       (OLD.status = 'DISPATCHED' AND NEW.status = 'DELIVERED')) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Invalid allocation status change';
  END IF;
END$$

-- T6 a cancelled allocation returns its stock; any change refreshes the request
CREATE TRIGGER trg_allocation_au AFTER UPDATE ON allocation
FOR EACH ROW
BEGIN
  IF NEW.status = 'CANCELLED' AND OLD.status = 'ALLOCATED' THEN
    UPDATE inventory SET quantity = quantity + NEW.quantity
     WHERE warehouse_id = NEW.warehouse_id AND item_id = NEW.item_id;
  END IF;
  IF NEW.status <> OLD.status THEN
    CALL sp_refresh_request_status(NEW.request_id);
  END IF;
END$$

DELIMITER ;

-- =====================================================================
-- 5. VIEWS
-- =====================================================================

-- stock of every warehouse-item pair with a reorder flag
CREATE VIEW v_stock_status AS
SELECT w.warehouse_name, i.item_name, i.unit, inv.quantity, inv.reorder_level,
       IF(inv.quantity < inv.reorder_level, 'REORDER', 'OK') AS stock_status
  FROM inventory inv
  JOIN warehouse w ON w.warehouse_id = inv.warehouse_id
  JOIN item i      ON i.item_id = inv.item_id;

-- only the rows that need restocking
CREATE VIEW v_low_stock AS
SELECT warehouse_name, item_name, quantity, reorder_level
  FROM v_stock_status
 WHERE stock_status = 'REORDER';

-- each request with its priority score and how much of it is covered
CREATE VIEW v_request_summary AS
SELECT r.request_id, z.zone_name, d.disaster_name, r.urgency, r.status, r.request_date,
       fn_priority_score(r.request_id) AS priority_score,
       rq.requested,
       COALESCE(al.allocated, 0) AS allocated,
       ROUND(100 * COALESCE(al.allocated, 0) / rq.requested, 1) AS fulfilment_pct
  FROM relief_request r
  JOIN zone z     ON z.zone_id = r.zone_id
  JOIN disaster d ON d.disaster_id = z.disaster_id
  JOIN (SELECT request_id, SUM(qty_requested) AS requested
          FROM request_item GROUP BY request_id) rq ON rq.request_id = r.request_id
  LEFT JOIN (SELECT request_id, SUM(quantity) AS allocated
               FROM allocation WHERE status <> 'CANCELLED'
              GROUP BY request_id) al ON al.request_id = r.request_id;

-- demand still not covered, per item, for open requests
CREATE VIEW v_unmet_demand AS
SELECT i.item_name,
       SUM(ri.qty_requested)                             AS requested,
       SUM(COALESCE(al.allocated, 0))                    AS allocated,
       SUM(ri.qty_requested - COALESCE(al.allocated, 0)) AS unmet
  FROM request_item ri
  JOIN relief_request r ON r.request_id = ri.request_id
                       AND r.status IN ('PENDING', 'PARTIAL', 'ALLOCATED')
  JOIN item i ON i.item_id = ri.item_id
  LEFT JOIN (SELECT request_id, item_id, SUM(quantity) AS allocated
               FROM allocation WHERE status <> 'CANCELLED'
              GROUP BY request_id, item_id) al
         ON al.request_id = ri.request_id AND al.item_id = ri.item_id
 GROUP BY i.item_name;

-- =====================================================================
-- 6. SIMULATED SCENARIO (test data). Dates are relative to the day the
--    script runs. Demo login for every user: password Relief@2026
-- =====================================================================
SET @today = CURDATE();
SET @now   = NOW();

INSERT INTO app_user (full_name, username, password_hash, role) VALUES
 ('System Administrator', 'admin',          'pbkdf2:sha256:600000$aaxGGykd22Hqyz6o$0bd00210fb5cc93b1b36a9d53cd69a63aa28e0160f74aeeee951c7c25d95b3de', 'ADMIN'),
 ('Ananya Rao',           'coord.kodagu',   'pbkdf2:sha256:600000$X1ym3AOPt5HQvzZW$a2615c74415df3b0ee313a032e07b32a7abbc65bd37ed273500a1b41e2653edc', 'COORDINATOR'),
 ('Imran Sheikh',         'coord.belagavi', 'pbkdf2:sha256:600000$DWFF1tL902UlsgaL$26052ae5072000a359601e00032b378067860dbcdfd07144de296eae475023e2', 'COORDINATOR'),
 ('Prakash Gowda',        'wm.madikeri',    'pbkdf2:sha256:600000$nCnKPSiw6CNseeMW$9ba4ab2eb3ba4b001bb496a30da90485000db7eee13d9673da7b1c4066717672', 'WAREHOUSE_MANAGER'),
 ('Lakshmi Narayan',      'wm.mysuru',      'pbkdf2:sha256:600000$PymeShEOYYNomDAc$68629a0aaeb0e333a0db32537cd540980c55f4108787179494306af2e7bc3f4c', 'WAREHOUSE_MANAGER'),
 ('Santosh Patil',        'wm.belagavi',    'pbkdf2:sha256:600000$dvVb40EVnXqwxQp9$a42e515eae02277b0cf9293727ffb9a230c9489b4e8770d0f4ca51173b7f6cb3', 'WAREHOUSE_MANAGER'),
 ('Kavya Poonacha',       'fo.kodagu',      'pbkdf2:sha256:600000$gfwl3SN73sk4txdq$0a49cd078bbda883d7e68150cf3db9eb5cb4cb9db5ff5e6ebdae2d772bedf8b0', 'FIELD_OFFICER'),
 ('Rahul Kulkarni',       'fo.belagavi',    'pbkdf2:sha256:600000$8wXLerMfF1BBHcay$2c341a2409f6de20699fa1aa23ac3e6d69f87652d849f1b9b820a287ad9e4939', 'FIELD_OFFICER');

INSERT INTO disaster (disaster_name, disaster_type, start_date) VALUES
 ('Udupi Coastal Cyclone', 'CYCLONE', @today - INTERVAL 25 DAY),
 ('Kodagu Flash Floods',   'FLOOD',   @today - INTERVAL 14 DAY),
 ('Krishna River Floods',  'FLOOD',   @today - INTERVAL 9 DAY);

INSERT INTO zone (disaster_id, zone_name, district, affected_population, damage_level) VALUES
 (1, 'Malpe Coast',   'Udupi',     2000, 2),
 (2, 'Madikeri Town', 'Kodagu',   12000, 5),
 (2, 'Virajpet',      'Kodagu',    6500, 3),
 (2, 'Somwarpet',     'Kodagu',    5200, 4),
 (2, 'Kushalnagar',   'Kodagu',    3000, 2),
 (3, 'Athani',        'Belagavi', 15000, 4),
 (3, 'Chikkodi',      'Belagavi',  9000, 3),
 (3, 'Gokak',         'Belagavi',  4500, 2);

INSERT INTO warehouse (warehouse_name, district, phone) VALUES
 ('Madikeri Relief Depot',       'Kodagu',   '9845100001'),
 ('Mysuru Central Warehouse',    'Mysuru',   '9845100002'),
 ('Belagavi District Warehouse', 'Belagavi', '9845100003');

INSERT INTO item (item_name, category, unit) VALUES
 ('Rice Bag 25 kg',             'FOOD',    'bag'),
 ('Ready-to-Eat Meal Pack',     'FOOD',    'packet'),
 ('Drinking Water 1 L',         'WATER',   'bottle'),
 ('Water Purification Tablets', 'WATER',   'strip'),
 ('ORS Sachet',                 'MEDICAL', 'sachet'),
 ('First Aid Kit',              'MEDICAL', 'kit'),
 ('Tarpaulin Sheet',            'SHELTER', 'piece'),
 ('Blanket',                    'SHELTER', 'piece'),
 ('Family Hygiene Kit',         'HYGIENE', 'kit');

-- reorder levels for every warehouse-item pair (stock starts at zero)
INSERT INTO inventory (warehouse_id, item_id, reorder_level) VALUES
 (1, 1,  20), (1, 2,  800), (1, 3, 1500), (1, 4,  300), (1, 5,  500),
 (1, 6,  40), (1, 7,  100), (1, 8,  200), (1, 9,  100),
 (2, 1, 100), (2, 2, 2000), (2, 3, 4000), (2, 4, 1000), (2, 5, 2000),
 (2, 6, 100), (2, 7,  300), (2, 8,  500), (2, 9,  300),
 (3, 1,  50), (3, 2, 1500), (3, 3, 3000), (3, 4,  800), (3, 5, 1500),
 (3, 6,  50), (3, 7,  150), (3, 8,  400), (3, 9,  300);

INSERT INTO donor (donor_name, donor_type, phone) VALUES
 ('State Disaster Response Fund', 'GOVERNMENT', NULL),
 ('Sahaya Relief Foundation',     'NGO',        '9900011122'),
 ('GreenLeaf Foods Pvt Ltd',      'CORPORATE',  '9900033344'),
 ('Medicare Distributors',        'CORPORATE',  '9900055566'),
 ('Ravi Kumar',                   'INDIVIDUAL', '9900077788'),
 ('Jal Seva Trust',               'NGO',        '9900099900');

-- ---- Udupi cyclone (handled and closed) ------------------------------
INSERT INTO donation (donor_id, warehouse_id, item_id, quantity, donation_date) VALUES
 (2, 2, 7, 600, @today - INTERVAL 26 DAY),
 (2, 2, 8, 800, @today - INTERVAL 26 DAY);

SET TIMESTAMP = UNIX_TIMESTAMP(TIMESTAMP(@today - INTERVAL 24 DAY, '09:00:00'));
INSERT INTO relief_request (zone_id, raised_by, urgency) VALUES (1, 2, 3);       -- request 1
INSERT INTO request_item VALUES (1, 7, 150), (1, 8, 300);
SET TIMESTAMP = UNIX_TIMESTAMP(TIMESTAMP(@today - INTERVAL 24 DAY, '11:00:00'));
CALL sp_allocate_request(1);
UPDATE allocation SET status = 'DISPATCHED' WHERE request_id = 1;
UPDATE allocation SET status = 'DELIVERED'  WHERE request_id = 1;
UPDATE disaster SET status = 'CLOSED' WHERE disaster_id = 1;

-- ---- donations for the floods ----------------------------------------
INSERT INTO donation (donor_id, warehouse_id, item_id, quantity, donation_date) VALUES
 (1, 2, 1,   600, @today - INTERVAL 12 DAY),
 (1, 2, 3, 12000, @today - INTERVAL 12 DAY),
 (1, 2, 4,  5000, @today - INTERVAL 12 DAY),
 (1, 2, 9,  1200, @today - INTERVAL 12 DAY),
 (1, 2, 8,  2000, @today - INTERVAL 12 DAY),
 (3, 2, 2,  9000, @today - INTERVAL 11 DAY),
 (4, 2, 5,  6000, @today - INTERVAL 10 DAY),
 (4, 2, 6,   400, @today - INTERVAL 10 DAY),
 (2, 1, 2,  2500, @today - INTERVAL 10 DAY),
 (2, 1, 5,  1500, @today - INTERVAL 10 DAY),
 (2, 1, 6,   120, @today - INTERVAL 10 DAY),
 (2, 1, 7,   450, @today - INTERVAL 10 DAY),
 (2, 1, 8,   800, @today - INTERVAL 10 DAY),
 (6, 1, 3,  5500, @today - INTERVAL 9 DAY),
 (1, 3, 3,  9000, @today - INTERVAL 8 DAY),
 (1, 3, 2,  7500, @today - INTERVAL 8 DAY),
 (1, 3, 4,  2500, @today - INTERVAL 8 DAY),
 (1, 3, 9,   600, @today - INTERVAL 8 DAY),
 (5, 3, 8,   300, @today - INTERVAL 7 DAY),
 (4, 3, 5,  2500, @today - INTERVAL 6 DAY);

-- ---- last 30 hours: field requests ------------------------------------
SET TIMESTAMP = UNIX_TIMESTAMP(@now - INTERVAL 30 HOUR);
INSERT INTO relief_request (zone_id, raised_by, urgency) VALUES (2, 7, 5);       -- request 2
INSERT INTO request_item VALUES (2, 3, 3000), (2, 2, 2000), (2, 6, 60);
SET TIMESTAMP = UNIX_TIMESTAMP(@now - INTERVAL 28 HOUR);
INSERT INTO relief_request (zone_id, raised_by, urgency) VALUES (4, 7, 4);       -- request 3
INSERT INTO request_item VALUES (3, 7, 400), (3, 8, 700), (3, 1, 120);
SET TIMESTAMP = UNIX_TIMESTAMP(@now - INTERVAL 26 HOUR);
CALL sp_allocate_request(2);
CALL sp_allocate_request(3);
SET TIMESTAMP = UNIX_TIMESTAMP(@now - INTERVAL 24 HOUR);
UPDATE allocation SET status = 'DISPATCHED' WHERE request_id = 2;
SET TIMESTAMP = UNIX_TIMESTAMP(@now - INTERVAL 22 HOUR);
UPDATE allocation SET status = 'DELIVERED' WHERE request_id = 2;
SET TIMESTAMP = UNIX_TIMESTAMP(@now - INTERVAL 20 HOUR);
INSERT INTO relief_request (zone_id, raised_by, urgency) VALUES (3, 7, 3);       -- request 4
INSERT INTO request_item VALUES (4, 3, 2500), (4, 5, 1200);
SET TIMESTAMP = UNIX_TIMESTAMP(@now - INTERVAL 19 HOUR);
UPDATE allocation SET status = 'DISPATCHED' WHERE request_id = 3 AND warehouse_id = 1;
SET TIMESTAMP = UNIX_TIMESTAMP(@now - INTERVAL 18 HOUR);
CALL sp_allocate_request(4);
SET TIMESTAMP = UNIX_TIMESTAMP(@now - INTERVAL 10 HOUR);
INSERT INTO relief_request (zone_id, raised_by, urgency) VALUES (6, 8, 5);       -- request 5
INSERT INTO request_item VALUES (5, 3, 6000), (5, 5, 2500), (5, 9, 1500);
SET TIMESTAMP = UNIX_TIMESTAMP(@now - INTERVAL 8 HOUR);
INSERT INTO relief_request (zone_id, raised_by, urgency) VALUES (7, 8, 4);       -- request 6
INSERT INTO request_item VALUES (6, 2, 5000), (6, 8, 600);
SET TIMESTAMP = UNIX_TIMESTAMP(@now - INTERVAL 5 HOUR);
INSERT INTO relief_request (zone_id, raised_by, urgency) VALUES (8, 8, 2);       -- request 7
INSERT INTO request_item VALUES (7, 4, 1500), (7, 9, 600);
SET TIMESTAMP = UNIX_TIMESTAMP(@now - INTERVAL 3 HOUR);
INSERT INTO relief_request (zone_id, raised_by, urgency) VALUES (5, 7, 3);       -- request 8
INSERT INTO request_item VALUES (8, 6, 50), (8, 1, 80);
SET TIMESTAMP = DEFAULT;
