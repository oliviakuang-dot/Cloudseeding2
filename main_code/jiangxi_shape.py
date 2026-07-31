import geopandas as gpd
import os

data_dir = os.environ['DATA_DIR']

# Load township data
townshape = gpd.read_file(f"{data_dir}/township_shapefile/xiangzhen.shp")

# Select Jiangxi Province and merge all geometries
townshape = townshape[townshape['省']=='江西省'].dissolve()
jx_poly = townshape[['省','geometry']]
jx_poly.rename(columns={"省":"prov"},inplace=True)
jx_poly.to_file(f"{data_dir}/jiangxi_shapefile/jiangxi_shape.shp")