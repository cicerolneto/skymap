import sys
import time
import math
import urllib
from bs4 import BeautifulSoup
from datetime import datetime
from multiprocessing import Process, current_process
from skymap.database import SkyMapDatabase
from skymap.geometry import ensure_angle_range, SphericalPoint
from skymap.constellations import ConstellationFinder
from skymap.coordinates import julian_year_difference, REFERENCE_EPOCH


RAD_TO_DEG = 360.0/(2*math.pi)
J1991_TO_J2000_PM_CONVERSION_FACTOR = ((datetime(2000, 1, 1).date() - datetime(1991, 4, 1).date()).days/365.25)/3.6e6
KM_PER_S_TO_PARSEC_PER_YEAR = 1.0/977780.0
MAS_FOR_FULL_CIRCLE = 360*60*60*1000.0
HIPPARCOS_EPOCH = datetime(1991, 4, 1).date()
TYCHO2_EPOCH = REFERENCE_EPOCH


GREEK_LETTERS = {
    "alp": "alpha",
    "bet": "beta",
    "gam": "gamma",
    "del": "delta",
    "eps": "epsilon",
    "zet": "zeta",
    "eta": "eta",
    "the": "theta",
    "iot": "iota",
    "kap": "kappa",
    "lam": "lambda",
    "mu": "mu",
    "nu": "nu",
    "xi": "xi",
    "omi": "omicron",
    "pi": "pi",
    "rho": "rho",
    "sig": "sigma",
    "tau": "tau",
    "ups": "upsilon",
    "phi": "phi",
    "chi": "chi",
    "psi": "psi",
    "ome": "omega"
}


def propagate_position(from_epoch, to_epoch, right_ascension, declination, proper_motion_ra, proper_motion_dec):
    """
    Simple propagation in angular coordinates.

    :param from_epoch: datetime
    :param to_epoch: datetime
    :param right_ascension: in degrees
    :param declination: in degrees
    :param proper_motion_ra: in mas/year, corrected for declination
    :param proper_motion_dec: in mas/year
    :return: new position
    """

    if not proper_motion_dec or not proper_motion_ra:
        return right_ascension, declination

    dt = julian_year_difference(to_epoch, from_epoch)

    # Convert proper motions to degrees per Julian year
    # 1 mas/year = 1e-3 as/year = 1e-3/60.0 amin/year = 1e-3/3600 degrees/year
    pm_ra = proper_motion_ra / 3.6e6
    pm_dec = proper_motion_dec / 3.6e6

    # Calculate the new positions
    ra = right_ascension + dt * pm_ra/math.cos(declination)
    dec = declination + dt * pm_dec

    return ra, dec


def propagate_position2(from_epoch, to_epoch, right_ascension, declination, proper_motion_ra, proper_motion_dec, distance=1.0, radial_velocity=0.0):
    """
    Rigorous propagation in Cartesian coordinates, using parallax information.

    :param from_epoch: datetime
    :param to_epoch: datetime
    :param right_ascension: in degrees
    :param declination: in degrees
    :param proper_motion_ra: in mas/year
    :param proper_motion_dec: in mas/year
    :param distance: in parsec
    :param radial_velocity: in km/s
    :return: new position
    """

    # Convert time difference to Julian years
    dt = julian_year_difference(to_epoch, from_epoch)

    # Convert degrees to radians
    right_ascension = math.radians(right_ascension)
    declination = math.radians(declination)

    # Convert proper motion (mas/year) to linear velocity in km/s
    velocity_ra = proper_motion_ra * 2 * math.pi * distance/(MAS_FOR_FULL_CIRCLE * KM_PER_S_TO_PARSEC_PER_YEAR)
    velocity_dec = proper_motion_dec * 2 * math.pi * distance/(MAS_FOR_FULL_CIRCLE * KM_PER_S_TO_PARSEC_PER_YEAR)

    # Convert spherical location to Cartesian location in parsecs
    # +x towards RA 0h, DEC 0
    # +y towards RA 6h, DEC 0
    # +z towards DEC 90
    x = distance * math.cos(declination) * math.cos(right_ascension)
    y = distance * math.cos(declination) * math.sin(right_ascension)
    z = distance * math.sin(declination)

    # Convert spherical velocities to Cartesian, in km/s
    vx = (radial_velocity * math.cos(declination) * math.cos(right_ascension)) - (velocity_ra * math.sin(right_ascension)) - (velocity_dec * math.sin(declination) * math.cos(right_ascension))
    vy = (radial_velocity * math.cos(declination) * math.sin(right_ascension)) + (velocity_ra * math.cos(right_ascension)) - (velocity_dec * math.sin(declination) * math.sin(right_ascension))
    vz = radial_velocity * math.sin(declination) + velocity_dec * math.cos(declination)

    # Convert velocities from km/s to parsec/yr
    vx *= KM_PER_S_TO_PARSEC_PER_YEAR
    vy *= KM_PER_S_TO_PARSEC_PER_YEAR
    vz *= KM_PER_S_TO_PARSEC_PER_YEAR

    # Propagate position in parsecs
    x += vx * dt
    y += vy * dt
    z += vz * dt

    # Convert new position to spherical
    dxy = math.sqrt(x**2 + y**2)
    right_ascension = math.degrees(math.atan2(y, x))
    declination = math.degrees(math.atan2(z, dxy))

    if right_ascension < 0:
        right_ascension += 360.0

    return right_ascension, declination


def angular_separation_seconds_of_arc(ra1, de1, ra2, de2):
    """
    Calculates the angular separation of two points.

    :param ra1: Right ascension of first point in degrees
    :param de1: Declination of first point in degrees
    :param ra2: Right ascension of second point in degrees
    :param de2: Declination of second point in degrees
    :return: The angular separation in seconds of arc.
    """

    dra = ra1 - ra2
    dde = de1 - de2
    return 3600 * math.sqrt((dra * math.cos(math.radians(de2))) ** 2 + dde ** 2)


def angular_sep_to_local_degrees(ra, de, sep):
    """
    Comverts the given angular separation from seconds of arc to local degrees.

    :param ra: The right ascension of the point at which to convert the angular separation, in degrees
    :param de: The declination of the point at which to convert the angular separation, in degrees
    :param sep: The angular separation to convert, in seconds of arc
    :return: A tuple containing the separation in degrees in RA and DE direction, both equal to the input separation
    """

    return sep/(3600.0*math.cos(de)), sep/3600.0


class Star(object):
    """
    A star.
    """

    def __init__(self, row):
        """
        Initialize the star object from a SkyMapDatabase star record.

        :param row: The database record for the star
        """

        self.data = row

    @property
    def hip(self):
        return self.data['hip']

    @property
    def bayer(self):
        """Returns the Bayer designation for the star, if present"""
        return self.data['bayer']

    @property
    def flamsteed(self):
        """Returns the Flamsteed number for the star, if present"""
        return self.data['flamsteed']

    @property
    def proper_name(self):
        """Returns the proper name for the star, if present"""
        return self.data['proper_name']

    @property
    def identifier_string(self):
        return ""

    @property
    def magnitude(self):
        """Retuns the visual magnitude for the star"""
        m = [self.data['hp_magnitude'], self.data['vt_magnitude'], self.data['magnitude']]
        return next((item for item in m if item is not None), None)

    @property
    def is_variable(self):
        """Returns true if the star is variable"""
        return (self.data['variability_type'] == "P") or (self.data['tyc_variable_flag'] == "V")

    @property
    def is_multiple(self):
        """Returns True if the star is a binary or multiple star system"""
        ncomp = self.data['number_of_components']
        if ncomp is not None and ncomp > 1:
            return True
        if self.data['tyc_multiple_flag'] == 'D':
            return True
        return False

    @property
    def min_magnitude(self):
        """Returns the minimum magnitude for variable stars"""
        return self.data['min_magnitude']

    @property
    def max_magnitude(self):
        """Returns the maximum magnitude for variable stars"""
        return self.data['max_magnitude']

    def propagate_position(self, date=None):
        """Propagates the position of the star to the given date"""
        epoch = datetime(2000, 1, 1).date()  # TODO: Use constant, and use that constant epoch as well for building the database
        return propagate_position(epoch, date, self.right_ascension, self.declination, self.proper_motion_ra, self.proper_motion_dec)

    @property
    def right_ascension(self):
        """Returns the database right ascension for the catalogue epoch in degrees"""
        return self.data['right_ascension']

    @property
    def declination(self):
        """Returns the database declination for the catalogue epoch in degrees"""
        return self.data['declination']

    @property
    def position(self):
        """Returns the position of the star in degrees"""
        return SphericalPoint(self.right_ascension, self.declination)

    @property
    def constellation(self):
        """Returns the constellation the star is in"""
        return self.data['constellation']


def build_star_database():
    """
    Builds the SkyMapDatabase using data from Tycho 2, Tycho, Hipparcos.
    Adds supplementary data from the HD-DM-GC-HR-HIP-Bayer-Flamsteed Cross Index, the Bright Star Catalog and the IAU list of proper names.
    Adds constellations.
    """

    db = SkyMapDatabase()
    create_table(db)
    add_tycho2(db)
    add_tycho1(db)
    add_hipparcos(db)
    add_indexes(db)
    add_cross_index(db)
    add_bright_star_catalog(db)
    add_proper_names(db)
    add_constellations(db)


def create_table(db):
    """
    Create the skymap_stars table in the SkyMapDatabase

    :param db: An open SkyMapDatabase instance
    """

    db.drop_table("skymap_stars")

    print "Creating table"
    t1 = time.time()
    q = """CREATE TABLE skymap_stars (
                        id INT NOT NULL AUTO_INCREMENT,
                        hip INT,
                        tyc1 INT,
                        tyc2 INT,
                        tyc3 INT,
                        ccdm VARCHAR(64),
                        ccdm_comp VARCHAR(2),
                        hd1 INT,
                        hd2 INT,
                        hr INT,
                        bd VARCHAR(64),
                        cod VARCHAR(64),
                        cpd VARCHAR(64),
                        bayer VARCHAR(128),
                        flamsteed INT,
                        proper_name VARCHAR(512),
                        variable_name VARCHAR(512),
                        constellation VARCHAR(64),

                        right_ascension DOUBLE,
                        declination DOUBLE,
                        proper_motion_ra DOUBLE,
                        proper_motion_dec DOUBLE,
                        
                        johnsonV DOUBLE,
                        johnsonBV DOUBLE,
                        hp_magnitude DOUBLE,
                        vt_magnitude DOUBLE,
                        bt_magnitude DOUBLE,

                        hp_max DOUBLE,
                        hp_min DOUBLE,
                        vt_max DOUBLE,
                        vt_min DOUBLE,
                        max DOUBLE,
                        min DOUBLE,
                        
                        variable BOOL,
                        multiple BOOL,
                        source VARCHAR(2),
                        
                        PRIMARY KEY (id)
                    )"""

    db.commit_query(q)
    t2 = time.time()
    print "{:.1f} s".format(t2 - t1)


def add_tycho2(db):
    """
    Add all Tycho-2 stars to the database that are not found in Hipparcos or Tycho-1.
    The HD number is added from Tyc2_HD.
    Astrometry is mean position at epoch J2000 (ICRS).

    :param db: An open SkyMapDatabase instance
    """

    print "Inserting Tycho-2 data"
    t1 = time.time()
    q = """
                INSERT INTO skymap_stars (
                    tyc1, tyc2, tyc3, hd1, hd2,
                    right_ascension,
                    declination,
                    proper_motion_ra, proper_motion_dec,
                    bt_magnitude, vt_magnitude,
                    johnsonV, johnsonBV,
                    source
                )
                SELECT
                    t2.TYC1, t2.TYC2, t2.TYC3, t2hd.HD1, t2hd.HD2,
                    IFNULL(t2.RAmdeg, t2.RAdeg) as RAdeg,
                    IFNULL(t2.DEmdeg, t2.DEdeg) as DEdeg,
                    t2.pmRA, t2.pmDE,
                    t2.BTmag, t2.VTmag,
                    t2.VTmag - 0.090 * (t2.BTmag - t2.VTmag),
                    0.085 * (t2.BTmag - t2.VTmag),
                    'T2'
                FROM tyc2_tyc2 AS t2
                LEFT JOIN (
                    SELECT TYC1, TYC2, TYC3, MIN(HD) AS HD1, CASE WHEN COUNT(HD)>1 THEN MAX(HD) ELSE NULL END AS HD2
                    FROM tyc2hd_tyc2_hd
                    WHERE Rem!='D'
                    GROUP BY TYC1, TYC2, TYC3
                ) AS t2hd
                ON t2.TYC1=t2hd.TYC1 AND t2.TYC2=t2hd.TYC2 AND t2.TYC3=t2hd.TYC3
                WHERE t2.HIP IS NULL AND t2.TYC != 'T' AND CONCAT(t2.TYC1, '-', t2.TYC2, '-', t2.TYC3) NOT IN (
                    SELECT CONCAT(TYC1, '-', TYC2, '-', TYC3) FROM hiptyc_tyc_main
                )
            """
    db.commit_query(q)
    t2 = time.time()
    print "{:.1f} s".format(t2 - t1)


def add_tycho1(db):
    """
    Add all Tycho-1 stars to the database that are not found in Hipparcos or Tycho-2 supplement 2, and for which the
    Tycho quality flag is not equal to 9.
    The HD number is added from Tyc2_HD.
    Astrometry is mean position at epoch J1991.25 (ICRS).

    :param db: An open SkyMapDatabase instance
    """
    print "Inserting Tycho-1 data"
    t1 = time.time()
    q = """
                INSERT INTO skymap_stars (
                    tyc1, tyc2, tyc3,
                    right_ascension,
                    declination,
                    proper_motion_ra, proper_motion_dec,
                    johnsonV, johnsonBV,
                    bt_magnitude, vt_magnitude,
                    vt_max, vt_min,
                    hd1, bd, cod, cpd,
                    multiple, variable,
                    source
                )
                SELECT 
                    t1.TYC1, t1.TYC2, t1.TYC3,
                    t1.RAdeg, t1.DEdeg,
                    t1.pmRA, t1.pmDE,
                    t1.Vmag, t1.`B-V`,
                    t1.BTmag, t1.VTmag,
                    t1.VTmax, t1.VTmin,
                    t1.HD, t1.BD, t1.CoD, t1.CPD,
                    t1.MultFlag='D', t1.VarFlag='V',
                    'T1'
                FROM hiptyc_tyc_main AS t1
                WHERE CONCAT(t1.TYC1, '-', t1.TYC2, '-', t1.TYC3) NOT IN (
                    SELECT CONCAT(TYC1, '-', TYC2, '-', TYC3) FROM tyc2_suppl_2
                ) AND t1.HIP IS NULL AND t1.Q != 9;
            """
    db.commit_query(q)
    t2 = time.time()
    print "{:.1f} s".format(t2 - t1)


def add_hipparcos(db):
    """
    Add data from the Hipparcos catalog to the star database.
    Astrometry is mean position at epoch J1991.25 (ICRS).

    :param db: An open SkyMapDatabase instance
    """

    print "Inserting Hipparcos data"
    t1 = time.time()
    q = """
                INSERT INTO skymap_stars (
                    hip, tyc1, tyc2, tyc3, ccdm, ccdm_comp,
                    right_ascension,
                    declination,
                    proper_motion_ra, proper_motion_dec,
                    johnsonV, johnsonBV,
                    bt_magnitude, vt_magnitude,
                    hp_magnitude, hp_max, hp_min,
                    variable,
                    hd1, bd, cod, cpd,
                    source
                )
                SELECT 
                      h.HIP, t.TYC1, t.TYC2, t.TYC3, d.CCDM, d.comp_id,
                      IFNULL(d.RAdeg, h.RAdeg), 
                      IFNULL(d.DEdeg, h.DEdeg),
                      IFNULL(d.pmRA, h.pmRA),
                      IFNULL(d.pmDE, h.pmDE),
                      h.Vmag, h.`B-V`,
                      IFNULL(d.BT, h.BTmag), 
                      IFNULL(d.VT, h.VTmag),
                      IFNULL(d.Hp, h.Hpmag),
                      h.Hpmax, h.Hpmin,
                      CASE WHEN (HVarType='P' OR (HVarType='U' AND Hpmin - Hpmax > 0.2)) THEN 1 ELSE 0 END,
                      h.HD, h.BD, h.CoD, h.CPD,
                      'H'
                FROM 
                    hiptyc_hip_main AS h
                LEFT JOIN 
                    hiptyc_h_dm_com AS d ON d.HIP = h.HIP
                LEFT JOIN
                    (
                        (
                            SELECT 
                                TYC1, TYC2, TYC3, HIP, CCDM
                            FROM
                                tyc2_tyc2
                        ) 
                        UNION ALL 
                        (
                            SELECT 
                                TYC1, TYC2, TYC3, HIP, CCDM
                            FROM
                                tyc2_suppl_1
                        )
                    ) AS t 
                    ON t.HIP = h.HIP
                    AND (
                        IFNULL(d.comp_id, '') = TRIM(IFNULL(t.CCDM, '')) -- Single or no component in Tycho record 
                        OR
                        TRIM(d.comp_id) IN (SUBSTR(t.CCDM, 1, 1) , SUBSTR(t.CCDM, 2, 1), SUBSTR(t.CCDM, 3, 1)) -- Multiple components in single Tycho record
                    )
                WHERE h.RAdeg IS NOT NULL;
    
    """
    db.commit_query(q)
    t2 = time.time()
    print "{:.1f} s".format(t2 - t1)


def add_indexes(db):
    """
    Add indexes to the star table on the TYC1-3, HIP, HD columns.

    :param db: An open SkyMapDatabase instance
    """

    print "Adding indexes"
    t1 = time.time()
    db.add_index("skymap_stars", "HIP")
    db.add_index("skymap_stars", "TYC1")
    db.add_index("skymap_stars", "TYC2")
    db.add_index("skymap_stars", "TYC3")
    db.add_multiple_column_index("skymap_stars", ("TYC1", "TYC2", "TYC3"), "TYC")
    db.add_index("skymap_stars", "HD1")
    db.add_index("skymap_stars", "HD2")
    db.add_index("skymap_stars", "HR")
    t2 = time.time()
    print "{:.1f} s".format(t2 - t1)


def add_cross_index(db):
    """
    Add information from the HD-DM-GC-HR-HIP-Bayer-Flamsteed Cross Index (IV/27A). Bayer, Flamsteed, HR numbers.

    :param db: An open SkyMapDatabase instance
    """

    print "Adding New Cross Index data"
    t1 = time.time()
    q = """
                UPDATE skymap_stars, cross_index_catalog
                SET
                  skymap_stars.bayer = cross_index_catalog.Bayer,
                  skymap_stars.flamsteed = cross_index_catalog.Fl,
                  skymap_stars.hr = cross_index_catalog.HR
                WHERE cross_index_catalog.HD=skymap_stars.hd1 OR cross_index_catalog.HD=skymap_stars.hd2
            """
    db.commit_query(q)
    t2 = time.time()
    print "{:.1f} s".format(t2 - t1)


def add_bright_star_catalog(db):
    """
    Adds HR numbers from the Bright Star Catalog

    :param db: An open SkyMapDatabase instance
    """

    print "Adding Bright Star Catalog data"
    t1 = time.time()
    q = """
                UPDATE skymap_stars, bsc_catalog
                SET
                  skymap_stars.hr = bsc_catalog.hr
                WHERE bsc_catalog.hd=skymap_stars.hd1 OR bsc_catalog.hd=skymap_stars.hd2
    """
    db.commit_query(q)
    t2 = time.time()
    print "{:.1f} s".format(t2 - t1)


def add_proper_names(db):
    """
    Adds the IAU proper names to the star database.

    :param db: An open SkyMapDatabase instance
    """

    print "Adding proper names"
    t1 = time.time()

    # Retrieve the proper name list
    url = "https://www.iau.org/public/themes/naming_stars/"
    r = urllib.urlopen(url).read()
    soup = BeautifulSoup(r, "html5lib")

    # Loop over all stars in the list
    for tr in soup.find_all("tbody")[0].find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue

        try:
            hip = int(tds[7].get_text().strip())
        except ValueError:
            hip = None
        try:
            hd = int(tds[8].get_text().strip())
        except ValueError:
            hd = None

        if hip is None and hd is None:
            continue

        proper_name = tds[2].get_text().strip()
        date = tds[9].get_text().strip()

        # Omit the stars that were added because of exoplanets
        if date == '2015-12-15':
            continue

        # Find and update the database record
        row = db.query_one("""SELECT id FROM skymap_stars WHERE hip={} ORDER BY hp_magnitude ASC LIMIT 1""".format(hip))
        if row is None:
            row = db.query_one("""SELECT id FROM skymap_stars WHERE hd1={0} OR hd2={0} ORDER BY hp_magnitude ASC LIMIT 1""".format(hd))
        q = """UPDATE skymap_stars SET proper_name="{}" WHERE id={}""".format(proper_name, row['id'])
        db.commit_query(q)

    # Add some special cases
    special_cases = {
        24186: "Kapteyn's Star",
        49908: "Groombridge 1618",
        57939: "Groombridge 1830",
        105090: "Lacaille 8760",
        114046: "Lacaille 9352",
        54035: "Lalande 21185",
        114622: "Bradley 3077"
    }

    for hip, proper_name in special_cases.items():
        rid = db.query_one("""SELECT id FROM skymap_stars WHERE hip={} ORDER BY hp_magnitude ASC LIMIT 1""".format(hip))['id']
        q = """UPDATE skymap_stars SET proper_name="{}" WHERE id={}""".format(proper_name, rid)
        db.commit_query(q)

    t2 = time.time()
    print "{:.1f} s".format(t2 - t1)


def add_constellations(db):
    """
    Update the star database to include the correct constellation designation for each star.

    :param db: An open SkyMapDatabase instance
    """

    print "Adding constellations"
    t1 = time.time()
    rows = db.query("""SELECT id, right_ascension, declination, source FROM skymap_stars""")
    nrecords = len(rows)

    # Prepare ConstellationFinders for Tycho and Hipparcos
    cftyc = ConstellationFinder(TYCHO2_EPOCH)
    cfhip = ConstellationFinder(HIPPARCOS_EPOCH)

    # Loop over all stars
    for i, r in enumerate(rows):
        # Display progress
        if i % 1000 == 0:
            sys.stdout.write("\r{0:.1f}%".format(i * 100.0 / (nrecords - 1)))
            sys.stdout.flush()

        if r['source'] == 'T2':
            cf = cftyc
        else:
            cf = cfhip
        c = cf.find(r['right_ascension'], r['declination'])
        db.commit_query("UPDATE skymap_stars SET constellation='{}' WHERE id={}".format(c, r['id']))

    t2 = time.time()
    print
    print "{:.1f} s".format(t2 - t1)


def select_stars(magnitude, constellation=None, ra_range=None, dec_range=None):
    """
    Select a set of stars brighter than the given magnitude, based on coordinate range and/or constellation membership.

    :param magnitude: The maximum magnitude to include
    :param constellation: The constellation name; if given, only stars from that constellation are returned
    :param ra_range: The range (min_ra, max_ra) of right ascension to include, in degrees
    :param dec_range: The range (min_dec, max_dec) of declination to include, in degrees
    :return: A list of Star objects
    """

    # Build the query
    q = """SELECT * FROM skymap_stars WHERE magnitude<={0}""".format(magnitude)

    if constellation:
        q += """ AND constellation='{0}'""".format(constellation)

    if ra_range:
        min_ra, max_ra = ra_range
        min_ra = ensure_angle_range(min_ra)
        max_ra = ensure_angle_range(max_ra)

        if min_ra < max_ra:
            q += """ AND right_ascension>={0} AND right_ascension<={1}""".format(min_ra, max_ra)
        elif max_ra < min_ra:
            q += """ AND (right_ascension>={0} OR right_ascension<={1})""".format(min_ra, max_ra)
        else:
            # min_ra is equal to max_ra: full circle: no ra limits
            pass

    if dec_range:
        min_dec, max_dec = dec_range

        if min_dec < -90 or min_dec > 90 or max_dec < -90 or max_dec > 90 or max_dec <= min_dec:
            raise ValueError("Illegal DEC range!")
        q += """ AND declination>={0} AND declination<={1}""".format(min_dec, max_dec)

    # Order stars from brightest to weakest so displaying them is easier
    q += """ ORDER BY magnitude ASC"""

    # Execute the query
    db = SkyMapDatabase()
    rows = db.query(q)
    result = [Star(row) for row in rows]
    db.close()

    return result



"""
Multiples:

For each star, find stars within a certain angular separation. 
Create table with IDs and for each star of the bunch add a reference to the brightest star of the bunch, and add the
angular separation to the brightest.

  

"""

def sum_magnitudes(m1, m2):
    """
    Computes the combined magnitude of two separate stars. Used when combining multiples into one displayed star.

    :param m1: Magnitude of first star
    :param m2: Magnitude of second star
    :return: The combined magnitude
    """

    return -2.5*math.log10(pow(10, -m1/2.5) + pow(10, -m2/2.5))


def get_stars_around_coordinate(ra, dec, angular_separation, db):
    """
    Retrieves all stars from the database that are found within a specified angular separation from the given coordinate.

    :param ra: The right ascension around which to search, in degrees
    :param dec: The declination around which to search, in degrees
    :param angular_separation: The maximum distance from the coordinate to include, in seconds of arc
    :param db: An opened SkyMapDatabase instance
    :return: A query result containing all found stars
    """

    # Transform the angular separation from seconds of arc to (local) degrees. Multiply by 1.2 for extra margin
    delta_ra = 1.2 * angular_separation / (3600.0 * math.cos(dec))
    delta_de = 1.2 * angular_separation / 3600.0

    # Build the query
    q = """SELECT * FROM skymap_stars WHERE """

    if ra - delta_ra < 0:
        q += """(right_ascension < {} OR right_ascension > {}) AND """.format(ra + delta_ra, ra - delta_ra + 360)
    elif ra + delta_ra > 360:
        q += """(right_ascension < {} OR right_ascension > {}) AND """.format(ra + delta_ra - 360, ra - delta_ra)
    else:
        q += """right_ascension > {} AND right_ascension < {} AND """.format(ra - delta_ra, ra + delta_ra)

    if dec - delta_de < -90:
        q += """declination < {}""".format(dec + delta_de)
    elif dec + delta_de > 90:
        q += """declination > {}""".format(dec - delta_de)
    else:
        q += """declination > {} AND declination < {}""".format(dec - delta_de, dec + delta_de)

    return db.query(q)


def find_multiples(stars, criterion):
    """
    Find all multiple stars for the given distance criterion.

    :param stars: A list of star database records
    :param criterion: The angular separation below which stars are considered part of a multiple system
    :return: ?
    """

    db = SkyMapDatabase()
    for s in stars:
        candidates = get_stars_around_coordinate(s['right_ascension'], s['declination'], criterion, db)
        for i, ci in enumerate(candidates):
            for cj in candidates[i+1:]:

                ra1 = ci['right_ascension']
                de1 = ci['declination']
                ra2 = cj['right_ascension']
                de2 = cj['declination']
                d = angular_separation_seconds_of_arc(ra1, de1, ra2, de2)
                if d < criterion:
                    #print "{}: {} - {} -> {}".format(current_process().name, ci['id'], cj['id'], d)
                    pass


def chunks(l, n):
    """
    Yield n successive chunks from l.

    :param l: The list to divide in chunks
    :param n: The number of chunks to divide the list into
    :return: A generator
    """

    newn = int(1.0 * len(l) / n + 0.5)
    for i in xrange(0, n-1):
        yield l[i*newn:i*newn+newn]
    yield l[n*newn-newn:]



if __name__ == "__main__":
    #build_star_database()

    nprocs = 100 # Optimum seems to be around 40: must have something to do with the database I suppose
    n = nprocs * 500
    criterion = 100
    db = SkyMapDatabase()
    stars = db.query("""SELECT id, right_ascension, declination FROM skymap_stars LIMIT {}""".format(n))
    print len(stars)

    procs = []

    t1 = time.time()
    for i, l in enumerate(chunks(stars, nprocs)):
        print len(l)
        p = Process(target=find_multiples, args=(l, criterion), name="Chunk #{}".format(i+1))
        procs.append(p)
        p.start()

    for p in procs:
        p.join()

    print "Time: {} s".format(time.time()-t1)

