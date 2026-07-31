import geopandas as gpd
from shapely.geometry import MultiPolygon
import matplotlib.pyplot as plt
import pandas as pd
import os


data_dir = os.environ['DATA_DIR']
check = os.environ['CHECK']

### Clean Township Shapefile

# Load data
townshape = gpd.read_file(f"{data_dir}/township_shapefile/xiangzhen.shp")

# Data clean
townshape = townshape[townshape['省'] == "江西省"]
townshape = townshape[['省','市','县','乡','geometry']]
townshape.columns = ["prov","city","county","town","geometry"]
townshape = townshape.reset_index(drop=True)

# Check geometry
s1 = set(townshape['geometry'].apply(lambda g: g.geom_type))
print(s1)

# Two types exists: polygon and multipolygon, all convert 
# to multipolygon to avoid geometry issues
s2 = set()
townshape['geometry'] = townshape['geometry'].apply(
    lambda g: MultiPolygon([g]) if g.geom_type == 'Polygon' else g
)
s2 = set(townshape['geometry'].apply(lambda g: g.geom_type))
print(s2) # should only have multipolygon


### Clean 2020 Cloudseeding Operation Data

# Import files
operation_2020 = pd.read_excel(f"{data_dir}/operation/2020.xlsx")

# Keep useful columns and rename
use_cols = {'GPS经度':'lon','GPS纬度':'lat','作业日期':'date','作业器具类型':'tool','作业类型':'type',
        '高炮炮弹用量(发)':'num_gaopao','火箭弹用量（枚）':'num_rocket',
        '烟条用量（根）':'num_cigar','其他用量':'num_other','作业开始时间':'start_time','作业结束时间':'end_time',
        '作业前天气状况':'weather_before','作业后天气状况':'weather_after','作业面积（平方公里）':'area',
        '作业效果':'effect','作业市':'city_o','作业县':'county_o','作业地点':'location_o'}
operation_2020 = operation_2020[list(use_cols.keys())]
operation_2020 = operation_2020.rename(columns=use_cols)

# Extract the town of operation
operation_2020_gdf = gpd.GeoDataFrame(
    operation_2020,
    geometry=gpd.points_from_xy(operation_2020.lon, operation_2020.lat),
    crs="EPSG:4326"  # Set the Coordinate Reference System (CRS)
)
joined_2020 = gpd.sjoin(operation_2020_gdf, townshape, how="left", predicate="within")

### Clean 2021-2025 Cloudseeding Operation Data

data_list_2021_2025 = []
for i in range(2021,2026):
    # Import files
    operation = pd.read_excel(f"{data_dir}/operation/{i}.xls")

    # Keep useful columns and rename
    use_cols_i = {'作业日期':'date', '作业开始时间':'start_time','作业结束时间':'end_time',
                  '所属市':'city_o','所属县':'county_o','作业器具类型':'tool', '作业用量':'num',
                  '作业前天气':'weather_before','作业后天气':'weather_after','作业面积':'area','作业效果':'effect',
                  '服务领域':'field','经度':'lon','纬度':'lat'}
    operation = operation[list(use_cols_i.keys())]
    operation = operation.rename(columns=use_cols_i)

    # Extract the town of operation
    operation_gdf = gpd.GeoDataFrame(
        operation,
        geometry=gpd.points_from_xy(operation.lon, operation.lat),
        crs="EPSG:4326"  # Set the Coordinate Reference System (CRS)
    )
    joined = gpd.sjoin(operation_gdf, townshape, how="left", predicate="within")
    data_list_2021_2025.append(joined)

joined_2021_2025 = pd.concat(data_list_2021_2025, ignore_index=True)
data = pd.concat([joined_2021_2025, joined_2020], ignore_index=True)

# Create date columns
data['date'] = pd.to_datetime(data['date'])

# Drop index column
data.drop(columns=['index_right'],inplace=True)

# Test by drawing histogram
if check == "True":
    data_temp = data
    data_temp['year'] = data_temp.date.dt.year
    year_counts = data_temp['year'].value_counts().sort_index()

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(year_counts.index, year_counts.values, color='#4C72B0', edgecolor='white')
    ax.set_xlabel('Year', fontsize=13)
    ax.set_ylabel('Count', fontsize=13)
    ax.set_title('Number of cloud seeding operations per year in Jiangxi', fontsize=15, fontweight='bold')
    ax.set_xticks(year_counts.index)
    ax.set_xticklabels(year_counts.index, rotation=45)
    plt.tight_layout()
    plt.savefig(f"{data_dir}/operation/operation_by_year.png", dpi=150)
    plt.close()

data.to_csv(f"{data_dir}/intermediate/cleaned_operation.csv")
