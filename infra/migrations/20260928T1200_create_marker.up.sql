-- Marker measurement — the physical scale references an Administrator registers,
-- and the only new table the feature needs.
--
-- A **Marker** is an object of known size (a printed fiducial card, an ID
-- badge, a bank card) that a staff member lays on a tile before photographing
-- it. The photo's pixels carry no scale; a Marker of known width and height in
-- the same frame is what turns pixel distances into millimetres.
--
-- **No foreign key to anything, in either direction, and that is the point.** A
-- Marker names no Tile, no Size and no Category — it is a ruler, not a
-- catalogue entry. A `size_id` here would be a second identity model of exactly
-- the kind AD-18 retired, quietly asserting that a given ruler belongs to a
-- given range. Measurements are likewise **not** stored: the result is a
-- suggestion that pre-fills the Scan screen's Size picker for one submission,
-- and what the staff member actually declared is already recorded by the Scan
-- row that `20260922T1900_create_scan` owns. Persisting the suggestion too
-- would give two answers to "what size was this scanned as" and no rule for
-- which one is true.
--
-- **The fiducial pair is both-or-neither, enforced by a CHECK.** A Marker
-- carrying both `aruco_dictionary` and `aruco_id` is found automatically in the
-- frame; one carrying neither is a plain object that only the manual
-- corner-tap path can use. Half a declaration is a card the detector will never
-- find and nobody would be told why, so the database refuses it rather than
-- leaving the rule to whichever of the two writers remembered it.
--
-- **Dimensions are `double precision`, not `numeric`.** Every consumer is
-- floating-point geometry — the homography in `api.measure`, the tolerance
-- comparison in `shared_schema.marker.match_size` — and a `numeric` would be
-- converted to a float at every one of them. The precision `numeric` protects
-- is precision a tape measure never had.
--
-- `IF NOT EXISTS` throughout, matching the eight migrations before it: a
-- truncated ledger must be able to replay the whole set.
--
-- **Apply this before deploying the code that reads it.** `apps/api/api/markers.py`
-- names this table and `GET /admin/markers` cannot serve a request without it.

CREATE TABLE IF NOT EXISTS marker (
    id                uuid              PRIMARY KEY DEFAULT gen_random_uuid(),
    -- The label a staff member reads off the Scan screen's picker. UNIQUE
    -- because two rulers called "ID badge" with different dimensions is a
    -- measurement that is wrong half the time with nothing on screen to say
    -- which half. Stored in the case it was typed — `shared_schema.marker`
    -- collapses and trims but never uppercases, because this is read by a
    -- human rather than joined on.
    name              text              NOT NULL UNIQUE,
    -- The printed size of the marker itself, in millimetres. For a fiducial
    -- this is the black square's outer edge, not the paper around it: the
    -- detector returns the black square's corners, and measuring to the paper
    -- would scale every result taken with this card by the quiet zone's width.
    width_mm          double precision  NOT NULL,
    height_mm         double precision  NOT NULL,
    -- Null together, or set together — see the CHECK below.
    aruco_dictionary  text,
    aruco_id          integer,
    created_at        timestamptz       NOT NULL DEFAULT now(),
    -- `users` has no BEFORE UPDATE trigger and every writer sets `updated_at`
    -- by hand (DW-17); `tile` follows the same rule, and so does this. This
    -- schema does not use triggers for invariants.
    updated_at        timestamptz       NOT NULL DEFAULT now(),

    -- The bounds `shared_schema.marker.clean_edge_mm` states, restated where
    -- they cannot be bypassed. Both ends are about arithmetic: below the floor
    -- one pixel of corner error moves the derived scale by more than the 1.5x
    -- gap between `45X90` and `60X30` — the confusion this feature exists to
    -- break — and above the ceiling the "marker" is larger than every tile in
    -- the catalogue and is almost certainly a typo that would silently scale
    -- every measurement taken with it.
    CONSTRAINT marker_width_mm_bounds
        CHECK (width_mm >= 20.0 AND width_mm <= 1000.0),
    CONSTRAINT marker_height_mm_bounds
        CHECK (height_mm >= 20.0 AND height_mm <= 1000.0),

    -- Both or neither. See the header.
    CONSTRAINT marker_aruco_pair
        CHECK ((aruco_dictionary IS NULL) = (aruco_id IS NULL)),

    -- The four families `shared_schema.marker.ArucoDictionary` allows, and the
    -- id range each one actually holds. A card printed with id 60 in
    -- `DICT_4X4_50` does not exist, and a Marker declaring one would be
    -- undetectable with no way to tell that from bad lighting.
    CONSTRAINT marker_aruco_dictionary_known
        CHECK (aruco_dictionary IS NULL OR aruco_dictionary IN (
            'DICT_4X4_50', 'DICT_5X5_100', 'DICT_6X6_250', 'DICT_APRILTAG_36h11'
        )),
    CONSTRAINT marker_aruco_id_in_range
        CHECK (
            aruco_id IS NULL
            OR (aruco_dictionary = 'DICT_4X4_50'        AND aruco_id BETWEEN 0 AND 49)
            OR (aruco_dictionary = 'DICT_5X5_100'       AND aruco_id BETWEEN 0 AND 99)
            OR (aruco_dictionary = 'DICT_6X6_250'       AND aruco_id BETWEEN 0 AND 249)
            OR (aruco_dictionary = 'DICT_APRILTAG_36h11' AND aruco_id BETWEEN 0 AND 586)
        )
);

-- The Scan screen lists every Marker on arrival, ordered by name, and there
-- will never be many — this is a handful of rulers, not a catalogue. No index
-- beyond the primary key and the UNIQUE on `name`, which already serves both
-- the duplicate check and the ordering.

-- --- Grants -------------------------------------------------------------------
-- Full DML, not `ALL PRIVILEGES`: TRUNCATE, REFERENCES and TRIGGER are not
-- things the application does. Spelled out per table because this schema has no
-- `ALTER DEFAULT PRIVILEGES` to fall back on — see the audit-log migration's
-- header for why — and `apps/api/tests/test_audit_immutability.py` fails the
-- build the day a table lands without one.

GRANT SELECT, INSERT, UPDATE, DELETE ON marker TO rocell_app;
