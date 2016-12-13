import math

from skymap.milkyway import get_milky_way_boundary_for_area
from skymap.constellations import get_constellation_boundaries_for_area
from skymap.hyg import select_stars
from skymap.map import *


A4_SIZE = (297.0, 210.0)


class SkyMapMaker(object):
    def __init__(self, filename=None, paper_size=A4_SIZE, margin_lr=(20, 20), margin_bt=(20, 20)):
        self.filename = filename
        self.paper_size = paper_size
        self.margin_lr = margin_lr
        self.margin_bt = margin_bt
        self.map = None
        self.figure = None

    def set_filename(self, filename):
        self.filename = filename
        basename = os.path.splitext(os.path.split(self.filename)[-1])[0]
        self.figure = MetaPostFigure(basename)

    # Map types
    def set_polar(self, filename, north=True, vertical_range=50):
        self.set_filename(filename)
        self.map = AzimuthalEquidistantMap(self.paper_size, self.margin_lr, self.margin_bt, north=north, reference_scale=vertical_range/2.0, celestial=True)

    def set_intermediate(self, filename, center, standard_parallel1=30, standard_parallel2=60, vertical_range=50):
        self.set_filename(filename)
        self.map = EquidistantConicMap(self.paper_size, self.margin_lr, self.margin_bt, center, standard_parallel1=standard_parallel1, standard_parallel2=standard_parallel2, reference_scale=vertical_range/2.0, celestial=True)

    def set_equatorial(self, filename, center_longitude, standard_parallel=25, vertical_range=50):
        self.set_filename(filename)
        self.map = EquidistantCylindricalMap(self.paper_size, self.margin_lr, self.margin_bt, center_longitude=center_longitude, standard_parallel=standard_parallel, reference_scale=vertical_range/2.0, celestial=True)

    # Drawing functions
    def draw_parallels(self, increment=10):
        print
        print "Drawing parallels"
        self.figure.comment("Parallels", True)

        min_latitude = int(increment * math.floor(self.map.min_latitude / float(increment)))
        for latitude in range(min_latitude, int(self.map.max_latitude) + 1, int(increment)):
            parallel = self.map.map_parallel(latitude)
            if isinstance(parallel, Circle):
                self.figure.draw_circle(parallel, linewidth=0.2)
            else:
                self.figure.draw_line(parallel, linewidth=0.2)
            marker = "{0}$^{{\\circ}}$".format(latitude)
            self.draw_ticks(parallel, marker, self.map.draw_parallel_ticks_on_horizontal_axis, self.map.draw_parallel_ticks_on_vertical_axis)

    def draw_meridians(self, increment=15):
        print
        print "Drawing meridians"
        self.figure.comment("Meridians", True)

        min_longitude = int(increment * math.floor(self.map.min_longitude / float(increment)))
        max_longitude = int(self.map.max_longitude)
        if max_longitude - 360 < min_longitude:
            max_longitude += 1

        for longitude in range(min_longitude, max_longitude, int(increment)):
            meridian = self.map.map_meridian(longitude)
            if isinstance(meridian, Circle):
                self.figure.draw_circle(meridian, linewidth=0.2)
            else:
                self.figure.draw_line(meridian, linewidth=0.2)
            if self.map.projection.celestial:
                ha = HourAngle()
                ha.from_degrees(longitude)
                if not longitude % 15:
                    marker = "\\textbf{{{0}\\textsuperscript{{h}}}}".format(ha.hours)

                else:
                    marker = "{0}\\textsuperscript{{m}}".format(ha.minutes)
            else:
                marker = "{0}$^{{\\circ}}$".format(longitude)
            self.draw_ticks(meridian, marker, self.map.draw_meridian_ticks_on_horizontal_axis, self.map.draw_meridian_ticks_on_vertical_axis)

    def draw_ticks(self, draw_object, text, horizontal_axis, vertical_axis):
        if horizontal_axis:
            for border, pos in [(self.map.bottom_border, "bot"), (self.map.top_border, "top")]:
                points = draw_object.inclusive_intersect_line(border)
                for p in points:
                    self.figure.draw_text(p, text, pos, size="small", delay_write=True)
        if vertical_axis:
            for border, pos in [(self.map.right_border, "rt"), (self.map.left_border, "lft")]:
                points = draw_object.inclusive_intersect_line(border)
                for p in points:
                    self.figure.draw_text(p, text, pos, size="small", delay_write=True)

    def draw_constellation_boundaries(self, constellation=None):
        print
        print "Drawing constellation borders"
        self.figure.comment("Constellation boundaries", True)

        drawn_edges = []
        edges = get_constellation_boundaries_for_area(self.map.min_longitude, self.map.max_longitude, self.map.min_latitude, self.map.max_latitude, constellation=constellation)
        for e in edges:
            if e.identifier in drawn_edges:
                continue
            points = [self.map.map_point(p) for p in e.interpolated_points]
            polygon = Polygon(points, closed=False)
            self.figure.draw_polygon(polygon, linewidth=0.2, dashed=True)
            drawn_edges.append(e.identifier)
            drawn_edges.append(e.complement)

    def draw_stars(self):
        print
        print "Drawing stars"
        self.figure.comment("Stars")

        stars = select_stars(magnitude=FAINTEST_MAGNITUDE, constellation=None, ra_range=(self.map.min_longitude, self.map.max_longitude), dec_range=(self.map.min_latitude, self.map.max_latitude))
        for star in stars:
            self.draw_star(star)

    def draw_star(self, star):
        p = self.map.map_point(star.position)
        if not self.map.inside_viewport(p):
            return

        # Print the star itself
        if star.is_variable:
            min_size = self.magnitude_to_size(star.var_min)
            max_size = self.magnitude_to_size(star.var_max)
            self.figure.draw_point(p, max_size + 0.15, color="white")
            c = Circle(p, 0.5 * max_size)
            self.figure.draw_circle(c, linewidth=0.15)
            if star.var_min < FAINTEST_MAGNITUDE:
                self.figure.draw_point(p, min_size)
            size = max_size
        else:
            size = self.magnitude_to_size(star.mag)
            self.figure.draw_point(p, size + 0.15, color="white")
            self.figure.draw_point(p, size)

        # Print the multiple bar
        if star.is_multiple:
            p1 = Point(p[0] - 0.5 * size - 0.2, p[1])
            p2 = Point(p[0] + 0.5 * size + 0.2, p[1])
            l = Line(p1, p2)
            self.figure.draw_line(l, linewidth=0.25)
            print "MULTIPLE:", star, star.mag, star.position

        # Print text
        if star.identifier_string.strip():
            text_pos = Point(p.x + 0.5 * size - 0.9, p.y)
            self.figure.draw_text(text_pos, star.identifier_string, "rt", "tiny", scale=0.75, delay_write=True)
        if star.proper:
            text_pos = Point(p.x, p.y - 0.5 * size + 0.8)
            self.figure.draw_text(text_pos, star.proper, "bot", "tiny", scale=0.75, delay_write=True)

    def magnitude_to_size(self, magnitude):
        if magnitude < -0.5:
            magnitude = -0.5
        scale = 6.1815*self.map.paper_width/465.0
        return scale * math.exp(-0.27 * magnitude)

    def draw_milky_way(self):
        edges = get_milky_way_boundary_for_area(self.map.min_longitude, self.map.max_longitude, self.map.min_latitude, self.map.max_latitude)
        for e in edges:
            e = self.map.map_line(e)
            self.figure.draw_line(e, linewidth=0.5)

    def render(self, open=False):
        self.draw_parallels()
        self.draw_meridians()
        self.draw_constellation_boundaries()
        self.draw_milky_way()
        self.draw_stars()

        #Clip the map area
        llborder = Point(self.margin_lr[0], self.margin_bt[0])
        urborder = Point(self.paper_size[0] - self.margin_lr[1], self.paper_size[1] - self.margin_bt[1])
        self.figure.clip(llborder, urborder)

        # Draw border
        self.figure.draw_rectange(llborder, urborder)

        # Create bounding box for page
        llcorner = Point(0, 0)
        urcorner = Point(self.paper_size[0], self.paper_size[1])
        self.figure.draw_rectange(llcorner, urcorner, linewidth=0)

        # Finish
        self.figure.end_figure()
        self.figure.render(self.filename, open=open)