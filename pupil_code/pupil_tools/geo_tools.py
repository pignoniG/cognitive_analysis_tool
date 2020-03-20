
from math import radians, log, tan, cos, pi, atan, sinh, degrees, sqrt, sin
import urllib
import urllib.request
import io
from PIL import Image


# GEODETIC TO CARTERSIAN FUNCTION
def geo2cart(lon, lat, h):
    a = 6378137        # WGS84 Major axis
    b = 6356752.3142   # WGS84 Minor axis
    e2 = 1-(b**2/a**2)
    N = float(a/sqrt(1-e2*(sin(radians(abs(lat)))**2)))
    X = (N+h)*cos(radians(lat))*cos(radians(lon))
    Y = (N+h)*cos(radians(lat))*sin(radians(lon))
    return X, Y

# DISTANCE FUNCTION
def distance(x1, y1, x2, y2):
    d = sqrt((x1-x2)**2+(y1-y2)**2)
    return d

# SPEED FUNCTION
def speed(x0, y0, x1, y1, t0, t1):
    d = sqrt((x0-x1)**2+(y0-y1)**2)
    delta_t = t1-t0
    if delta_t == 0:
        delta_t = 0.001
    s = float(d/delta_t)
    return s

def deg2num(lat_deg, lon_deg, zoom):
    print(lat_deg, lon_deg)

    lat_rad = radians(lat_deg)
    n = 2.00 ** zoom

    xtile = int((lon_deg + 180.0) / 360 * n)
    ytile = int((1 - log(tan(lat_rad) + (1 / cos(lat_rad))) / pi) / 2.0 * n)
    return (xtile, ytile)

def num2deg(xtile, ytile, zoom):
    n = 2 ** zoom
    lon_deg = xtile / n * 360 - 180
    lat_rad = atan(sinh(pi * (1 - 2 * ytile / n)))
    lat_deg = degrees(lat_rad)
    return (lat_deg, lon_deg)

def getImageCluster(lat_deg, lon_deg, delta_lat, delta_long):
    print(lat_deg, lon_deg, delta_lat, delta_long)

    zoom = 13
    smurl = r"http://a.tile.openstreetmap.org/{0}/{1}/{2}.png"
    xmin, ymax = deg2num(lat_deg, lon_deg, zoom)
    xmax, ymin = deg2num(lat_deg + delta_lat, lon_deg + delta_long, zoom)

    lat_max, lon_max = num2deg(xmin, ymax+1, zoom)
    lat_min, lon_min = num2deg(xmax+1, ymin, zoom)



    Cluster = Image.new('RGB', ((xmax-xmin+1)*256-1, (ymax-ymin+1)*256-1))

    for xtile in range(xmin, xmax+1):
        for ytile in range(ymin, ymax+1):
            try:
                imgurl = smurl.format(zoom, xtile, ytile)
                #print(f"Opening: {imgurl}")

                req = urllib.request.Request(imgurl, headers={'User-Agent' : 'Mozilla/5.0 (Windows NT 6.1; Win64; x64)'})
                imgstr = urllib.request.urlopen(req).read()
                tile = Image.open(io.BytesIO(imgstr))

                Cluster.paste(tile, box=((xtile-xmin)*256, (ytile-ymin)*255))

            except Exception as error:
                print(error)
                print("Couldn't download image")
                tile = None

    print(lat_max, lon_min, lat_min, lon_max)
    print("lat_max", "lon_min", "lat_min", "lon_max")

    return Cluster, lat_max, lon_min, lat_min, lon_max