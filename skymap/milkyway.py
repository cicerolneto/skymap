import os
import urllib
import zipfile
import re

from skymap.database import SkyMapDatabase
from skymap.geometry import HourAngle, DMSAngle, SphericalPoint, ensure_angle_range, Line

DATA_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "data", "milkyway")
DATA_FILE = os.path.join(DATA_FOLDER, "milkyway.zip")
URL = "http://www.skymap.com/files/overlays/milky.zip"


def parse_file(file_path, db, edge_id):
    with open(file_path, "r") as fp:
        lines = fp.readlines()

    for l in lines:
        l = l.strip()
        if not l or l.startswith(";"):
            continue
        if l.startswith("MOVE"):
            p1 = extract_point(l)
        if l.startswith("DRAW"):
            p2 = extract_point(l)
            q = """INSERT INTO milkyway VALUES ({0}, "{1}", "{2}", {3}, {4})""".format(edge_id, p1.longitude, p1.latitude, p2.longitude, p2.latitude)
            db.commit_query(q)

            # Move to next point
            p1 = p2
            edge_id += 1
    return edge_id


def extract_point(line):
    point_pattern = "^[A-Z]+\s(\d\d \d\d \d\d), (\-?\d\d \d\d)$"
    m = re.search(point_pattern, line)
    try:
        long = m.groups()[0]
        lat = m.groups()[1]

        h, m, s = (int(x) for x in long.split())
        longitude = HourAngle(h, m, s).to_degrees()

        d, m = (int(x) for x in lat.split())
        latitude = DMSAngle(degrees=d, minutes=m).to_degrees()

        return SphericalPoint(longitude, latitude)
    except AttributeError:
        return None


def get_milky_way_boundary_for_area(min_longitude, max_longitude, min_latitude, max_latitude):
    # Convert longitude to 0-360 values
    min_longitude = ensure_angle_range(min_longitude)
    max_longitude = ensure_angle_range(max_longitude)
    if max_longitude == min_longitude:
        max_longitude += 360

    db = SkyMapDatabase()
    q = "SELECT * FROM milkyway WHERE"

    if min_longitude < max_longitude:
        q += " ((ra1>={0} AND ra1<={1}".format(min_longitude, max_longitude)
    else:
        q += " (((ra1>={0} OR ra1<={1})".format(min_longitude, max_longitude)

    q += " AND dec1>={0} AND dec1<={1}) OR".format(min_latitude, max_latitude)

    if min_longitude < max_longitude:
        q += " (ra2>={0} AND ra2<={1}".format(min_longitude, max_longitude)
    else:
        q += " ((ra2>={0} OR ra2<={1})".format(min_longitude, max_longitude)

    q += " AND dec2>={0} AND dec2<={1}))".format(min_latitude, max_latitude)

    print q
    result = db.query(q)

    lines = []
    for row in result:
        p1 = SphericalPoint(row['ra1'], row['dec1'])
        p2 = SphericalPoint(row['ra2'], row['dec2'])
        lines.append(Line(p1, p2))

    db.close()

    return lines


def build_milkyway_database():
    print("")
    print("Building milky way boundary database")

    # Download data file
    if not os.path.exists(DATA_FOLDER):
        os.makedirs(DATA_FOLDER)
    if not os.path.exists(DATA_FILE):
        print("Downloading {0}".format(URL))
        urllib.urlretrieve(URL, DATA_FILE)
        zip_ref = zipfile.ZipFile(DATA_FILE, 'r')
        zip_ref.extractall(DATA_FOLDER)
        zip_ref.close()

    print("Filling database")
    db = SkyMapDatabase()

    # Drop table
    db.drop_table("milkyway")

    # Create table
    db.commit_query("""CREATE TABLE milkyway (
                            id INT PRIMARY KEY ,
                            ra1 REAL,
                            dec1 REAL,
                            ra2 REAL,
                            dec2 REAL
        )""")

    # Fill table
    edge_id = 0
    edge_id = parse_file(os.path.join(DATA_FOLDER, "Milkyway.sol"), db, edge_id)
    edge_id = parse_file(os.path.join(DATA_FOLDER, "Magellanic clouds.sol"), db, edge_id)

    db.close()
