# Author: Anora Wu
# Date: Jan 7th 2026
# Construct a panel data, with each hour between 2020-2025 being the time variable and each grid being the identity. 
# Each identity has a geometry and a id. 
# Fill in the cloud seeding operation hour and location into the time slots and the grid 

import geopandas as gpd
import pandas as pd
import numpy as np
import os
import warnings
import matplotlib.pyplot as plt
from shapely.geometry import box
from pyproj import Transformer

data_dir = os.environ['DATA_DIR']
check = os.environ['CHECK']

### CONSTRUCT GRID ###

# Load and project JX polygon to EPSG:32650 
jx_poly = gpd.read_file(f"{data_dir}/jiangxi_shapefile/jiangxi_shape.shp").geometry.iloc[0]
# Original jx_poly was in "EPSG:4326", convert it to "EPSG:32650" to construct grids in kilometers
# "EPSG:32650" is used between between 114°E and 120°E
jx_poly_proj = gpd.GeoSeries([jx_poly], crs="EPSG:4326").to_crs("EPSG:32650").iloc[0]

# Calculate the bound of JX province            
minx, miny, maxx, maxy = jx_poly_proj.bounds              

# Bins for 5km (5000m) grid
grid_size = 5000
# Create boundaries for grids
# The last bin created by np.arange will cover the maxx and maxy
x_bins = np.arange(minx, maxx + grid_size, grid_size)
y_bins = np.arange(miny, maxy + grid_size, grid_size)

# Create box geometries that covered all jx_poly_proj based on generated bins 
polygons = []
for i in range(len(y_bins)-1):
    for j in range(len(x_bins)-1):
        # create 5km * 5km grids
        poly = box(x_bins[j], y_bins[i], x_bins[j+1], y_bins[i+1])
        polygons.append({
            "cell_id": f"{i}_{j}", # use i_j here because y_bins are row numbers while x_bins are column numbers
            "geometry": poly,
            "cell_y": i,
            "cell_x": j
        })
jx_grid = gpd.GeoDataFrame(polygons, crs="EPSG:32650")

# Filtering out grids outside JX, only keeping grids whose area of intersection with JX is larger than 0
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    jx_grid = jx_grid[jx_grid.geometry.intersection(jx_poly_proj).area > 0]

# Plot the shape of Jiangxi and grids to check
if check == "True":
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_title('Jiangxi Shapefile and Grids', fontsize=15, fontweight='bold')

    jx_grid.plot(ax=ax, color='black', edgecolor=None)
    jx_poly_proj_geoseries = gpd.GeoSeries([jx_poly_proj], crs="EPSG:32650")
    jx_poly_proj_geoseries.plot(ax=ax, color='blue', marker='o', markersize=5)

    plt.tight_layout()
    plt.savefig(f"{data_dir}/check/jiangxi_and_grids.png", dpi=150)
    plt.close()

# Save as GeoPackage 
# EPSG:32650
jx_grid.to_file(f"{data_dir}/intermediate/jx_grid.gpkg", layer='grid', driver="GPKG")

# Save as CSV for later use
df = pd.DataFrame(jx_grid.drop(columns='geometry'))
df.to_csv(f"{data_dir}/intermediate/jx_grid.csv", index=False)


### FILL IN OPERATION DATA ###

operation_data = pd.read_csv(f"{data_dir}/intermediate/cleaned_operation.csv")

# Correct a known longitude/latitude swap before assigning grid cells.
# Note: the township spatial join was already completed in clean_town_operation.py. 
# Therefore, this correction updates only the coordinates used for grid assignment. 
# The previously joined city, county, and town values in cleaned_operation.csv remain unmatched.
condition = (operation_data['date'] == "2022-10-27") & (operation_data['start_time'] == "09:42") & (operation_data['city_o'] == "九江市")
operation_data.loc[condition, 'lon'] = 115.56
operation_data.loc[condition, 'lat'] = 29.043

# Identify distant mismatches using the manually reviewed case files.
review_files = [
    f"{data_dir}/check/cross_city_location_review.csv",
    f"{data_dir}/check/cross_county_same_city_review.csv",
]

mismatch_reviews = pd.concat(
    [pd.read_csv(path) for path in review_files],
    ignore_index=True,
)

# "Distant mismatches" includes both distant location conflicts and
# suspected coordinate issues (cases that contains a detailed site name supporting the reported location).
distant_cases = mismatch_reviews.loc[
    mismatch_reviews["review_status"].isin(
        ["distant_location_conflict", "suspected_coordinate_issue"]
    )
].copy()

# Some reviewed cases combine multiple reported-county labels with "|".
distant_cases["reported_county"] = (
    distant_cases["reported_county"]
    .astype("string")
    .str.split(r"\s*\|\s*")
)
distant_cases = distant_cases.explode("reported_county")

# Construct stable matching keys.
operation_data["_lon_key"] = operation_data["lon"].round(6)
operation_data["_lat_key"] = operation_data["lat"].round(6)
operation_data["_city_key"] = operation_data["city_o"].astype("string").str.strip()
operation_data["_county_key"] = operation_data["county_o"].astype("string").str.strip()

distant_cases["_lon_key"] = distant_cases["lon"].round(6)
distant_cases["_lat_key"] = distant_cases["lat"].round(6)
distant_cases["_city_key"] = (
    distant_cases["reported_city"].astype("string").str.strip()
)
distant_cases["_county_key"] = (
    distant_cases["reported_county"].astype("string").str.strip()
)

match_columns = [
    "_lon_key",
    "_lat_key",
    "_city_key",
    "_county_key",
]

distant_case_lookup = (
    distant_cases[match_columns]
    .drop_duplicates()
    .assign(is_distant_mismatch=True)
)

operation_data = operation_data.merge(
    distant_case_lookup,
    on=match_columns,
    how="left",
    validate="many_to_one",
)

operation_data["is_distant_mismatch"] = (
    operation_data["is_distant_mismatch"].eq(True)
)

# Confirm that the reviewed classification still matches 187 source records.
distant_count = int(operation_data["is_distant_mismatch"].sum())
if distant_count != 187:
    raise ValueError(
        f"Expected 187 distant mismatch records, but matched {distant_count}. "
        "The source data or review files may have changed."
    )

# Transfer lat and lon to EPSG:32650
# "always_xy=True" ensures using the traditional GIS order, 
# that is longitude, latitude for EPSG:4326 and easting, northing for EPSG:32650
transformer = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True)
operation_data['xs'], operation_data['ys'] = transformer.transform(
    operation_data['lon'].values, 
    operation_data['lat'].values
)

# Get cell_x and cell_y, which starts from 0 (rather than 1)
operation_data['cell_x'] = (np.array(operation_data['xs'])-minx)//grid_size 
operation_data['cell_y'] = (np.array(operation_data['ys'])-miny)//grid_size 

# Generate cell_id of the cell each operation data is in
operation_data['cell_id'] = (
    operation_data['cell_y'].astype(int).astype(str) + "_" + 
    operation_data['cell_x'].astype(int).astype(str)
)

# Keep operations assigned to grid cells that overlap Jiangxi.
# Note: a point in a boundary cell may itself be outside Jiangxi, 
# so this does not guarantee that every operation lies within the Jiangxi boundary.
valid_cells = set(jx_grid['cell_id'])
operation_data = operation_data[operation_data['cell_id'].isin(valid_cells)]

# Drop distant mismatches from the main sample.
distant_in_valid_cells = int(operation_data["is_distant_mismatch"].sum())
operation_data = operation_data.loc[
    ~operation_data["is_distant_mismatch"]
].copy()

# Remove temporary matching fields but retain the audit flag.
operation_data.drop(
    columns=["_lon_key", "_lat_key", "_city_key", "_county_key"],
    inplace=True,
)

print(
    f"Dropped {distant_in_valid_cells} distant mismatch records; "
    f"{len(operation_data)} operation records remain."
)

# Save the final operation sample after the coordinate correction,
# valid-grid restriction, and distant-mismatch exclusion.
operation_data.to_csv(
    f"{data_dir}/intermediate/final_operation_sample.csv",
    index=False,
)

# If True, check the cell id as well as spatial distribution of operations
if check == "True":

    # Check the cell id by using sjoin to find id 
    operation_data_geodata = gpd.GeoDataFrame(
    operation_data, 
    geometry=gpd.points_from_xy(operation_data['xs'], operation_data['ys']),
    crs="EPSG:32650" 
    )
    joined_operation = gpd.sjoin(operation_data_geodata, jx_grid, how="left", predicate="within")
    if len(joined_operation[joined_operation['cell_id_right']!=joined_operation['cell_id_left']]) != 0:
        print("Error: the cell ids for operation data is not correct")

    # Plot spacial distribution of operations
    point_counts = joined_operation.groupby("cell_id_right").size().reset_index(name="operation_count")
    joined_grid = jx_grid.merge(point_counts, left_on="cell_id", right_on="cell_id_right", how="left")
    joined_grid["operation_count"] = joined_grid["operation_count"].fillna(0).astype(int)

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_title('Number of operations in each grid', fontsize=15, fontweight='bold')
    joined_grid.plot(column="operation_count", legend=True, cmap="OrRd", ax=ax)

    plt.tight_layout()
    plt.savefig(f"{data_dir}/check/spacial_distribution_operations.png", dpi=150)
    plt.close()


# Create exact start and end timestamps
operation_data["start_dt"] = pd.to_datetime(
    operation_data["date"].astype(str)
    + " "
    + operation_data["start_time"].astype(str),
    format="mixed",
)

operation_data["end_dt"] = pd.to_datetime(
    operation_data["date"].astype(str)
    + " "
    + operation_data["end_time"].astype(str),
    format="mixed",
)

# Need to tackle cases such that operation starts at night and ends in the next day
# Assume the operation crossed midnight when its end time is before its start time
crosses_midnight = operation_data["end_dt"] < operation_data["start_dt"]
operation_data.loc[crosses_midnight, "end_dt"] += pd.Timedelta(days=1)

# Create hourly timestamps for the hourly grid panel
operation_data["start_hour"] = operation_data["start_dt"].dt.floor("h")
operation_data["end_hour"] = operation_data["end_dt"].dt.floor("h")

# Count operation starts by hour and grid cell
op_counts_start = (
    operation_data.groupby(["start_hour", "cell_id"])
    .size()
    .reset_index(name="op_count_start")
    .rename(columns={"start_hour": "time"})
)

# Count operation ends by hour and grid cell
op_counts_end = (
    operation_data.groupby(["end_hour", "cell_id"])
    .size()
    .reset_index(name="op_count_end")
    .rename(columns={"end_hour": "time"})
)
# Rename start_hour and end_hour to time after aggregation so both count datasets
# remain compatible with the existing yearly panel merges on time and cell_id.

# Save exact operation timestamps before hourly aggregation.
# The yearly grid panels constructed below use start_hour and end_hour, while this file preserves minute-level information.
operation_data.to_csv(
    f"{data_dir}/intermediate/operation_with_exact_times.csv",
    index=False,
)

# Construct panel by year - a dataset of 6 years in total would be too large to be efficient
for which_year in range(2020,2026):

    # create empty panel
    # hourly frequency as discussed with Cael
    date_range = pd.date_range(start=f'{which_year}-01-01', end=f'{which_year+1}-01-01', freq='h', inclusive='left')
    dates_df = pd.DataFrame({'time': date_range})
    dates_df['year'] = dates_df['time'].dt.year
    dates_df['day_of_year'] = dates_df['time'].dt.day_of_year
    dates_df['hour'] = dates_df['time'].dt.hour

    grid_ids = jx_grid[['cell_id']].copy()
    dates_df['key'] = 1
    grid_ids['key'] = 1
    panel_df = pd.merge(dates_df, grid_ids, on='key').drop('key', axis=1)

    # Merge into the grid
    final_panel = pd.merge(panel_df, op_counts_end, on=['time', 'cell_id'], how='left')
    final_panel = pd.merge(final_panel, op_counts_start, on=['time', 'cell_id'], how='left')
    final_panel['op_count_end'] = final_panel['op_count_end'].fillna(0).astype(int)
    final_panel['op_count_start'] = final_panel['op_count_start'].fillna(0).astype(int)
    jx_grid_c = jx_grid.drop(columns='geometry')
    final_grid = pd.merge(final_panel, jx_grid_c, on=['cell_id'], how='left')

    final_grid.to_csv(f"{data_dir}/intermediate/grid_with_operation_{which_year}.csv", index=False)

