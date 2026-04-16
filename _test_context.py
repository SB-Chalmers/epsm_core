"""Test spatial query for context buildings."""
import duckdb

con = duckdb.connect("epc_sweden.duckdb", read_only=True)
con.execute("LOAD spatial;")

# Get ÄGIR 17 centroid
r = con.execute("""
    SELECT ST_AsText(ST_Centroid(ST_GeomFromWKB(geom))) as centroid
    FROM footprints
    WHERE UPPER(fastighetsbeteckning) = 'ÄGIR 17' AND husnummer = 1
""").fetchone()
print("ÄGIR 17 centroid (WGS84):", r[0])

# Count buildings within various radii (in degrees, ~0.0045 deg lat = 500m)
for deg in [0.003, 0.005, 0.01]:
    r2 = con.execute("""
        WITH target AS (
            SELECT ST_Centroid(ST_GeomFromWKB(geom)) as pt
            FROM footprints
            WHERE UPPER(fastighetsbeteckning) = 'ÄGIR 17' AND husnummer = 1
            LIMIT 1
        )
        SELECT COUNT(*) as cnt
        FROM footprints f, target t
        WHERE ST_Distance(ST_Centroid(ST_GeomFromWKB(f.geom)), t.pt) < ?
    """, [deg]).fetchone()
    meters_approx = deg * 111000
    print(f"  Buildings within ~{meters_approx:.0f}m ({deg} deg): {r2[0]}")

# Get actual context buildings with their heights
print("\nContext buildings near ÄGIR 17 (within ~500m):")
rows = con.execute("""
    WITH target AS (
        SELECT ST_Centroid(ST_GeomFromWKB(geom)) as pt,
               objektidentitet as target_id
        FROM footprints
        WHERE UPPER(fastighetsbeteckning) = 'ÄGIR 17' AND husnummer = 1
        LIMIT 1
    ),
    nearby AS (
        SELECT f.objektidentitet, f.fastighetsbeteckning, f.husnummer,
               f.andamal1, f.FormularId,
               ST_Distance(ST_Centroid(ST_GeomFromWKB(f.geom)), t.pt) as dist_deg
        FROM footprints f, target t
        WHERE ST_Distance(ST_Centroid(ST_GeomFromWKB(f.geom)), t.pt) < 0.005
          AND f.objektidentitet != t.target_id
    )
    SELECT n.objektidentitet, n.fastighetsbeteckning, n.husnummer,
           n.andamal1, n.FormularId, e.EgenAntalPlan, n.dist_deg
    FROM nearby n
    LEFT JOIN epc e ON n.FormularId = e.FormularId
    ORDER BY n.dist_deg
    LIMIT 50
""").fetchall()

for row in rows:
    objid, fastbet, husnr, andamal, fid, floors, dist = row
    height = f"{int(floors) * 3.0:.0f}m ({floors} fl)" if floors else "15m (default)"
    dist_m = dist * 111000  # rough conversion
    print(f"  {dist_m:6.0f}m | {fastbet or '?':20s} | hn={husnr} | {andamal or '?':30s} | {height}")

con.close()
