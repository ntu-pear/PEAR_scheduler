import os
from urllib.parse import quote_plus

import sqlalchemy as sa
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Load environment variables from .env file
load_dotenv()

# Get the database URL from environment variables
DB_URL_LOCAL = os.getenv("DB_URL_LOCAL")
DB_DRIVER = os.getenv("DB_DRIVER")

DB_SERVER = os.getenv("DB_SERVER")

# DB_DATABASE_DEV = "scheduler_service_dev" 
DB_DATABASE = os.getenv("DB_DATABASE")
DB_DATABASE_PORT = os.getenv("DB_DATABASE_PORT")
DB_USERNAME = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Get the database URL from environment (DOCKER LOCAL)
DB_URL_LOCAL = os.getenv("DB_URL_LOCAL")
DB_DRIVER = os.getenv("DB_DRIVER")
DB_SERVER = os.getenv("DB_SERVER")
DB_DATABASE = os.getenv("DB_DATABASE")
DB_DATABASE_PORT = os.getenv("DB_DATABASE_PORT")
DB_USERNAME = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# Create encoded password for use in raw connection strings (like FastAPI app)
DB_PASSWORD_DEV_ENCODED = quote_plus(DB_PASSWORD) if DB_PASSWORD else ""

##### Note that this connection is to the DEV environment ####
# COMMMENT out this section when doing local development

# For consumer/SQLAlchemy URL.create() - uses raw password (auto-encoded)
connection_url = sa.URL.create(
    "mssql+pyodbc",
    username=DB_USERNAME,
    password=DB_PASSWORD,  # Raw password - SQLAlchemy handles encoding
    host=DB_SERVER,
    port=DB_DATABASE_PORT,
    database=DB_DATABASE,
    query={"driver": DB_DRIVER, "TrustServerCertificate": "yes"},
)

# For FastAPI app/raw connection strings - uses encoded password
DB_CONN_STR_RAW = f"mssql+pyodbc://{DB_USERNAME}:{DB_PASSWORD_DEV_ENCODED}@{DB_SERVER}:{DB_DATABASE_PORT}/{DB_DATABASE}?driver={DB_DRIVER.replace(' ', '+')}&TrustServerCertificate=yes"

###############################################################

########## LOCAL DOCKER DEVELOPMENT ##########
# connection_url = sa.URL.create(
#     "mssql+pyodbc",
#     username=DB_USERNAME,
#     password=DB_PASSWORD,
#     host=DB_SERVER,
#     port=DB_DATABASE_PORT,
#     database=DB_DATABASE,
#     query={"driver": DB_DRIVER, "TrustServerCertificate": "yes"},
# )
##############################################

engine = sa.create_engine(connection_url)
##############################################################
# print(DATABASE_URL)
# engine = create_engine(DATABASE_URL, connect_args={"timeout": 30})
# engine_dev = create_engine(DATABASE_URL_DEV, )  # Increase the timeout if necessary

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()