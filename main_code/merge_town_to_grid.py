# Author: Anora Wu
# Date: Jan 7th 2026
# Construct a panel data, with each day between 2020-2025 being the time variable and each grid being the identity. 
# Each identity has a geometry and a id. 
# Fill in the cloud seeding operation day and location into the time slots and the grid 

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

# Correct one mistake in the data
condition = (operation_data['date'] == "2022-10-27") & (operation_data['start_time'] == "09:42") & (operation_data['city_o'] == "九江市")
operation_data.loc[condition, 'lon'] = 115.56
operation_data.loc[condition, 'lat'] = 29.043

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

# Filtering out invalid entries (operation outside JX)
valid_cells = set(jx_grid['cell_id'])
operation_data = operation_data[operation_data['cell_id'].isin(valid_cells)]

# If True, check the cell id as well as spacial distribution of operations
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


# Construct two operation data set - one using start time and one using end time
# Use start time as operation time
operation_data_start = operation_data.copy()
operation_data_start['time'] = pd.to_datetime(
    operation_data_start['date'].astype(str) + ' ' +
    operation_data_start['start_time'].astype(str), format='mixed' 
)
operation_data_start['time'] = operation_data_start['time'].dt.floor('h')

# Use end time as operation time
# Need to tackle cases such that operation starts at night and ends in the next day
operation_data_end = operation_data.copy()

# If end_time is earlier than start_time, the operation likely crossed midnight
operation_data_end['start_dt'] = pd.to_datetime(
    operation_data_end['date'].astype(str) + ' ' +
    operation_data_end['start_time'].astype(str), format='mixed'
)
operation_data_end['end_dt'] = pd.to_datetime(
    operation_data_end['date'].astype(str) + ' ' +
    operation_data_end['end_time'].astype(str), format='mixed'
)

# Add a day when end is before start
crosses_midnight = operation_data_end['end_dt'] < operation_data_end['start_dt']
operation_data_end.loc[crosses_midnight, 'end_dt'] += pd.Timedelta(days=1)
operation_data_end['time'] = operation_data_end['end_dt'].dt.floor('h')

# Count operation times
op_counts_end = operation_data_end.groupby(['time','cell_id']).size().reset_index(name='op_count_end')
op_counts_start = operation_data_start.groupby(['time','cell_id']).size().reset_index(name='op_count_start')

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

